"""
RunController -- image generation execution, queuing, and progress.

Owns the run lifecycle: validation, execution (via ``Run``), job queue
management, progress updates, cancellation, and time estimation.
"""

import datetime
import os
import time
import traceback
from copy import deepcopy
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ui_qt.sound_player import play_sound
from utils.logging_setup import get_logger
from utils.translations import I18N
from utils.utils import Utils

_ = I18N._
logger = get_logger("ui_qt.run_controller")


def clear_quotes(s: str) -> str:
    """Strip leading/trailing single or double quotes from *s*."""
    if len(s) > 0:
        if s.startswith('"'):
            s = s[1:]
        if s.endswith('"'):
            s = s[:-1]
        if s.startswith("'"):
            s = s[1:]
        if s.endswith("'"):
            s = s[:-1]
    return s


class RunController:
    """Manages image generation runs and job queuing.

    Parameters
    ----------
    app_window : AppWindow
        The parent window providing access to sidebar widgets and
        notification controller.
    """

    def __init__(self, app_window):
        self._app = app_window

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @property
    def _sp(self):
        """Shorthand for the sidebar panel."""
        return self._app.sidebar_panel

    def has_runs_pending(self) -> bool:
        """Return True if any run or preset schedule is still queued."""
        return (
            self._app.job_queue.has_pending()
            or (self._app.job_queue_preset_schedules is not None
                and self._app.job_queue_preset_schedules.has_pending())
        )

    # ------------------------------------------------------------------
    # Blacklist validation
    # ------------------------------------------------------------------
    def validate_blacklist(self, text: str) -> bool:
        """Validate *text* against the blacklist.

        Returns True if validation passes, False if blacklisted items found.
        """
        from utils.config import config
        from utils.globals import PromptMode, BlacklistMode, BlacklistPromptMode
        from sd_runner.blacklist import Blacklist, BlacklistException

        if not config.blacklist_prevent_execution:
            return True

        prompt_mode = PromptMode.get(self._sp.prompt_mode_combo.currentText())
        if prompt_mode.is_nsfw() and Blacklist.get_blacklist_prompt_mode() == BlacklistPromptMode.ALLOW_IN_NSFW:
            return True

        filtered = Blacklist.find_blacklisted_items(text)
        if not filtered:
            filtered = Blacklist.check_user_prompt_detailed(text)

        if filtered:
            if not Blacklist.get_blacklist_silent_removal():
                alert_text = _("Blacklisted items found in prompt: {0}").format(filtered)
                self._app.notification_ctrl.alert(_("Invalid Prompt Tags"), alert_text, kind="error")
            if Blacklist.get_blacklist_mode() == BlacklistMode.FAIL_PROMPT:
                if Blacklist.get_blacklist_silent_removal():
                    self._app.notification_ctrl.alert(
                        _("Invalid Prompt Tags"), _("Blacklist validation failed!"), kind="error"
                    )
                raise BlacklistException("Blacklist validation failed", [], filtered)
            return False
        return True

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self, event=None) -> None:
        """Start an image generation run (or enqueue it).

        The heavy lifting runs on a background
        thread; UI updates are marshalled to the main thread via
        ``_MainThreadBridge``-wrapped ``AppActions``.
        """
        from run import Run
        from sd_runner.blacklist import BlacklistException
        from sd_runner.timed_schedules_manager import timed_schedules_manager, ScheduledShutdownException
        from sd_runner.models import Model
        from sd_runner.gen_config import GenConfig
        from sd_runner.resolution import Resolution
        from utils.globals import Globals, ResolutionGroup, WorkflowType
        from utils.time_estimator import TimeEstimator

        app = self._app
        sp = self._sp

        if app.current_run is not None and app.current_run.is_infinite():
            app.current_run.cancel("Infinite run switch")

        # Check for scheduled shutdown
        try:
            timed_schedules_manager.check_for_shutdown_request(datetime.datetime.now())
        except ScheduledShutdownException as e:
            self._handle_scheduled_shutdown(e)
            return

        if event is not None and app.job_queue_preset_schedules is not None and app.job_queue_preset_schedules.has_pending():
            ok = app.notification_ctrl.alert(
                _("Confirm Run"),
                _("Starting a new run will cancel the current preset schedule. Are you sure you want to proceed?"),
                kind="askokcancel",
            )
            if not ok:
                return
            app.job_queue_preset_schedules.cancel()

        if sp.run_preset_schedule_check.isChecked():
            if app.job_queue_preset_schedules is not None and not app.job_queue_preset_schedules.has_pending():
                self.run_preset_schedule()
                return
        else:
            if app.job_queue_preset_schedules is not None:
                app.job_queue_preset_schedules.cancel()

        args, args_copy = app.get_args()

        # Sync tags from sidebar
        sp.set_prompt_massage_tags()
        sp.set_positive_tags()
        sp.set_negative_tags()

        try:
            args.validate()
        except BlacklistException as e:
            app.notification_ctrl.handle_error(str(e), "Blacklist Validation Error")
            return
        except Exception as e:
            ok = app.notification_ctrl.alert(
                _("Confirm Run"),
                str(e) + "\n\n" + _("Are you sure you want to proceed?"),
                kind="askokcancel",
            )
            if not ok:
                return

        # Sync latest UI-derived args into runner_app_config before persisting.
        # This ensures history navigation restores current fields (including LoRA tags).
        app.runner_app_config.set_from_run_config(args_copy)

        # Store config after validation
        app.cache_ctrl.store_info_cache()
        self.update_progress(override_text=_("Setting up run..."))

        # Time estimation check
        workflow_type = args.workflow_tag
        models = Model.get_models(
            args.model_tags,
            default_tag=Model.get_default_model_tag(workflow_type),
            inpainting=args.inpainting,
        )
        if len(models) == 0:
            app.notification_ctrl.handle_error(_("No models found"), _("No models found"))
            return

        resolution_group = ResolutionGroup.get(args.resolution_group)
        resolutions = Resolution.get_resolutions(
            args.res_tags,
            architecture_type=models[0].architecture_type,
            resolution_group=resolution_group,
        )
        # Include adapter/source combinations in time estimation.
        control_nets = []
        ip_adapters = []
        is_dir_controlnet = False
        is_dir_ipadapter = False
        source_prompt_multiplier = 1
        try:
            from sd_runner.control_nets import get_control_nets
            from sd_runner.ip_adapters import get_ip_adapters
            from utils.utils import Utils

            control_files = (
                Utils.split(args.control_nets, ",")
                if args.control_nets and args.control_nets != ""
                else None
            )
            ip_files = (
                Utils.split(args.ip_adapters, ",")
                if args.ip_adapters and args.ip_adapters != ""
                else None
            )
            source_prompt_files = (
                Utils.split(args.source_prompts, ",")
                if getattr(args, "source_prompts", None) and args.source_prompts != ""
                else None
            )
            control_nets, is_dir_controlnet = get_control_nets(control_files, app_actions=None)
            ip_adapters, is_dir_ipadapter = get_ip_adapters(ip_files, app_actions=None)
            source_prompt_multiplier = 1
            if source_prompt_files:
                source_is_dir = len(source_prompt_files) == 1 and os.path.isdir(source_prompt_files[0])
                source_iterates = source_is_dir or len(source_prompt_files) > 1
                if source_iterates:
                    if source_is_dir:
                        source_prompt_multiplier = len(
                            Utils.get_files_from_dir(
                                source_prompt_files[0],
                                recursive=False,
                                random_sort=False,
                                allowed_extensions=Utils.IMAGE_EXTENSIONS,
                            )
                        )
                    else:
                        source_prompt_multiplier = len([p for p in source_prompt_files if os.path.isfile(p)])
        except Exception as e:
            logger.warning(f"Failed to include adapters in run estimate: {e}")

        iterate_control = bool(is_dir_controlnet)
        iterate_ip = bool(is_dir_ipadapter)
        iterate_source = source_prompt_multiplier > 1

        # For directory iteration modes, estimate one adapter per iteration,
        # then multiply by the number of adapter iterations separately.
        # Directory paths come from glob so existence is guaranteed — skip is_valid().
        # Manual entries may not exist, so keep the validity filter for that case.
        if iterate_control:
            n_control_nets = len(control_nets)
            estimate_control_nets = control_nets[:1] if n_control_nets > 0 else control_nets
        else:
            valid_control_nets = [c for c in control_nets if c.is_valid()]
            n_control_nets = len(valid_control_nets)
            estimate_control_nets = valid_control_nets

        if iterate_ip:
            n_ip_adapters = len(ip_adapters)
            estimate_ip_adapters = ip_adapters[:1] if n_ip_adapters > 0 else ip_adapters
        else:
            valid_ip_adapters = [i for i in ip_adapters if i.is_valid()]
            n_ip_adapters = len(valid_ip_adapters)
            estimate_ip_adapters = valid_ip_adapters

        adapter_iterations = 1
        if iterate_control:
            adapter_iterations *= n_control_nets
        if iterate_ip:
            adapter_iterations *= n_ip_adapters
        if iterate_source:
            adapter_iterations *= source_prompt_multiplier
        if adapter_iterations < 1:
            adapter_iterations = 1

        if args.batch_limit is not None and args.batch_limit > 0:
            adapter_iterations = min(adapter_iterations, int(args.batch_limit))

        gen_config = GenConfig(
            workflow_id=workflow_type,
            models=models,
            n_latents=args.n_latents,
            resolutions=resolutions,
            control_nets=estimate_control_nets,
            ip_adapters=estimate_ip_adapters,
            run_config=args,
        )
        per_iteration_images = max(1, gen_config.maximum_gens_per_latent())
        requested_total = int(args.total) if args.total and args.total > 0 else 1
        estimated_image_count = per_iteration_images * requested_total * adapter_iterations
        estimated_seconds = TimeEstimator.estimate_queue_time(estimated_image_count, gen_config.n_latents)

        if estimated_seconds > Globals.TIME_ESTIMATION_CONFIRMATION_THRESHOLD_SECONDS:
            formatted_time = TimeEstimator.format_time(estimated_seconds)
            threshold_formatted = TimeEstimator.format_time(
                Globals.TIME_ESTIMATION_CONFIRMATION_THRESHOLD_SECONDS
            )
            play_sound("alert")
            ok = app.notification_ctrl.alert(
                _("Long Running Job Confirmation"),
                _("The estimated time for this run is {0}, which exceeds the threshold of {1}.\n\n"
                  "This run will generate {2} images.\n\n"
                  "Are you sure you want to proceed?").format(
                    formatted_time, threshold_formatted, estimated_image_count
                ),
                kind="askokcancel",
            )
            if not ok:
                return

        def run_async(run_args) -> None:
            Utils.prevent_sleep(True)
            app.job_queue.job_running = True
            sp.cancel_btn.setVisible(True)
            app.current_run = Run(run_args, ui_callbacks=app.app_actions, delay_after_last_run=self.has_runs_pending())
            try:
                app.current_run.execute()
            except ScheduledShutdownException as e:
                self._handle_scheduled_shutdown(e)
            except Exception as e:
                traceback.print_exc()
                app.current_run.cancel("Run failure")
                app.notification_ctrl.alert(_("Run Error"), str(e), kind="error")
            sp.cancel_btn.setVisible(False)
            app.job_queue.job_running = False
            next_job_args = app.job_queue.take()

            # A slot just opened; promote one staged server request into the main
            # queue now so staging and the main queue drain in parallel (FIFO order).
            # If the main queue still has items the promoted job queues behind them;
            # if the main queue is empty it starts its own run_async via server_run_callback.
            staging = getattr(app, "server_staging_queue", None)
            promoted = False
            if staging is not None and staging.has_pending():
                staged = staging.take()
                if staged is not None:
                    wf_type, staged_args = staged
                    logger.info(
                        f"Promoting staged server request "
                        f"({staging.pending_count()} remaining in staging queue)"
                    )
                    app.app_actions.server_run_callback(wf_type, staged_args)
                    promoted = True

            if next_job_args:
                app.current_run.delay_after_last_run = True
                Utils.start_thread(run_async, use_asyncio=False, args=[next_job_args])
            elif not promoted:
                Utils.prevent_sleep(False)
                self.clear_progress()

        if app.job_queue.has_pending():
            app.job_queue.add(args)
        else:
            Utils.start_thread(run_async, use_asyncio=False, args=[args])

    def cancel(self, event=None, reason: str | None = None) -> None:
        """Cancel the current run."""
        if hasattr(self._app, "current_run") and self._app.current_run is not None:
            self._app.current_run.cancel(reason=reason)
        self.clear_progress()

    def revert_to_simple_gen(self, event=None) -> None:
        """Cancel current run and restart with simple generation workflow."""
        from utils.globals import WorkflowType
        self.cancel(reason="Revert to simple generation")
        self._sp.workflow_combo.setCurrentText(WorkflowType.SIMPLE_IMAGE_GEN_LORA.get_translation())
        self.run()

    # ------------------------------------------------------------------
    # Preset schedule execution
    # ------------------------------------------------------------------
    def run_preset_schedule(self, override_args: dict | None = None) -> None:
        """Execute a preset schedule in a background thread."""
        from sd_runner.timed_schedules_manager import timed_schedules_manager, ScheduledShutdownException
        from utils.config import config

        if override_args is None:
            override_args = {}

        app = self._app
        sp = self._sp

        def run_preset_async():
            try:
                timed_schedules_manager.check_for_shutdown_request(datetime.datetime.now())
            except ScheduledShutdownException as e:
                self._handle_scheduled_shutdown(e)
                return

            app.job_queue_preset_schedules.job_running = True

            if "control_net" in override_args:
                sp.controlnet_file_entry.setText(override_args["control_net"])
            if "ip_adapter" in override_args:
                sp.ipadapter_file_entry.setText(override_args["ip_adapter"])
            if "source_prompt" in override_args:
                sp.source_prompt_file_entry.setText(override_args["source_prompt"])

            starting_total = int(sp.total_combo.currentText())

            from ui_qt.presets.schedules_window import SchedulesWindow
            from ui_qt.presets.presets_window import PresetsWindow
            schedule = SchedulesWindow.current_schedule
            if schedule is None:
                raise Exception("No Schedule Selected")

            logger.info("Running preset schedule")
            for preset_task in schedule.get_tasks():
                if (not app.job_queue_preset_schedules.has_pending()
                        or not sp.run_preset_schedule_check.isChecked()
                        or (app.current_run is not None
                            and not app.current_run.is_infinite()
                            and app.current_run.is_cancelled)):
                    app.job_queue_preset_schedules.cancel()
                    return
                try:
                    preset = PresetsWindow.get_preset_by_name(preset_task.name)
                except Exception as e:
                    app.notification_ctrl.handle_error(str(e), "Preset Schedule Error")
                    raise e
                sp.set_widgets_from_preset(preset, manual=False)
                sp.total_combo.setCurrentText(
                    str(preset_task.count_runs if preset_task.count_runs > 0 else starting_total)
                )
                self.run()
                time.sleep(0.1)
                started_run_id = app.current_run.id
                while (app.current_run is not None
                       and started_run_id == app.current_run.id
                       and not app.current_run.is_cancelled
                       and not app.current_run.is_complete):
                    if (not app.job_queue_preset_schedules.has_pending()
                            or not sp.run_preset_schedule_check.isChecked()):
                        app.job_queue_preset_schedules.cancel()
                        return
                    time.sleep(1)

            sp.total_combo.setCurrentText(str(starting_total))
            app.job_queue_preset_schedules.job_running = False
            next_preset_schedule_args = app.job_queue_preset_schedules.take()
            if next_preset_schedule_args is None:
                app.job_queue_preset_schedules.cancel()
            else:
                self.run_preset_schedule(override_args=next_preset_schedule_args)

        Utils.start_thread(run_preset_async, use_asyncio=False, args=[])

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------
    def update_progress(
        self,
        current_index: int = -1,
        total: int = -1,
        pending_adapters: int = 0,
        prepend_text: str | None = None,
        batch_current: int | None = None,
        batch_limit: int | None = None,
        override_text: str | None = None,
        adapter_current: int | None = None,
        adapter_total: int | None = None,
    ) -> None:
        """Update progress labels on the sidebar."""
        sp = self._sp

        if override_text is not None:
            text = override_text
            sp.label_batch_info.setText("")
            sp.label_adapter_progress.setText("")
        else:
            if total == -1:
                text = str(current_index) + _(" (unlimited)")
            else:
                text = f"{current_index}/{total}"

        if prepend_text is not None:
            sp.label_progress.setText(prepend_text + text)
        else:
            sp.label_progress.setText(text)

        if override_text is None:
            # Batch info
            if batch_limit is not None and batch_limit > 0 and total > 0 and batch_limit < total:
                if batch_current is None:
                    batch_current = ((current_index - 1) // total) + 1 if current_index > 0 else 1
                sp.label_batch_info.setText(_("Batch: {0}/{1}").format(batch_current, batch_limit))
            else:
                sp.label_batch_info.setText("")

            # Adapter progress
            if adapter_current is not None and adapter_total is not None and adapter_total > 1:
                sp.label_adapter_progress.setText(
                    _("Adapter: {0}/{1}").format(adapter_current, adapter_total)
                )
            elif pending_adapters is not None and isinstance(pending_adapters, int) and pending_adapters > 0:
                sp.label_adapter_progress.setText(
                    _("Remaining: {0} adapters").format(pending_adapters)
                )
            else:
                sp.label_adapter_progress.setText("")

            # Pending adapters label
            if pending_adapters is not None:
                if isinstance(pending_adapters, int) and pending_adapters > 0:
                    sp.label_pending_adapters.setText(
                        _("{0} remaining adapters").format(pending_adapters)
                    )
                else:
                    sp.label_pending_adapters.setText("")

            # Preset schedules pending
            if self._app.job_queue_preset_schedules is not None:
                preset_text = self._app.job_queue_preset_schedules.pending_text()
                sp.label_pending_preset_schedules.setText(preset_text if preset_text else "")

    def update_pending(self, count_pending: int = 0) -> None:
        """Update the pending-generations label."""
        sp = self._sp
        if count_pending <= 0:
            sp.label_pending.setText("")
            if (self._app.job_queue_preset_schedules is not None
                    and not self._app.job_queue_preset_schedules.has_pending()
                    and self._app.current_run is not None
                    and self._app.current_run.is_complete):
                play_sound()
                sp.label_pending_adapters.setText("")
        else:
            sp.label_pending.setText(_("{0} pending generations").format(count_pending))

    def update_time_estimation(
        self,
        workflow_type: str = "",
        gen_config=None,
        remaining_count: int = 1,
    ) -> None:
        """Update the time-estimation label.

        """
        from utils.time_estimator import TimeEstimator

        if gen_config is None:
            return

        total_seconds = 0
        total_jobs = gen_config.maximum_gens_per_latent()
        current_job_time = TimeEstimator.estimate_queue_time(
            total_jobs * remaining_count, gen_config.n_latents
        )
        total_seconds += current_job_time

        if self._app.job_queue.has_pending():
            queue_time = self._app.job_queue.estimate_time(gen_config)
            total_seconds += queue_time

        if (self._app.job_queue_preset_schedules is not None
                and self._app.job_queue_preset_schedules.has_pending()):
            preset_time = self._app.job_queue_preset_schedules.estimate_time(gen_config)
            total_seconds += preset_time

        current_estimate = TimeEstimator.format_time(total_seconds)
        self._sp.label_time_est.setText(current_estimate)

    def clear_progress(self) -> None:
        """Clear all progress / time-estimation labels."""
        sp = self._sp
        sp.label_time_est.setText("")
        sp.label_batch_info.setText("")
        sp.label_adapter_progress.setText("")
        sp.label_progress.setText("")
        sp.label_pending_adapters.setText("")
        sp.label_pending_preset_schedules.setText("")

    # ------------------------------------------------------------------
    # Time estimation
    # ------------------------------------------------------------------
    def calculate_current_run_estimated_time(self, workflow_type: str, gen_config) -> int:
        """Calculate estimated seconds for the current run only."""
        from utils.time_estimator import TimeEstimator
        total_jobs = gen_config.maximum_gens_per_latent()
        current_job_time = TimeEstimator.estimate_queue_time(total_jobs, gen_config.n_latents)
        logger.debug(f"Estimated time: {total_jobs} jobs, {current_job_time}s")
        return current_job_time

    # ------------------------------------------------------------------
    # Server callback
    # ------------------------------------------------------------------
    def server_run_callback(self, workflow_type, args: dict):
        """Called by ``SDRunnerServer`` when a remote run request arrives."""
        from utils.globals import WorkflowType
        from utils.config import config

        app = self._app

        # If the main run queue is at its limit, stage the request rather than reject it.
        staging = getattr(app, "server_staging_queue", None)
        if staging is not None and len(app.job_queue.pending_jobs) >= app.job_queue.max_size:
            try:
                pos = staging.add(workflow_type, args)
                logger.info(
                    f"Main run queue full ({app.job_queue.max_size}) — "
                    f"staged server request at position {pos}"
                )
                return {"queued": "staged", "position": pos}
            except Exception as e:
                logger.error(f"Server staging queue full: {e}")
                return {"error": "staging queue full", "data": str(e)}

        sp = self._sp

        if workflow_type is not None:
            sp.workflow_combo.setCurrentText(workflow_type.get_translation())
        elif config.debug:
            logger.debug("Rerunning from server request with last settings.")

        if len(args) > 0:
            if "source_prompt" in args:
                source_path = args["source_prompt"].replace(",", "\\,")
                if "append" in args and args["append"] and sp.source_prompt_file_entry.text().strip():
                    sp.source_prompt_file_entry.setText(
                        sp.source_prompt_file_entry.text() + "," + source_path
                    )
                else:
                    sp.source_prompt_file_entry.setText(source_path)
            if "control_net" in args and workflow_type == WorkflowType.IMAGE_EDIT:
                cn_path = args["control_net"].replace(",", "\\,")
                if "append" in args and args["append"] and sp.controlnet_file_entry.text().strip():
                    sp.controlnet_file_entry.setText(sp.controlnet_file_entry.text() + "," + cn_path)
                else:
                    sp.controlnet_file_entry.setText(cn_path)
            if "image" in args:
                image_path = args["image"].replace(",", "\\,")
                if workflow_type in [
                    WorkflowType.CONTROLNET, WorkflowType.RENOISER, WorkflowType.REDO_PROMPT
                ]:
                    if (sp.run_preset_schedule_check.isChecked()
                            and self._app.job_queue_preset_schedules is not None
                            and self._app.job_queue_preset_schedules.has_pending()):
                        self._app.job_queue_preset_schedules.add({"control_net": image_path})
                        return {}
                    elif "append" in args and args["append"] and sp.controlnet_file_entry.text().strip():
                        sp.controlnet_file_entry.setText(
                            sp.controlnet_file_entry.text() + "," + image_path
                        )
                    else:
                        sp.controlnet_file_entry.setText(image_path)
                elif workflow_type in [WorkflowType.IP_ADAPTER, WorkflowType.IMG2IMG, WorkflowType.IMAGE_EDIT]:
                    if (sp.run_preset_schedule_check.isChecked()
                            and self._app.job_queue_preset_schedules is not None
                            and self._app.job_queue_preset_schedules.has_pending()):
                        self._app.job_queue_preset_schedules.add({"ip_adapter": image_path})
                        return {}
                    if "append" in args and args["append"] and sp.ipadapter_file_entry.text().strip():
                        sp.ipadapter_file_entry.setText(
                            sp.ipadapter_file_entry.text() + "," + image_path
                        )
                    else:
                        sp.ipadapter_file_entry.setText(image_path)
                else:
                    logger.warning(f"Unhandled workflow type for server connection: {workflow_type}")

        self.run()
        return {}

    # ------------------------------------------------------------------
    # Scheduled shutdown
    # ------------------------------------------------------------------
    def _handle_scheduled_shutdown(self, e) -> None:
        """Route to main thread and show the shutdown countdown dialog.

        Safe to call from any thread: routes through _MainThreadBridge so that
        Qt widget creation and the countdown QTimer always run on the GUI thread.
        """
        self._app._thread_bridge.invoke(self._run_shutdown_dialog, e)

    def _run_shutdown_dialog(self, e) -> None:
        """Show the shutdown countdown dialog. Must be called on the main thread."""
        logger.info(f"Scheduled shutdown requested: {e}")
        schedule_name = e.schedule.name if e.schedule else "Unknown Schedule"
        try:
            from ui_qt.presets.scheduled_shutdown_dialog import ScheduledShutdownDialog
            shutdown_dialog = ScheduledShutdownDialog(
                self._app, schedule_name, countdown_seconds=6
            )
            # exec() blocks this method (on the main thread) while the countdown
            # runs.  The dialog calls on_closing() itself via _force_shutdown();
            # we only need to quit() the event loop after it closes.
            shutdown_dialog.exec()
            if not shutdown_dialog.cancelled:
                QApplication.instance().quit()
        except ImportError:
            logger.warning("ScheduledShutdownDialog not available, shutting down immediately")
            self._app.on_closing()
            QApplication.instance().quit()

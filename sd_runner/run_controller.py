"""
RunController -- image generation execution, queuing, and progress.

Owns the run lifecycle: validation, execution (via ``Run``), job queue
management, progress updates, cancellation, and time estimation.

Driven by either application object: ``AppWindow``, or ``HeadlessApp`` when
there is no display. What the two differ on is reached through the application
it was given -- the thread bridge, the notification sink, the progress actions
-- so this holds one implementation rather than a branch per caller. The
exception is the sidebar: the commands that mean "read the UI" are refused by
finding none, which is why those checks test for it rather than for a mode.

Qt is imported inside the three places that need it -- the alert sound and the
scheduled-shutdown dialog -- rather than at module level, so this module can be
imported by a process that has no display. Those three sit on paths a headless
caller does not take: the long-run confirmation, the sidebar progress labels,
and a countdown dialog.
"""

import datetime
import os
import time
import traceback

from sd_runner.models import NoModelsFound
from utils.logging_setup import get_logger
from utils.translations import I18N
from utils.utils import Utils

_ = I18N._
logger = get_logger("run_controller")

#: Origin recorded for a server run whose client did not name itself. The
#: single sentinel for that case: the server reports "" rather than inventing
#: one of its own, so the two cannot disagree. An identifier rather than prose
#: -- it is stored on the run and persisted, so it must not shift with the
#: display locale.
SERVER_ORIGIN = "server"


def origin_for_client(client_id: str) -> str:
    """The origin to record on a run started by a request from *client_id*.

    One rule in one place: every server entry point that sets ``run_origin``
    goes through it, so an unidentified client cannot be named one way on the
    virtual path and another on the widget-backed one. The client id itself is
    kept unresolved everywhere else -- including on a staged request -- so that
    a stored empty id still means "the client did not say", not "the client
    called itself server".
    """
    return client_id or SERVER_ORIGIN


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
    app_window : AppWindow | HeadlessApp
        The application object, supplying the queues, the stored config, the
        thread bridge and the notification sink. A ``sidebar_panel`` on it is
        what makes the UI-shaped commands answerable.
    """

    def __init__(self, app_window):
        self._app = app_window
        # Set by resume_paused_queue() when it starts a pending SD run while
        # staged server requests are also waiting. Consumed by the very next
        # _post_run() so that run doesn't immediately cascade into promoting
        # a staged request — the user's resume already chose the SD queue.
        self._skip_next_staging_promotion = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @property
    def _sp(self):
        """Shorthand for the sidebar panel."""
        return self._app.sidebar_panel

    def _on_main(self, func, *args, **kwargs):
        """Run *func* on the GUI thread, blocking this thread until it returns.

        A no-op indirection when already on the GUI thread, so it is safe to use
        unconditionally in code reachable from either.
        """
        return self._app._thread_bridge.invoke(func, *args, **kwargs)

    def current_run_origin(self) -> str:
        """Which client the run currently executing came from, or "" for the user's.

        One field rather than a boolean plus an id: the two could otherwise
        disagree about whether a run was server-initiated.
        """
        current_run = getattr(self._app, "current_run", None)
        if current_run is None or getattr(current_run, "is_complete", False):
            return ""
        return str(getattr(getattr(current_run, "args", None), "run_origin", "") or "")

    def current_run_is_server_run(self) -> bool:
        """Whether the run currently executing came from a server request."""
        return bool(self.current_run_origin())

    def run_status(self, origin: str = "") -> dict:
        """How much work is outstanding, and whether any of it is *origin*'s.

        For a client that was told its request was accepted and wants to know
        when it is done. Answers by origin rather than by a per-run handle
        because the origin already exists and a handle does not: the id a
        ``Run`` carries is created when the queue *starts* it, so there is
        nothing to hand back at the moment a request is accepted. Runs from one
        origin are therefore not distinguished from each other.

        GUI thread only -- reads the queues and the current run.
        """
        app = self._app
        current_origin = self.current_run_origin()
        pending = len(getattr(app.job_queue, "pending_jobs", []))
        staging = getattr(app, "server_staging_queue", None)
        status = {
            "running": bool(current_origin) or bool(getattr(app.job_queue, "job_running", False)),
            "current_origin": current_origin,
            "queued": pending,
            "staged": staging.pending_count() if staging is not None else 0,
        }
        if origin:
            status["mine_running"] = current_origin == origin
        return status

    def has_runs_pending(self) -> bool:
        """Return True if any run or preset schedule is still queued."""
        return (
            self._app.job_queue.has_pending()
            or (self._app.job_queue_preset_schedules is not None
                and self._app.job_queue_preset_schedules.has_pending())
        )

    def should_delay_after_last_run(self, run_args) -> bool:
        """Return whether the final iteration should use post-run delay."""
        from utils.config import config
        if run_args and run_args.total == 1:
            if config.delay_after_single_run:
                return True
        return self.has_runs_pending()

    # ------------------------------------------------------------------
    # Blacklist validation
    # ------------------------------------------------------------------
    def validate_blacklist(self, text: str) -> bool:
        """Validate *text* against the blacklist.

        Returns True if validation passes, False if blacklisted items found.

        The prompt mode comes from the stored config rather than the combo
        showing it, so this is answerable with no widgets to read -- it gates
        every prompt that reaches a backend, including on the server path.
        """
        from utils.config import config
        from utils.globals import BlacklistMode, BlacklistPromptMode
        from sd_runner.blacklist import Blacklist, BlacklistException

        if not config.blacklist_prevent_execution:
            return True

        prompt_mode = self._app.runner_app_config.prompter_config.prompt_mode
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

        violated, score, phrase = Blacklist.check_similarity(text)
        if violated:
            alert_text = _(
                "Prompt too similar to blocked concept \"{0}\" ({1:.0%})"
            ).format(phrase, score)
            if not Blacklist.get_blacklist_silent_removal():
                self._app.notification_ctrl.alert(
                    _("Similarity Check Failed"), alert_text, kind="error"
                )
            raise BlacklistException("Similarity check failed", [], {text: phrase})

        return True

    # ------------------------------------------------------------------
    # Run async worker (shared by run() and resume_paused_queue())
    # ------------------------------------------------------------------
    def set_run_controls_visible(self, visible: bool) -> None:
        """Show or hide the cancel/pause buttons. Must be called on the main thread."""
        sp = self._sp
        sp.cancel_btn.setVisible(visible)
        sp.pause_queue_btn.setVisible(visible)

    def _post_run(self) -> None:
        """Post-run queue cleanup and next-run dispatch.

        Runs on the main thread via the bridge so it cannot race with
        server_batch_enqueue, which also executes on the main thread through
        the same bridge. Both paths read and write job_queue and the staging
        queue, so serialising them here prevents a double-_run_async launch that
        could otherwise occur in the window between job_running=False and the
        staging promotion completing.
        """
        app = self._app
        app.job_queue.job_running = False
        next_job_args = app.job_queue.take()

        # A slot just opened; promote one staged server request into the main
        # queue now so staging and the main queue drain in parallel (FIFO order).
        staging = getattr(app, "server_staging_queue", None)
        promoted = False
        skip_staging = self._skip_next_staging_promotion
        self._skip_next_staging_promotion = False
        if not skip_staging and staging is not None and staging.has_pending():
            staged = staging.take()
            if staged is not None:
                command_type, staged_args, staged_client = staged
                logger.info(
                    f"Promoting staged server request "
                    f"({staging.pending_count()} remaining in staging queue)"
                )
                self._promote_staged_request(command_type, staged_args, staged_client)
                promoted = True

        if next_job_args:
            if app.job_queue.paused:
                app.job_queue.pending_jobs.insert(0, next_job_args)
                Utils.prevent_sleep(False)
                app.app_actions.clear_progress()
            else:
                app.current_run.delay_after_last_run = True
                Utils.start_thread(self._run_async, use_asyncio=False, args=[next_job_args])
        elif not promoted:
            Utils.prevent_sleep(False)
            app.app_actions.clear_progress()

    def _run_async(self, run_args) -> None:
        from sd_runner.run import Run
        from sd_runner.timed_schedules_manager import ScheduledShutdownException
        from sd_runner.virtual_run_config import apply_prompt_globals

        app = self._app
        Utils.prevent_sleep(True)
        app.job_queue.job_running = True
        # Every run path converges here before touching the backend, so this is
        # the one place that asks for it. A backend already running (ours or
        # adopted) returns immediately.
        #
        # Ordering is load-bearing. Blocking is fine -- this method always runs
        # on a worker thread -- but a cold backend blocks it for up to
        # backend_startup_timeout, and job_running is what every enqueue path
        # reads to decide whether to queue behind this run or launch a second
        # _run_async of its own. Asking before that flag is set leaves a
        # ten-minute window in which an arriving request starts a concurrent
        # run and overwrites current_run.
        self._ensure_backend_started(run_args)
        # Prompt text reaches generation through process-wide Prompter/Globals
        # state, not through the run config. Both run paths carry their tags on
        # the run and apply them here, at execution, so a queued run generates
        # with its own tags rather than whatever a later run pushed while it
        # waited. A no-op for a run that carries none.
        apply_prompt_globals(run_args)
        # Route button visibility through the bridge — Qt widgets must only be
        # mutated on the main (GUI) thread; direct calls from here would violate
        # that rule and can produce non-deterministic crashes.
        app.app_actions.set_run_controls_visible(True)
        # NOTE: app.current_run is written on a background thread while the main
        # thread may read it (e.g. current_run.is_infinite()). The assignment is
        # effectively atomic under CPython's GIL, but a logical race remains.
        app.current_run = Run(
            run_args,
            ui_callbacks=app.app_actions,
            delay_after_last_run=self.should_delay_after_last_run(run_args),
        )
        try:
            app.current_run.execute()
        except ScheduledShutdownException as e:
            self._handle_scheduled_shutdown(e)
        except Exception as e:
            traceback.print_exc()
            app.current_run.cancel("Run failure")
            # Bridged: this method is the worker thread body, and the alert
            # builds a QMessageBox. Every other UI touch here goes out through
            # app_actions, which wraps its own; this one reaches the controller
            # directly and so has to bridge for itself.
            self._on_main(
                app.notification_ctrl.alert, _("Run Error"), str(e), kind="error"
            )
        app.app_actions.set_run_controls_visible(False)
        # All post-run state changes (job_running flag, queue take, staging
        # promotion, next-run dispatch) are marshalled to the main thread so
        # they cannot interleave with server_batch_enqueue.
        app.app_actions.post_run()

    def resume_paused_queue(self) -> None:
        """Start processing a paused/restored queue without adding a new run."""
        app = self._app
        if app.job_queue.job_running:
            return
        staging = getattr(app, "server_staging_queue", None)
        has_pending_jobs = bool(app.job_queue.pending_jobs)
        has_staging = staging is not None and staging.has_pending()
        if not has_pending_jobs and not has_staging:
            return
        app.job_queue.paused = False
        if has_pending_jobs:
            if has_staging:
                self._skip_next_staging_promotion = True
            first = app.job_queue.take()
            Utils.start_thread(self._run_async, use_asyncio=False, args=[first])
        else:
            staged = staging.take()
            if staged is not None:
                command_type, staged_args, staged_client = staged
                logger.info(
                    f"Promoting staged server request on queue resume "
                    f"({staging.pending_count()} remaining in staging queue)"
                )
                self._promote_staged_request(command_type, staged_args, staged_client)

    def toggle_pause_queue(self) -> None:
        """Toggle the queue pause state and update the sidebar button label."""
        app = self._app
        app.job_queue.paused = not app.job_queue.paused
        label = _("Resume Queue") if app.job_queue.paused else _("Pause Queue")
        self._sp.pause_queue_btn.setText(label)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self, event=None, origin: str = "") -> None:
        """Start an image generation run (or enqueue it).

        The heavy lifting runs on a background
        thread; UI updates are marshalled to the main thread via
        ``_MainThreadBridge``-wrapped ``AppActions``.

        *origin* names the client a server request came from, and is empty for
        a run the user started here. It records the run's origin, not its
        configuration: the callers that pass it do read the sidebar -- that is
        the point of the commands they serve -- but the user did not press Run,
        so the progress label still has to say where the run came from.
        """
        from sd_runner.blacklist import BlacklistException
        from sd_runner.timed_schedules_manager import timed_schedules_manager, ScheduledShutdownException
        from utils.globals import Globals
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

        # Set after get_args() so it stays off args_copy, which is what is
        # written back to runner_app_config -- where a run came from is not one
        # of the user's saved settings.
        args.run_origin = origin

        # get_args() already synced these from the sidebar into runner_app_config
        # (and re-syncing here would run blacklist validation a second time, so
        # a blocked tag would alert twice). Carrying them on the run instead lets
        # _run_async apply them when this run actually starts.
        args.positive_tags = app.runner_app_config.positive_tags
        args.negative_tags = app.runner_app_config.negative_tags
        args.prompt_massage_tags = app.runner_app_config.prompt_massage_tags
        args.exclusion_tags = app.runner_app_config.exclusion_tags

        try:
            args.validate()
        except BlacklistException as e:
            app.notification_ctrl.handle_error(str(e), _("Blacklist Validation Error"))
            return
        except NoModelsFound as e:
            # Not offered as a confirmation: with no model there is nothing to
            # generate with, so proceeding would fail further in with a less
            # answerable message.
            app.notification_ctrl.handle_error(str(e), _("No models found"))
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
        app.app_actions.update_progress(override_text=_("Setting up run..."))

        # Time estimation check. The scans this makes over adapter and source
        # prompt directories take as long as those directories are large, and
        # it touches no widget -- _run_virtual relies on that too, keeping it
        # off the GUI thread. Running it off thread here keeps the window
        # painting while the Run button works.
        estimate = app.responsiveness.run_off_thread(
            lambda: self._estimate_run_outcome(args))
        if isinstance(estimate, NoModelsFound):
            app.notification_ctrl.handle_error(str(estimate), _("No models found"))
            return
        if estimate is None:
            app.notification_ctrl.handle_error(
                _("Could not estimate the run."), _("Run Error"))
            return
        estimated_seconds, estimated_image_count = estimate

        if estimated_seconds > Globals.TIME_ESTIMATION_CONFIRMATION_THRESHOLD_SECONDS:
            formatted_time = TimeEstimator.format_time(estimated_seconds)
            threshold_formatted = TimeEstimator.format_time(
                Globals.TIME_ESTIMATION_CONFIRMATION_THRESHOLD_SECONDS
            )
            from sd_runner.ui.sound_player import play_sound
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

        self._enqueue_run(args)

    def _estimate_run_outcome(self, args):
        """``_estimate_run``'s result, or the ``NoModelsFound`` it raised.

        ``run_off_thread`` answers a failure with None and carries no exception
        back, so the one failure the interactive caller tells apart is returned
        as a value. Any other failure stays a None the caller reports as such.
        """
        try:
            return self._estimate_run(args)
        except NoModelsFound as e:
            return NoModelsFound(str(e))

    def _estimate_run(self, args):
        """Return ``(estimated_seconds, estimated_image_count)`` for *args*.

        Shared by the interactive path, which asks the user to confirm a long
        run, and the server path, which has no user to ask and enforces a
        ceiling instead. Raises ``NoModelsFound`` when the model tags match
        nothing, leaving it to the caller to decide how to report that.
        """
        from sd_runner.gen_config import GenConfig
        from sd_runner.models import Model
        from sd_runner.resolution import Resolution
        from utils.globals import ResolutionGroup
        from utils.time_estimator import TimeEstimator

        workflow_type = args.workflow_tag
        models = Model.get_models(
            args.model_tags,
            default_tag=Model.get_default_model_tag(workflow_type),
            inpainting=args.inpainting,
        )
        if len(models) == 0:
            raise NoModelsFound(_("No models found"))

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
        # maximum_gens_per_latent() excludes the latent multiplier, so it has to
        # be applied here. Leaving it to estimate_queue_time gave the right
        # seconds but returned a count n_latents times too small -- which is the
        # number a client refused by the size ceiling is told.
        estimated_image_count = (
            per_iteration_images * requested_total * adapter_iterations * gen_config.n_latents
        )
        estimated_seconds = TimeEstimator.estimate_run_seconds(gen_config, estimated_image_count)
        return estimated_seconds, estimated_image_count

    def _enqueue_run(self, args) -> None:
        """Queue *args* behind any running job, or start it now if idle."""
        app = self._app
        if app.job_queue.job_running:
            app.job_queue.add(args)
        elif app.job_queue.pending_jobs:
            # Queue has restored/pending jobs but isn't running — add new job at
            # the end and kick off execution from the first pending job.
            app.job_queue.paused = False
            app.job_queue.add(args)
            first = app.job_queue.take()
            Utils.start_thread(self._run_async, use_asyncio=False, args=[first])
        else:
            Utils.start_thread(self._run_async, use_asyncio=False, args=[args])

    def cancel(self, event=None, reason: str | None = None) -> None:
        """Cancel the current run."""
        if hasattr(self._app, "current_run") and self._app.current_run is not None:
            self._app.current_run.cancel(reason=reason)
        self._app.app_actions.clear_progress()

    def revert_to_simple_gen(self, event=None, origin: str = "") -> None:
        """Cancel current run and restart with simple generation workflow."""
        from utils.globals import WorkflowType
        self.cancel(reason="Revert to simple generation")
        self._sp.workflow_combo.setCurrentText(WorkflowType.SIMPLE_IMAGE_GEN_LORA.get_translation())
        self.run(origin=origin)

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

        # This loop runs on a worker thread, so every widget touch below is
        # routed to the GUI thread. Qt widgets may only be read or written
        # there; doing it from here produces intermittent crashes and corrupted
        # widget state rather than a clean failure.
        def apply_overrides_and_read_total() -> int:
            if "control_net" in override_args:
                sp.controlnet_file_entry.setText(override_args["control_net"])
            if "ip_adapter" in override_args:
                sp.ipadapter_file_entry.setText(override_args["ip_adapter"])
            if "source_prompt" in override_args:
                sp.source_prompt_file_entry.setText(override_args["source_prompt"])
            return int(sp.total_combo.currentText())

        def start_task(preset, count_runs: int, starting_total: int) -> None:
            sp.set_widgets_from_preset(preset, manual=False)
            sp.total_combo.setCurrentText(str(count_runs if count_runs > 0 else starting_total))
            # No origin, deliberately, even when a server request fed this
            # schedule through _divert_to_preset_schedule: a schedule is the
            # user's own loop driving their own UI, and each task's settings
            # come from the preset and the sidebar rather than from the
            # request. The request contributed one file path, not the run. So
            # these runs show a blank Origin column and no progress marker,
            # the same as if the schedule had been started by hand.
            self.run()

        def schedule_check_is_set() -> bool:
            return sp.run_preset_schedule_check.isChecked()

        def run_preset_async():
            try:
                timed_schedules_manager.check_for_shutdown_request(datetime.datetime.now())
            except ScheduledShutdownException as e:
                self._handle_scheduled_shutdown(e)
                return

            app.job_queue_preset_schedules.job_running = True

            starting_total = self._on_main(apply_overrides_and_read_total)

            from sd_runner.presets_state import PresetsState
            from sd_runner.schedules_state import SchedulesState
            schedule = SchedulesState.current_schedule
            if schedule is None:
                raise Exception("No Schedule Selected")

            logger.info("Running preset schedule")
            for preset_task in schedule.get_tasks():
                if (not app.job_queue_preset_schedules.has_pending()
                        or not self._on_main(schedule_check_is_set)
                        or (app.current_run is not None
                            and not app.current_run.is_infinite()
                            and app.current_run.is_cancelled)):
                    app.job_queue_preset_schedules.cancel()
                    return
                try:
                    preset = PresetsState.get_preset_by_name(preset_task.name)
                except Exception as e:
                    # Bridged for the same reason as every other UI call in this
                    # closure: it runs on a worker thread and this one raises a
                    # dialog.
                    self._on_main(
                        app.notification_ctrl.handle_error,
                        str(e), _("Preset Schedule Error"),
                    )
                    raise e
                self._on_main(start_task, preset, preset_task.count_runs, starting_total)
                time.sleep(0.1)
                started_run_id = app.current_run.id
                while (app.current_run is not None
                       and started_run_id == app.current_run.id
                       and not app.current_run.is_cancelled
                       and not app.current_run.is_complete):
                    if (not app.job_queue_preset_schedules.has_pending()
                            or not self._on_main(schedule_check_is_set)):
                        app.job_queue_preset_schedules.cancel()
                        return
                    time.sleep(1)

            self._on_main(sp.total_combo.setCurrentText, str(starting_total))
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

        # A server run no longer writes its parameters into the sidebar, so
        # without this the progress label would advance for a run whose settings
        # appear nowhere on screen and look indistinguishable from the user's own.
        origin = self.current_run_origin()
        if origin:
            marker = "[" + Utils.get_centrally_truncated_string(origin, 24) + "] "
            prepend_text = marker if prepend_text is None else marker + prepend_text

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
                from sd_runner.ui.sound_player import play_sound
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
        current_job_time = TimeEstimator.estimate_run_seconds(
            gen_config, total_jobs * remaining_count * gen_config.n_latents
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
        current_job_time = TimeEstimator.estimate_run_seconds(
            gen_config, total_jobs * gen_config.n_latents
        )
        logger.debug(f"Estimated time: {total_jobs} jobs, {current_job_time}s")
        return current_job_time

    # ------------------------------------------------------------------
    # Server callback
    # ------------------------------------------------------------------
    def server_run_callback(self, command_type, args: dict, client_id: str = ""):
        """Called by ``SDRunnerServer`` when a remote run request arrives.

        Runs on the listener thread and bridges only the parts that must happen
        on the GUI thread, so the listener is not held for the whole request.
        Takes the ``CommandType`` rather than a pre-resolved workflow: several
        commands select no workflow, so a null one would not say which arrived.
        """
        from extensions.sd_runner_server import CommandKind

        # A command that brought its own parameters is built from stored state
        # instead of being round-tripped through the sidebar, so it neither
        # disturbs what the user has open nor depends on it. last_settings is
        # the exception by definition -- reusing current settings is the point
        # of the command -- so it stays on the widget-backed path, which has to
        # run on the GUI thread in its entirety.
        if command_type is not None and command_type.kind is CommandKind.PARAMETERIZED_GENERATE:
            return self._run_virtual(command_type, args, client_id)
        if getattr(self._app, "sidebar_panel", None) is None:
            # "Reuse what is currently set" has no answer where nothing is set:
            # an application with no widgets has no current settings to reuse,
            # and inventing some would serve a different request than the one
            # the client made.
            logger.warning(
                f"Refused server request '{command_type}': no user interface to read"
            )
            return {"error": "no user interface", "data": str(command_type)}
        return self._on_main(self._run_from_widgets, command_type, args, client_id)

    def server_health_check(self, level: int = 1, timeout: int = 60,
                            software: str = "") -> dict:
        """Answer a client asking whether a backend is operational.

        Runs on the listener thread and bridges only the two quick UI reads it
        needs. Deliberately *not* wrapped at the wiring like the other
        callbacks: a level 2 check makes several HTTP requests and can take
        tens of seconds against a backend that is loading a model, and running
        that on the GUI thread would freeze the window for the duration.

        *software* names a specific backend; without it the one currently
        selected is checked. Answering about a backend other than the active
        one costs nothing here and saves the client from having to switch the
        selection to ask.

        *timeout* bounds the whole answer rather than each request within it.
        Four statuses come back, and the distinctions are the point: ``ok``,
        ``starting`` for one SD Runner is itself bringing up, ``timeout`` for
        one that is too slow to answer, and ``error`` for one that refuses.
        Only the last needs someone to go and look.
        """
        import time as _time

        from extensions.backend_health import check, check_functional
        from utils.globals import SoftwareType

        try:
            software_type = (SoftwareType[software] if software
                             else self._on_main(self._selected_software_type))
        except KeyError:
            return {"status": "error", "level": level,
                    "error": "unknown software", "detail": str(software)}

        if software_type.is_cloud():
            # Nothing local to reach; the API's own availability is its
            # business and is not something this app can speak to.
            return {"status": "ok", "level": level, "backend": software_type.value,
                    "note": "cloud_backend_no_local_check"}

        started = _time.monotonic()
        if level >= 2:
            result = check_functional(software_type, timeout=timeout)
        else:
            result = check(software_type, timeout=timeout)
        latency_ms = int((_time.monotonic() - started) * 1000)

        response = {
            "level": level,
            "backend": software_type.value,
            "latency_ms": latency_ms,
        }
        if not result.reachable:
            if self._backend_is_starting(software_type):
                # Autolaunch is what creates this window, so it is also what
                # has to explain it: a backend SD Runner is still bringing up
                # is not broken, and a client told "error" would give up on
                # something that will answer shortly.
                response.update(status="starting",
                                note="backend is still starting")
                return response
            response.update(
                status="timeout" if result.timed_out else "error",
                error=result.detail or "unreachable",
                detail=result.url,
            )
            return response

        response["status"] = "ok"
        if result.detail:
            response["note"] = result.detail
        # A run of our own in flight explains a non-idle backend, and is itself
        # evidence it is working -- so it is reported rather than diagnosed.
        if self._on_main(self._app.job_queue.has_pending):
            response["note"] = "generation_in_progress"
        return response

    def _selected_software_type(self):
        """The backend currently selected in the sidebar. GUI thread only."""
        from utils.globals import SoftwareType
        return SoftwareType[self._sp.software_combo.currentText()]

    def _backend_is_starting(self, software_type) -> bool:
        """Whether SD Runner is currently bringing this backend up itself."""
        from extensions.backend_process import starting_backends

        try:
            return software_type in starting_backends(
                getattr(self._app, "backend_processes", None)
            )
        except Exception:
            return False

    def _ensure_backend_started(self, run_args) -> None:
        """Ask the app window to start *run_args*'s backend, if it needs it.

        Called from ``_run_async``, the point every run path converges on
        before it touches the backend. An unrecognized ``software_type`` (a
        cloud backend, or a value that fails validation elsewhere) has no
        managed process to start, so it is left for ``Run`` to construct the
        generator and report whatever is actually wrong.
        """
        from utils.globals import SoftwareType

        try:
            software_type = SoftwareType[run_args.software_type]
        except KeyError:
            return
        self._app.ensure_backend_started(software_type)

    def server_revert_to_simple_gen(self, client_id: str = ""):
        """Server entry point for ``revert_to_simple_gen``.

        Separate from the method itself because that one is also exposed through
        ``AppActions``, where a UI caller correctly supplies no origin, so the
        naming of an unidentified client belongs at the server edge rather than
        inside a method both callers share.
        """
        if getattr(self._app, "sidebar_panel", None) is None:
            # The command means "put the workflow selector back to simple gen",
            # which is a state only a window holds.
            logger.warning("Refused revert_to_simple_gen: no user interface to set")
            return {"error": "no user interface", "data": "revert_to_simple_gen"}
        self.revert_to_simple_gen(origin=origin_for_client(client_id))
        return None

    def _promote_staged_request(self, command_type, args: dict, client_id: str = "") -> None:
        """Hand a staged request back to the run path, off the GUI thread.

        Every promotion site runs on the GUI thread, where ``_on_main`` is a
        direct call -- so calling ``server_run_callback`` from one would build
        the whole run there, including ``validate()`` and the directory scans
        ``_estimate_run`` performs when a size ceiling is configured. Starting a
        worker restores the split the listener-thread path already has: the
        widget sections bridge back, everything else stays off.

        ``ServerStagingQueue``'s no-lock invariant still holds. ``take()`` has
        already happened on the GUI thread at the call site, and the ``add()``
        this may reach is inside the bridged commit, so both ends of the queue
        remain main-thread only.
        """
        Utils.start_thread(
            self._run_promoted_async, use_asyncio=False, args=[command_type, args, client_id]
        )

    def _run_promoted_async(self, command_type, args: dict, client_id: str = "") -> None:
        """Worker body for _promote_staged_request."""
        try:
            result = self.server_run_callback(command_type, args, client_id)
        except Exception as e:
            logger.error(f"Promoted server request '{command_type}' failed: {e}")
            result = {"error": "promotion failed", "data": str(e)}
        if isinstance(result, dict) and result.get("error"):
            # Nothing was enqueued. The promoting site left the progress and
            # wake state in place expecting a run to follow, so release it if
            # nothing else has started meanwhile.
            self._on_main(self._clear_progress_if_idle)

    def _clear_progress_if_idle(self) -> None:
        """Release progress and wake state if no run followed. GUI thread only."""
        app = self._app
        if app.job_queue.job_running or app.job_queue.pending_jobs:
            return
        Utils.prevent_sleep(False)
        app.app_actions.clear_progress()

    def _stage_if_queue_full(self, command_type, args: dict, client_id: str = ""):
        """Stage the request if the run queue is full. GUI thread only.

        Returns a response dict when the request was staged (or could not be),
        or None when there is room and the caller should proceed. Kept together
        with the enqueue in one bridged section so the check and the act cannot
        be separated by another request.
        """
        app = self._app
        staging = getattr(app, "server_staging_queue", None)
        if staging is None or len(app.job_queue.pending_jobs) < app.job_queue.max_size:
            return None
        try:
            pos = staging.add(command_type, args, client_id)
            logger.info(
                f"Main run queue full ({app.job_queue.max_size}) — "
                f"staged server request at position {pos}"
            )
            return {"queued": "staged", "position": pos}
        except Exception as e:
            logger.error(f"Server staging queue full: {e}")
            return {"error": "staging queue full", "data": str(e)}

    def _run_from_widgets(self, command_type, args: dict, client_id: str = ""):
        """The widget-backed path, for commands that mean "use current settings".

        GUI thread only, start to finish: it reads and writes the sidebar and
        calls run(), which reads it again and may raise dialogs.

        Only CommandKind.CONTEXTUAL_GENERATE arrives here -- STATE commands are
        answered inside SDRunnerServer and every PARAMETERIZED_GENERATE goes to
        _run_virtual -- so the command selects no workflow, and the args this
        can honour are the ones that do not depend on one. An image or control
        net names the input of a particular workflow, which is what the
        parameterized commands carry; asking to reuse the current settings and
        also supplying one contradicts itself, so it is reported and ignored
        rather than guessed at.
        """
        from sd_runner.virtual_run_config import escape_path

        args = args or {}

        staged = self._stage_if_queue_full(command_type, args, client_id)
        if staged is not None:
            return staged

        sp = self._sp
        append = bool(args.get("append"))

        unsupported = [key for key in ("image", "control_net") if key in args]
        if unsupported:
            logger.warning(
                f"Server request '{command_type}' selects no workflow; "
                f"ignoring {', '.join(unsupported)}"
            )

        if "edit_suffix" in args:
            from sd_runner.presets_state import PresetsState
            edit_suffix = args["edit_suffix"]
            preset = PresetsState.get_preset_by_suffix(edit_suffix)
            if preset is not None:
                logger.info(f"Switching to preset '{preset.name}' for edit_suffix '{edit_suffix}'")
                sp.set_widgets_from_preset(preset, manual=False)
            else:
                logger.warning(f"No preset found with edit_suffix matching '{edit_suffix}'")

        if "target_dir" in args:
            sp.target_dir_entry.setText(str(args["target_dir"] or ""))

        if "source_prompt" in args:
            source_path = escape_path(args["source_prompt"])
            existing = sp.source_prompt_file_entry.text().strip()
            if append and existing:
                sp.source_prompt_file_entry.setText(existing + "," + source_path)
            else:
                sp.source_prompt_file_entry.setText(source_path)

        self.run(origin=origin_for_client(client_id))
        return {}

    def _divert_to_preset_schedule(self, workflow_type, request: dict) -> bool:
        """Hand a request's image to a running preset schedule instead of running it.

        A schedule owns the adapter fields for its whole duration, so starting a
        competing run would fight it for them. The schedule is the user's own,
        which is why this stays on the UI-coupled path.

        The requesting client is not carried across: only the image path is
        handed over, and the runs the schedule then starts are the user's own
        rather than the request's, so they carry no origin.
        """
        from sd_runner.virtual_run_config import escape_path
        from utils.globals import image_input_field

        app = self._app
        if "image" not in request:
            return False
        # Before the widget read, not after: a schedule is the user's own and
        # is started from the window, so an application without one can never
        # be running a schedule to divert to.
        if getattr(app, "sidebar_panel", None) is None:
            return False
        if not self._sp.run_preset_schedule_check.isChecked():
            return False
        if app.job_queue_preset_schedules is None or not app.job_queue_preset_schedules.has_pending():
            return False

        key = image_input_field(workflow_type)
        if key is None:
            return False

        app.job_queue_preset_schedules.add({key: escape_path(request["image"])})
        return True

    def _run_virtual(self, command_type, request: dict, client_id: str = ""):
        """Build and enqueue a server run without reading or writing the sidebar.

        Runs on the calling (listener) thread and bridges exactly two sections:
        one read of the shared state it starts from, and one to decide what
        happens to the finished run. The work between them -- the overlay, the
        validation, and the size estimate's directory scans -- is widget-free
        and stays off the GUI thread.
        """
        from sd_runner.virtual_run_config import build_from_base_args

        request = request or {}

        # Taken on the GUI thread: RunnerAppConfig and the preset list are
        # shared mutable state the UI writes as the user works, so reading them
        # from here could catch either mid-update. Everything after this works
        # on the snapshot. The schedule diversion is decided here too: it reads
        # the same UI state, and settling it before the build keeps a request
        # that only ever hands its image to a schedule from being built,
        # estimated, and possibly refused over a size ceiling for a run that
        # was never going to be queued.
        snapshot = self._on_main(self._snapshot_for_server_run, command_type, request)
        if snapshot is None:
            return {}
        base_args, preset = snapshot

        try:
            run_config = build_from_base_args(
                base_args, command_type, request, preset=preset
            )
            run_config.validate()
        except NoModelsFound as e:
            # Named separately from the generic rejection below so a client can
            # tell "this request was malformed" from "this runner currently has
            # no model to serve it with", which is not about the request at all.
            logger.error(f"Rejected server request '{command_type}': {e}")
            return {"error": "no models found", "data": str(e)}
        except Exception as e:
            # No dialog: there is no user at this end to answer one, and a modal
            # here would block the listener thread waiting on this call.
            logger.error(f"Rejected server request '{command_type}': {e}")
            return {"error": "invalid run config", "data": str(e)}

        rejection = self._server_run_exceeds_ceiling(command_type, run_config)
        if rejection is not None:
            return rejection

        run_config.run_origin = origin_for_client(client_id)
        return self._on_main(
            self._commit_server_run, command_type, request, run_config, client_id
        )

    def _snapshot_for_server_run(self, command_type, request: dict):
        """Return ``(base_args, preset)`` for one request. GUI thread only.

        One consistent read of the shared state a virtual run starts from, or
        None when the request was handed to a running preset schedule instead
        and there is no run to build.
        """
        from sd_runner.virtual_run_config import base_args_from_app_config

        workflow_type = command_type.workflow_type if command_type is not None else None
        if self._divert_to_preset_schedule(workflow_type, request):
            return None

        # A request brings only its own parameters -- the model, resolutions,
        # counts and the rest come from the stored config -- and most of those
        # fields reach it only when the user starts a run of their own. Without
        # this the request would be served with the settings as of that run
        # rather than the ones the sidebar is showing. Absent on a headless
        # application object, which has no widgets to be ahead of the config.
        sync = getattr(self._app, "sync_config_from_widgets", None)
        if sync is not None:
            sync()

        base_args = base_args_from_app_config(self._app.runner_app_config)
        # Set here because the pre-pass is held on PresetsState, deliberately
        # not on RunnerAppConfig, so base_args_from_app_config cannot reach it
        # from the config it is given.
        base_args["intermediate_prompt"] = self._app.active_intermediate_prompt()

        preset = None
        if "edit_suffix" in request:
            from sd_runner.presets_state import PresetsState
            edit_suffix = request["edit_suffix"]
            preset = PresetsState.get_preset_by_suffix(edit_suffix)
            if preset is None:
                logger.warning(f"No preset found with edit_suffix matching '{edit_suffix}'")
            else:
                logger.info(f"Applying preset '{preset.name}' for edit_suffix '{edit_suffix}'")

        return base_args, preset

    def _commit_server_run(self, command_type, request: dict, run_config, client_id: str = ""):
        """Decide what happens to a built server run. GUI thread only.

        The queue-full check and the enqueue live together here so they cannot
        be separated by another request arriving in between -- the check and
        the act have to be one section, and this is the only part of a virtual
        run that touches a widget or the queues.
        """
        staged = self._stage_if_queue_full(command_type, request, client_id)
        if staged is not None:
            return staged

        self._enqueue_run(run_config)
        return {}

    def _server_run_exceeds_ceiling(self, command_type, run_config):
        """Return an error response if the run is too large to accept unattended.

        The interactive path asks the user to confirm a long run. A server
        request has nobody to ask, and a modal would block the listener thread
        waiting on this call, so an over-size request is refused with an answer
        the client can act on instead. Unset (0 or less) means no ceiling.
        """
        from utils.config import config
        from utils.time_estimator import TimeEstimator

        try:
            ceiling = float(getattr(config, "server_run_max_seconds", 0) or 0)
        except (TypeError, ValueError):
            return None
        if ceiling <= 0:
            return None

        try:
            estimated_seconds, estimated_image_count = self._estimate_run(run_config)
        except NoModelsFound as e:
            logger.error(f"Rejected server request '{command_type}': {e}")
            return {"error": "no models found", "data": str(e)}
        except Exception as e:
            # An estimate is a guard, not a precondition -- a failure to compute
            # one should not stop a run the user's own path would have accepted.
            logger.warning(f"Could not estimate server request '{command_type}': {e}")
            return None

        if estimated_seconds > ceiling:
            logger.warning(
                f"Rejected server request '{command_type}': estimated "
                f"{TimeEstimator.format_time(estimated_seconds)} for "
                f"{estimated_image_count} image(s), over the "
                f"{TimeEstimator.format_time(ceiling)} ceiling"
            )
            return {
                "error": "run too large",
                "data": {
                    "estimated_seconds": estimated_seconds,
                    "estimated_image_count": estimated_image_count,
                    "ceiling_seconds": ceiling,
                },
            }
        return None

    def server_batch_enqueue(self, requests: list, client_id: str = "") -> dict:
        """Add all batch items from a run_batch command directly to ServerStagingQueue.

        Called via the _MainThreadBridge as a single bridge call for the whole
        batch, avoiding the per-item BlockingQueuedConnection calls that previously
        caused crashes under high request volume.
        """
        from extensions.sd_runner_server import CommandType

        app = self._app
        staging = getattr(app, "server_staging_queue", None)
        if staging is None:
            return {"error": "staging queue not available", "count": 0}

        enqueued = 0
        rejected = 0
        for req in requests:
            type_str = req.get('type', '')
            try:
                command_type = CommandType.resolve(type_str)
            except ValueError:
                logger.warning("server_batch_enqueue: unknown command type %r, skipping", type_str)
                continue
            if not command_type.is_batchable():
                logger.warning("server_batch_enqueue: skipping unbatchable type %r", type_str)
                continue
            try:
                staging.add(command_type, command_type.normalize_args(req.get('args')), client_id)
                enqueued += 1
            except Exception:
                rejected += 1

        if rejected:
            logger.warning(
                "server_batch_enqueue: staging queue full — %d of %d request(s) rejected",
                rejected, rejected + enqueued,
            )
        logger.info("server_batch_enqueue: staged %d item(s)", enqueued)

        # If nothing is running yet, promote the first staging item so work starts immediately.
        if enqueued > 0 and not app.job_queue.has_pending():
            staged = staging.take()
            if staged is not None:
                command_type, staged_args, staged_client = staged
                self._promote_staged_request(command_type, staged_args, staged_client)

        return {"count": enqueued}

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
        # Outside the try: the ImportError branch below quits through it too, so
        # it has to be bound before anything can raise.
        from PySide6.QtWidgets import QApplication
        try:
            from sd_runner.ui.presets.scheduled_shutdown_dialog import ScheduledShutdownDialog
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

"""
PromptConfigWindow -- detailed prompt configuration settings (PySide6 port).

Ported from ``ui/prompt_config_window.py``.

**Status: Shell only** -- static class helpers and the ``__init__`` signature
are wired; the full UI (concept-count dropdowns, chance sliders, checkboxes)
still needs to be built.

.. note::

    **Integration with ``AppWindow``**

    Unlike most secondary windows, ``PromptConfigWindow`` needs tighter
    coupling with the main ``AppWindow``:

    * It receives and mutates the shared ``RunnerAppConfig`` instance
      (``app_window.runner_app_config``).  All widget-change callbacks
      write directly back into that config so that the next generation
      run picks up the updated values.

    * The class-level ``set_args_from_prompter_config()`` is called by
      ``RunController`` / ``app_window`` at run time to push the live
      widget values into the ``RunConfig`` args just before a job is
      submitted.

    * ``WindowLauncher.open_prompt_config_window()`` instantiates this
      window, passing the current ``runner_app_config``.  The window
      must **not** copy the config -- it must reference the *same* object.

    * On close, ``set_prompt_config_window_instance(None)`` clears the
      class-level reference so subsequent calls know to create a new
      window.

    When the full UI is built, ``_build_ui`` should mirror the two-column
    layout of the original (basic generation settings on the left, concept
    count dropdowns + chance sliders on the right), using ``QFormLayout``
    or ``QGridLayout``.  ``QComboBox`` replaces ``OptionMenu``,
    ``QSlider`` replaces ``Scale``, ``QCheckBox`` replaces ``Checkbutton``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from lib.multi_display_qt import SmartDialog
from sd_runner.base_image_generator import BaseImageGenerator
from sd_runner.prompter_configuration import PrompterConfiguration
from sd_runner.prompter import Prompter
from sd_runner.run_config import RunConfig
from ui_qt.app_style import AppStyle
from utils.globals import Sampler, Scheduler
from utils.runner_app_config import RunnerAppConfig
from utils.translations import I18N

if TYPE_CHECKING:
    from ui.app_actions import AppActions

_ = I18N._


class PromptConfigWindow(SmartDialog):
    """
    Detailed prompt configuration -- concept counts, chance sliders,
    generation parameters (seed, steps, CFG, denoise, sampler, scheduler),
    and boolean flags (override negative, tags at start, sparse mix, etc.).
    """

    _runner_app_config: RunnerAppConfig = RunnerAppConfig()
    _prompt_config_window_instance: Optional[PromptConfigWindow] = None

    # ------------------------------------------------------------------
    # Class-level accessors (called by RunController / AppWindow)
    # ------------------------------------------------------------------
    @classmethod
    def set_runner_app_config(cls, runner_app_config: RunnerAppConfig) -> None:
        cls._runner_app_config = runner_app_config

    @classmethod
    def get_runner_app_config(cls) -> RunnerAppConfig:
        return cls._runner_app_config

    @classmethod
    def set_prompt_config_window_instance(cls, instance: Optional[PromptConfigWindow]) -> None:
        cls._prompt_config_window_instance = instance

    @classmethod
    def get_prompt_config_window_instance(cls) -> Optional[PromptConfigWindow]:
        return cls._prompt_config_window_instance

    @classmethod
    def set_args_from_prompter_config(cls, args: RunConfig) -> None:
        """Push current widget / config values into *args* before a run."""
        if cls._prompt_config_window_instance is not None:
            cls._prompt_config_window_instance._sync_config_from_widgets()

        cfg = cls._runner_app_config
        args.seed = int(cfg.seed)
        args.steps = int(cfg.steps)
        args.cfg = float(cfg.cfg)
        args.sampler = Sampler.get(cfg.sampler)
        args.scheduler = Scheduler.get(cfg.scheduler)
        args.denoise = float(cfg.denoise)
        BaseImageGenerator.RANDOM_SKIP_CHANCE = float(cfg.random_skip_chance)
        Prompter.set_tags_apply_to_start(cfg.tags_apply_to_start)
        args.continuous_seed_variation = cfg.continuous_seed_variation
        cfg.prompter_config.sparse_mixed_tags = cfg.sparse_mixed_tags

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __init__(
        self,
        parent: QWidget,
        app_actions: AppActions,
        runner_app_config: RunnerAppConfig,
        geometry: str = "1000x700",
    ):
        super().__init__(
            parent=parent,
            title=_("Prompt Configuration"),
            geometry=geometry,
        )
        self.setStyleSheet(AppStyle.apply_stylesheet())
        self._app_actions = app_actions
        self._cfg = runner_app_config

        # Wire class-level references
        self.__class__.set_runner_app_config(runner_app_config)
        self.__class__.set_prompt_config_window_instance(self)

        self._build_ui()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.close)
        self.show()

    # ------------------------------------------------------------------
    # UI (placeholder -- to be filled in)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """
        TODO: Build the full two-column layout.

        Left column (basic generation settings):
            - Sampler ``QComboBox``
            - Scheduler ``QComboBox``
            - Seed / Steps / CFG / Denoise ``QLineEdit``
            - Random Skip Chance ``QLineEdit``
            - Multiplier ``QComboBox``
            - Checkboxes: Override Negative, Tags at Start, Sparse Mixed,
              Continuous Seed Variation

        Right column (prompts configuration):
            - Concept-count dropdowns (low/high) for each category
              (concepts, positions, locations, animals, colors, times,
              dress, expressions, actions, descriptions, characters,
              random_words, nonsense, jargon, witticisms)
            - Chance sliders (specific locations, specific times,
              specify humans, art styles, emphasis, animals inclusion,
              dress inclusion)
            - Witticisms ratio slider (sayings / puns)

        Close button at bottom.
        """
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel(_("Detailed Prompt Configuration"))
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        root.addWidget(title)

        placeholder = QLabel(
            _("(Full prompt configuration UI is not yet implemented.\n"
              "Generation settings are still managed via the Tkinter backend.)")
        )
        placeholder.setWordWrap(True)
        root.addWidget(placeholder)

        root.addStretch()

        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Config sync (to be completed with widget reads)
    # ------------------------------------------------------------------
    def _sync_config_from_widgets(self) -> None:
        """Read all widget values back into ``self._cfg``.

        TODO: implement when the full UI is built.
        """
        pass  # placeholder

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        self.__class__.set_prompt_config_window_instance(None)
        super().closeEvent(event)

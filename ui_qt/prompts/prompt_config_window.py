"""
PromptConfigWindow -- detailed prompt configuration settings (PySide6 port).

Ported from ``ui/prompt_config_window.py``.

**Integration with ``AppWindow``:**

* Receives and mutates the shared ``RunnerAppConfig`` instance
  (``app_window.runner_app_config``).  All widget-change callbacks write
  directly back into that config so the next generation run picks up the
  updated values.
* The class-level ``set_args_from_prompter_config()`` is called by
  ``RunController`` / ``app_window`` just before a job is submitted.
* On close, ``set_prompt_config_window_instance(None)`` clears the
  singleton so subsequent calls create a new window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from lib.multi_display_qt import SmartDialog
from lib.tooltip_qt import create_tooltip
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

# Range 0..50 for concept-count dropdowns
_COUNT_ITEMS = [str(i) for i in range(51)]

# Multiplier options (matches original ordering)
_MULTIPLIER_ITEMS: list[str] = []
_base = [str(i) for i in range(8)]
_base.insert(2, "1.5")
_base.insert(1, "0.75")
_base.insert(1, "0.5")
_base.insert(1, "0.25")
_base.insert(1, "0.1")
_MULTIPLIER_ITEMS = _base


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
        geometry: str = "1050x720",
    ):
        super().__init__(
            parent=parent,
            title=_("Prompt Configuration"),
            geometry=geometry,
        )
        self.setStyleSheet(AppStyle.get_stylesheet())
        self._app_actions = app_actions
        self._cfg = runner_app_config
        self._updating = False  # guard against recursive signal loops

        # Wire class-level references
        self.__class__.set_runner_app_config(runner_app_config)
        self.__class__.set_prompt_config_window_instance(self)

        # Dicts to hold category combo refs: name -> (low_combo, high_combo)
        self._cat_combos: dict[str, tuple[QComboBox, QComboBox]] = {}
        # Slider refs: name -> QSlider
        self._sliders: dict[str, QSlider] = {}

        self._build_ui()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.close)
        self.show()

    # ==================================================================
    # UI construction
    # ==================================================================
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # Title
        title = QLabel(_("Detailed Prompt Configuration"))
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        root.addWidget(title)

        # Scrollable body with two columns
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(16)

        # --- Left column (basic generation) ---
        left = QVBoxLayout()
        left.setSpacing(4)
        self._build_left_column(left)
        body_layout.addLayout(left)

        # --- Right column (prompts configuration) ---
        right = QVBoxLayout()
        right.setSpacing(4)
        self._build_right_column(right)
        body_layout.addLayout(right)

        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        # Close button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Left column
    # ------------------------------------------------------------------
    def _build_left_column(self, col: QVBoxLayout) -> None:
        col.addWidget(self._section_label(_("Basic Generation Settings")))

        pc = self._cfg.prompter_config
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        r = 0

        # Sampler
        grid.addWidget(QLabel(_("Sampler")), r, 0)
        self._sampler_combo = QComboBox()
        self._sampler_combo.addItems(Sampler.display_values())
        self._sampler_combo.setCurrentText(
            Sampler.get(self._cfg.sampler).display()
        )
        self._sampler_combo.currentTextChanged.connect(self._on_widget_changed)
        grid.addWidget(self._sampler_combo, r, 1, 1, 2)
        r += 1

        # Scheduler
        grid.addWidget(QLabel(_("Scheduler")), r, 0)
        self._scheduler_combo = QComboBox()
        self._scheduler_combo.addItems(Scheduler.display_values())
        self._scheduler_combo.setCurrentText(
            Scheduler.get(self._cfg.scheduler).display()
        )
        self._scheduler_combo.currentTextChanged.connect(self._on_widget_changed)
        grid.addWidget(self._scheduler_combo, r, 1, 1, 2)
        r += 1

        # Seed / Steps / CFG / Denoise / Random Skip
        for label_text, attr, width in [
            (_("Seed"), "seed", 10),
            (_("Steps"), "steps", 6),
            (_("CFG"), "cfg", 6),
            (_("Denoise"), "denoise", 6),
            (_("Random Skip Chance"), "random_skip_chance", 6),
        ]:
            grid.addWidget(QLabel(label_text), r, 0)
            le = QLineEdit(str(getattr(self._cfg, attr)))
            le.setMaximumWidth(120)
            le.textChanged.connect(self._on_widget_changed)
            setattr(self, f"_edit_{attr}", le)
            grid.addWidget(le, r, 1, 1, 2)
            r += 1

        # Multiplier
        grid.addWidget(QLabel(_("Multiplier")), r, 0)
        self._multiplier_combo = QComboBox()
        self._multiplier_combo.addItems(_MULTIPLIER_ITEMS)
        self._multiplier_combo.setCurrentText(str(pc.multiplier))
        self._multiplier_combo.currentTextChanged.connect(self._on_widget_changed)
        grid.addWidget(self._multiplier_combo, r, 1, 1, 2)
        r += 1

        col.addLayout(grid)

        # --- Checkboxes ---------------------------------------------------
        col.addWidget(self._section_label(_("Options")))
        self._cb_override_negative = QCheckBox(_("Override Base Negative"))
        self._cb_override_negative.setChecked(bool(self._cfg.override_negative))
        self._cb_override_negative.stateChanged.connect(self._on_widget_changed)
        col.addWidget(self._cb_override_negative)

        self._cb_tags_at_start = QCheckBox(_("Tags Applied to Prompt Start"))
        self._cb_tags_at_start.setChecked(bool(self._cfg.tags_apply_to_start))
        self._cb_tags_at_start.stateChanged.connect(self._on_widget_changed)
        col.addWidget(self._cb_tags_at_start)

        self._cb_sparse_mix = QCheckBox(_("Sparse Mixed Tags"))
        self._cb_sparse_mix.setChecked(bool(pc.sparse_mixed_tags))
        self._cb_sparse_mix.stateChanged.connect(self._on_widget_changed)
        col.addWidget(self._cb_sparse_mix)

        self._cb_continuous_seed = QCheckBox(_("Continuous Seed Variation"))
        self._cb_continuous_seed.setChecked(bool(self._cfg.continuous_seed_variation))
        self._cb_continuous_seed.stateChanged.connect(self._on_widget_changed)
        col.addWidget(self._cb_continuous_seed)

        col.addStretch()

    # ------------------------------------------------------------------
    # Right column
    # ------------------------------------------------------------------
    def _build_right_column(self, col: QVBoxLayout) -> None:
        pc = self._cfg.prompter_config

        col.addWidget(self._section_label(_("Prompts Configuration")))

        # --- Category count combos ----------------------------------------
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.addWidget(QLabel(_("Category")), 0, 0)
        grid.addWidget(QLabel(_("Low")), 0, 1)
        grid.addWidget(QLabel(_("High")), 0, 2)

        categories = [
            "concepts", "positions", "locations", "animals", "colors",
            "times", "dress", "expressions", "actions", "descriptions",
            "characters", "random_words", "nonsense", "jargon", "witticisms",
        ]
        for i, name in enumerate(categories, start=1):
            cc = pc.get_category_config(name)
            display_name = name.replace("_", " ").title()
            grid.addWidget(QLabel(_(display_name)), i, 0)
            lo = QComboBox()
            lo.addItems(_COUNT_ITEMS)
            lo.setCurrentText(str(cc.low))
            lo.currentTextChanged.connect(self._on_widget_changed)
            hi = QComboBox()
            hi.addItems(_COUNT_ITEMS)
            hi.setCurrentText(str(cc.high))
            hi.currentTextChanged.connect(self._on_widget_changed)
            grid.addWidget(lo, i, 1)
            grid.addWidget(hi, i, 2)
            self._cat_combos[name] = (lo, hi)

        col.addLayout(grid)

        # --- Witticisms ratio slider --------------------------------------
        col.addWidget(self._section_label(_("Subcategory Weights")))
        witt_row = QHBoxLayout()
        lbl = QLabel(_("Sayings / Puns Ratio"))
        create_tooltip(
            lbl,
            _("0 = mostly sayings, 50 = equal blend, 100 = mostly puns"),
        )
        witt_row.addWidget(lbl)
        self._witticisms_slider = QSlider(Qt.Orientation.Horizontal)
        self._witticisms_slider.setRange(0, 100)
        ratio = pc.get_witticisms_ratio()
        self._witticisms_slider.setValue(int(max(0, min(100, ratio * 100))))
        self._witticisms_slider.valueChanged.connect(self._on_widget_changed)
        self._sliders["witticisms_ratio"] = self._witticisms_slider
        witt_row.addWidget(self._witticisms_slider, stretch=1)
        col.addLayout(witt_row)

        # --- Chance sliders -----------------------------------------------
        col.addWidget(self._section_label(_("Chance Sliders")))
        slider_defs = [
            (_("Specific Locations Chance"), "specific_locations",
             pc.get_specific_locations_chance()),
            (_("Specific Times Chance"), "specific_times",
             pc.get_specific_times_chance()),
            (_("Specify Humans Chance"), "specify_humans",
             pc.specify_humans_chance),
            (_("Art Styles Chance"), "art_styles",
             pc.art_styles_chance),
            (_("Emphasis Chance"), "emphasis",
             pc.emphasis_chance),
            (_("Animals Inclusion Chance"), "animals_inclusion",
             pc.get_category_config("animals").get_inclusion_chance()),
            (_("Dress Inclusion Chance"), "dress_inclusion",
             pc.get_category_config("dress").get_inclusion_chance()),
        ]
        for label_text, key, initial in slider_defs:
            row = QHBoxLayout()
            row.addWidget(QLabel(label_text))
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(int(float(initial) * 100))
            sl.valueChanged.connect(self._on_widget_changed)
            self._sliders[key] = sl
            row.addWidget(sl, stretch=1)
            col.addLayout(row)

        col.addStretch()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 12pt; font-weight: bold; margin-top: 8px;")
        return lbl

    # ==================================================================
    # Widget → Config sync
    # ==================================================================
    def _on_widget_changed(self, *_args) -> None:
        """Debounced handler -- push all widget values into the config."""
        if self._updating:
            return
        self._updating = True
        try:
            self._sync_config_from_widgets()
        finally:
            self._updating = False

    def _sync_config_from_widgets(self) -> None:
        """Read all widget values back into ``self._cfg``."""
        try:
            cfg = self._cfg
            pc: PrompterConfiguration = cfg.prompter_config

            # --- Basic generation settings --------------------------------
            cfg.sampler = Sampler.from_display(self._sampler_combo.currentText()).name
            cfg.scheduler = Scheduler.from_display(self._scheduler_combo.currentText()).name
            cfg.seed = self._edit_seed.text().strip() or "-1"
            cfg.steps = self._edit_steps.text().strip() or "-1"
            cfg.cfg = self._edit_cfg.text().strip() or "-1"
            cfg.denoise = self._edit_denoise.text().strip() or "-1"
            cfg.random_skip_chance = self._edit_random_skip_chance.text().strip() or "0"
            try:
                pc.multiplier = float(self._multiplier_combo.currentText())
            except ValueError:
                pass

            # --- Checkboxes -----------------------------------------------
            cfg.override_negative = self._cb_override_negative.isChecked()
            cfg.tags_apply_to_start = self._cb_tags_at_start.isChecked()
            cfg.sparse_mixed_tags = self._cb_sparse_mix.isChecked()
            pc.sparse_mixed_tags = cfg.sparse_mixed_tags
            cfg.continuous_seed_variation = self._cb_continuous_seed.isChecked()

            # --- Category counts ------------------------------------------
            for name, (lo_cb, hi_cb) in self._cat_combos.items():
                lo = int(lo_cb.currentText())
                hi = int(hi_cb.currentText())
                extra: dict = {}
                if name == "locations":
                    extra["specific_chance"] = self._sliders["specific_locations"].value() / 100.0
                elif name == "times":
                    extra["specific_chance"] = self._sliders["specific_times"].value() / 100.0
                elif name == "animals":
                    extra["inclusion_chance"] = self._sliders["animals_inclusion"].value() / 100.0
                elif name == "dress":
                    extra["inclusion_chance"] = self._sliders["dress_inclusion"].value() / 100.0
                pc.set_category(name, lo, hi, **extra)

            # --- Witticisms ratio slider ----------------------------------
            ratio = self._witticisms_slider.value() / 100.0
            total_weight = 2.0
            pc.set_witticisms_weights(
                sayings_weight=(1.0 - ratio) * total_weight,
                puns_weight=ratio * total_weight,
            )

            # --- Remaining chance sliders ---------------------------------
            pc.set_specific_locations_chance(self._sliders["specific_locations"].value() / 100.0)
            pc.set_specific_times_chance(self._sliders["specific_times"].value() / 100.0)
            pc.specify_humans_chance = self._sliders["specify_humans"].value() / 100.0
            pc.art_styles_chance = self._sliders["art_styles"].value() / 100.0
            pc.emphasis_chance = self._sliders["emphasis"].value() / 100.0
            pc.get_category_config("animals").inclusion_chance = (
                self._sliders["animals_inclusion"].value() / 100.0
            )
            pc.get_category_config("dress").inclusion_chance = (
                self._sliders["dress_inclusion"].value() / 100.0
            )

        except (ValueError, AttributeError, KeyError):
            # Ignore transient errors (empty fields, missing keys, etc.)
            pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        # Final sync before closing
        self._sync_config_from_widgets()
        self.__class__.set_prompt_config_window_instance(None)
        super().closeEvent(event)

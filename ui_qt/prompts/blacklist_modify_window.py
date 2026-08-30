"""
BlacklistModifyWindow -- edit a single blacklist item.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from lib.multi_display_qt import SmartDialog
from sd_runner.blacklist import BlacklistItem
from ui_qt.auth.password_utils import require_password
from ui_qt.window_focus import clear_class_ref_if_self
from utils.globals import ProtectedActions
from utils.translations import I18N

if TYPE_CHECKING:
    from ui_qt.app_actions import AppActions

_ = I18N._


class BlacklistModifyWindow(SmartDialog):
    """Edit or create a single :class:`BlacklistItem`."""

    def __init__(
        self,
        parent: QWidget,
        refresh_callback: Callable,
        blacklist_item: Optional[BlacklistItem],
        app_actions: AppActions,
        geometry: str = "600x400",
        is_model: bool = False,
    ):
        self._is_new = blacklist_item is None
        self._is_model = is_model
        self._item = (
            BlacklistItem("", enabled=True, use_regex=False,
                          use_word_boundary=True, use_space_as_optional_nonword=True)
            if self._is_new else blacklist_item
        )
        self._original_string = "" if self._is_new else self._item.string

        super().__init__(
            parent=parent,
            title=_("Modify Blacklist Item: {0}").format(self._item.string),
            geometry=geometry,
        )
        self._refresh_callback = refresh_callback
        self._app_actions = app_actions
        self._saved = False  # set True after successful save to skip closeEvent re-check

        # Store original values for change tracking
        self._original_values = {
            "string": self._original_string,
            "enabled": self._item.enabled,
            "use_regex": self._item.use_regex,
            "use_word_boundary": self._item.use_word_boundary,
            "use_space_as_optional_nonword": getattr(self._item, "use_space_as_optional_nonword", False),
            "exception_pattern": getattr(self._item, "exception_pattern", "") or "",
            "apply_to_whole_prompt": getattr(self._item, "apply_to_whole_prompt", False),
            "apply_to_prompt_tags": getattr(self._item, "apply_to_prompt_tags", True),
        }

        root = QVBoxLayout(self)

        # --- String field ---------------------------------------------------
        root.addWidget(QLabel(_("Blacklist String")))
        self._string_entry = QLineEdit(self._original_string)
        root.addWidget(self._string_entry)

        # --- Checkboxes -----------------------------------------------------
        self._enabled_cb = QCheckBox(_("Enabled"))
        self._enabled_cb.setChecked(self._item.enabled)
        root.addWidget(self._enabled_cb)

        self._regex_cb = QCheckBox(_("Use glob-based regex"))
        self._regex_cb.setChecked(self._item.use_regex)
        root.addWidget(self._regex_cb)

        self._boundary_cb = QCheckBox(_("Use word boundary matching"))
        self._boundary_cb.setChecked(self._item.use_word_boundary)
        root.addWidget(self._boundary_cb)

        self._space_cb = QCheckBox(_("Convert spaces to optional non-word characters"))
        self._space_cb.setChecked(getattr(self._item, "use_space_as_optional_nonword", False))
        root.addWidget(self._space_cb)

        # --- Exception pattern ----------------------------------------------
        root.addWidget(QLabel(_("Exception Pattern (optional regex to unfilter tags)")))
        self._exception_entry = QLineEdit(getattr(self._item, "exception_pattern", "") or "")
        root.addWidget(self._exception_entry)

        # --- Whole-prompt matching (tag items only) --------------------------
        self._whole_prompt_cb = QCheckBox(_("Apply to whole prompt (match full text, not individual tags)"))
        self._whole_prompt_cb.setChecked(getattr(self._item, "apply_to_whole_prompt", False))
        if is_model:
            self._whole_prompt_cb.setVisible(False)
        root.addWidget(self._whole_prompt_cb)

        # --- Whether the user's own wording is checked (tag items only) ------
        self._prompt_tags_cb = QCheckBox(_("Apply to prompt tags (check what you type, not just generated content)"))
        self._prompt_tags_cb.setToolTip(
            _("Uncheck to keep filtering this term out of generated content while "
              "still allowing it in prompt tags you write yourself.")
        )
        self._prompt_tags_cb.setChecked(getattr(self._item, "apply_to_prompt_tags", True))
        if is_model:
            self._prompt_tags_cb.setVisible(False)
        root.addWidget(self._prompt_tags_cb)

        # --- Buttons --------------------------------------------------------
        btn_row = QHBoxLayout()
        preview_btn = QPushButton(_("Preview"))
        preview_btn.clicked.connect(self._preview)
        btn_row.addWidget(preview_btn)
        done_btn = QPushButton(_("Done"))
        done_btn.clicked.connect(self._finalize)
        btn_row.addWidget(done_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        root.addStretch()

        QShortcut(QKeySequence("Escape"), self, self._close_with_check)
        self.show()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _has_changes(self) -> bool:
        s = self._string_entry.text().strip()
        if self._is_new:
            return s != ""
        return {
            "string": s,
            "enabled": self._enabled_cb.isChecked(),
            "use_regex": self._regex_cb.isChecked(),
            "use_word_boundary": self._boundary_cb.isChecked(),
            "use_space_as_optional_nonword": self._space_cb.isChecked(),
            "exception_pattern": self._exception_entry.text().strip(),
            "apply_to_whole_prompt": self._whole_prompt_cb.isChecked(),
            "apply_to_prompt_tags": self._prompt_tags_cb.isChecked(),
        } != self._original_values

    def _validate_and_build(self) -> Optional[BlacklistItem]:
        s = self._string_entry.text().strip()
        if not s:
            self._app_actions.alert(
                _("Error"), _("Blacklist string cannot be empty."),
                kind="error", master=self,
            )
            return None
        exc = self._exception_entry.text().strip() or None
        return BlacklistItem(
            string=s,
            enabled=self._enabled_cb.isChecked(),
            use_regex=self._regex_cb.isChecked(),
            use_word_boundary=self._boundary_cb.isChecked(),
            use_space_as_optional_nonword=self._space_cb.isChecked(),
            exception_pattern=exc,
            apply_to_whole_prompt=self._whole_prompt_cb.isChecked(),
            apply_to_prompt_tags=self._prompt_tags_cb.isChecked(),
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _preview(self) -> None:
        temp = self._validate_and_build()
        if temp is None:
            return
        from ui_qt.prompts.blacklist_preview_window import BlacklistPreviewWindow
        BlacklistPreviewWindow(self, None, temp)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _finalize(self) -> None:
        if not self._has_changes():
            self._saved = True
            self.close()
            self._app_actions.toast(_("No changes were made"))
            return
        item = self._validate_and_build()
        if item is None:
            return
        self._saved = True
        self.close()
        self._refresh_callback(item, self._is_new, self._original_string)

    def _close_with_check(self) -> None:
        if self._has_changes():
            resp = self._app_actions.alert(
                _("Unsaved Changes"),
                _("Do you want to save changes before closing?"),
                kind="askyesnocancel",
                master=self,
            )
            if resp is True:
                self._finalize()
            elif resp is False:
                self._saved = True  # skip closeEvent re-prompt
                self.close()
            # None (Cancel) → keep open
        else:
            self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._saved or not self._has_changes():
            from ui_qt.prompts.blacklist_window import BlacklistWindow
            clear_class_ref_if_self(BlacklistWindow, "_modify_window", self)
            event.accept()
            return
        resp = self._app_actions.alert(
            _("Unsaved Changes"),
            _("Do you want to save changes before closing?"),
            kind="askyesnocancel",
            master=self,
        )
        if resp is True:
            item = self._validate_and_build()
            if item is not None:
                self._saved = True
                from ui_qt.prompts.blacklist_window import BlacklistWindow
                clear_class_ref_if_self(BlacklistWindow, "_modify_window", self)
                event.accept()
                self._refresh_callback(item, self._is_new, self._original_string)
                return
            event.ignore()
            return
        elif resp is False:
            from ui_qt.prompts.blacklist_window import BlacklistWindow
            clear_class_ref_if_self(BlacklistWindow, "_modify_window", self)
            event.accept()
            return
        else:
            event.ignore()

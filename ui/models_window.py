import tkinter.font as fnt
from tkinter import Toplevel, Frame, Label, StringVar, Entry, Listbox, SINGLE, END
from tkinter.ttk import Button, Notebook

from ui.app_style import AppStyle
from sd_runner.models import Model
from utils.translations import I18N

_ = I18N._


class ModelsWindow:
    top_level = None

    def __init__(self, master, app_actions):
        ModelsWindow.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        ModelsWindow.top_level.title(_("Models"))
        ModelsWindow.top_level.geometry("800x600")

        self.master = ModelsWindow.top_level
        self.app_actions = app_actions

        # Ensure models are loaded
        Model.load_all_if_unloaded()

        # Main frame
        self.frame = Frame(self.master, bg=AppStyle.BG_COLOR)
        self.frame.grid(column=0, row=0, sticky="nsew", padx=10, pady=10)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)

        # Notebook
        self.notebook = Notebook(self.frame)
        self.notebook.grid(column=0, row=0, sticky="nsew")

        # Tabs
        self.checkpoints_tab = Frame(self.notebook, bg=AppStyle.BG_COLOR)
        self.adapters_tab = Frame(self.notebook, bg=AppStyle.BG_COLOR)
        self.notebook.add(self.checkpoints_tab, text=_("Checkpoints"))
        self.notebook.add(self.adapters_tab, text=_("LoRAs & Adapters"))

        # Build each tab
        self._build_checkpoints_tab()
        self._build_adapters_tab()

        # Close binding
        self.master.bind("<Escape>", lambda e: self.master.destroy())
        self.master.protocol("WM_DELETE_WINDOW", self.master.destroy)

    def _build_checkpoints_tab(self):
        self.checkpoints_tab.columnconfigure(0, weight=1)
        self.checkpoints_tab.rowconfigure(2, weight=1)
        # Filter
        Label(self.checkpoints_tab, text=_("Filter"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR).grid(column=0, row=0, sticky="w")
        self.cp_filter = StringVar(self.master)
        self.cp_filter_entry = Entry(self.checkpoints_tab, textvariable=self.cp_filter, width=40, font=fnt.Font(size=9))
        self.cp_filter_entry.grid(column=0, row=1, sticky="we", pady=(0, 6))
        # List
        self.cp_listbox = Listbox(self.checkpoints_tab, selectmode=SINGLE, font=fnt.Font(size=9))
        self.cp_listbox.grid(column=0, row=2, sticky="nsew")
        # Buttons
        btn_frame = Frame(self.checkpoints_tab, bg=AppStyle.BG_COLOR)
        btn_frame.grid(column=0, row=3, sticky="we", pady=(6, 0))
        replace_btn = Button(btn_frame, text=_("Replace"), command=lambda: self._select_checkpoint(replace=True))
        replace_btn.grid(column=0, row=0, padx=(0, 6))
        add_btn = Button(btn_frame, text=_("Add"), command=lambda: self._select_checkpoint(replace=False))
        add_btn.grid(column=1, row=0, padx=(0, 6))
        close_btn = Button(btn_frame, text=_("Close"), command=self.master.destroy)
        close_btn.grid(column=2, row=0)

        # Populate
        self._refresh_checkpoint_list()
        self.cp_filter.trace_add("write", lambda *_: self._refresh_checkpoint_list())
        self.cp_listbox.bind("<Double-Button-1>", lambda e: self._select_checkpoint())

    def _build_adapters_tab(self):
        self.adapters_tab.columnconfigure(0, weight=1)
        self.adapters_tab.rowconfigure(2, weight=1)
        # Filter
        Label(self.adapters_tab, text=_("Filter"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR).grid(column=0, row=0, sticky="w")
        self.ad_filter = StringVar(self.master)
        self.ad_filter_entry = Entry(self.adapters_tab, textvariable=self.ad_filter, width=40, font=fnt.Font(size=9))
        self.ad_filter_entry.grid(column=0, row=1, sticky="we", pady=(0, 6))
        # List
        self.ad_listbox = Listbox(self.adapters_tab, selectmode=SINGLE, font=fnt.Font(size=9))
        self.ad_listbox.grid(column=0, row=2, sticky="nsew")
        # Buttons
        btn_frame = Frame(self.adapters_tab, bg=AppStyle.BG_COLOR)
        btn_frame.grid(column=0, row=3, sticky="we", pady=(6, 0))
        replace_btn = Button(btn_frame, text=_("Replace"), command=lambda: self._select_adapter(replace=True))
        replace_btn.grid(column=0, row=0, padx=(0, 6))
        add_btn = Button(btn_frame, text=_("Add"), command=lambda: self._select_adapter(replace=False))
        add_btn.grid(column=1, row=0, padx=(0, 6))
        close_btn = Button(btn_frame, text=_("Close"), command=self.master.destroy)
        close_btn.grid(column=2, row=0)

        # Populate
        self._refresh_adapter_list()
        self.ad_filter.trace_add("write", lambda *_: self._refresh_adapter_list())
        self.ad_listbox.bind("<Double-Button-1>", lambda e: self._select_adapter())

    def _refresh_checkpoint_list(self):
        filter_text = (self.cp_filter.get() or "").lower()
        items = sorted(list(Model.CHECKPOINTS.keys()))
        if filter_text:
            items = [m for m in items if filter_text in m.lower()]
        self.cp_listbox.delete(0, END)
        for item in items:
            self.cp_listbox.insert(END, item)

    def _refresh_adapter_list(self):
        filter_text = (self.ad_filter.get() or "").lower()
        items = sorted(list(Model.LORAS.keys()))
        if filter_text:
            items = [m for m in items if filter_text in m.lower()]
        self.ad_listbox.delete(0, END)
        for item in items:
            self.ad_listbox.insert(END, item)

    def _select_checkpoint(self, replace=True):
        try:
            idx = self.cp_listbox.curselection()
            if not idx:
                return
            value = self.cp_listbox.get(idx[0])
            # Unified callback: is_lora=False
            self.app_actions.set_model_from_models_window(value, is_lora=False, replace=replace)
            # Close after action
            self.master.destroy()
        except Exception:
            # Do nothing on selection issues
            pass

    def _select_adapter(self, replace=False):
        try:
            idx = self.ad_listbox.curselection()
            if not idx:
                return
            value = self.ad_listbox.get(idx[0])
            # Unified callback: is_lora=True
            self.app_actions.set_model_from_models_window(value, is_lora=True, replace=replace)
            # Keep window open when adding, close when replacing
            if replace:
                self.master.destroy()
        except Exception:
            pass



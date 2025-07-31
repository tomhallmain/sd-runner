from tkinter import Toplevel, Frame, Label, StringVar, Entry, Button, messagebox, Checkbutton, BooleanVar
import tkinter.font as fnt

from ui.app_style import AppStyle
from ui.auth.password_core import PasswordManager
from ui.auth.password_session_manager import PasswordSessionManager
from utils.translations import I18N

_ = I18N._


class PasswordDialog:
    """Simple password dialog for authentication."""
    
    def __init__(self,
        master,
        config,
        action_name,
        callback=None,
        app_actions=None,
        action_enum=None,
        custom_text=None,
        allow_unauthenticated=False
    ):
        self.master = master
        self.config = config
        self.action_name = action_name
        self.callback = callback
        self.app_actions = app_actions
        self.action_enum = action_enum  # Store the action enum for session management
        self.custom_text = custom_text  # Store custom text for display
        self.allow_unauthenticated = allow_unauthenticated  # Whether to allow unauthenticated access
        self.result = False
        
        # Check if password is configured
        self.password_configured = self._is_password_configured()
        
        # Create dialog window
        self.dialog = Toplevel(master, bg=AppStyle.BG_COLOR)
        self.dialog.title(_("Password Required") if self.password_configured else _("Password Protection"))
        
        # Adjust geometry based on whether custom text is provided
        if self.custom_text and len(self.custom_text) > 100:
            # Larger window for long custom text
            self.dialog.geometry("500x400" if self.password_configured else "550x450")
        else:
            self.dialog.geometry("450x300" if self.password_configured else "500x350")
            
        self.dialog.resizable(False, False)
        self.dialog.transient(master)
        self.dialog.grab_set()
        
        # Center the dialog
        self.dialog.update_idletasks()
        if self.custom_text and len(self.custom_text) > 100:
            width = 500 if self.password_configured else 550
            height = 400 if self.password_configured else 450
        else:
            width = 450 if self.password_configured else 500
            height = 300 if self.password_configured else 350
        x = (self.dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (height // 2)
        self.dialog.geometry(f"{width}x{height}+{x}+{y}")
        
        self.setup_ui()
        
        # Bind events
        if self.password_configured:
            self.dialog.bind("<Return>", self.verify_password)
        self.dialog.bind("<Escape>", self.cancel)
        self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)
        
        # Focus on appropriate element
        if self.password_configured:
            self.password_entry.focus()
    
    def _is_password_configured(self):
        """Check if a password is configured for the application."""
        return PasswordManager.is_security_configured()

    def _should_show_security_advice(self):
        """Check if security advice should be shown."""
        return self.config.is_security_advice_enabled()
    
    def setup_ui(self):
        """Set up the UI components."""
        # Main frame
        main_frame = Frame(self.dialog, bg=AppStyle.BG_COLOR)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        if self.password_configured:
            self._setup_password_ui(main_frame)
        else:
            # Check if we should show security advice
            if self._should_show_security_advice():
                self._setup_advertisement_ui(main_frame)
            else:
                # User has disabled security advice, proceed without showing dialog
                self.cancel(result=True)
    
    def _setup_password_ui(self, main_frame):
        """Set up UI for password entry."""
        # Title
        title_label = Label(main_frame, text=_("Password Required"), 
                           font=fnt.Font(size=14, weight="bold"))
        title_label.pack(pady=(0, 10))
        title_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Action description
        action_label = Label(main_frame, 
                           text=_("Password required for: {0}").format(self.action_name),
                           wraplength=400)
        action_label.pack(pady=(0, 10))
        action_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Custom text (if provided)
        if self.custom_text:
            custom_label = Label(main_frame, 
                               text=self.custom_text,
                               wraplength=400,
                               font=fnt.Font(size=9))
            custom_label.pack(pady=(0, 20))
            custom_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        else:
            # Add some spacing if no custom text
            spacer_label = Label(main_frame, text="")
            spacer_label.pack(pady=(0, 20))
            spacer_label.config(bg=AppStyle.BG_COLOR)
        
        # Password entry
        password_frame = Frame(main_frame, bg=AppStyle.BG_COLOR)
        password_frame.pack(pady=(0, 20))
        
        password_label = Label(password_frame, text=_("Password:"))
        password_label.pack(anchor="w")
        password_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        self.password_var = StringVar()
        self.password_entry = Entry(password_frame, textvariable=self.password_var, 
                                   show="*", width=30, font=fnt.Font(size=10))
        self.password_entry.pack(fill="x", pady=(5, 0))
        
        # Buttons
        button_frame = Frame(main_frame, bg=AppStyle.BG_COLOR)
        button_frame.pack(fill="x")
        
        ok_button = Button(button_frame, text=_("OK"), command=self.verify_password)
        ok_button.pack(side="right", padx=(10, 0))
        
        cancel_button = Button(button_frame, text=_("Cancel"), command=self.cancel)
        cancel_button.pack(side="right")
    
    def _setup_advertisement_ui(self, main_frame):
        """Set up UI for password protection advertisement."""
        # Title
        title_label = Label(main_frame, text=_("Password Protection Available"), 
                           font=fnt.Font(size=14, weight="bold"))
        title_label.pack(pady=(0, 15))
        title_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Action description
        action_label = Label(main_frame, 
                           text=_("This action requires password protection: {0}").format(self.action_name),
                           wraplength=450)
        action_label.pack(pady=(0, 10))
        action_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Custom text (if provided)
        if self.custom_text:
            custom_label = Label(main_frame, 
                               text=self.custom_text,
                               wraplength=450,
                               font=fnt.Font(size=9))
            custom_label.pack(pady=(0, 15))
            custom_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Information text
        if self.allow_unauthenticated:
            info_text = _("Password protection is not currently configured. You can:")
            info_label = Label(main_frame, text=info_text, wraplength=450)
            info_label.pack(pady=(0, 10))
            info_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
            
            # Options list
            options_frame = Frame(main_frame, bg=AppStyle.BG_COLOR)
            options_frame.pack(pady=(0, 10))
            options_frame.config(bg=AppStyle.BG_COLOR)
            
            option1 = Label(options_frame, text=_("• Configure password protection for sensitive actions"), 
                           wraplength=400, justify="left")
            option1.pack(anchor="w", pady=2)
            option1.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
            
            option2 = Label(options_frame, text=_("• Continue without password protection (less secure)"), 
                           wraplength=400, justify="left")
            option2.pack(anchor="w", pady=2)
            option2.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)

            # Don't show again checkbox
            self.dont_show_again_var = BooleanVar(value=not self.config.is_security_advice_enabled())
            dont_show_checkbox = Checkbutton(main_frame, text=_("Don't show this security advice again"),
                                           variable=self.dont_show_again_var,
                                           bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                                           selectcolor=AppStyle.BG_COLOR)
            dont_show_checkbox.pack(pady=(5, 15))

            # Buttons
            button_frame = Frame(main_frame, bg=AppStyle.BG_COLOR)
            button_frame.pack(fill="x")
            
            configure_button = Button(button_frame, text=_("Configure Protection"), 
                                     command=self.open_password_admin)
            configure_button.pack(side="right", padx=(10, 0))
            
            continue_button = Button(button_frame, text=_("Continue Without Protection"), 
                                    command=self.continue_without_protection)
            continue_button.pack(side="right", padx=(10, 0))
            
            cancel_button = Button(button_frame, text=_("Cancel"), command=self.cancel)
            cancel_button.pack(side="right")
        else:
            # When unauthenticated access is not allowed
            info_text = _("Password protection is required for this action but is not currently configured.")
            info_label = Label(main_frame, text=info_text, wraplength=450)
            info_label.pack(pady=(0, 10))
            info_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
            
            # Buttons
            button_frame = Frame(main_frame, bg=AppStyle.BG_COLOR)
            button_frame.pack(fill="x")
            
            configure_button = Button(button_frame, text=_("Configure Protection"), 
                                     command=self.open_password_admin)
            configure_button.pack(side="right", padx=(10, 0))
            
            cancel_button = Button(button_frame, text=_("Cancel"), command=self.cancel)
            cancel_button.pack(side="right")
    
    def verify_password(self, event=None):
        """Verify the entered password."""
        password = self.password_var.get()
        
        # Check if password is correct
        if self.check_password(password):
            self.cancel(result=True)
        else:
            messagebox.showerror(_("Error"), _("Incorrect password"))
            self.password_var.set("")
            self.password_entry.focus()
    
    def check_password(self, password):
        """Check if the password is correct."""
        return PasswordManager.verify_password(password)
    
    def open_password_admin(self):
        """Open the password administration window."""
        self.cancel(result=False)
        
        # Use app_actions callback to open the password admin window
        if self.app_actions and self.app_actions.open_password_admin_window:
            self.app_actions.open_password_admin_window()
        else:
            raise Exception("AppActions failed to initialize")
    
    def continue_without_protection(self):
        """Continue without password protection."""
        # Check if user wants to disable security advice
        if hasattr(self, 'dont_show_again_var') and self.dont_show_again_var.get():
            self.config.set_security_advice_enabled(False)
            self.config.save_settings()

        # Record an unauthenticated session if we have the action enum
        if self.action_enum:
            PasswordSessionManager.record_successful_verification(self.action_enum, is_authenticated=False)
        
        self.cancel(result=True)
    
    def cancel(self, event=None, result=False):
        """Cancel the password dialog."""
        self.result = result
        self.dialog.destroy()
        if self.callback:
            self.callback(result)
    
    @staticmethod
    def prompt_password(
        master,
        config,
        action_name,
        callback=None,
        app_actions=None,
        action_enum=None,
        custom_text=None,
        allow_unauthenticated=False
    ):
        """Static method to prompt for password."""
        dialog = PasswordDialog(
            master,
            config,
            action_name,
            callback,
            app_actions,
            action_enum,
            custom_text,
            allow_unauthenticated)
        return dialog.result 
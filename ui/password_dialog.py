from tkinter import Toplevel, Frame, Label, StringVar, Entry, Button, messagebox
import tkinter.font as fnt

from ui.app_style import AppStyle
from ui.password_admin_window import PasswordAdminWindow
from ui.password_utils import PasswordManager
from utils.translations import I18N

_ = I18N._


class PasswordDialog:
    """Simple password dialog for authentication."""
    
    def __init__(self, master, action_name, callback=None):
        self.master = master
        self.action_name = action_name
        self.callback = callback
        self.result = False
        
        # Check if password is configured
        self.password_configured = self._is_password_configured()
        
        # Create dialog window
        self.dialog = Toplevel(master, bg=AppStyle.BG_COLOR)
        self.dialog.title(_("Password Required") if self.password_configured else _("Password Protection"))
        self.dialog.geometry("450x300" if self.password_configured else "500x350")
        self.dialog.resizable(False, False)
        self.dialog.transient(master)
        self.dialog.grab_set()
        
        # Center the dialog
        self.dialog.update_idletasks()
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
        return PasswordManager.is_password_configured()
    
    def setup_ui(self):
        """Set up the UI components."""
        # Main frame
        main_frame = Frame(self.dialog, bg=AppStyle.BG_COLOR)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        if self.password_configured:
            self._setup_password_ui(main_frame)
        else:
            self._setup_advertisement_ui(main_frame)
    
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
        action_label.pack(pady=(0, 20))
        action_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
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
        action_label.pack(pady=(0, 15))
        action_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Information text
        info_text = _("Password protection is not currently configured. You can:")
        info_label = Label(main_frame, text=info_text, wraplength=450)
        info_label.pack(pady=(0, 10))
        info_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Options list
        options_frame = Frame(main_frame, bg=AppStyle.BG_COLOR)
        options_frame.pack(pady=(0, 20))
        options_frame.config(bg=AppStyle.BG_COLOR)
        
        option1 = Label(options_frame, text=_("• Configure password protection for sensitive actions"), 
                       wraplength=400, justify="left")
        option1.pack(anchor="w", pady=2)
        option1.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        option2 = Label(options_frame, text=_("• Continue without password protection (less secure)"), 
                       wraplength=400, justify="left")
        option2.pack(anchor="w", pady=2)
        option2.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
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
    
    def verify_password(self, event=None):
        """Verify the entered password."""
        password = self.password_var.get()
        
        # TODO: Implement actual password verification using the encryptor
        # For now, we'll use a simple check against a stored password
        # This should be replaced with proper password verification from the encryptor
        
        # Check if password is correct (placeholder implementation)
        if self.check_password(password):
            self.result = True
            self.dialog.destroy()
            if self.callback:
                self.callback(True)
        else:
            messagebox.showerror(_("Error"), _("Incorrect password"))
            self.password_var.set("")
            self.password_entry.focus()
    
    def check_password(self, password):
        """Check if the password is correct."""
        return PasswordManager.verify_password(password)
    
    def open_password_admin(self):
        """Open the password administration window."""
        self.dialog.destroy()
        if self.callback:
            self.callback(False)  # Cancel the original action
        
        # Open the password admin window
        PasswordAdminWindow(self.master, getattr(self.master, 'app_actions', None))
    
    def continue_without_protection(self):
        """Continue without password protection."""
        self.result = True
        self.dialog.destroy()
        if self.callback:
            self.callback(True)
    
    def cancel(self, event=None):
        """Cancel the password dialog."""
        self.result = False
        self.dialog.destroy()
        if self.callback:
            self.callback(False)
    
    @staticmethod
    def prompt_password(master, action_name, callback=None):
        """Static method to prompt for password."""
        dialog = PasswordDialog(master, action_name, callback)
        return dialog.result


# Example usage
if __name__ == "__main__":
    import tkinter as tk
    
    def password_callback(result):
        if result:
            print("Password accepted!")
        else:
            print("Password cancelled or incorrect.")
    
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    result = PasswordDialog.prompt_password(root, "Edit Blacklist", password_callback)
    print(f"Dialog result: {result}")
    
    root.mainloop() 
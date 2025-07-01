from tkinter import Toplevel, Frame, Label, StringVar, Entry, Button, messagebox
import tkinter.font as fnt

from ui.app_style import AppStyle
from utils.translations import I18N

_ = I18N._


class PasswordDialog:
    """Simple password dialog for authentication."""
    
    def __init__(self, master, action_name, callback=None):
        self.master = master
        self.action_name = action_name
        self.callback = callback
        self.result = False
        
        # Create dialog window
        self.dialog = Toplevel(master, bg=AppStyle.BG_COLOR)
        self.dialog.title(_("Password Required"))
        self.dialog.geometry("400x200")
        self.dialog.resizable(False, False)
        self.dialog.transient(master)
        self.dialog.grab_set()
        
        # Center the dialog
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (400 // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (200 // 2)
        self.dialog.geometry(f"400x200+{x}+{y}")
        
        self.setup_ui()
        
        # Bind events
        self.dialog.bind("<Return>", self.verify_password)
        self.dialog.bind("<Escape>", self.cancel)
        self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)
        
        # Focus on password entry
        self.password_entry.focus()
    
    def setup_ui(self):
        """Set up the UI components."""
        # Main frame
        main_frame = Frame(self.dialog, bg=AppStyle.BG_COLOR)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        title_label = Label(main_frame, text=_("Password Required"), 
                           font=fnt.Font(size=14, weight="bold"))
        title_label.pack(pady=(0, 10))
        title_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Action description
        action_label = Label(main_frame, 
                           text=_("Password required for: {0}").format(self.action_name),
                           wraplength=350)
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
        # TODO: Implement proper password verification using the encryptor
        # This is a placeholder that should be replaced with actual verification
        # from the encryptor module
        
        # For now, return True to allow access (remove this in production)
        return True
    
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
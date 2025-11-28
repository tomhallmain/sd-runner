import threading
import time
from tkinter import Frame, Label, Button, BOTH, YES, LEFT

from lib.multi_display import SmartToplevel
from ui.app_style import AppStyle
from utils.translations import I18N

_ = I18N._


class ScheduledShutdownDialog:
    """Dialog that shows a countdown before scheduled shutdown."""
    
    def __init__(self, parent, schedule_name, countdown_seconds=6):
        self.parent = parent
        self.schedule_name = schedule_name
        self.countdown_seconds = countdown_seconds
        self.dialog = None
        self.countdown_label = None
        self.cancelled = False
        
    def show(self):
        """Show the countdown dialog and start the countdown."""
        self.dialog = SmartToplevel(persistent_parent=self.parent,
                                   title=_("Scheduled Shutdown"),
                                   geometry="400x200",
                                   center=True)
        self.dialog.resizable(False, False)
        
        # Center the dialog
        self.dialog.transient(self.parent)
        self.dialog.grab_set()
        
        # Make it stay on top
        self.dialog.attributes('-topmost', True)
        
        # Create main frame
        main_frame = Frame(self.dialog, bg=AppStyle.BG_COLOR)
        main_frame.pack(expand=True, fill=BOTH, padx=20, pady=20)
        
        # Title label
        title_label = Label(main_frame, text=_("Scheduled Shutdown"), 
                           font=("Arial", 14, "bold"),
                           bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        title_label.pack(pady=(0, 10))
        
        # Schedule info
        schedule_label = Label(main_frame, 
                              text=_("Schedule: {}").format(self.schedule_name),
                              font=("Arial", 10),
                              bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        schedule_label.pack(pady=(0, 10))
        
        # Countdown label
        self.countdown_label = Label(main_frame, 
                                    text=_("Shutting down in {} seconds...").format(self.countdown_seconds),
                                    font=("Arial", 12, "bold"),
                                    fg="red", bg=AppStyle.BG_COLOR)
        self.countdown_label.pack(pady=(0, 20))
        
        # Button frame
        button_frame = Frame(main_frame, bg=AppStyle.BG_COLOR)
        button_frame.pack()
        
        # Cancel button (commented out for now)
        # cancel_btn = Button(button_frame, text=_("Cancel Shutdown"), 
        #                    command=self.cancel_shutdown)
        # cancel_btn.pack(side=LEFT, padx=(0, 10))
        
        # Shutdown now button
        shutdown_now_btn = Button(button_frame, text=_("Shutdown Now"), 
                                 command=self.shutdown_now)
        shutdown_now_btn.pack(side=LEFT)
        
        # Start countdown in a separate thread
        self.countdown_thread = threading.Thread(target=self._countdown_loop, daemon=True)
        self.countdown_thread.start()
        
        # Center the dialog on screen
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (self.dialog.winfo_width() // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (self.dialog.winfo_height() // 2)
        self.dialog.geometry(f"+{x}+{y}")
        
        return self.cancelled
    
    def _countdown_loop(self):
        """Run the countdown loop."""
        for remaining in range(self.countdown_seconds, 0, -1):
            if self.cancelled:
                return
                
            # Update the countdown label
            if self.countdown_label and self.countdown_label.winfo_exists():
                self.countdown_label.config(
                    text=_("Shutting down in {} seconds...").format(remaining),
                    bg=AppStyle.BG_COLOR
                )
                self.dialog.update()
            
            time.sleep(1)
        
        # Time's up, shutdown
        if not self.cancelled and self.dialog and self.dialog.winfo_exists():
            self.dialog.after(0, self._force_shutdown)
    
    def cancel_shutdown(self):
        """Cancel the scheduled shutdown."""
        self.cancelled = True
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.destroy()
    
    def shutdown_now(self):
        """Shutdown immediately."""
        self.cancelled = False
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.destroy()
        self._force_shutdown()
    
    def _force_shutdown(self):
        """Force the application to shutdown."""
        if hasattr(self.parent, 'on_closing'):
            self.parent.on_closing()

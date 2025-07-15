from tkinter import Toplevel, Label, LEFT

class Tooltip:
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay  # milliseconds
        self.tipwindow = None
        self.id = None
        self.x = self.y = 0
        self.widget.bind('<Enter>', self.schedule)
        self.widget.bind('<Leave>', self.hide)
        self.widget.bind('<Motion>', self.move)

    def schedule(self, event=None):
        self.unschedule()
        self.id = self.widget.after(self.delay, self.show)

    def unschedule(self):
        id_ = self.id
        self.id = None
        if id_:
            self.widget.after_cancel(id_)

    def show(self, event=None):
        if self.tipwindow or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert") if self.widget.winfo_class() != 'TCombobox' else (0, 0, 0, 0)
        x = x + self.widget.winfo_rootx() + 20
        y = y + cy + self.widget.winfo_rooty() + 20
        self.tipwindow = tw = Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = Label(tw, text=self.text, justify=LEFT,
                         background="#ffffe0", relief="solid", borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack(ipadx=4, ipady=2)

    def move(self, event):
        if self.tipwindow:
            x = event.x_root + 20
            y = event.y_root + 10
            self.tipwindow.wm_geometry(f"+{x}+{y}")

    def hide(self, event=None):
        self.unschedule()
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy() 
import tkinter as tk
import queue
import logging

from tkinter import ttk
from urllib.parse import unquote


class tkHelper:
    def __init__(self, logger: logging = logging):
        self.logger = logger
        self.logger.debug("tkHelper initialized")
    
    def center_window(window: tk.Tk, width: int, height: int):
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        position_top = int(screen_height / 2 - height / 2)
        position_right = int(screen_width / 2 - width / 2)
        window.geometry(f"{width}x{height}+{position_right}+{position_top}")

    def clear_window(window: tk.Tk):
        for widget in window.winfo_children():
            widget.destroy()
        window.update()

    # Fix: This run twice for no reason
    # widget.edit_modified(False) trigger the event again
    def txt_on_modified(self, event: tk.Event) -> None:
        """
        Event handler for the <<Modified>> event of a Tkinter Text widget.
        This function is triggered when the content of the Text widget is modified.
        It retrieves the current content of the widget, decodes the URL if needed,
        and updates the widget with the decoded URL. The function temporarily unbinds
        the <<Modified>> event to prevent recursive calls while updating the widget.
        Args:
            event (tk.Event): The event object containing information about the <<Modified>> event.
        """
        widget: tk.Text = event.widget
        
        widget.unbind("<<Modified>>")
        url = widget.get("1.0", tk.END).strip()
        self.logger.debug(f"Url: {url}")
        
        decoded_url = None
        if '%' in url:
            try:
                decoded_url = unquote(url).strip()
            except Exception as e:
                self.logger.error(f"Error decoding URL: {e}")
            else:
                widget.delete("1.0", tk.END)
                widget.insert("1.0", decoded_url)
                self.logger.debug(f"Decoded URL: {decoded_url}")
        
        widget.edit_modified(False)
        
        widget.bind("<<Modified>>", lambda e: self.txt_on_modified(e))

    
class DownloadProgressBar:
    def __init__(self, root, total_size, label, vertical=False):
        self.root = root
        
        self.total_size = max(total_size, 1)
        self.downloaded_size = 0
        
        self.frame = tk.Frame(self.root)
        self.frame.pack()
        
        if vertical:
            self.progress = ttk.Progressbar(
                self.root, orient="vertical", length=200, mode="determinate"
            )
            side = "bottom"
            self.progress.pack(in_=self.frame, side=side, padx=3, pady=20)
        else:
            self.progress = ttk.Progressbar(
                self.root, orient="horizontal", length=400, mode="determinate"
            )
            side = "top"
            self.progress.pack(in_=self.frame, side=side, pady=20)
        
        self.progress["maximum"] = total_size
        
        self.label = tk.Label(self.frame, text=label)
        self.label.pack(in_=self.frame, side=side, pady=10)
        self.percent_label = tk.Label(self.root, text="0%")
        if not vertical:
            self.percent_label.pack(in_=self.frame, side=side, pady=10)
        
        self.queue = queue.Queue()
        
        if total_size < 1:
            self.progress["value"] = 1
            self.percent_label.config(text="100%")
    
    def config(self, **kwargs):
        # if p_color := kwargs.get("p_color"):
        #     self.progress.config(style=f"color.TProgressbar")
        if fg := kwargs.get("fg"):
            self.label.config(fg=fg)
            self.percent_label.config(fg=fg)
        if bg := kwargs.get("bg"):
            self.frame.config(bg=bg)
            # self.progress.config(style=f"{bg}.TProgressbar")
            self.label.config(bg=bg)
            self.percent_label.config(bg=bg)
        

    def update(self, chunk_size):
        self.queue.put(chunk_size)
    
    def update_progress(self, chunk_size):
        self.downloaded_size += chunk_size
        self.progress["value"] = self.downloaded_size
        percent = (self.downloaded_size / self.total_size) * 100
        self.percent_label.config(text=f"{percent:.2f}%")

    def process_queue(self):
        try:
            while True:
                chunk_size = self.queue.get_nowait()
                self.downloaded_size += chunk_size
                self.progress["value"] = self.downloaded_size
                percent = (self.downloaded_size / self.total_size) * 100
                self.percent_label.config(text=f"{percent:.2f}%")
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)
    
    def set_progress(self, current_value, max_value=None):
        if max_value:
            self.total_size = max(max_value, 1)
        self.progress["maximum"] = self.total_size
        
        self.downloaded_size = current_value
        self.progress["value"] = self.downloaded_size
            
        percent = (self.downloaded_size / self.total_size) * 100
        self.percent_label.config(text=f"{percent:.2f}%")
    
    def destroy(self):
        self.progress.destroy()
        self.label.destroy()
        self.percent_label.destroy()
        self.root.update()

if __name__ == "__main__":
    pass
        
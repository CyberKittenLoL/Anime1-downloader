import os
import re
import time
import getpass
import logging
import threading
import requests
import configparser
import tkinter as tk
from tkinter import messagebox
from concurrent.futures import ThreadPoolExecutor, as_completed
import _tkinter

# Custom imports
from helper.tk_helper import tkHelper, DownloadProgressBar
from helper.anime1_fetch import DownloadHelper

__version__ = "0.0.1"

CONFIG_PATH = "config.ini"
LOG_DIR = "logs"

CONFIG_DEFAULT = {
    "APP": {
        "download_path": f"C:/Users/{getpass.getuser()}/Downloads",
        "max_workers": 4,
    },
    
    # "DEBUG": {
    #     "log_level": "INFO",
    #     "log_file_level": "DEBUG",
    #     "log_file": "%%DATETIME%%.log"
    # }
}

def init_config():
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        try:
            config.read(CONFIG_PATH)
            for key in CONFIG_DEFAULT:
                for k, v in CONFIG_DEFAULT[key].items():
                    if k not in config[key]:
                        config[key][k] = v

            with open(CONFIG_PATH, "w") as config_file:
                config.write(config_file)
            return config
        except Exception as e:
            logging.error(
                f"Error reading config file. Using default config. Exception: {e}"
            )

    for key in CONFIG_DEFAULT:
        config[key] = CONFIG_DEFAULT[key]

    with open(CONFIG_PATH, "w") as config_file:
        config.write(config_file)

    return config

class Anime1_downloader:
    def __init__(self):
        self.stop_flag = threading.Event()
        
        self.config = init_config()
        self.download_path = self.config["APP"]["download_path"]
        self.max_workers = int(self.config["APP"]["max_workers"])
        
        self.logger = logging.getLogger(__name__)
        self.init_logging()    

        self.download_helper: DownloadHelper
        self.tkHelper = tkHelper(self.logger)
        
    def init_logging(self):
        """
        Initializes the logging configuration based on the config file.
        """
        
        log_level = self.config.get("DEBUG", "log_level", fallback="")
        log_file_level = self.config.get("DEBUG", "log_file_level", fallback="")
        
        log_level_int = getattr(logging, log_level.upper(), logging.WARNING)
        log_level_file_int = getattr(logging, log_file_level.upper(), logging.WARNING)
        self.logger.setLevel(min(log_level_int, log_level_file_int))
        
        
        log_file = self.config.get("DEBUG", "log_file", fallback="")
        if "%DATETIME%" in log_file:
            log_file = log_file.replace("%DATETIME%", time.strftime("%Y%m%d-%H%M%S") + f"{int(time.time() * 1000) % 1000:03d}")
        
        if log_file:
            log_files = []
            if not os.path.exists(LOG_DIR):
                os.makedirs(LOG_DIR)
            else:
                for file in os.listdir(LOG_DIR):
                    if re.match(r"app_log_.*\.log$", file):
                        log_files.append(os.path.join(LOG_DIR, file))
            log_files.sort(key=os.path.getctime)
            if len(log_files) >= 5:
                for file in log_files[:-4]:
                    os.remove(file)
            log_file = os.path.join(os.getcwd(), f"{LOG_DIR}/app_log_{log_file}")

        formatter = logging.Formatter('%(asctime)s::%(msecs)03d [%(name)s] [%(levelname)s]: %(message)s', datefmt='%H:%M:%S')

        if log_level:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(log_level_int)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
        if log_file_level:
            file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
            file_handler.setLevel(log_level_file_int)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        self.logger.info(f"Anime1 downloader {__version__}")
        self.logger.info(f"PID: {os.getpid()}")
        if log_level == "DEBUG":
            self.logger.debug(f"CWD: {os.getcwd()}")
            self.logger.debug(f"{' Machine details: ':=^50}")
            self.logger.debug(f"Username: {getpass.getuser()}")
            self.logger.debug(f"OS: {os.name} {os.sys.platform}")
            self.logger.debug(f"Python Version: {os.sys.version}")
            self.logger.debug(f"{' Config: ':=^50}")
            self.logger.debug(f"Config Path: {CONFIG_PATH}")
            self.logger.debug(f"Download Path: {self.download_path}")
            self.logger.debug(f"Max Workers: {self.max_workers}")
            self.logger.debug(f"{' Log detail: ':=^50}")
            self.logger.debug(f"Log level: {log_level}")
            self.logger.debug(f"Log file: {log_file}")
            self.logger.debug("="*50)

    def start(self, restart: bool = False) -> int:
        """
        Starts the application by initializing it.

        Returns:
            int: The status code returned by the initialization process.
        """
        self.download_helper = DownloadHelper(self.logger)
        
        if not restart:
            self.root = tk.Tk()
            
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.exit_app(0))
        self.init_app()
        self.logger.debug("Finished initializing the app.")
        self.exit_code = 0
        if not restart:
            self.root.mainloop()

        return self.exit_code
    
    def init_app(self):
        """
        Initializes the application window for the Anime1 Downloader.
        This method sets up the main window with a title, background color, and centers it on the screen.
        It also creates and packs the URL entry label, entry field, and submit button.
        When the submit button is clicked, it validates the URL and proceeds to fetch video data if the URL is valid.
        Returns:
            int: The exit code of the application.
        """
        self.root.title("Anime1 Downloader")
        self.root.configure(bg="black")
        tkHelper.center_window(self.root, 600, 400)

        url_label = tk.Label(self.root,
                             text="Enter URL",
                             font=("Helvetica", 16),
                             fg="white",
                             bg="black",
                             )
        url_label.pack(pady=20)

        url_text = tk.Text(self.root,
                           font=("Helvetica", 14),
                           height=8,
                           width=40,
                           wrap=tk.WORD,
                           bg="light gray")
        url_text.pack(pady=5, expand=True)
        
        url_text.bind("<<Modified>>", lambda e: self.tkHelper.txt_on_modified(e))
        
        def on_submit():
            submit_button.config(state=tk.DISABLED)
            submit_button.config(text="Loading Data...")
            url_text.config(state=tk.DISABLED)
            self.root.update()
            
            url = url_text.get("1.0", tk.END).strip()
            
            self.logger.debug("Testing URL: %s", url)
            is_url = re.match(r"https?://anime1\.(?:me|pw)", url)
            session = requests.Session()
            if is_url:
                url_response = session.get(url)
            else:
                class A:
                    def __init__(self):
                        self.status_code = 0
                        self.text = "Invalid URL, unable to fetch data"
                url_response = A()
                
            
            if (url_response.status_code != 200):
                if url_response.status_code == 403:
                    self.logger.error("Forbidden (%i): %s", url_response.status_code, url_response.text)
                    messagebox.showerror(
                        "Forbidden",
                        "Access to the URL is forbidden. Please check the URL and VPN then try again.",
                    )
                else:
                    self.logger.error("Invalid URL (%i): %s", url_response.status_code, url_response.text)
                    messagebox.showerror(
                        "Invalid URL",
                        "Please enter a valid URL from anime1.me",
                    )
                submit_button.config(state=tk.NORMAL)
                submit_button.config(text="Submit")
                url_text.config(state=tk.NORMAL)
                return

            # self.root.destroy()
            data = self.download_helper.get_video_data_me(url)
            if not data:
                messagebox.showerror(
                    "Error",
                    "Failed to fetch video data. Please check the URL and try again.",
                )
                submit_button.config(state=tk.NORMAL)
                submit_button.config(text="Submit")
                url_text.config(state=tk.NORMAL)
                return
            
            tkHelper.clear_window(self.root)
            self.selected_episodes_ui(data)

        submit_button = tk.Button(
            self.root,
            text="Submit",
            command=on_submit,
            bg="blue",
            fg="white",
            font=("Helvetica", 14),
        )
        submit_button.pack(pady=40)
        
        url_text.bind("<Return>", lambda e: on_submit())

    def selected_episodes_ui(self, data) -> None:
        """
        Creates and displays the UI for selecting episodes to download.
        Args:
            data (dict): A dictionary containing the following keys:
                - "title" (str): The title of the anime.
                - "total episode" (int): The total number of episodes.
                - "data" (list): A list of episode data.
        UI Elements:
            - Title label displaying the anime title.
            - Label indicating the total number of episodes.
            - Listbox for selecting multiple episodes.
            - Button to select all episodes.
            - Button to download selected episodes.
        The UI allows users to select episodes from a list and initiate the download process.
        """
        def select_all():
            listbox.select_set(0, tk.END)
            on_select(None)

        def on_select(event):
            selected_indices = listbox.curselection()
            selected_episodes.clear()
            for i in selected_indices:
                selected_episodes.append(listbox.get(i))
            download_button.config(text=f"Download ({len(selected_episodes)})")

        self.root.title(f"Anime1 Downloader {data["title"]}")
        tkHelper.center_window(self.root, 500, 600)

        frame = tk.Frame(self.root, bg="black")
        frame.pack(pady=20)

        title = tk.Label(
            frame,
            text=data["title"],
            bg="black",
            fg="white",
            font=("Helvetica", 16),
            wraplength=400
        )
        title.pack(pady=10)

        label = tk.Label(
            frame,
            text="Select Episodes to Download",
            bg="black",
            fg="white",
            font=("Helvetica", 16),
        )
        label.pack(pady=5)

        label = tk.Label(
            frame,
            text=f"Total {data['total episode']} EPs",
            bg="black",
            fg="white",
            font=("Helvetica", 14),
        )
        label.pack(pady=10)

        listbox_frame = tk.Frame(frame, bg="black")
        listbox_frame.pack(pady=10)

        scrollbar = tk.Scrollbar(listbox_frame, orient=tk.VERTICAL)
        listbox = tk.Listbox(
            listbox_frame,
            selectmode=tk.MULTIPLE,
            bg="white",
            fg="black",
            font=("Helvetica", 12),
            width=30,
            height=10,
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        for i in data["names"]:
            listbox.insert(tk.END, i)

        listbox.bind("<<ListboxSelect>>", on_select)
        selected_episodes = []

        select_all_button = tk.Button(
            frame,
            text="Select All",
            command=select_all,
            bg="green",
            fg="white",
            font=("Helvetica", 14),
        )
        select_all_button.pack(pady=10)
        
        def on_submit_download(data, selected_episodes):
            self.root.unbind("<Return>")
            self.download_episodes(data, selected_episodes)

        download_button = tk.Button(
            frame,
            text="Download (0)",
            command=lambda: on_submit_download(data, selected_episodes),
            bg="blue",
            fg="white",
            font=("Helvetica", 14),
        )
        download_button.pack(pady=20)
        
        self.root.bind("<Return>", lambda e: on_submit_download(data, selected_episodes))

    def download_ui(self, data, eps):
        """
        Sets up and displays the download user interface.
        Parameters:
        data (dict): A dictionary containing information about the download, such as the title.
        eps (list): A list of episodes to be downloaded.
        The UI includes:
        - A title label displaying the title from the data dictionary.
        - A progress bar to show the download progress.
        - A percentage label to show the download percentage.
        The window is centered and configured with a black background.
        """
        tkHelper.clear_window(self.root)
        self.root.configure(bg="black")
        tkHelper.center_window(self.root, 500, 600)
        self.root.title(f"Downloading {data['title']} {0}/{len(eps)} Episodes")
        
        title = tk.Label(
            self.root,
            text=data["title"],
            bg="black",
            fg="white",
            font=("Helvetica", 16),
        )
        title.pack(pady=20)
        
        ep_processbar = tk.Frame(self.root, bg="black")
        ep_processbar.pack(pady=20)
        
        self.ep_processbar_dict = {}
        
        for episode in eps:
            match = re.search(r"\[(\d+(\.\d+)?)\]$", episode)
            if match:
                ep_str = match.group(1)
                if '.' in ep_str:
                    ep_id = float(ep_str)
                else:
                    ep_id = int(ep_str)
            else:
                ep_id = episode
            
            self.ep_processbar_dict[episode] = DownloadProgressBar(
                ep_processbar, 100, f"{ep_id}", vertical=True
            )
            self.ep_processbar_dict[episode].frame.pack(side=tk.LEFT, padx=3)
            self.ep_processbar_dict[episode].config(bg="black", fg="white")
            

        self.root.progress_bar = DownloadProgressBar(
            self.root, len(eps), f"Downloading Episodes (0/{len(eps)})"
        )
        self.root.progress_bar.frame.pack(pady=20)
        self.root.progress_bar.config(bg="black", fg="white")

        self.root.progress_bar.process_queue()
        self.root.update()

    def update_progress(self, downloaded_size, total_size):
        """
        Updates the progress bar and labels with the current download progress.

        Args:
            downloaded_size (int): The size of the data that has been downloaded so far.
            total_size (int): The total size of the data to be downloaded.

        Returns:
            None
        """
        self.root.progress_bar.update(1)
        self.root.progress_bar.percent_label.config(
            text=f"{downloaded_size / total_size * 100:.2f}%"
        )
        self.root.progress_bar.label.config(
            text=f"Downloading Episodes ({downloaded_size}/{total_size})"
        )
        self.root.update()

    def download_episodes(self, data, eps):
        self.download_ui(data, eps)
        self.logger.debug("Starting download of %s episodes", len(eps))
        start_time = time.time()
        
        self.download_helper.total_eps = len(eps)
        
        def download_task():
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = []
                for episode in eps:
                    if self.stop_flag.is_set():
                        self.logger.debug("Download stopped")
                        return
                    futures.append(
                        executor.submit(
                            self.download_helper.download_episode,
                            episode,
                            data,
                            self.download_path
                        )
                    )

                downloaded_size = 0
                for future in as_completed(futures):
                    if self.stop_flag.is_set():
                        self.logger.debug("Download stopped")
                        for f in futures:
                            f.cancel()
                        return
                    try:
                        future.result()
                        downloaded_size += 1
                        self.root.title(f"Downloading {data['title']} {downloaded_size}/{len(eps)} Episodes")
                        # self.root.after(
                        #     0, self.root.progress_bar.update_progress, downloaded_size
                        # )
                    except Exception as e:
                        self.logger.error(f"Error downloading episode: {e}")
        
        self.download_thread = threading.Thread(target=download_task, daemon=True)
        self.download_thread.start()
        
        while self.download_thread.is_alive() and not self.stop_flag.is_set():
            try:
                self.root.progress_bar.set_progress(self.download_helper.downloaded_size, self.download_helper.total_size)
                
                for episode in eps:
                    ep_state = self.download_helper.process.get(episode)
                    if ep_state:
                        if ep_state.get("finished", False):
                            self.ep_processbar_dict[episode].label.config(bg="green")
                        else:
                            self.ep_processbar_dict[episode].set_progress(ep_state["downloaded_size"], ep_state["total_size"])
                self.root.update()
                self.root.progress_bar.label.config(
                    text=f"Downloading Episodes ({self.download_helper.finished}/{self.download_helper.total_eps})"
                )
            except _tkinter.TclError:
                break
            
            finally:
                time.sleep(0.1)
        self.logger.info(f"Time taken: {time.time() - start_time:.2f} seconds")
        self.download_complete(data["title"])

    def download_complete(self, title=None):
        """
        Updates the progress bar label to indicate that the download is complete,
        and creates a frame with two buttons: one to download another anime and
        another to exit the application.
        The "Download Another Anime" button triggers the exit_app method with an
        argument of 1, while the "Exit" button quits the application.
        The buttons are styled with specific background colors, foreground colors,
        and fonts, and are packed into the frame with padding.
        """
        
        tkHelper.clear_window(self.root)
        # for episode in self.ep_processbar_dict:
        #     self.ep_processbar_dict[episode].frame.destroy()
        # self.root.frame.destroy()
        
        self.root.h1 = tk.Label(
            self.root,
            text="Download Completed",
            bg="black",
            fg="white",
            font=("Helvetica", 16),
        )
        self.root.h1.pack(pady=20)

        button_frame = tk.Frame(self.root, bg="black")
        button_frame.pack(pady=20)
        
        folder_location = f"{self.download_path}/{title}" if title is not None else self.download_path
        self.root.open_folder = tk.Button(
            button_frame,
            text="Open Folder",
            command=lambda: os.startfile(folder_location),
            bg="green",
            fg="white",
            font=("Helvetica", 14),
        )
        self.root.open_folder.pack(side=tk.LEFT, padx=10, pady=10)
        
        self.root.download_another = tk.Button(
            button_frame,
            text="Download Another Anime",
            command=self.restart_app,
            bg="blue",
            fg="white",
            font=("Helvetica", 14),
        )
        self.root.download_another.pack(side=tk.LEFT, padx=10)

        self.root.exit_button = tk.Button(
            button_frame,
            text="Exit",
            command=self.root.quit,
            bg="red",
            fg="white",
            font=("Helvetica", 14),
        )
        self.root.exit_button.pack(side=tk.RIGHT, padx=10)

    def download_search(self, search):
        pass

    def download_search_range(self, search, start, end):
        pass

    def download_search_latest(self, search):
        pass

    def download_search_new(self, search):
        pass

    def download_search_all(self, search):
        pass
    
    def restart_app(self):
        self.logger.debug("Restarting the app")
        # self.root.destroy()
        tkHelper.clear_window(self.root)
        self.start(True)
    
    def exit_app(self, code=None):
        tkHelper.clear_window(self.root)
        label = tk.Label(
            self.root,
            text="Exiting...",
            bg="black",
            fg="white",
            font=("Helvetica", 16),
        )
        label.pack(pady=20)
        label1 = tk.Label(
            self.root,
            text="Wait for the download to finish",
            bg="black",
            fg="white",
            font=("Helvetica", 16),
        )
        label1.pack(pady=20)
        self.root.update()
        
        
        self.stop_flag.set()
        if getattr(self, "download_thread", None) and self.download_thread.is_alive():
            self.download_helper.download_stop = True
            self.download_thread.join()
            
        if code is None:
            code = self.exit_code
        
        self.logger.debug("Exiting (%s)", code)
        self.exit_code = code
        self.root.destroy()
        self.root.quit()
        self.logger.info("Exit (%s)", code)


if __name__ == "__main__":
    while True:
        downloader = Anime1_downloader()
        r = downloader.start()
        if r != 1:
            break

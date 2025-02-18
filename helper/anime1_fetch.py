import json
import logging
import os
import re
from bs4 import BeautifulSoup
import requests
from pprint import pprint

HEADERS = {
    "accept": "/",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,zh-TW;q=0.7,zh;q=0.6",
    # "cache-control": "no-cache",
    "content-type": "application/x-www-form-urlencoded",
    "pragma": "no-cache",
    "priority": "u=1, i",
    "sec-ch-ua": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "referer": "https://anime1.me/",
}

DOWNLOADING_EXTENSION = ".downloading"

API_URL = "https://v.anime1.me/api"


class DownloadHelper:
    def __init__(self, download_path: str, logger: logging = logging) -> None:
        self.download_path = download_path
        self.logger = logger

        self.total_eps = 0
        self.download_stop = False

        self.process = {}
        self.total_size = 0
        self.downloaded_size = 0
        self.finished = 0

        self.logger.debug("DownloadHelper initialized")

    def get_video_data_me(self, url: str) -> dict:
        """
        Fetches video data from a given URL.
        This method sends a GET request to the specified URL, parses the HTML content,
        and extracts video-related information such as title, total episodes, and names.
        The extracted data is returned as a dictionary.
        Args:
            url (str): The URL of the webpage to fetch video data from.
        Returns:
            dict: A dictionary containing the following keys:
                - "title" (str): The title of the video or webpage.
                - "total episode" (int): The total number of episodes found.
                - "names" (list): A list of names associated with the video data.
                - "data" (dict): A dictionary mapping names to their corresponding video data.
        """
        self.logger.debug(f"Fetching video data for {url}")
        data = {"title": "", "total episode": 0, "names": [], "data": {}}

        # ----------- Fetching data from website -----------
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()  # Raise an HTTPError for bad responses
            # if response.status_code != 200:
            #     self.logger.error(f"Failed to fetch URL {url}. Status code: {response.status_code}")
            #     raise requests.RequestException(response)
        except requests.RequestException as e:
            raise e

        # ----------- Parsing data -----------
        # Parse the HTML content using BeautifulSoup

        soup = BeautifulSoup(response.text, "html.parser")

        # ----------- Extracting title -----------
        header_tag = soup.find("header", class_="page-header")
        if header_tag:
            title = header_tag.find("h1").text
        else:
            meta_tag = soup.find("meta", attrs={"name": "keywords"})
            if meta_tag:
                title = meta_tag["content"]
            else:
                title = "Unknown"
                self.logger.warning(f"Title not found for {url}")

        data["title"] = title

        # ----------- Extracting video data -----------
        articles = soup.find_all("article")
        for article in articles:
            name_tag = article.find("h2", class_="entry-title")
            if name_tag:
                name = name_tag.text.strip()
            else:
                name = "Unknown"
                self.logger.warning(f"Name not found in article for {url}")

            video_ele = article.find("video")
            if video_ele and "data-apireq" in video_ele.attrs:
                video_data = video_ele["data-apireq"]
                data["total episode"] += 1
                data["names"].append(name)
                data["data"][name] = video_data
            else:
                self.logger.warning(
                    f"Video element or data-apireq attribute not found in article for {url}"
                )

        numeric_positions = [(i, int(re.search(r'\[(\d+)\]', name).group(1))) for i, name in enumerate(data['names']) if re.search(r'\[(\d+)\]', name)]

        for i in range(len(numeric_positions) - 1):
            start_pos, start_val = numeric_positions[i]
            end_pos, end_val = numeric_positions[i + 1]
            gap = end_pos - start_pos - 1
            
            if gap > 0:
                for j in range(1, gap + 1):
                    gap_pos = start_pos + j
                    new_value = start_val + j * (end_val - start_val) / (gap + 1)
                    original_string = data['names'][gap_pos]
                    data['names'][gap_pos] = re.sub(r'\[.*?\]', f'[{new_value:.1f} {original_string[original_string.index("[") + 1:-1]}]', original_string)

        if numeric_positions:
            start = numeric_positions[0][1]
            end = numeric_positions[-1][1]            
            if start > end:
                data["names"].reverse()
        else:
            self.logger.error("No video found in the page")
            return None

        soup.find_all("player_html5_api")
        self.logger.debug("Anime data fetched successfully")
        return data

    def video_detail_api(self, session: requests.Session, d) -> dict:
        # Required session to work

        body = f"d={d}"

        response = session.post(API_URL, headers=HEADERS, data=body)
        try:
            response_json = response.json()
            response_dict = dict(response_json)
            self.logger.debug(f"API Response: {response_dict}")
        except json.JSONDecodeError:
            self.logger.error("Failed to decode JSON from response")
        return response_dict

    @staticmethod
    def get_expected_size(url: str, session: requests.Session = None) -> int:
        """
        Get the expected file size of a video from the server.
        Args:
            url (str): The URL of the video file.
        Returns:
            int: The expected file size in bytes.
        """
        header = HEADERS.copy()
        if session is None:
            head_response = requests.head(url, headers=header)
        else:
            head_response = session.head(url, headers=header)
        if head_response.status_code != 200:
            raise requests.RequestException(
                f"Failed to get file size. Status code: {head_response.status_code}"
            )

        expected_size = int(head_response.headers.get("Content-Length", 0))
        return expected_size

    @staticmethod
    def check_filename(path: str, filename: str) -> str:
        checked_title: str = "".join(
            c if c.isalnum() or c not in "/\\" or c in "._-" else "_" for c in filename
        )
        checked_title = re.sub(r"_+", "_", checked_title)
        if checked_title[-1] == "_":
            checked_title = checked_title[:-1]
        return os.path.join(path, f"{checked_title}.mp4")

    def download_video(
        self, _id, data: dict, session: requests.Session, chunk_size=8192
    ) -> None:
        if self.download_stop:
            self.logger.debug(f"{str(_id):>3} | Download stopped")
            return

        self.logger.info(f"{_id:>3} | Downloading video from {data['url']}")

        header = HEADERS.copy()

        if self.process.get(_id, None) is None:
            self.process[_id] = {
                "total_size": -1,
                "downloaded_size": 0,
                "finished": False,
                "success": False,
            }
        if self.process[_id].get("loading", False):
            self.logger.debug(
                f"{str(_id):>3} | Resuming download {self.process[_id]['downloaded_size'] / (1024 * 1024)/self.process[_id]['total_size']:.2%}"
            )
            header["Range"] = f"bytes={self.process[_id]['downloaded_size']}-"
            output_path = self.check_filename(data["download_path"], str(_id))
            output_path_temp = output_path + DOWNLOADING_EXTENSION
        else:
            # ------ Get the expected file size from the server ------
            expected_size = self.get_expected_size(data["url"], session)
            expected_size_mb = expected_size / (1024 * 1024)
            self.logger.debug(
                f"{str(_id):>3} | Expected file size: {expected_size_mb:.2f} MB"
            )

            # ---------------- Set file name and path ----------------
            output_path = self.check_filename(data["download_path"], str(_id))
            output_path_temp = f"{output_path}{DOWNLOADING_EXTENSION}"

            #  ----------------- Init process -----------------
            self.process[_id]["total_size"] = expected_size
            self.process[_id]["loading"] = False
            self.total_size += expected_size
            downloaded = 0

            # ------------ Check if have previous data ------------
            if os.path.exists(output_path_temp):
                downloaded = os.path.getsize(output_path_temp)
                if downloaded == expected_size:
                    self.downloaded_size += downloaded
                    self.process[_id]["downloaded_size"] = downloaded
                    self.process[_id]["success"] = True
                    self.finished += 1
                    self.logger.debug(f"{str(_id):>3} | File already fully downloaded")

                    if os.path.exists(output_path):
                        os.remove(output_path)
                    os.rename(output_path_temp, output_path)
                    return

                elif 0 < downloaded < expected_size:
                    downloaded_mb = downloaded / (1024 * 1024)
                    self.logger.debug(
                        f"{str(_id):>3} | Resuming download from {downloaded_mb} mb {downloaded_mb/expected_size_mb:.2%}"
                    )
                    header["Range"] = f"bytes={downloaded}-"

                else:
                    if downloaded >= expected_size:
                        self.logger.debug(
                            f"{str(_id):>3} | File are corrupted, re-downloading"
                        )
                    else:
                        self.logger.debug(f"{str(_id):>3} | Starting download")
                    os.remove(output_path_temp)
                    downloaded = 0
            else:
                self.logger.debug(f"{str(_id):>3} | Starting download")
            self.process[_id]["downloaded_size"] = downloaded
            self.downloaded_size += downloaded

        # ----------------- Start downloading -----------------
        response: requests.Response = session.get(
            data["url"], headers=header, stream=True
        )

        # ------------------- Downloading -------------------
        # Check for range not satisfiable
        if response.status_code == 416:
            # 416 Range Not Satisfiable
            # The server cannot serve the requested range
            # Re-download file
            self.logger.warning(
                f"{str(_id):>3} | Re-downloading file (Error response: 416)"
            )
            response: requests.Response = session.get(
                data["url"], headers=HEADERS, stream=True
            )

        # ----------------- Downloading Success -----------------
        if response.status_code in [200, 206]:
            if not os.path.exists(data["download_path"]):
                self.logger.debug(
                    f"{str(_id):>3} | Creating directory {data['download_path']}"
                )
                os.makedirs(data["download_path"])

            self.process[_id]["loading"] = True

            with open(output_path_temp, "ab") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if self.download_stop:
                        self.logger.debug(f"{str(_id):>3} | Download stopped")
                        return
                    if chunk:
                        f.write(chunk)
                        self.downloaded_size += len(chunk)
                        self.process[_id]["downloaded_size"] += len(chunk)

            # ----------------- Download completed -----------------
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(output_path_temp, output_path)
            self.process[_id]["success"] = True
            self.process[_id]["downloaded_size"] = self.process[_id]["total_size"]
            self.finished += 1
            self.logger.info(
                f"{str(_id):>3} | Download completed successfully: {output_path}"
            )

        # ----------------- Error handling -----------------
        elif response.status_code == 403:
            self.logger.error("403 Forbidden: Access to the resource is denied.")
            self.process[_id]["success"] = False
            return
        else:
            self.logger.error(
                f"{str(_id):^3} | Failed to download video. Status code: {response.status_code}. Message: {response.text}"
            )
            self.process[_id]["success"] = False

        # ----------------- Clean up -----------------
        # del self.process[_id]

    def download_episode(self, _id, data) -> None:
        """
        Downloads a specific episode of an anime.
        Args:
            _id (int): The ID of the episode to download.
            data (dict): A dictionary containing the data of the anime, including episode details.
        Returns:
            None
        Raises:
            Exception: If there is an error fetching video data for the specified episode.
        """
        session = requests.Session()

        try:
            api_data = self.video_detail_api(session, data["data"][_id])
            self.logger.debug(f"API Data: {api_data}")
            video_data = {
                "download_path": f"{self.download_path}/{data['title']}",
                "url": "https:" + api_data["s"][0]["src"],
            }
            self.logger.debug(f"Video Data: {video_data}")
            self.download_video(_id, video_data, session)

        except Exception as e:
            self.logger.error(f"Error fetching video data for {_id}: {e}")
            raise e



def test():
    url = "https://anime1.me/category/2020%e5%b9%b4%e5%86%ac%e5%ad%a3/%e6%88%90%e7%be%a4%e7%b5%90%e4%bc%b4-%e8%a5%bf%e9%a0%93%e5%ad%b8%e5%9c%92"
    response = requests.get(url)
    data = {"title": "", "total episode": 0, "names": [], "data": {}}

    soup = BeautifulSoup(response.text, "html.parser")

    articles = soup.find_all("article")
    for article in articles:
        name_tag = article.find("h2", class_="entry-title")
        if name_tag:
            name = name_tag.text.strip()
        else:
            name = "Unknown"
            logging.warning(f"Name not found in article for {url}")

        video_ele = article.find("video")
        if video_ele and "data-apireq" in video_ele.attrs:
            video_data = video_ele["data-apireq"]
            data["total episode"] += 1
            data["names"].append(name)
            data["data"][name] = video_data
        else:
            player_space = article.find(class_="player-space")
            if not player_space:
                logging.warning(
                    f"Video element or data-apireq attribute not found in article for {url}"
                )
            else:
                src = player_space.find("button")["data-src"]
                print(src)

    data["names"].reverse()  # Website is reversed

    print(data)

    soup = BeautifulSoup(response.text, "html.parser")
    other_video = soup.find_all("player_html5_api")
    print(other_video)

def test2():
    URL = r"https://ipp.anime1.me/DkiRr?autoplay=1"
    session = requests.Session()
    response = session.get(URL, headers=HEADERS)
    
    # {"c":"679",
    # "e":"2b",
    # "t":1731506121,
    # "p":0,
    # "s":"a424bc070358074db5a6b793fbe1f29e"}
    
    
    soup = BeautifulSoup(response.text, "html.parser")
    source = soup.find("source")
    if source:
        print(source["src"])
        header = HEADERS.copy()
        # response = requests.get(source["src"])
        downloaded_size = 0
        # response: requests.Response = session.get(
        #     source["src"], headers=header, stream=True
        # )
        response: requests.Response = session.get(source["src"], headers=header)
        print(response.status_code)
        print(response.text)
        # with open("temp.mp4", "ab") as f:
        #     for chunk in response.iter_content(chunk_size=8192):
        #         if chunk:
        #             f.write(chunk)
        #             downloaded_size += len(chunk)
        
        print(downloaded_size)
        
    else:
        print("Not found")
        print(response.text)
        
if __name__ == "__main__":
    # messagebox.showinfo("Info", "Please run the main file to start the download process.")
    # exit()
    
    # test()
    test2()

import json
import logging
import os
import re
from bs4 import BeautifulSoup
import requests

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


class DownloadHelper:
    def __init__(self, logger: logging = logging) -> None:
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
            response = requests.get(url)
            response.raise_for_status()  # Raise an HTTPError for bad responses
        except requests.RequestException as e:
            self.logger.error(f"Error fetching URL {url}: {e}")
            return data

        # ----------- Parsing data -----------
        soup = BeautifulSoup(response.text, "html.parser")
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
                self.logger.warning(f"Video element or data-apireq attribute not found in article for {url}")

        data["names"].reverse()  # Website is reversed

        self.logger.info("Anime data fetched successfully")
        self.logger.debug(f"Url: {url}")
        return data

    def video_detail_api(self, session: requests.Session, d) -> dict:
        # Required session to work

        url = "https://v.anime1.me/api"
        body = f"d={d}"

        response = session.post(url, headers=HEADERS, data=body)
        try:
            response_json = response.json()
            response_dict = dict(response_json)
            self.logger.debug(f"API Response: {response_dict}")
        except json.JSONDecodeError:
            self.logger.error("Failed to decode JSON from response")
        return response_dict

    def download_video(
        self, _id, data: dict, session: requests.Session, chunk_size=8192
    ) -> None:
        self.logger.info(f"{_id:>3} | Downloading video from {data['url']}")
        if self.download_stop:
            self.logger.debug(f"{str(_id):>3} | Download stopped")
            return

        header = HEADERS.copy()

        if self.process.get(_id, None) is not None:
            self.logger.debug(
                f"{str(_id):>3} | Resuming download {self.process[_id]['downloaded_size'] / (1024 * 1024)/self.process[_id]['total_size']:.2%}"
            )
            header["Range"] = f"bytes={self.process[_id]['downloaded_size']}-"
        else:
            # ------ Get the expected file size from the server ------
            head_response = session.head(data["url"], headers=header)
            if head_response.status_code != 200:
                self.logger.error(
                    f"Failed to get file size. Status code: {head_response.status_code}"
                )
                return
            expected_size = int(head_response.headers.get("Content-Length", 0))
            expected_size_mb = expected_size / (1024 * 1024)
            self.logger.debug(
                f"{str(_id):>3} | Expected file size: {expected_size_mb:.2f} MB"
            )

            # ---------------- Set file name and path ----------------
            checked_title: str = "".join(
                c if c.isalnum() or c in "._-" else "_" for c in _id
            )
            checked_title = re.sub(r"_+", "_", checked_title)
            if checked_title[-1] == "_":
                checked_title = checked_title[:-1]
            output_path = os.path.join(data["download_path"], f"{checked_title}.mp4")
            output_path_temp = output_path + DOWNLOADING_EXTENSION

            #  ----------------- Init process -----------------
            self.process[_id] = {"total_size": expected_size, "finished": False}
            self.total_size += expected_size
            downloaded = 0

            # ------------ Check if have previous data ------------
            if os.path.exists(output_path_temp):
                downloaded = os.path.getsize(output_path_temp)
                if downloaded == expected_size:
                    self.downloaded_size += downloaded
                    self.process[_id]["downloaded_size"] = downloaded
                    self.process[_id]["finished"] = True
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

        # ----------------- Downloading -----------------
        # if response.status_code == 416:
        #     self.logger.debug(f"{str(_id):>3} | File already fully downloaded")
        #     self.process[_id]["finished"] = True
        #     self.finished += 1
        #     return
        if response.status_code in [200, 206]:
            if not os.path.exists(data["download_path"]):
                self.logger.debug(
                    f"{str(_id):>3} | Creating directory {data['download_path']}"
                )
                os.makedirs(data["download_path"])

            with open(output_path_temp, "ab") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if self.download_stop:
                        self.logger.debug(f"{str(_id):>3} | Download stopped")
                        return
                    if chunk:
                        f.write(chunk)
                        self.downloaded_size += len(chunk)
                        self.process[_id]["downloaded_size"] += len(chunk)

            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(output_path_temp, output_path)
            self.process[_id]["finished"] = True
            self.finished += 1
            self.logger.info(
                f"{str(_id):>3} | Download completed successfully: {output_path}"
            )

        # ----------------- Error handling -----------------
        elif response.status_code == 403:
            self.logger.error("403 Forbidden: Access to the resource is denied.")
            return
        else:
            self.logger.error(
                f"{str(_id):^3} | Failed to download video. Status code: {response.status_code}. Message: {response.text}"
            )

    def download_episode(self, _id, data, download_path) -> None:
        session = requests.Session()

        try:
            api_data = self.video_detail_api(session, data["data"][_id])
            self.logger.debug(f"API Data: {api_data}")
            video_data = {
                "download_path": f"{download_path}/{data['title']}",
                "url": "https:" + api_data["s"][0]["src"],
            }
            self.logger.debug(f"Video Data: {video_data}")
            self.download_video(_id, video_data, session)

        except Exception as e:
            self.logger.error(f"Error fetching video data for {_id}: {e}")

"""
Download Worker Module
QThread-based worker handling chunked HTTP downloads and yt-dlp video downloads with pause/resume support.
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests
import yt_dlp
from PyQt6.QtCore import QThread, pyqtSignal

from downloader_app.core.hongguo_search import get_drama_details, get_episode_stream_url
from downloader_app.models.download_task import DownloadTask, TaskStatus
from downloader_app.utils.logger import setup_logger
from downloader_app.utils.validators import extract_filename_from_url, sanitize_filename

logger = setup_logger("downloader.worker")


def get_ffmpeg_path() -> str | None:
    """Finds ffmpeg executable in system PATH or via imageio_ffmpeg."""
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        exe_dir = os.path.dirname(exe)
        # Ensure a standard ffmpeg.exe exists in the binaries folder for compatibility
        std_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        std_path = os.path.join(exe_dir, std_name)
        if not os.path.exists(std_path) and os.path.exists(exe):
            try:
                shutil.copyfile(exe, std_path)
            except OSError as err:
                logger.debug(f"Could not copy ffmpeg to standard name: {err}")

        if exe_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = exe_dir + os.pathsep + os.environ.get("PATH", "")

        return std_path if os.path.exists(std_path) else exe
    except (ImportError, OSError):
        return None


def clean_ansi_escapes(text: str) -> str:
    """Strips terminal ANSI color codes from strings."""
    ansi_regex = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_regex.sub("", text).strip()


class DownloadCancelledError(Exception):
    """Raised when a download is cancelled by user."""


class DownloadPausedError(Exception):
    """Raised when a download is paused by user."""


class DownloadWorker(QThread):
    """
    Worker thread that executes a download task.
    Emits Qt signals to report status, progress, speed, completion, and errors.
    """

    progress_changed = pyqtSignal(
        str, float, float
    )  # task_id, percent, speed_bytes_sec
    status_changed = pyqtSignal(str, object)  # task_id, TaskStatus
    download_finished = pyqtSignal(str)  # task_id
    error = pyqtSignal(str, str)  # task_id, error_message
    filename_determined = pyqtSignal(str, str)  # task_id, filename

    def __init__(
        self,
        task: DownloadTask,
        chunk_size: int = 64 * 1024,
        timeout: int = 30,
    ):
        super().__init__()
        self.task = task
        self.chunk_size = chunk_size
        self.timeout = timeout
        self._is_paused = False
        self._is_cancelled = False

    def pause(self) -> None:
        """Flags the worker to pause the active download."""
        self._is_paused = True

    def cancel(self) -> None:
        """Flags the worker to cancel and terminate the download."""
        self._is_cancelled = True

    def run(self) -> None:
        """Entrypoint for the worker thread."""
        logger.info(f"Starting download task {self.task.id}: {self.task.url}")
        self.task.status = TaskStatus.DOWNLOADING
        self.status_changed.emit(self.task.id, TaskStatus.DOWNLOADING)

        try:
            # Check whether to use Hongguo, yt-dlp, or direct requests
            if self._is_hongguo_url(self.task.url):
                self._download_hongguo_series()
            elif self._should_use_ytdlp(self.task.url):
                self._download_with_ytdlp()
            else:
                self._download_with_requests()

        except (DownloadCancelledError, DownloadPausedError):
            if self._is_cancelled:
                logger.info(f"Task {self.task.id} was cancelled.")
                self.task.status = TaskStatus.CANCELLED
                self.status_changed.emit(self.task.id, TaskStatus.CANCELLED)
            else:
                logger.info(f"Task {self.task.id} was paused.")
                self.task.status = TaskStatus.PAUSED
                self.status_changed.emit(self.task.id, TaskStatus.PAUSED)
        except Exception as e:
            if self._is_cancelled:
                logger.info(f"Task {self.task.id} was cancelled.")
                self.task.status = TaskStatus.CANCELLED
                self.status_changed.emit(self.task.id, TaskStatus.CANCELLED)
            elif self._is_paused:
                logger.info(f"Task {self.task.id} was paused.")
                self.task.status = TaskStatus.PAUSED
                self.status_changed.emit(self.task.id, TaskStatus.PAUSED)
            else:
                raw_err = str(e)
                err_msg = clean_ansi_escapes(raw_err)
                logger.exception(f"Download error on task {self.task.id}: {err_msg}")
                self.task.status = TaskStatus.ERROR
                self.task.error_message = err_msg
                self.status_changed.emit(self.task.id, TaskStatus.ERROR)
                self.error.emit(self.task.id, err_msg)

    def _should_use_ytdlp(self, url: str) -> bool:
        """Determines whether URL should be handled by yt-dlp rather than raw HTTP stream."""
        try:
            extractors = yt_dlp.extractor.gen_extractors()
            for ie in extractors:
                if ie.IE_NAME.lower() != "generic" and ie.suitable(url):
                    return True
        except (AttributeError, ValueError):
            pass
        return False

    def _download_with_requests(self) -> None:
        """Streams direct HTTP/HTTPS download with chunking and resume support."""
        url = self.task.url
        dest_dir = Path(self.task.destination_path or ".")
        dest_dir.mkdir(parents=True, exist_ok=True)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Referer": "https://hongguoduanju.com/",
        }

        # Step 1: Query headers / metadata gracefully
        content_disp = None
        try:
            initial_resp = requests.head(
                url, headers=headers, allow_redirects=True, timeout=self.timeout
            )
            if initial_resp.status_code == 200:
                content_disp = initial_resp.headers.get("Content-Disposition")
        except requests.RequestException as e:
            logger.debug(f"HEAD request failed for {url}: {e}")

        if not self.task.filename or self.task.filename.startswith("download"):
            self.task.filename = extract_filename_from_url(url, content_disp)
        self.filename_determined.emit(self.task.id, self.task.filename)

        final_filepath = dest_dir / self.task.filename
        part_filepath = dest_dir / f"{self.task.filename}.part"

        # Check existing bytes for Range header
        existing_bytes = 0
        if part_filepath.exists():
            existing_bytes = part_filepath.stat().st_size

        if existing_bytes > 0:
            headers["Range"] = f"bytes={existing_bytes}-"
            logger.info(f"Resuming task {self.task.id} at byte {existing_bytes}")

        req_method = requests.get(
            url, headers=headers, stream=True, timeout=self.timeout
        )

        # Check if server accepted Range
        if req_method.status_code == 206:
            # Partial Content
            content_range = req_method.headers.get("Content-Range", "")
            if "/" in content_range:
                try:
                    total_length = int(content_range.split("/")[-1])
                except ValueError:
                    total_length = existing_bytes + int(
                        req_method.headers.get("Content-Length", 0)
                    )
            else:
                total_length = existing_bytes + int(
                    req_method.headers.get("Content-Length", 0)
                )
            mode = "ab"
            downloaded = existing_bytes
        elif req_method.status_code == 200:
            # Full content (server does not support Range or fresh start)
            total_length = int(req_method.headers.get("Content-Length", 0))
            mode = "wb"
            downloaded = 0
            existing_bytes = 0
        else:
            req_method.raise_for_status()

        self.task.total_bytes = total_length
        self.task.downloaded_bytes = downloaded

        start_time = time.time()
        last_speed_time = start_time
        last_downloaded = downloaded

        with open(part_filepath, mode) as f:
            for chunk in req_method.iter_content(chunk_size=self.chunk_size):
                if self._is_cancelled:
                    f.close()
                    if part_filepath.exists():
                        part_filepath.unlink(missing_ok=True)
                    self.task.status = TaskStatus.CANCELLED
                    self.status_changed.emit(self.task.id, TaskStatus.CANCELLED)
                    return

                if self._is_paused:
                    self.task.status = TaskStatus.PAUSED
                    self.status_changed.emit(self.task.id, TaskStatus.PAUSED)
                    return

                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    self.task.downloaded_bytes = downloaded

                    # Calculate progress & speed
                    now = time.time()
                    if now - last_speed_time >= 0.2:
                        elapsed = now - last_speed_time
                        speed = (downloaded - last_downloaded) / elapsed
                        last_speed_time = now
                        last_downloaded = downloaded
                        self.task.speed_bytes_per_sec = speed

                        if total_length > 0:
                            percent = (downloaded / total_length) * 100.0
                        else:
                            percent = 0.0
                        self.task.progress_percent = percent
                        self.progress_changed.emit(self.task.id, percent, speed)

        # Download completed
        if part_filepath.exists():
            if final_filepath.exists():
                final_filepath.unlink(missing_ok=True)
            part_filepath.replace(final_filepath)

        self.task.progress_percent = 100.0
        self.task.speed_bytes_per_sec = 0.0
        self.task.status = TaskStatus.DONE
        self.progress_changed.emit(self.task.id, 100.0, 0.0)
        self.status_changed.emit(self.task.id, TaskStatus.DONE)
        self.download_finished.emit(self.task.id)
        logger.info(f"Task {self.task.id} completed: {final_filepath}")

    def _download_with_ytdlp(self) -> None:
        """Handles video downloads using yt-dlp extractor."""
        dest_dir = Path(self.task.destination_path or ".")
        dest_dir.mkdir(parents=True, exist_ok=True)

        def ytdlp_hook(d: dict) -> None:
            if self._is_cancelled:
                raise DownloadCancelledError("Download cancelled by user")
            if self._is_paused:
                raise DownloadPausedError("Download paused by user")

            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                speed = d.get("speed") or 0.0

                filename = d.get("filename")
                if filename and not self.task.filename:
                    clean_name = os.path.basename(filename)
                    self.task.filename = clean_name
                    self.filename_determined.emit(self.task.id, clean_name)

                percent = (downloaded / total * 100.0) if total > 0 else 0.0
                self.task.downloaded_bytes = downloaded
                self.task.total_bytes = total
                self.task.progress_percent = percent
                self.task.speed_bytes_per_sec = speed
                self.progress_changed.emit(self.task.id, percent, speed)

            elif status == "finished":
                self.task.progress_percent = 100.0
                self.task.speed_bytes_per_sec = 0.0
                self.progress_changed.emit(self.task.id, 100.0, 0.0)

        out_template = str(dest_dir / "%(title)s.%(ext)s")
        ffmpeg_bin = get_ffmpeg_path()
        node_bin = shutil.which("node") or shutil.which("deno")
        ydl_opts = {
            "outtmpl": out_template,
            "progress_hooks": [ytdlp_hook],
            "quiet": True,
            "no_warnings": True,
            "continuedl": True,
            "nocheckcertificate": True,
            "retries": 10,
            "fragment_retries": 10,
            "file_access_retries": 5,
            "concurrent_fragment_downloads": 4,
            "buffersize": 1024 * 1024,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-Hans", "zh-Hant", "zh", "en", "km"],
            "subtitlesformat": "srt",
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
            },
        }
        if node_bin:
            ydl_opts["js_runtimes"] = {"node": {}} if "node" in node_bin.lower() else {"deno": {}}

        quality_str = str(getattr(self.task, "quality", "1080p") or "1080p").lower()
        if "2160" in quality_str or "4k" in quality_str:
            target_res = "2160"
        elif "1440" in quality_str or "2k" in quality_str:
            target_res = "1440"
        elif "720" in quality_str:
            target_res = "720"
        elif "480" in quality_str:
            target_res = "480"
        elif "360" in quality_str:
            target_res = "360"
        elif "best" in quality_str:
            target_res = ""
        else:
            target_res = "1080"

        ydl_opts["format"] = "bestvideo+bestaudio/best"
        format_sort = []
        if target_res:
            format_sort.append(f"res:{target_res}")
        format_sort.extend(["fps", "vbr", "tbr", "quality", "size"])
        ydl_opts["format_sort"] = format_sort

        if ffmpeg_bin:
            ydl_opts["ffmpeg_location"] = ffmpeg_bin
            ydl_opts["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info to get filename beforehand
            info = ydl.extract_info(self.task.url, download=False)
            if info:
                title = info.get("title", "video")
                ext = info.get("ext", "mp4")
                filename = sanitize_filename(f"{title}.{ext}")
                self.task.filename = filename
                self.filename_determined.emit(self.task.id, filename)

            ydl.download([self.task.url])

        self.task.status = TaskStatus.DONE
        self.status_changed.emit(self.task.id, TaskStatus.DONE)
        self.download_finished.emit(self.task.id)
        logger.info(f"Task {self.task.id} (yt-dlp) completed successfully.")

    def _is_hongguo_url(self, url: str) -> bool:
        """Checks if URL is a Hongguo short drama URL or series ID."""
        if not url:
            return False
        clean = url.strip()
        if "hongguoduanju.com" in clean or "series_id=" in clean or "/player/" in clean:
            return True
        if clean.isdigit() and len(clean) >= 15:
            return True
        return False

    def _extract_hongguo_series_id(self, url: str) -> str | None:
        """Extracts series_id from a Hongguo URL or string."""
        clean = url.strip()
        if "series_id=" in clean:
            match = re.search(r"series_id=(\d+)", clean)
            if match:
                return match.group(1)
        if "/player/" in clean:
            match = re.search(r"/player/(\d+)", clean)
            if match:
                return match.group(1)
        if clean.isdigit():
            return clean
        return None

    def _extract_hongguo_ep_index(self, url: str) -> int | None:
        """Extracts single episode index from URL if present (e.g. #ep_5)."""
        if "#ep_" in url:
            match = re.search(r"#ep_(\d+)", url)
            if match:
                return int(match.group(1))
        return getattr(self.task, "single_ep_index", None)

    def _download_hongguo_series(self) -> None:
        """Downloads all episodes or a single episode of a Hongguo drama series."""
        url = self.task.url
        series_id = self._extract_hongguo_series_id(url)
        if not series_id:
            raise ValueError(f"Could not extract series_id from Hongguo URL: {url}")

        single_ep = self._extract_hongguo_ep_index(url)
        if single_ep is not None:
            self._download_hongguo_single_episode(series_id, single_ep)
            return

        logger.info(f"Fetching drama details for Hongguo series_id: {series_id}")
        details = get_drama_details(series_id)
        if not details or not details.get("vid_list"):
            raise ValueError(f"Failed to fetch episodes or VID list for Hongguo series {series_id}")

        is_episodes_mode = "#episodes" in url or getattr(self.task, "is_episodes", False)

        raw_title = details.get("title") or f"Hongguo_Series_{series_id}"
        series_title = sanitize_filename(raw_title)

        dest_dir = Path(self.task.destination_path or ".")
        dest_dir.mkdir(parents=True, exist_ok=True)

        if is_episodes_mode:
            final_filename = f"{series_title} [Episodes]"
            save_dir = dest_dir / f"{series_title} (Episodes)"
        else:
            final_filename = f"{series_title}.mp4"
            save_dir = dest_dir / f"{series_title}_eps_{series_id}"

        save_dir.mkdir(parents=True, exist_ok=True)
        final_filepath = dest_dir / final_filename

        self.task.filename = final_filename
        self.filename_determined.emit(self.task.id, final_filename)

        vid_list = details["vid_list"]
        selected_eps = getattr(self.task, "selected_episodes", None)
        if selected_eps:
            ep_items = [(idx, vid_list[idx - 1]) for idx in selected_eps if 1 <= idx <= len(vid_list)]
        else:
            ep_items = list(enumerate(vid_list, start=1))

        total_episodes = len(ep_items)
        logger.info(f"Downloading Hongguo series '{series_title}' ({'EPISODES MODE' if is_episodes_mode else 'FULL MOVIE MODE'}) with {total_episodes} selected episodes.")

        downloaded_files = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://hongguoduanju.com/",
        }

        try:
            total_downloaded = 0
            total_estimated_bytes = 0
            start_time = time.time()
            last_speed_time = start_time
            last_downloaded = 0

            # Scan existing downloaded files in save_dir to account for resumed downloads
            for ep_f in save_dir.glob("*.mp4"):
                if ep_f.stat().st_size > 10000:
                    total_downloaded += ep_f.stat().st_size

            self.task.downloaded_bytes = total_downloaded

            for step_num, (idx, vid) in enumerate(ep_items, start=1):
                if self._is_cancelled:
                    raise DownloadCancelledError("Download cancelled by user")
                if self._is_paused:
                    raise DownloadPausedError("Download paused by user")

                ep_file = save_dir / (f"{series_title}_EP{idx:03d}.mp4" if is_episodes_mode else f"ep_{idx:04d}.mp4")
                if ep_file.exists() and ep_file.stat().st_size > 10000:
                    downloaded_files.append(ep_file)
                    continue

                ep_stream = get_episode_stream_url(series_id, idx, vid)
                if not ep_stream or not ep_stream.get("video_url"):
                    logger.warning(f"Could not get stream URL for episode {idx} (vid={vid}), skipping.")
                    continue

                stream_url = ep_stream["video_url"]

                resp = requests.get(stream_url, headers=headers, stream=True, timeout=self.timeout)
                resp.raise_for_status()

                ep_content_len = int(resp.headers.get("Content-Length", 0))
                if ep_content_len > 0:
                    avg_ep_size = (total_downloaded + ep_content_len) / step_num
                    total_estimated_bytes = int(total_downloaded + ep_content_len + avg_ep_size * (total_episodes - step_num))
                    self.task.total_bytes = total_estimated_bytes

                part_ep_file = save_dir / f"{ep_file.name}.part"
                with open(part_ep_file, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=self.chunk_size):
                        if self._is_cancelled:
                            f.close()
                            part_ep_file.unlink(missing_ok=True)
                            raise DownloadCancelledError("Download cancelled by user")
                        if self._is_paused:
                            f.close()
                            raise DownloadPausedError("Download paused by user")
                        if chunk:
                            f.write(chunk)
                            total_downloaded += len(chunk)
                            self.task.downloaded_bytes = total_downloaded

                            now = time.time()
                            if now - last_speed_time >= 0.2:
                                elapsed = now - last_speed_time
                                speed = (total_downloaded - last_downloaded) / elapsed
                                last_speed_time = now
                                last_downloaded = total_downloaded
                                self.task.speed_bytes_per_sec = speed

                                max_percent = 100.0 if is_episodes_mode else 99.0
                                if total_estimated_bytes > 0:
                                    percent = min(max_percent, (total_downloaded / total_estimated_bytes) * 100.0)
                                else:
                                    percent = min(max_percent, (step_num / total_episodes) * 100.0)

                                self.task.progress_percent = percent
                                self.progress_changed.emit(self.task.id, percent, speed)

                if part_ep_file.exists():
                    part_ep_file.replace(ep_file)
                    downloaded_files.append(ep_file)

            if not downloaded_files:
                raise RuntimeError("No episodes could be downloaded for series.")

            final_total_bytes = sum(f.stat().st_size for f in downloaded_files)
            self.task.total_bytes = final_total_bytes
            self.task.downloaded_bytes = final_total_bytes

            if is_episodes_mode:
                self.task.progress_percent = 100.0
                self.task.speed_bytes_per_sec = 0.0
                self.task.status = TaskStatus.DONE
                self.progress_changed.emit(self.task.id, 100.0, 0.0)
                self.status_changed.emit(self.task.id, TaskStatus.DONE)
                self.download_finished.emit(self.task.id)
                logger.info(f"Hongguo series '{series_title}' all individual episodes saved to: {save_dir}")
                return

            # Concat with FFmpeg for Full Movie mode
            self.task.progress_percent = 99.0
            self.task.speed_bytes_per_sec = 0.0
            self.progress_changed.emit(self.task.id, 99.0, 0.0)
            concat_txt = save_dir / "concat_list.txt"
            with open(concat_txt, "w", encoding="utf-8") as f:
                for ep_p in downloaded_files:
                    safe_path = ep_p.name.replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")

            ffmpeg_bin = get_ffmpeg_path() or "ffmpeg"
            logger.info(f"Concatenating {len(downloaded_files)} episodes using FFmpeg...")

            cmd = [
                ffmpeg_bin,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_txt),
                "-c", "copy",
                str(final_filepath),
            ]

            process = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(save_dir)
            )

            if process.returncode != 0 and not final_filepath.exists():
                logger.error(f"FFmpeg concat failed: {process.stderr}")
                raise RuntimeError(f"FFmpeg concatenation failed: {process.stderr[:200]}")

            # Clean up temp directory
            try:
                shutil.rmtree(save_dir, ignore_errors=True)
            except Exception as clean_err:
                logger.warning(f"Could not remove temp directory {save_dir}: {clean_err}")

            self.task.progress_percent = 100.0
            self.task.speed_bytes_per_sec = 0.0
            self.task.status = TaskStatus.DONE
            self.progress_changed.emit(self.task.id, 100.0, 0.0)
            self.status_changed.emit(self.task.id, TaskStatus.DONE)
            self.download_finished.emit(self.task.id)
            logger.info(f"Hongguo series '{series_title}' completed successfully: {final_filepath}")

        except Exception:
            raise

    def _download_hongguo_single_episode(self, series_id: str, ep_index: int) -> None:
        """Downloads a single specific episode directly to the destination path."""
        logger.info(f"Fetching drama details for single episode {ep_index} of series_id: {series_id}")
        details = get_drama_details(series_id)
        if not details or not details.get("vid_list"):
            raise ValueError(f"Failed to fetch metadata or VID list for series {series_id}")

        vid_list = details["vid_list"]
        if ep_index < 1 or ep_index > len(vid_list):
            raise ValueError(f"Invalid episode index {ep_index} for series with {len(vid_list)} episodes")

        vid = vid_list[ep_index - 1]
        raw_title = details.get("title") or f"Hongguo_Series_{series_id}"
        series_title = sanitize_filename(raw_title)

        if not self.task.filename or self.task.filename.startswith("download"):
            self.task.filename = f"{series_title} - Episode {ep_index:02d}.mp4"
        self.filename_determined.emit(self.task.id, self.task.filename)

        dest_dir = Path(self.task.destination_path or ".")
        dest_dir.mkdir(parents=True, exist_ok=True)

        final_filepath = dest_dir / self.task.filename
        part_filepath = dest_dir / f"{self.task.filename}.part"

        ep_stream = get_episode_stream_url(series_id, ep_index, vid)
        if not ep_stream or not ep_stream.get("video_url"):
            raise RuntimeError(f"Could not get stream URL for episode {ep_index} (vid={vid})")

        stream_url = ep_stream["video_url"]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://hongguoduanju.com/",
        }

        resp = requests.get(stream_url, headers=headers, stream=True, timeout=self.timeout)
        resp.raise_for_status()

        total_bytes = int(resp.headers.get("Content-Length", 0))
        self.task.total_bytes = total_bytes

        downloaded = 0
        start_time = time.time()
        last_speed_time = start_time
        last_downloaded = 0

        with open(part_filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=self.chunk_size):
                if self._is_cancelled:
                    f.close()
                    part_filepath.unlink(missing_ok=True)
                    raise DownloadCancelledError("Download cancelled by user")
                if self._is_paused:
                    f.close()
                    raise DownloadPausedError("Download paused by user")
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    self.task.downloaded_bytes = downloaded

                    now = time.time()
                    if now - last_speed_time >= 0.2:
                        elapsed = now - last_speed_time
                        speed = (downloaded - last_downloaded) / elapsed
                        last_speed_time = now
                        last_downloaded = downloaded
                        self.task.speed_bytes_per_sec = speed

                        percent = (downloaded / total_bytes * 100.0) if total_bytes > 0 else 0.0
                        self.task.progress_percent = percent
                        self.progress_changed.emit(self.task.id, percent, speed)

        if part_filepath.exists():
            if final_filepath.exists():
                final_filepath.unlink(missing_ok=True)
            part_filepath.replace(final_filepath)

        self.task.progress_percent = 100.0
        self.task.speed_bytes_per_sec = 0.0
        self.task.status = TaskStatus.DONE
        self.progress_changed.emit(self.task.id, 100.0, 0.0)
        self.status_changed.emit(self.task.id, TaskStatus.DONE)
        self.download_finished.emit(self.task.id)
        logger.info(f"Task {self.task.id} (Single Episode {ep_index}) completed: {final_filepath}")

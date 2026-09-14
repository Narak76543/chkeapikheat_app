"""
Video Splitter Core Module
Lossless QThread-based video splitter using FFmpeg segmenting with stream copy (-c copy).
Splits a movie into customizable minute-based episodes or extracts specific time range clips.
"""

import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from downloader_app.core.downloader import get_ffmpeg_path
from downloader_app.utils.logger import setup_logger
from downloader_app.utils.validators import sanitize_filename

logger = setup_logger("downloader.video_splitter")


class VideoSplitterWorker(QThread):
    """Worker thread that executes lossless FFmpeg stream splitting or clip trimming."""

    progress_changed = pyqtSignal(float)
    status_changed = pyqtSignal(str)
    finished = pyqtSignal(str, list)  # output_dir, generated_file_paths
    error = pyqtSignal(str)

    # Signal aliases for backward compatibility
    progress = progress_changed
    completed = finished

    def __init__(
        self,
        input_file: str,
        minutes_per_episode: float = 10.0,
        output_dir: str = "",
        title_prefix: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        parent: QThread | None = None,
    ) -> None:
        super().__init__(parent)
        self.input_file = Path(input_file)
        self.minutes_per_episode = max(0.1, float(minutes_per_episode))
        self.output_dir = Path(output_dir) if output_dir else self.input_file.parent / f"{self.input_file.stem}_episodes"
        self.title_prefix = title_prefix or self.input_file.stem
        self.start_time = start_time.strip() if start_time and start_time.strip() else None
        self.end_time = end_time.strip() if end_time and end_time.strip() else None
        self._process: subprocess.Popen | None = None
        self._is_cancelled: bool = False

    def cancel(self) -> None:
        """Stops the FFmpeg splitting process if active."""
        self._is_cancelled = True
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.kill()
            except OSError:
                pass
        logger.info(
            f"VideoSplitterWorker for {self.input_file.name} cancelled by user."
        )

    def run(self) -> None:
        ffmpeg_bin = get_ffmpeg_path()
        if not ffmpeg_bin:
            self.error.emit("FFmpeg executable could not be found.")
            return

        if not self.input_file.exists():
            self.error.emit(f"Input file not found: {self.input_file}")
            return

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.error.emit(f"Failed to create output directory: {e}")
            return

        ext = self.input_file.suffix or ".mp4"
        clean_prefix = sanitize_filename(self.title_prefix, fallback="Episode")

        # Check mode: Time range cut vs. N-minute episode segmenting
        is_range_mode = bool(self.start_time or self.end_time)

        if is_range_mode:
            out_file = self.output_dir / f"{clean_prefix}_Cut{ext}"
            cmd = [ffmpeg_bin, "-y"]
            if self.start_time:
                cmd.extend(["-ss", self.start_time])
            if self.end_time:
                cmd.extend(["-to", self.end_time])
            cmd.extend([
                "-i",
                str(self.input_file.resolve()),
                "-c",
                "copy",
                "-map",
                "0",
                str(out_file),
            ])
        else:
            segment_seconds = int(self.minutes_per_episode * 60)
            out_pattern = self.output_dir / f"ep%d_{clean_prefix}{ext}"
            cmd = [
                ffmpeg_bin,
                "-y",
                "-i",
                str(self.input_file.resolve()),
                "-c",
                "copy",
                "-map",
                "0",
                "-f",
                "segment",
                "-segment_time",
                str(segment_seconds),
                "-reset_timestamps",
                "1",
                "-segment_start_number",
                "1",
                str(out_pattern),
            ]

        logger.info(f"Running video split command for output dir: {self.output_dir}")
        self.status_changed.emit("Splitting video...")
        self.progress_changed.emit(10.0)

        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NO_WINDOW

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )

            _, stderr = self._process.communicate()

            if self._is_cancelled:
                self.error.emit("Splitting cancelled.")
                return

            if self._process.returncode != 0:
                err_summary = stderr[-400:] if stderr else "Unknown error"
                logger.error(f"FFmpeg split failed: {err_summary}")
                self.error.emit(f"FFmpeg error: {err_summary}")
                return

            if is_range_mode:
                generated_files = [str(out_file)] if out_file.exists() else []
            else:
                generated_files = sorted(
                    str(p) for p in self.output_dir.glob(f"ep*_{clean_prefix}{ext}")
                )

            self.progress_changed.emit(100.0)
            self.status_changed.emit("Splitting completed!")
            self.finished.emit(str(self.output_dir), generated_files)
            logger.info(
                f"Successfully split into {len(generated_files)} files in {self.output_dir}"
            )

        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            logger.error(f"Unexpected error during video split: {e}")
            self.error.emit(str(e))

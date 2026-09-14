"""
Queue Manager Module
Manages download task list, worker execution, concurrency limits, and task lifecycle.
"""

from PyQt6.QtCore import QObject, pyqtSignal

from downloader_app.core.config import AppConfig
from downloader_app.core.downloader import DownloadWorker
from downloader_app.models.download_task import DownloadTask, TaskStatus
from downloader_app.utils.logger import setup_logger
from downloader_app.utils.validators import extract_filename_from_url

logger = setup_logger("downloader.queue_manager")


class QueueManager(QObject):
    """
    Coordinates download queue, enforces max concurrent downloads, and delegates work to DownloadWorkers.
    """

    task_added = pyqtSignal(object)  # DownloadTask
    task_updated = pyqtSignal(object)  # DownloadTask
    task_removed = pyqtSignal(str)  # task_id
    queue_counts_changed = pyqtSignal(int, int)  # active_count, total_count

    def __init__(self, config: AppConfig | None = None):
        super().__init__()
        self.config = config or AppConfig.load()
        self.tasks: list[DownloadTask] = []
        self._workers: dict[str, DownloadWorker] = {}

    def get_task(self, task_id: str) -> DownloadTask | None:
        """Finds task by ID."""
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def add(
        self,
        url: str,
        destination_path: str | None = None,
        filename: str | None = None,
        poster_url: str = "",
        duration: str = "",
        is_episodes: bool = False,
        single_ep_index: int | None = None,
        quality: str = "1080p",
    ) -> DownloadTask:
        """Adds a new URL to the download queue."""
        dest = destination_path or self.config.download_dir
        fname = filename or extract_filename_from_url(url)
        task = DownloadTask(
            url=url,
            destination_path=dest,
            filename=fname,
            poster_url=poster_url,
            duration=duration,
            status=TaskStatus.QUEUED,
            is_episodes=is_episodes,
            single_ep_index=single_ep_index,
            quality=quality,
        )
        self.tasks.append(task)
        logger.info(f"Added task {task.id} ({fname}) for URL {url}")
        self.task_added.emit(task)
        self._notify_counts()
        self._process_queue()
        return task

    def pause(self, task_id: str) -> None:
        """Pauses a currently active or queued download."""
        task = self.get_task(task_id)
        if not task:
            return

        if task_id in self._workers:
            logger.info(f"Requesting pause for task {task_id}")
            self._workers[task_id].pause()
        else:
            task.status = TaskStatus.PAUSED
            self.task_updated.emit(task)
            self._notify_counts()

    def resume(self, task_id: str) -> None:
        """Resumes a paused or error task."""
        task = self.get_task(task_id)
        if not task:
            return

        if task.status in (TaskStatus.PAUSED, TaskStatus.ERROR):
            logger.info(f"Resuming task {task_id}")
            task.status = TaskStatus.QUEUED
            task.error_message = None
            self.task_updated.emit(task)
            self._notify_counts()
            self._process_queue()

    def retry(self, task_id: str) -> None:
        """Retries a failed download task."""
        self.resume(task_id)

    def cancel(self, task_id: str) -> None:
        """Cancels an active, queued, or paused download."""
        task = self.get_task(task_id)
        if not task:
            return

        logger.info(f"Cancelling task {task_id}")
        if task_id in self._workers:
            self._workers[task_id].cancel()
        else:
            task.status = TaskStatus.CANCELLED
            self.task_updated.emit(task)

        self._notify_counts()
        self._process_queue()

    def remove(self, task_id: str) -> None:
        """Cancels and removes task from the queue."""
        self.cancel(task_id)
        self.tasks = [t for t in self.tasks if t.id != task_id]
        if task_id in self._workers:
            del self._workers[task_id]
        self.task_removed.emit(task_id)
        self._notify_counts()
        self._process_queue()

    def active_download_count(self) -> int:
        """Returns the number of currently downloading tasks."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.DOWNLOADING)

    def has_active_downloads(self) -> bool:
        """Checks if any tasks are currently downloading."""
        return self.active_download_count() > 0

    def cleanup_all(self) -> None:
        """Stops all running workers gracefully on app shutdown."""
        logger.info("Cleaning up all active download workers...")
        for worker in list(self._workers.values()):
            worker.pause()
            worker.wait(1000)

    def _notify_counts(self) -> None:
        """Emits updated count of active downloads and total tasks."""
        active = self.active_download_count()
        total = len(self.tasks)
        self.queue_counts_changed.emit(active, total)

    def _process_queue(self) -> None:
        """Starts queued downloads up to max_concurrent_downloads."""
        active_count = self.active_download_count()
        available_slots = self.config.max_concurrent_downloads - active_count

        if available_slots <= 0:
            return

        for task in self.tasks:
            if available_slots <= 0:
                break
            if task.status == TaskStatus.QUEUED:
                task.status = TaskStatus.DOWNLOADING
                self._start_worker(task)
                available_slots -= 1

    def _start_worker(self, task: DownloadTask) -> None:
        """Spawns and connects a DownloadWorker for a task."""
        worker = DownloadWorker(
            task=task,
            chunk_size=self.config.chunk_size_bytes,
            timeout=self.config.timeout_seconds,
        )
        self._workers[task.id] = worker

        worker.progress_changed.connect(self._on_progress_changed)
        worker.status_changed.connect(self._on_status_changed)
        worker.download_finished.connect(self._on_finished)
        worker.error.connect(self._on_error)
        worker.filename_determined.connect(self._on_filename_determined)

        from PyQt6.QtCore import QTimer

        worker.finished.connect(
            lambda t_id=task.id: QTimer.singleShot(
                2000, lambda: self._cleanup_worker(t_id)
            )
        )

        worker.start()
        self._notify_counts()

    def _cleanup_worker(self, task_id: str) -> None:
        """Safely removes worker reference after QThread execution finishes completely."""
        if task_id in self._workers:
            del self._workers[task_id]

    def _on_progress_changed(self, task_id: str, percent: float, speed: float) -> None:
        task = self.get_task(task_id)
        if task:
            task.progress_percent = percent
            task.speed_bytes_per_sec = speed
            self.task_updated.emit(task)

    def _on_status_changed(self, task_id: str, status: TaskStatus) -> None:
        task = self.get_task(task_id)
        if task:
            task.status = status
            self.task_updated.emit(task)
            self._notify_counts()

    def _on_filename_determined(self, task_id: str, filename: str) -> None:
        task = self.get_task(task_id)
        if task:
            task.filename = filename
            self.task_updated.emit(task)

    def _on_finished(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.DONE
            self.task_updated.emit(task)
        self._notify_counts()
        self._process_queue()

    def _on_error(self, task_id: str, error_msg: str) -> None:
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.ERROR
            task.error_message = error_msg
            self.task_updated.emit(task)
        self._notify_counts()
        self._process_queue()

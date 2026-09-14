"""
Unit tests for QueueManager concurrency limits and lifecycle.
"""

from unittest.mock import patch

import pytest
from PyQt6.QtCore import QCoreApplication

from downloader_app.core.config import AppConfig
from downloader_app.core.queue_manager import QueueManager
from downloader_app.models.download_task import TaskStatus


@pytest.fixture(scope="session")
def qapp():
    """Initializes QCoreApplication for Qt signal/slot testing."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_queue_manager_add_task(qapp, tmp_path):
    config = AppConfig(download_dir=str(tmp_path), max_concurrent_downloads=2)
    qm = QueueManager(config=config)

    added_tasks = []
    qm.task_added.connect(lambda t: added_tasks.append(t))

    with patch.object(qm, "_start_worker") as mock_start:
        task1 = qm.add("https://example.com/file1.zip")
        task2 = qm.add("https://example.com/file2.zip")
        task3 = qm.add("https://example.com/file3.zip")

        assert len(qm.tasks) == 3
        assert len(added_tasks) == 3
        assert task1.status == TaskStatus.DOWNLOADING
        assert task2.status == TaskStatus.DOWNLOADING
        assert task3.status == TaskStatus.QUEUED

        # Only 2 should be started due to max_concurrent_downloads = 2
        assert mock_start.call_count == 2


def test_queue_manager_concurrency_limit(qapp, tmp_path):
    config = AppConfig(download_dir=str(tmp_path), max_concurrent_downloads=1)
    qm = QueueManager(config=config)

    with patch.object(qm, "_start_worker") as mock_start:
        t1 = qm.add("https://example.com/1.mp4")
        t2 = qm.add("https://example.com/2.mp4")

        # Concurrency limit is 1, so only 1 starts
        assert mock_start.call_count == 1
        assert t1.status == TaskStatus.DOWNLOADING
        assert t2.status == TaskStatus.QUEUED

        # Simulate t1 finishing
        t1.status = TaskStatus.DONE
        qm._on_finished(t1.id)

        # After t1 finishes, t2 should start
        assert mock_start.call_count == 2
        assert t2.status == TaskStatus.DOWNLOADING


def test_queue_manager_pause_resume_cancel(qapp, tmp_path):
    config = AppConfig(download_dir=str(tmp_path), max_concurrent_downloads=2)
    qm = QueueManager(config=config)

    with patch.object(qm, "_start_worker"):
        t1 = qm.add("https://example.com/test.zip")

        # Pause while queued
        qm.pause(t1.id)
        assert t1.status == TaskStatus.PAUSED

        # Resume (transitions to QUEUED then immediately to DOWNLOADING via _process_queue)
        qm.resume(t1.id)
        assert t1.status == TaskStatus.DOWNLOADING

        # Cancel
        qm.cancel(t1.id)
        assert t1.status == TaskStatus.CANCELLED

        # Remove
        qm.remove(t1.id)
        assert len(qm.tasks) == 0

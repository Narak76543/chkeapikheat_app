"""
Unit tests for DownloadWorker with mocked network calls and pause/resume.
"""

from unittest.mock import MagicMock, patch

from downloader_app.core.downloader import DownloadWorker
from downloader_app.models.download_task import DownloadTask, TaskStatus


def test_download_worker_successful_requests(qapp, tmp_path):
    dest_dir = tmp_path / "downloads"
    dest_dir.mkdir()

    task = DownloadTask(
        url="https://example.com/testfile.bin",
        destination_path=str(dest_dir),
        filename="testfile.bin",
    )

    worker = DownloadWorker(task=task, chunk_size=1024)

    # Mock responses
    mock_head = MagicMock()
    mock_head.headers = {"Content-Length": "2048"}

    mock_get = MagicMock()
    mock_get.status_code = 200
    mock_get.headers = {"Content-Length": "2048"}
    mock_get.iter_content = MagicMock(return_value=[b"x" * 1024, b"y" * 1024])

    finished_signals = []
    worker.download_finished.connect(lambda tid: finished_signals.append(tid))

    with patch("requests.head", return_value=mock_head), patch(
        "requests.get", return_value=mock_get
    ):
        worker.run()

    assert task.status == TaskStatus.DONE
    assert task.progress_percent == 100.0
    assert len(finished_signals) == 1
    assert (dest_dir / "testfile.bin").exists()
    assert (dest_dir / "testfile.bin").stat().st_size == 2048


def test_download_worker_pause_preserves_part(qapp, tmp_path):
    dest_dir = tmp_path / "downloads"
    dest_dir.mkdir()

    task = DownloadTask(
        url="https://example.com/bigfile.bin",
        destination_path=str(dest_dir),
        filename="bigfile.bin",
    )

    worker = DownloadWorker(task=task, chunk_size=512)

    mock_head = MagicMock()
    mock_head.headers = {"Content-Length": "2048"}

    def chunk_generator(*args, **kwargs):
        yield b"a" * 512
        # Pause during iteration
        worker.pause()
        yield b"b" * 512

    mock_get = MagicMock()
    mock_get.status_code = 200
    mock_get.headers = {"Content-Length": "2048"}
    mock_get.iter_content = MagicMock(side_effect=chunk_generator)

    with patch("requests.head", return_value=mock_head), patch(
        "requests.get", return_value=mock_get
    ):
        worker.run()

    assert task.status == TaskStatus.PAUSED
    assert (dest_dir / "bigfile.bin.part").exists()
    assert (dest_dir / "bigfile.bin.part").stat().st_size == 512


def test_download_worker_resume_range_header(qapp, tmp_path):
    dest_dir = tmp_path / "downloads"
    dest_dir.mkdir()

    # Pre-create part file
    part_file = dest_dir / "resumable.bin.part"
    part_file.write_bytes(b"a" * 1024)

    task = DownloadTask(
        url="https://example.com/resumable.bin",
        destination_path=str(dest_dir),
        filename="resumable.bin",
    )

    worker = DownloadWorker(task=task, chunk_size=1024)

    mock_head = MagicMock()
    mock_head.headers = {"Content-Length": "2048"}

    mock_get = MagicMock()
    mock_get.status_code = 206
    mock_get.headers = {
        "Content-Length": "1024",
        "Content-Range": "bytes 1024-2047/2048",
    }
    mock_get.iter_content = MagicMock(return_value=[b"b" * 1024])

    with patch("requests.head", return_value=mock_head), patch(
        "requests.get", return_value=mock_get
    ) as mock_get_call:
        worker.run()

        # Check Range header was passed
        headers_used = mock_get_call.call_args[1].get("headers", {})
        assert headers_used.get("Range") == "bytes=1024-"

    assert task.status == TaskStatus.DONE
    final_file = dest_dir / "resumable.bin"
    assert final_file.exists()
    assert final_file.stat().st_size == 2048


def test_is_hongguo_url(qapp):
    task = DownloadTask(url="https://hongguoduanju.com/detail?series_id=7680498052242623513")
    worker = DownloadWorker(task=task)
    assert worker._is_hongguo_url(task.url)
    assert worker._extract_hongguo_series_id(task.url) == "7680498052242623513"

    raw_id_task = DownloadTask(url="7680498052242623513")
    worker_raw = DownloadWorker(task=raw_id_task)
    assert worker_raw._is_hongguo_url(raw_id_task.url)
    assert worker_raw._extract_hongguo_series_id(raw_id_task.url) == "7680498052242623513"


def test_download_hongguo_series(qapp, tmp_path):
    dest_dir = tmp_path / "downloads"
    dest_dir.mkdir()

    task = DownloadTask(
        url="https://hongguoduanju.com/detail?series_id=1234567890123456",
        destination_path=str(dest_dir),
    )
    worker = DownloadWorker(task=task)

    mock_details = {
        "title": "Test Drama",
        "vid_list": ["vid1", "vid2"],
    }
    mock_ep1 = {"video_url": "https://cdn.example.com/ep1.mp4"}
    mock_ep2 = {"video_url": "https://cdn.example.com/ep2.mp4"}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_content = MagicMock(return_value=[b"video_data_bytes"])

    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with patch("downloader_app.core.downloader.get_drama_details", return_value=mock_details), patch(
        "downloader_app.core.downloader.get_episode_stream_url", side_effect=[mock_ep1, mock_ep2]
    ), patch("downloader_app.core.downloader.get_ffmpeg_path", return_value="ffmpeg"), patch(
        "requests.get", return_value=mock_resp
    ), patch(
        "subprocess.run", return_value=mock_proc
    ):
        # Pre-create output file as subprocess is mocked
        out_file = dest_dir / "Test Drama.mp4"
        out_file.write_bytes(b"merged_video_data")

        worker.run()

    assert task.status == TaskStatus.DONE
    assert task.filename == "Test Drama.mp4"


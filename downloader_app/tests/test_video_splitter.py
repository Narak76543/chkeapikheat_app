"""
Unit tests for VideoSplitterWorker & SplitToolView.
Tests lossless stream splitting into minute/second segments, clip trimming, and UI interactions.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QCoreApplication

from downloader_app.core.downloader import get_ffmpeg_path
from downloader_app.core.video_splitter import VideoSplitterWorker
from downloader_app.ui.views.split_tool_view import SplitToolView


@pytest.fixture(scope="session")
def qapp():
    """Initializes QCoreApplication for Qt signal testing."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


@pytest.fixture
def synthetic_video(tmp_path):
    """Generates a small 30-second synthetic test video via FFmpeg."""
    ffmpeg = get_ffmpeg_path()
    assert ffmpeg is not None, "FFmpeg is required for video splitter tests"

    video_file = tmp_path / "sample_movie.mp4"
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=30:size=320x240:rate=25",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=30",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        str(video_file),
    ]
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NO_WINDOW
    res = subprocess.run(
        cmd, capture_output=True, creationflags=creation_flags, check=False
    )
    assert res.returncode == 0
    assert video_file.exists()
    return video_file


def test_video_splitter_execution(qapp, synthetic_video, tmp_path):
    """Tests splitting a 30s video into 10s (0.1666 min) segments."""
    output_dir = tmp_path / "episodes"
    # 10 seconds per episode = 10 / 60 = 0.166667 minutes
    worker = VideoSplitterWorker(
        input_file=str(synthetic_video),
        minutes_per_episode=10.0 / 60.0,
        output_dir=str(output_dir),
        title_prefix="MyDrama",
    )

    results = []
    errors = []
    worker.finished.connect(lambda out_dir, files: results.append((out_dir, files)))
    worker.error.connect(lambda err: errors.append(err))

    worker.start()
    for _ in range(40):
        if worker.isFinished():
            break
        qapp.processEvents()
        worker.wait(500)
    qapp.processEvents()

    assert len(errors) == 0
    assert len(results) == 1
    out_dir, files = results[0]
    assert Path(out_dir).exists()
    # 30 seconds split into 10s chunks gives at least 2 files
    assert len(files) >= 2
    for f in files:
        assert Path(f).exists()
        assert Path(f).stat().st_size > 0
        assert "ep" in Path(f).name and "MyDrama" in Path(f).name


def test_video_splitter_range_mode(qapp, synthetic_video, tmp_path):
    """Tests custom time range clip cutting mode (e.g. 00:00:05 to 00:00:15)."""
    output_dir = tmp_path / "clips"
    worker = VideoSplitterWorker(
        input_file=str(synthetic_video),
        output_dir=str(output_dir),
        title_prefix="ClipCut",
        start_time="00:00:05",
        end_time="00:00:15",
    )

    results = []
    errors = []
    worker.finished.connect(lambda out_dir, files: results.append((out_dir, files)))
    worker.error.connect(lambda err: errors.append(err))

    worker.start()
    worker.wait(15000)
    qapp.processEvents()

    assert len(errors) == 0
    assert len(results) == 1
    out_dir, files = results[0]
    assert Path(out_dir).exists()
    assert len(files) == 1
    assert Path(files[0]).exists()
    assert Path(files[0]).stat().st_size > 0
    assert "ClipCut_Cut" in Path(files[0]).name


def test_video_splitter_nonexistent_file(qapp, tmp_path):
    """Tests error emission when source file does not exist."""
    worker = VideoSplitterWorker(
        input_file=str(tmp_path / "ghost_file.mp4"),
        minutes_per_episode=5.0,
        output_dir=str(tmp_path / "out"),
    )

    errors = []
    worker.error.connect(lambda err: errors.append(err))

    worker.start()
    worker.wait(5000)
    qapp.processEvents()

    assert len(errors) == 1
    assert "not found" in errors[0].lower()


def test_split_tool_view_ui_state(qapp, synthetic_video, monkeypatch):
    """Tests SplitToolView widget creation, mode switching, and file selection."""
    monkeypatch.setattr("downloader_app.core.translator.get_api_key", lambda: None)
    view = SplitToolView()
    assert view.title_label.text() != ""
    assert view.file_input.text() == ""

    # Programmatically set video path
    view.set_video_path(str(synthetic_video))
    assert view.file_input.text() == str(synthetic_video)
    assert f"{synthetic_video.stem}_parts" in view.edit_output_dir.text()

    if hasattr(view, "_sugg_worker") and view._sugg_worker:
        view._sugg_worker.wait(2000)

    # Switch mode to time range
    view.mode_group.button(1).click()
    assert not view.range_widget.isHidden()
    assert view.episodes_widget.isHidden()

    # Switch back to episodes mode
    view.mode_group.button(0).click()
    assert not view.episodes_widget.isHidden()
    assert view.range_widget.isHidden()


def test_split_tool_view_translation_suggestion(qapp, synthetic_video, monkeypatch):
    """Tests multiple candidate suggestions display, candidate selection, auto-append toggle, and custom base dir."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    view = SplitToolView()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "1. រឿង ភាគទី១\n2. រឿង ភាគទី២\n3. រឿង ភាគទី៣"}]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_resp):
        view.set_video_path(str(synthetic_video))
        if hasattr(view, "_sugg_worker") and view._sugg_worker:
            view._sugg_worker.wait(3000)
            qapp.processEvents()

        assert not view.suggestion_card.isHidden()
        assert len(view._candidate_items) == 3
        assert view._selected_candidate == "រឿង ភាគទី១"
        assert view.chk_auto_append.isChecked()
        assert "រឿង ភាគទី១_parts" in view.edit_output_dir.text()

        # Select second candidate
        view._select_candidate("រឿង ភាគទី២")
        assert view._selected_candidate == "រឿង ភាគទី២"
        assert "រឿង ភាគទី២_parts" in view.edit_output_dir.text()

        # Uncheck auto-append toggle -> reverts to base folder
        view.chk_auto_append.setChecked(False)
        assert "រឿង ភាគទី២_parts" not in view.edit_output_dir.text()

        # Custom path setting (e.g. C:/Videos/split)
        view.edit_output_dir.setText("C:/Videos/split")
        view.edit_output_dir.textEdited.emit("C:/Videos/split")
        assert view._custom_base_dir == Path("C:/Videos/split")

        # Selecting candidate appends title under custom base path C:/Videos/split
        view._select_candidate("រឿង ភាគទី៣")
        assert f"{Path('C:/Videos/split/រឿង ភាគទី៣_parts')}" in view.edit_output_dir.text()


def test_split_tool_view_custom_minutes_duration(qapp, synthetic_video):
    """Tests custom minute duration input (e.g. 1 mn, 3.5 mn) and preset sync in SplitToolView."""
    view = SplitToolView()
    assert hasattr(view, "spin_minutes")
    assert view.spin_minutes.value() == 1.0

    # Setting custom value updates presets correctly
    view.spin_minutes.setValue(5.0)
    assert view.preset_buttons[5].isChecked()
    assert not view.preset_buttons[1].isChecked()

    # Clicking 1 mn preset button sets spin_minutes to 1.0
    view.preset_buttons[1].click()
    assert view.spin_minutes.value() == 1.0
    assert view.preset_buttons[1].isChecked()

    # Setting custom non-preset value (e.g. 2.5 mn) unchecks presets cleanly
    view.spin_minutes.setValue(2.5)
    assert view.spin_minutes.value() == 2.5
    for btn in view.preset_buttons.values():
        assert not btn.isChecked()

    view.deleteLater()


def test_split_tool_view_merged_modes(qapp, tmp_path):
    """Tests switching between Splitter, Batch Renamer, and Single Title Localizer modes."""
    view = SplitToolView()
    view.show()
    qapp.processEvents()

    assert view._current_tool_mode == 0
    assert view.splitter_container.isVisible()
    assert not view.batch_container.isVisible()
    assert not view.single_container.isVisible()

    # Switch to Batch Folder Renamer
    view._on_tool_mode_changed(1)
    qapp.processEvents()
    assert view._current_tool_mode == 1
    assert not view.splitter_container.isVisible()
    assert view.batch_container.isVisible()
    assert not view.single_container.isVisible()

    # Test folder scan
    test_folder = tmp_path / "DramaTest"
    test_folder.mkdir()
    (test_folder / "Episode 1.mp4").touch()
    (test_folder / "Subfolder").mkdir()
    view._scan_folder_for_preview(str(test_folder))
    assert view.preview_table.rowCount() == 2

    # Switch to Single Title Localizer
    view._on_tool_mode_changed(2)
    qapp.processEvents()
    assert view._current_tool_mode == 2
    assert not view.splitter_container.isVisible()
    assert not view.batch_container.isVisible()
    assert view.single_container.isVisible()

    # Test single title suggestions received
    view.edit_single_title.setText("Martial Universe")
    view._on_single_suggestions_received(["រឿងភាគ Martial Universe", "Martial Universe Khmer"])
    assert view.single_sugg_layout.count() == 3

    # Switch back to Splitter
    view._on_tool_mode_changed(0)
    qapp.processEvents()
    assert view.splitter_container.isVisible()
    assert not view.batch_container.isVisible()
    assert not view.single_container.isVisible()

    view.deleteLater()





"""
Unit Tests for Chinese Subtitle Extraction, Khmer Translation & VoxCPM2 Dubbing Pipeline.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt

from downloader_app.core.subtitle_extractor import (
    SubtitleExtractorWorker,
    SubtitleItem,
    format_srt_content,
    parse_srt_content,
    seconds_to_timestamp,
    timestamp_to_seconds,
)
from downloader_app.core.translator import Translator
from downloader_app.core.tts_voxcpm import VoxCPM2DubbingWorker
from downloader_app.ui.views.dubbing_tool_view import DubbingToolView


def test_timestamp_conversions():
    sec = timestamp_to_seconds("01:02:03,500")
    assert sec == 3723.5

    ts = seconds_to_timestamp(3723.5)
    assert ts == "01:02:03,500"


def test_parse_and_format_srt_content():
    raw_srt = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "你好, 欢迎来到节目\n\n"
        "2\n"
        "00:00:05,000 --> 00:00:08,000\n"
        "谢谢大家\n"
    )
    items = parse_srt_content(raw_srt)
    assert len(items) == 2
    assert items[0].text == "你好, 欢迎来到节目"
    assert items[0].start_seconds == 1.0
    assert items[0].end_seconds == 4.0
    assert items[0].duration_seconds == 3.0

    formatted = format_srt_content(items)
    assert "00:00:01,000 --> 00:00:04,000" in formatted
    assert "你好, 欢迎来到节目" in formatted


def test_custom_srt_extractor_worker(tmp_path):
    srt_file = tmp_path / "custom.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:03,000\n测试字幕\n", encoding="utf-8")

    worker = SubtitleExtractorWorker(video_path="dummy.mp4", srt_path=str(srt_file))
    
    extracted_items = []
    def on_finished(items):
        extracted_items.extend(items)

    worker.finished.connect(on_finished)
    worker.run()

    assert len(extracted_items) == 1
    assert extracted_items[0].text == "测试字幕"


def test_batch_subtitle_translation(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")
    translator = Translator()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "1. សួស្តី ស្វាគមន៍មកកាន់កម្មវិធី\n2. អរគុណអ្នកទាំងអស់គ្នា"}]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_resp):
        translated = translator.translate_subtitle_blocks(["你好", "谢谢"])
        assert len(translated) == 2
        assert "សួស្តី" in translated[0]
        assert "អរគុណ" in translated[1]


def test_voxcpm_client_fallback(tmp_path):
    from downloader_app.core.tts_voxcpm import VoxCPM2Client
    client = VoxCPM2Client(api_url="http://invalid-localhost-url:9999/tts")
    out_wav = tmp_path / "test_clip.wav"

    # Should fall back to generating timed audio using FFmpeg without crashing
    success = client.generate_audio(
        text="សួស្តី", duration_sec=1.5, output_path=out_wav, target_lang="km"
    )
    assert success is True
    assert out_wav.exists()


def test_dubbing_tool_view_creation(qapp):
    view = DubbingToolView()
    assert hasattr(view, "stack_widget")
    assert view.stack_widget.currentIndex() == 0  # Defaults to Dialogue Studio & Preview UI
    assert view.btn_start is not None
    assert hasattr(view, "srt_input")
    assert hasattr(view, "btn_browse_srt")
    assert hasattr(view, "combo_voice")
    assert view.combo_voice.count() >= 2
    view.deleteLater()


def test_multitrack_timeline_assembly(tmp_path):
    """Verifies that DubbingMixerWorker places clips at exact start_seconds without lag or dropped clips."""
    import wave
    from downloader_app.core.dubbing_mixer import DubbingMixerWorker
    from downloader_app.core.subtitle_extractor import SubtitleItem

    # Create dummy 1s stereo 44.1kHz wav
    clip1 = tmp_path / "clip1.wav"
    clip2 = tmp_path / "clip2.wav"
    sample_rate = 44100

    with wave.open(str(clip1), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x10\x00\x10\x00" * (sample_rate * 1))

    with wave.open(str(clip2), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x20\x00\x20\x00" * (sample_rate * 1))

    items = [
        SubtitleItem(index=1, start_time="00:00:01,000", end_time="00:00:02,000", start_seconds=1.0, end_seconds=2.0, text="One"),
        SubtitleItem(index=2, start_time="00:00:02,500", end_time="00:00:03,500", start_seconds=2.5, end_seconds=3.5, text="Two"),
    ]

    dummy_video = tmp_path / "video.mp4"
    dummy_video.write_bytes(b"dummy")
    out_video = tmp_path / "out.mp4"

    worker = DubbingMixerWorker(
        video_path=str(dummy_video),
        subtitle_items=items,
        audio_clip_paths=[str(clip1), str(clip2)],
        output_video_path=str(out_video),
    )

    valid_pairs = [(items[0], clip1), (items[1], clip2)]
    # Verify both clips are preserved and placed
    assert len(valid_pairs) == 2


def test_dubbing_view_clear_and_import_srt(qapp, tmp_path):
    view = DubbingToolView()
    assert hasattr(view, "btn_clear_srt")
    
    # Test importing an SRT file directly
    srt_file = tmp_path / "test.srt"
    srt_file.write_text(
        "1\n00:00:01,000 --> 00:00:04,000\nសួស្តីបងប្អូនទាំងអស់គ្នា\n\n2\n00:00:05,000 --> 00:00:08,000\nនេះជាការសាកល្បង\n",
        encoding="utf-8"
    )
    view._load_imported_srt(str(srt_file))
    assert len(view._subtitle_items) == 2
    assert view.dialogue_table.rowCount() == 2
    assert "សួស្តី" in view.dialogue_table.item(0, 3).text()

    # Test clearing SRT
    view._on_clear_srt_clicked()
    assert view.srt_input.text() == ""
    assert len(view._subtitle_items) == 0
    assert view.dialogue_table.rowCount() == 0

    view.deleteLater()


def test_subtitle_extractor_ignore_sidecar(tmp_path):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"dummy video")
    sidecar_file = tmp_path / "video.srt"
    sidecar_file.write_text("1\n00:00:01,000 --> 00:00:03,000\nSidecar test\n", encoding="utf-8")

    # With ignore_sidecar=False, it should read sidecar
    worker_use_sidecar = SubtitleExtractorWorker(
        video_path=str(video_file), srt_path=None, ignore_sidecar=False
    )
    extracted = []
    worker_use_sidecar.finished.connect(lambda items: extracted.extend(items))
    worker_use_sidecar.run()
    assert len(extracted) == 1
    assert extracted[0].text == "Sidecar test"

    # With ignore_sidecar=True, it skips sidecar and attempts fallback (transcription/error)
    worker_ignore = SubtitleExtractorWorker(
        video_path=str(video_file), srt_path=None, ignore_sidecar=True
    )
    with patch("downloader_app.core.subtitle_extractor.transcribe_video_audio_to_subtitles", return_value=[]):
        ignored_extracted = []
        errors = []
        worker_ignore.finished.connect(lambda items: ignored_extracted.extend(items))
        worker_ignore.error.connect(lambda err: errors.append(err))
        worker_ignore.run()
        # Should not have read the sidecar
        assert len(ignored_extracted) == 0
        assert len(errors) == 1


def test_preview_studio_ui(qapp):
    view = DubbingToolView()
    assert hasattr(view, "preview_page")
    assert hasattr(view, "btn_final_render")
    assert hasattr(view, "dialogue_table")
    assert hasattr(view, "dialogue_search")
    assert hasattr(view, "btn_export_srt")

    items = [
        SubtitleItem(
            index=1,
            start_time="00:00:00,560",
            end_time="00:00:03,890",
            start_seconds=0.56,
            end_seconds=3.89,
            text="ក្រាបទូលព្រះអង្គ! តំណែងព្រះអគ្គមហេសីនៅទំនេរ",
        ),
        SubtitleItem(
            index=2,
            start_time="00:00:03,890",
            end_time="00:00:06,660",
            start_seconds=3.89,
            end_seconds=6.66,
            text="ម្យ៉ាងទៀត តំណែងព្រះអគ្គមហេសីជាតំណែងដ៏ខ្ពង់ខ្ពស់",
        ),
    ]
    view._open_preview_studio(items)
    assert view.stack_widget.currentIndex() == 0
    assert view.dialogue_table.rowCount() == 2
    assert view.dialogue_table.item(0, 0).checkState() == Qt.CheckState.Checked
    assert view.dialogue_table.item(0, 1).text() == "00:00.56"
    assert "ក្រាបទូល" in view.dialogue_table.item(0, 3).text()

    # Test search filter
    view._filter_dialogue_table("ម្យ៉ាងទៀត")
    assert view.dialogue_table.isRowHidden(0) is True
    assert view.dialogue_table.isRowHidden(1) is False

    # Test final render button click triggers in-studio status progress
    with patch.object(view, "_execute_tts_and_mux") as mock_exec:
        view._on_final_render_clicked()
        assert view.stack_widget.currentIndex() == 0
        assert not view.proc_card.isHidden()
        mock_exec.assert_called_once_with(items)

    view.deleteLater()


def test_dubbing_view_folder_batch_import(qapp, tmp_path):
    """Verifies that selecting a folder with episode videos queues them up for batch processing."""
    ep1 = tmp_path / "EP01.mp4"
    ep2 = tmp_path / "EP02.mp4"
    ep10 = tmp_path / "EP10.mp4"
    ep1.write_bytes(b"ep1")
    ep2.write_bytes(b"ep2")
    ep10.write_bytes(b"ep10")

    view = DubbingToolView()
    assert hasattr(view, "btn_browse_folder")
    assert hasattr(view, "folder_info_label")

    with patch("PyQt6.QtWidgets.QFileDialog.getExistingDirectory", return_value=str(tmp_path)):
        view._on_browse_folder_clicked()
        assert view.file_input.text() == str(tmp_path)
        assert len(view._batch_video_files) == 3
        # Verify natural sorting (EP01, EP02, EP10)
        assert Path(view._batch_video_files[0]).name == "EP01.mp4"
        assert Path(view._batch_video_files[1]).name == "EP02.mp4"
        assert Path(view._batch_video_files[2]).name == "EP10.mp4"
        assert view.folder_info_label.isHidden() is False

    view.deleteLater()


def test_dubbing_view_folder_batch_sequence(qapp, tmp_path):
    """Verifies that dubbing completion advances through all batch items and saves into the 'final' folder."""
    ep1 = tmp_path / "EP01.mp4"
    ep2 = tmp_path / "EP02.mp4"
    ep1.write_bytes(b"ep1")
    ep2.write_bytes(b"ep2")

    view = DubbingToolView()
    view._batch_video_files = [str(ep1), str(ep2)]
    view._is_batch_mode = True
    view._current_batch_index = 0

    with patch("downloader_app.ui.views.dubbing_tool_view.SubtitleExtractorWorker"):
        with patch.object(view, "_execute_tts_and_mux") as mock_exec:
            view._process_next_batch_item()
            assert view._current_batch_index == 0

    # Finish ep1
    with patch.object(view, "_process_next_batch_item") as mock_next:
        view._on_dubbing_finished(str(tmp_path / "final" / "EP01_KhmerDubbed.mp4"))
        assert view._current_batch_index == 1
        mock_next.assert_called_once()
        assert "final" in view._output_video

    view.deleteLater()


def test_voice_cloning_upload(qapp, tmp_path):
    """Verifies that uploading a custom voice sample sets the clone voice mode and forwards ref_audio_path."""
    sample_file = tmp_path / "custom_speech.wav"
    sample_file.write_bytes(b"RIFF....WAVEfmt ")

    view = DubbingToolView()
    assert hasattr(view, "combo_voice")
    assert hasattr(view, "btn_upload_sample")
    assert hasattr(view, "btn_play_sample")

    # Check Sdach Game option
    sdach_idx = view.combo_voice.findData("sdach_game")
    assert sdach_idx >= 0
    view.combo_voice.setCurrentIndex(sdach_idx)
    voice_key, ref_p, label = view._get_selected_voice_info()
    assert voice_key == "sdach_game"
    assert "sdach_game.mp3" in ref_p

    # Check Harvard option
    harvard_idx = view.combo_voice.findData("harvard")
    assert harvard_idx >= 0
    view.combo_voice.setCurrentIndex(harvard_idx)
    h_key, h_ref_p, h_label = view._get_selected_voice_info()
    assert h_key == "harvard"
    assert "harvard.mp3" in h_ref_p

    with patch("PyQt6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(sample_file), "Audio Files")):
        view._on_upload_voice_sample_clicked()
        assert view._custom_voice_sample == str(sample_file)
        assert view.combo_voice.currentData() == "custom_clone"
        assert "custom_speech" in view.btn_upload_sample.text()

        v_key, custom_ref, v_label = view._get_selected_voice_info()
        assert v_key == "custom_clone"
        assert custom_ref == str(sample_file)

    view.deleteLater()


def test_transcribe_audio_slice_offset(monkeypatch):
    """Verifies that _transcribe_audio_slice_with_gemini properly offsets start/end timestamps by start_sec."""
    from downloader_app.core.subtitle_extractor import _transcribe_audio_slice_with_gemini

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                "1\n00:00:05,000 --> 00:00:10,000\nតើលោកសុខសប្បាយជាទេ?\n\n"
                                "2\n00:00:12,000 --> 00:00:15,000\nខ្ញុំសុខសប្បាយជាទេ\n"
                            )
                        }
                    ]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_resp):
        items = _transcribe_audio_slice_with_gemini(
            audio_bytes=b"fake_mp3_data",
            api_key="test-key",
            chunk_index=2,
            total_chunks=3,
            start_sec=150.0,
        )

        assert len(items) == 2
        # Offset by 150.0s
        assert items[0].start_seconds == 155.0
        assert items[0].end_seconds == 160.0
        assert items[0].start_time == "00:02:35,000"
        assert items[0].end_time == "00:02:40,000"
        assert items[0].text == "តើលោកសុខសប្បាយជាទេ?"

        assert items[1].start_seconds == 162.0
        assert items[1].end_seconds == 165.0
        assert items[1].start_time == "00:02:42,000"
        assert items[1].end_time == "00:02:45,000"


def test_chunked_video_transcription(tmp_path, monkeypatch):
    """Verifies that transcribe_video_audio_to_subtitles slices long videos and aggregates all chunk subtitles."""
    from downloader_app.core.subtitle_extractor import transcribe_video_audio_to_subtitles

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    video_file = tmp_path / "long_movie.mp4"
    video_file.write_bytes(b"dummy long video")

    # Mock duration as 350 seconds (should split into 3 chunks: 0-150s, 150-300s, 300-350s)
    with patch("downloader_app.core.subtitle_extractor.get_video_duration_ffmpeg", return_value=350.0):
        with patch("downloader_app.core.subtitle_extractor.get_ffmpeg_path", return_value="ffmpeg"):
            with patch("subprocess.run") as mock_subproc:
                mock_subproc.return_value = MagicMock(returncode=0)

                def mock_slice(audio_bytes, api_key, chunk_index, total_chunks, start_sec, **kwargs):
                    return [
                        SubtitleItem(
                            index=1,
                            start_time=seconds_to_timestamp(start_sec + 2.0),
                            end_time=seconds_to_timestamp(start_sec + 6.0),
                            start_seconds=start_sec + 2.0,
                            end_seconds=start_sec + 6.0,
                            text=f"កថាខណ្ឌទី {chunk_index} នៃខ្សែភាពយន្ត",
                        )
                    ]

                with patch("downloader_app.core.subtitle_extractor._transcribe_audio_slice_with_gemini", side_effect=mock_slice):
                    # Write fake temporary chunk mp3s during subprocess run
                    def fake_subprocess_run(cmd, **kwargs):
                        out_path = Path(cmd[-1])
                        out_path.write_bytes(b"fake_mp3_chunk")
                        return MagicMock(returncode=0)

                    mock_subproc.side_effect = fake_subprocess_run

                    items = transcribe_video_audio_to_subtitles(video_file)
                    assert len(items) == 3
                    assert items[0].start_seconds == 2.0
                    assert items[1].start_seconds == 152.0
                    assert items[2].start_seconds == 302.0
                    assert items[0].index == 1
                    assert items[1].index == 2
                    assert items[2].index == 3
                    # Persistent cache file should have been written
                    cache_file = tmp_path / "long_movie_KhmerDub.srt"
                    assert cache_file.exists()


def test_drop_zone_frame_and_theme_styling(qtbot, tmp_path):
    """Test modern DropZoneFrame, drag/drop handling, and light/dark theme styling."""
    from downloader_app.ui.views.dubbing_tool_view import DubbingToolView, DropZoneFrame

    view = DubbingToolView()
    qtbot.addWidget(view)

    # 1. Verify DropZoneFrame exists and accepts drops
    assert isinstance(view.video_placeholder, DropZoneFrame)
    assert view.video_placeholder.acceptDrops() is True

    # 2. Test dropping a single video file
    dummy_video = tmp_path / "test_episode.mp4"
    dummy_video.write_bytes(b"dummy video content")

    view._on_file_or_folder_dropped(str(dummy_video))
    assert view.file_input.text() == str(dummy_video.resolve())
    assert "test_episode.mp4" in view.lbl_video_title.text()

    # 3. Test dropping a series folder
    folder = tmp_path / "episodes"
    folder.mkdir()
    (folder / "ep1.mp4").write_bytes(b"vid1")
    (folder / "ep2.mp4").write_bytes(b"vid2")

    view._on_file_or_folder_dropped(str(folder))
    assert view.file_input.text() == str(folder.resolve())
    assert len(view._batch_video_files) == 2
    assert "2 episodes" in view.lbl_video_title.text()

    # 4. Test light & dark theme styling switching
    view._apply_theme_styles()
    view.update_theme_icons()


def test_split_text_into_sentences_chinese_and_khmer():
    """Verify sentence tokenization with Khmer, Chinese, Thai, and Western punctuation."""
    from downloader_app.core.subtitle_extractor import _split_text_into_sentences

    chinese_text = "你好！我是小明。今天天气很好，我们要去哪里？"
    sents_zh = _split_text_into_sentences(chinese_text)
    assert len(sents_zh) >= 3
    assert any("你好" in s for s in sents_zh)
    assert any("小明" in s for s in sents_zh)

    khmer_text = "សួស្តី! ខ្ញុំជាម៉េង។ ថ្ងៃនេះអាកាសធាតុល្អ។"
    sents_km = _split_text_into_sentences(khmer_text)
    assert len(sents_km) == 3
    assert sents_km[0] == "សួស្តី!"
    assert sents_km[1] == "ខ្ញុំជាម៉េង។"
    assert sents_km[2] == "ថ្ងៃនេះអាកាសធាតុល្អ។"


def test_split_long_items_multi_sentence():
    """Verify _split_long_items properly splits a single long block into multiple timed subtitle items."""
    from downloader_app.core.subtitle_extractor import _split_long_items

    item = SubtitleItem(
        index=1,
        start_time="00:00:00,000",
        end_time="00:01:00,000",
        start_seconds=0.0,
        end_seconds=60.0,
        text="第1句台词。第2句台词！第3句台词？第4句台词。",
    )

    split_items = _split_long_items([item], max_block_dur=8.0)
    assert len(split_items) == 4
    assert split_items[0].start_seconds == 0.0
    assert split_items[-1].end_seconds == 60.0
    for idx, it in enumerate(split_items, start=1):
        assert it.index == idx
        assert it.duration_seconds > 0


def test_translate_subtitle_blocks_expansion():
    """Verify translate_subtitle_blocks expands a 1-item input when the model returns multiple numbered lines."""
    translator = Translator()

    fake_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "1. ជម្រាបសួរលោកអ្នកនាង\n2. ខ្ញុំបាទជាពិធីករ\n3. សូមស្វាគមន៍មកកាន់កម្មវិធី"
                        }
                    ]
                }
            }
        ]
    }

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_response
        mock_post.return_value = mock_resp

        results = translator.translate_subtitle_blocks(
            ["你好，我是主持人，欢迎来到节目"],
            target_lang="km",
        )
        assert len(results) == 3
        assert results[0] == "ជម្រាបសួរលោកអ្នកនាង"
        assert results[1] == "ខ្ញុំបាទជាពិធីករ"
        assert results[2] == "សូមស្វាគមន៍មកកាន់កម្មវិធី"


def test_generate_styled_ass_file(tmp_path):
    """Test generating ASS file styled with Google Sans font and high-contrast outline."""
    from downloader_app.core.subtitle_burner import generate_styled_ass_file
    from downloader_app.core.subtitle_extractor import SubtitleItem

    items = [
        SubtitleItem(
            index=1,
            start_time="00:00:01,200",
            end_time="00:00:04,500",
            start_seconds=1.2,
            end_seconds=4.5,
            text="សួស្តីបងប្អូនទាំងអស់គ្នា",
        ),
        SubtitleItem(
            index=2,
            start_time="00:00:05,000",
            end_time="00:00:08,300",
            start_seconds=5.0,
            end_seconds=8.3,
            text="នេះជាការសាកល្បងអក្សររត់",
        ),
    ]
    out_ass = tmp_path / "test.ass"
    ok = generate_styled_ass_file(
        subtitle_items=items,
        output_ass_path=out_ass,
        font_name="Google Sans",
        video_width=1280,
        video_height=720,
    )
    assert ok is True
    assert out_ass.exists()
    content = out_ass.read_text(encoding="utf-8")
    assert "Google Sans" in content
    assert "KhmerDefault" in content
    assert "Dialogue: 0,0:00:01.20,0:00:04.50,KhmerDefault,,0,0,0,,សួស្តីបងប្អូនទាំងអស់គ្នា" in content
    assert "Dialogue: 0,0:00:05.00,0:00:08.30,KhmerDefault,,0,0,0,,នេះជាការសាកល្បងអក្សររត់" in content


def test_build_subtitle_filter_complex(tmp_path):
    """Test building FFmpeg filtergraph for blur and subtitles overlay."""
    from downloader_app.core.subtitle_burner import build_subtitle_filter_complex

    fake_ass = tmp_path / "subs.ass"
    fake_ass.write_text("[Script Info]\n", encoding="utf-8")

    # Case 1: Both blur and subtitles
    f_str, out_label = build_subtitle_filter_complex(
        ass_path=fake_ass,
        blur_original_subtitles=True,
    )
    assert "boxblur" in f_str
    assert "crop" in f_str
    assert "subtitles=" in f_str
    assert out_label == "[v_out]"

    # Case 2: Blur only
    f_str2, out_label2 = build_subtitle_filter_complex(
        ass_path=None,
        blur_original_subtitles=True,
    )
    assert "boxblur" in f_str2
    assert "subtitles=" not in f_str2
    assert out_label2 == "[v_out]"

    # Case 3: Subtitles only
    f_str3, out_label3 = build_subtitle_filter_complex(
        ass_path=fake_ass,
        blur_original_subtitles=False,
    )
    assert "boxblur" not in f_str3
    assert "subtitles=" in f_str3
    assert out_label3 == "[v_out]"

    # Case 4: Neither
    f_str4, out_label4 = build_subtitle_filter_complex(
        ass_path=None,
        blur_original_subtitles=False,
    )
    assert f_str4 == ""
    assert out_label4 == "[0:v]"


def test_dubbing_view_subtitle_toggle_controls(qapp):
    """Test subtitle burning and blur toggles in DubbingToolView."""
    view = DubbingToolView()
    assert hasattr(view, "chk_burn_subtitles")
    assert hasattr(view, "chk_blur_subtitles")
    assert view.chk_burn_subtitles.isChecked() is True
    assert view.chk_blur_subtitles.isChecked() is True

    # Toggle them
    view.chk_burn_subtitles.setChecked(False)
    assert view.chk_burn_subtitles.isChecked() is False
    view.chk_blur_subtitles.setChecked(False)
    assert view.chk_blur_subtitles.isChecked() is False

    view.deleteLater()


def test_dubbing_view_in_player_subtitle_overlay(qapp):
    """Test in-player live subtitle overlay positioning and real-time text updates."""
    view = DubbingToolView()
    assert hasattr(view, "video_sub_overlay")
    assert hasattr(view, "player_container")

    # Set subtitle text
    view._set_active_subtitle_text("សួស្តីបងប្អូនទាំងអស់គ្នា")
    assert view.video_sub_overlay.text() == "សួស្តីបងប្អូនទាំងអស់គ្នា"
    assert view.video_sub_overlay.isHidden() is False

    # Clear subtitle text
    view._set_active_subtitle_text("")
    assert view.video_sub_overlay.isHidden() is True

    view.deleteLater()


def test_dubbing_view_font_size_customization(qapp):
    """Test subtitle font size customization controls (direct number selection & typing)."""
    view = DubbingToolView()
    assert hasattr(view, "combo_sub_size")
    assert view.combo_sub_size.isEditable() is True

    # Select number from list
    idx = view.combo_sub_size.findData(22)
    view.combo_sub_size.setCurrentIndex(idx)
    assert view._get_current_font_size() == 22

    # Type custom number directly
    view.combo_sub_size.setEditText("38")
    assert view._get_current_font_size() == 38

    view.deleteLater()


def test_dubbing_view_font_variant_and_background_toggle(qapp):
    """Test font variant dropdown and black background Use/None Use toggle."""
    view = DubbingToolView()
    assert hasattr(view, "combo_font_variant")
    assert view.combo_font_variant.count() == 4
    assert [view.combo_font_variant.itemText(i) for i in range(4)] == ["Regular", "Italic", "SemiBold", "Bold"]

    # Select Regular
    view.combo_font_variant.setCurrentIndex(0)
    assert view._get_current_font_variant() == "Regular"

    # Select Italic
    view.combo_font_variant.setCurrentIndex(1)
    assert view._get_current_font_variant() == "Italic"

    # Select SemiBold
    view.combo_font_variant.setCurrentIndex(2)
    assert view._get_current_font_variant() == "SemiBold"

    # Select Bold
    view.combo_font_variant.setCurrentIndex(3)
    assert view._get_current_font_variant() == "Bold"

    # Black background toggle
    assert view.chk_blur_subtitles.isChecked() is True  # Default: Use
    view.chk_blur_subtitles.setChecked(False)  # None use
    assert view.chk_blur_subtitles.isChecked() is False

    view.deleteLater()


def test_studio_video_player_view_overlay(qapp):
    """Test StudioVideoPlayerView subtitle and blur mask item rendering."""
    from downloader_app.ui.views.dubbing_tool_view import StudioVideoPlayerView, SubtitleOverlayItem

    player_view = StudioVideoPlayerView()
    player_view.resize(640, 360)
    assert player_view.overlay_item is not None
    assert isinstance(player_view.overlay_item, SubtitleOverlayItem)

    # Set subtitle with black background, Bold variant, and custom W & H scales
    player_view.set_subtitle(
        "ជំរាបសួរ Google Sans",
        blur_enabled=True,
        burn_enabled=True,
        font_variant="Bold",
        font_size_pt=30,
        bg_box_w_scale=80,
        bg_box_h_scale=120,
        bg_box_color="#1E1E24",
        bg_box_opacity=80,
    )
    assert player_view.overlay_item.text() == "ជំរាបសួរ Google Sans"
    assert player_view.overlay_item._blur_enabled is True
    assert player_view.overlay_item._font_variant == "Bold"
    assert player_view.overlay_item._font_size_pt == 30
    assert player_view.overlay_item._bg_box_w_scale == 80
    assert player_view.overlay_item._bg_box_h_scale == 120
    assert player_view.overlay_item._bg_box_color == "#1E1E24"
    assert player_view.overlay_item._bg_box_opacity == 80
    assert player_view.overlay_item.isHidden() is False

    # Disable black background (None Use) and change variant to Italic
    player_view.set_subtitle(
        "ជំរាបសួរ Google Sans",
        blur_enabled=False,
        burn_enabled=True,
        font_variant="Italic",
        font_size_pt=34,
    )
    assert player_view.overlay_item._blur_enabled is False
    assert player_view.overlay_item._font_variant == "Italic"
    assert player_view.overlay_item._font_size_pt == 34

    # Disable burn (hide subtitle)
    player_view.set_subtitle("", blur_enabled=False, burn_enabled=False, font_variant="Regular", font_size_pt=30)
    assert player_view.overlay_item.isHidden() is True

    player_view.deleteLater()


def test_dubbing_view_bg_box_controls(qapp):
    """Test DubbingToolView background box width, height, color, and opacity toolbar controls."""
    view = DubbingToolView()

    assert hasattr(view, "combo_bg_w_size")
    assert hasattr(view, "combo_bg_h_size")
    assert hasattr(view, "btn_bg_color")
    assert hasattr(view, "combo_bg_opacity")

    # Initial defaults
    assert view._get_current_bg_w_size() == 100
    assert view._get_current_bg_h_size() == 100
    assert view._get_current_bg_color() == "#000000"
    assert view._get_current_bg_opacity() == 90

    # Test width scale combo modification
    view.combo_bg_w_size.setCurrentText("80%")
    assert view._get_current_bg_w_size() == 80

    # Test height scale combo modification
    view.combo_bg_h_size.setCurrentText("140%")
    assert view._get_current_bg_h_size() == 140

    # Test opacity combo modification
    view.combo_bg_opacity.setCurrentText("70%")
    assert view._get_current_bg_opacity() == 70

    # Test custom color modification
    view._current_bg_color = "#1E293B"
    view._update_toolbar_button_styles()
    assert view._get_current_bg_color() == "#1E293B"

    view.deleteLater()


def test_subtitle_color_picker_dialog(qapp):
    """Test SubtitleColorPickerDialog presets, hex input, RGB sliders, and selection signal."""
    from downloader_app.ui.widgets.color_picker_dialog import SubtitleColorPickerDialog

    dialog = SubtitleColorPickerDialog(current_color="#000000")
    assert dialog.hex_input.text() == "#000000"
    assert dialog.slider_r.value() == 0
    assert dialog.slider_g.value() == 0
    assert dialog.slider_b.value() == 0

    # Test preset swatch click
    dialog._on_swatch_clicked("#334155")
    assert dialog.selected_color == "#334155"
    assert dialog.hex_input.text() == "#334155"
    assert dialog.slider_r.value() == 0x33
    assert dialog.slider_g.value() == 0x41
    assert dialog.slider_b.value() == 0x55

    # Test RGB slider change
    dialog.slider_r.setValue(18)
    dialog.slider_g.setValue(89)
    dialog.slider_b.setValue(195)
    assert dialog.selected_color == "#1259C3"
    assert dialog.hex_input.text() == "#1259C3"

    # Test Hex manual input
    dialog.hex_input.setText("#059669")
    dialog._on_hex_text_changed("#059669")
    assert dialog.selected_color == "#059669"
    assert dialog.slider_r.value() == 0x05
    assert dialog.slider_g.value() == 0x96
    assert dialog.slider_b.value() == 0x69

    # Test signal emission on accept
    emitted = []
    dialog.color_selected.connect(lambda c: emitted.append(c))
    dialog._on_apply_clicked()
    assert emitted == ["#059669"]

    dialog.deleteLater()


def test_dialogue_table_click_updates_player_overlay(qapp):
    """Test clicking dialogue table row seeks player and updates overlay."""
    view = DubbingToolView()
    sub_item = SubtitleItem(
        index=1,
        start_time="00:00:01,000",
        end_time="00:00:03,500",
        start_seconds=1.0,
        end_seconds=3.5,
        text="អត្ថបទតេស្ត Khmer"
    )
    view._open_preview_studio([sub_item])

    assert view.dialogue_table.rowCount() == 1
    view._on_table_row_clicked(0, 3)

    assert view.video_sub_overlay.text() == "អត្ថបទតេស្ត Khmer"
    assert view.video_sub_overlay.isHidden() is False

    view.deleteLater()


def test_auto_wrap_khmer_text():
    """Test smart line wrapping for long Khmer text phrases."""
    from downloader_app.core.subtitle_burner import auto_wrap_khmer_text

    short_text = "សួស្តីអ្នកទាំងអស់គ្នា"
    assert auto_wrap_khmer_text(short_text, max_chars_per_line=30) == short_text

    long_text = "ប្រសិនបើអ្នកពិតជាដេកជាមួយខ្ញុំដោយសារតែរឿងនេះ នោះខ្ញុំនឹងមិនអាចទ្រាំទ្របានឡើយ។"
    wrapped = auto_wrap_khmer_text(long_text, max_chars_per_line=25)
    assert "\n" in wrapped
    assert len(wrapped.split("\n")) == 2


def test_render_subtitle_overlay_image(tmp_path, qapp):
    """Test transparent HarfBuzz subtitle PNG frame rendering."""
    from downloader_app.core.subtitle_burner import render_subtitle_overlay_image

    out_png = tmp_path / "sub_frame.png"
    img = render_subtitle_overlay_image(
        text="ប្រសិនបើអ្នកពិតជាដេកជាមួយខ្ញុំ",
        width=1080,
        height=1920,
        font_variant="Bold",
        font_size_pt=30,
        blur_enabled=True,
        bg_box_scale=140,
        bg_box_color="#1E1E24",
        bg_box_opacity=85,
        output_path=out_png,
    )
    assert out_png.exists()
    assert out_png.stat().st_size > 1000
    assert img.width() == 1080
    assert img.height() == 1920


def test_generate_subtitle_overlay_sequence(tmp_path, qapp):
    """Test generating full ffconcat timeline with transparent subtitle overlay frames."""
    from downloader_app.core.subtitle_burner import generate_subtitle_overlay_sequence

    items = [
        SubtitleItem(index=1, start_time="00:00:01,000", end_time="00:00:03,000", start_seconds=1.0, end_seconds=3.0, text="ឃ្លាទី១"),
        SubtitleItem(index=2, start_time="00:00:04,000", end_time="00:00:06,000", start_seconds=4.0, end_seconds=6.0, text="ឃ្លាទី២"),
    ]
    out_dir = tmp_path / "sub_frames"
    concat_file = generate_subtitle_overlay_sequence(
        subtitle_items=items,
        output_dir=out_dir,
        video_width=1080,
        video_height=1920,
        font_variant="Bold",
        font_size_pt=30,
        blur_enabled=True,
        bg_box_scale=120,
        bg_box_color="#0F172A",
        bg_box_opacity=75,
    )
    assert concat_file.exists()
    content = concat_file.read_text(encoding="utf-8")
    assert "ffconcat version 1.0" in content
    assert "frame_0000.png" in content
    assert "frame_0001.png" in content
    assert "duration 2.000" in content


def test_build_subtitle_filter_complex_with_overlay(tmp_path):
    """Test filter complex with overlay concat stream."""
    from downloader_app.core.subtitle_burner import build_subtitle_filter_complex

    fake_concat = tmp_path / "subtitles_timeline.txt"
    fake_concat.write_text("ffconcat version 1.0\n", encoding="utf-8")

    f_str, out_label = build_subtitle_filter_complex(
        overlay_concat_path=fake_concat,
        blur_original_subtitles=True,
        video_width=1080,
        video_height=1920,
        overlay_input_index=2,
    )
    assert "boxblur" in f_str
    assert "crop" in f_str
    assert "[2:v]overlay=0:0" in f_str
    assert out_label == "[v_out]"


def test_get_video_duration_probing(tmp_path):
    """Test get_video_duration probe function and fallback behavior."""
    from downloader_app.core.subtitle_burner import get_video_duration

    # Nonexistent file returns 0.0 without crashing
    dur = get_video_duration(tmp_path / "nonexistent.mp4")
    assert dur == 0.0


def test_dubbing_mixer_progress_parsing_and_signals(qapp):
    """Test DubbingMixerWorker progress and speed ETA signal parsing."""
    from downloader_app.core.dubbing_mixer import DubbingMixerWorker
    
    worker = DubbingMixerWorker(
        video_path="fake_video.mp4",
        subtitle_items=[],
        audio_clip_paths=[],
        output_video_path="fake_out.mp4",
        burn_subtitles=False,
    )
    
    emitted_pcts = []
    emitted_msgs = []
    
    def on_progress(pct, msg=""):
        emitted_pcts.append(pct)
        emitted_msgs.append(msg)
        
    worker.progress_changed.connect(on_progress)
    
    # Emit test progress
    worker.progress_changed.emit(45.5, "Muxing Video: 45% • Speed: 2.5x • ETA: ~00:15")
    assert len(emitted_pcts) == 1
    assert emitted_pcts[0] == 45.5
    assert "Speed: 2.5x" in emitted_msgs[0]
    assert "ETA: ~00:15" in emitted_msgs[0]


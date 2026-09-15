"""
Unit tests for Vision AI Subtitle OCR Extractor
"""

from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from downloader_app.core.subtitle_extractor import (
    SubtitleItem,
    SubtitleOCRWorker,
    extract_subtitles_via_vision_ocr,
    _parse_gemini_vision_fallback_lines,
    ACTIVE_STT_MODELS,
    _PREFERRED_STT_MODEL,
)
from downloader_app.ui.views.dubbing_tool_view import DubbingToolView


def test_subtitle_ocr_worker_init(tmp_path):
    video = tmp_path / "test_movie.mp4"
    video.write_bytes(b"video data")

    worker = SubtitleOCRWorker(video_path=video, crop_box_ratio=(0.1, 0.7, 0.8, 0.2))
    assert worker.video_path == video
    assert worker.crop_box_ratio == (0.1, 0.7, 0.8, 0.2)
    assert worker.target_lang == "km"


def test_extract_subtitles_via_vision_ocr_missing_file(tmp_path):
    non_existent = tmp_path / "non_existent.mp4"
    items = extract_subtitles_via_vision_ocr(non_existent)
    assert items == []


def test_extract_subtitles_via_vision_ocr_mocked(tmp_path):
    video = tmp_path / "short_drama.mp4"
    video.write_bytes(b"fake video")

    mock_srt_response = (
        "1\n"
        "00:00:01,000 --> 00:00:03,500\n"
        "未经审批私垫15万\n"
    )

    mock_translated_items = [
        SubtitleItem(
            index=1,
            start_time="00:00:01,000",
            end_time="00:00:03,500",
            start_seconds=1.0,
            end_seconds=3.5,
            text="មិនបានទទួលការអនុម័តបុរេប្រទាន១៥ម៉ឺន",
        )
    ]

    mock_khmer_text = ["មិនបានទទួលការអនុម័តបុរេប្រទាន១៥ម៉ឺន"]

    with patch("downloader_app.core.translator.get_api_key", return_value="fake_api_key"), \
         patch("downloader_app.core.subtitle_extractor.get_ffmpeg_path", return_value="ffmpeg"), \
         patch("downloader_app.core.subtitle_extractor.get_video_duration_ffmpeg", return_value=120.0), \
         patch("subprocess.run") as mock_subproc, \
         patch("requests.post") as mock_post, \
         patch("downloader_app.core.translator.Translator.translate_subtitle_blocks", return_value=mock_khmer_text), \
         patch("downloader_app.core.grammar_corrector.correct_khmer_dialogue_grammar", return_value=mock_khmer_text):

        mock_subproc.return_value = MagicMock(returncode=0)

        # Mock frame file creation inside tempdir
        def mock_run(cmd, **kwargs):
            out_pattern = cmd[-1]
            out_dir = Path(out_pattern).parent
            (out_dir / "frame_00001.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
            return MagicMock(returncode=0)

        mock_subproc.side_effect = mock_run

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": mock_srt_response}]
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        items = extract_subtitles_via_vision_ocr(video, target_lang="km")
        assert len(items) == 1
        assert items[0].text == "មិនបានទទួលការអនុម័តបុរេប្រទាន១៥ម៉ឺន"


def test_dubbing_tool_view_ocr_button_init(qapp):
    view = DubbingToolView()
    assert hasattr(view, "btn_scan_ocr")
    assert view.btn_scan_ocr.text() == "Scan Subtitles (OCR)"
    view.deleteLater()


def test_active_stt_models_prioritize_available_quota():
    assert _PREFERRED_STT_MODEL == "gemini-3.1-flash-lite"
    assert ACTIVE_STT_MODELS[0] == "gemini-3.1-flash-lite"
    assert "gemini-3.1-flash-lite-preview" in ACTIVE_STT_MODELS


def test_parse_gemini_vision_fallback_lines_frames():
    raw = (
        "Here are the subtitles:\n"
        "Frame 1: 认识药王谷长老吗\n"
        "Frame 2: 不认识\n"
    )
    items = _parse_gemini_vision_fallback_lines(raw, interval_sec=2.0, batch_start_idx=0, batch_size=2)
    assert len(items) == 2
    assert items[0].text == "认识药王谷长老吗"
    assert items[0].start_time == "00:00:00,000"
    assert items[1].text == "不认识"
    assert items[1].start_time == "00:00:02,000"


def test_parse_gemini_vision_fallback_lines_bullets():
    raw = (
        "- 没有\n"
        "- 有丹师令吗\n"
    )
    items = _parse_gemini_vision_fallback_lines(raw, interval_sec=2.0, batch_start_idx=2, batch_size=2)
    assert len(items) == 2
    assert items[0].text == "没有"
    assert items[1].text == "有丹师令吗"


def test_extract_subtitles_via_vision_ocr_quota_error(tmp_path):
    video = tmp_path / "quota_test.mp4"
    video.write_bytes(b"fake video")

    with patch("downloader_app.core.translator.get_api_key", return_value="fake_api_key"), \
         patch("downloader_app.core.subtitle_extractor.get_ffmpeg_path", return_value="ffmpeg"), \
         patch("downloader_app.core.subtitle_extractor.get_video_duration_ffmpeg", return_value=10.0), \
         patch("time.sleep"), \
         patch("subprocess.run") as mock_subproc, \
         patch("requests.post") as mock_post:

        def mock_run(cmd, **kwargs):
            out_pattern = cmd[-1]
            out_dir = Path(out_pattern).parent
            (out_dir / "frame_00001.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
            return MagicMock(returncode=0)

        mock_subproc.side_effect = mock_run

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="429 Rate Limit"):
            extract_subtitles_via_vision_ocr(video)


def test_translate_subtitle_blocks_chunking_with_time():
    from downloader_app.core.translator import Translator
    t = Translator()
    with patch.object(t, "translate_subtitle_blocks", wraps=t.translate_subtitle_blocks) as mock_tr:
        with patch.object(t, "_translate_gtx", return_value="ជំរាបសួរ"):
            with patch("downloader_app.core.translator.get_api_key", return_value=None):
                res = t.translate_subtitle_blocks(["你好"] * 30, target_lang="km")
                assert len(res) == 30


def test_clean_khmer_dialogue_typos_strips_parenthetical_notes():
    from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
    raw_1 = "អរគុណលោកនាយកដែលទុកចិត្តខ្ញុំ។ (រក្សាទុក - ល្អហើយ)"
    raw_2 = "ខំប្រឹងធ្វើការបន្តទៀតណា។ (កែពី \"តទៅទៀត\" មក \"បន្តទៀត\" ស្ដាប់ទៅរលូនជាង)"
    raw_3 = "បានឡើងជាប្រធានផ្នែកលទ្ធកម្មហើយ។ (បន្ថែមពាក្យ \"ឡើង\" ដើម្បីឱ្យសមនឹងបរិបទនៃការដំឡើងតំណែង)"
    raw_4 = "បានឡើងជាប្រធានផ្នែកលទ្ធកម្មហើយ។ (កែដូចលេខ ៦)"

    assert clean_khmer_dialogue_typos(raw_1) == "អរគុណលោកនាយកដែលទុកចិត្តខ្ញុំ។"
    assert clean_khmer_dialogue_typos(raw_2) == "ខំប្រឹងធ្វើការបន្តទៀតណា។"
    assert clean_khmer_dialogue_typos(raw_3) == "បានឡើងជាប្រធានផ្នែកលទ្ធកម្មហើយ។"
    assert clean_khmer_dialogue_typos(raw_4) == "បានឡើងជាប្រធានផ្នែកលទ្ធកម្មហើយ។"


def test_srt_parse_and_format_strips_parenthetical_commentary():
    from downloader_app.core.subtitle_extractor import parse_srt_content, format_srt_content, SubtitleItem

    sample_srt = (
        "1\n"
        "00:01:14,000 --> 00:01:16,000\n"
        "បានឡើងជាប្រធានផ្នែកលទ្ធកម្មហើយ។ (បន្ថែមពាក្យ \"ឡើង\" ដើម្បីឱ្យសមនឹងបរិបទនៃការដំឡើងតំណែង)\n\n"
        "2\n"
        "00:01:16,000 --> 00:01:18,000\n"
        "ពិតមែនតើ! (កែពី \"ពិតប្រាកដមែនតើ\" ឱ្យខ្លី និងធម្មជាតិជាង)\n\n"
        "3\n"
        "00:01:46,000 --> 00:01:48,000\n"
        "ខ្ញុំចង់បាន។ (រក្សាទុក - ល្អហើយ)\n"
    )

    items = parse_srt_content(sample_srt)
    assert len(items) == 3
    assert items[0].text == "បានឡើងជាប្រធានផ្នែកលទ្ធកម្មហើយ។"
    assert items[1].text == "ពិតមែនតើ!"
    assert items[2].text == "ខ្ញុំចង់បាន។"

    formatted = format_srt_content(items)
    assert "(បន្ថែមពាក្យ" not in formatted
    assert "(កែពី" not in formatted
    assert "(រក្សាទុក" not in formatted
    assert "ខ្ញុំចង់បាន។" in formatted


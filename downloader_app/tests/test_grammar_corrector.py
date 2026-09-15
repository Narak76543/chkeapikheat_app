"""
Unit tests for Khmer Grammar & Phrase Corrector Engine
"""

from unittest.mock import MagicMock, patch

from downloader_app.core.grammar_corrector import (
    _parse_numbered_lines,
    correct_khmer_dialogue_grammar,
)


def test_parse_numbered_lines():
    raw = (
        "1. ខ្ញុំដឹងហើយ\n"
        "2. តោះទៅទាំងអស់គ្នា\n"
        "3. គ្មានបញ្ហាទេ\n"
    )
    res = _parse_numbered_lines(raw, 3)
    assert len(res) == 3
    assert res[0] == "ខ្ញុំដឹងហើយ"
    assert res[1] == "តោះទៅទាំងអស់គ្នា"
    assert res[2] == "គ្មានបញ្ហាទេ"


def test_correct_khmer_dialogue_grammar_empty():
    assert correct_khmer_dialogue_grammar([]) == []


def test_correct_khmer_dialogue_grammar_mocked():
    input_lines = ["ខ្ញុំដឹងហើយ (គ្មានទិន្នន័យ)", "តោះទៅ"]
    mock_response_text = (
        "1. ខ្ញុំយល់ដឹងហើយ\n"
        "2. តោះទៅទាំងអស់គ្នា\n"
    )

    with patch("downloader_app.core.grammar_corrector.get_api_key", return_value="fake_api_key"), \
         patch("requests.post") as mock_post:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": mock_response_text}]
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        progress_calls = []
        def _on_progress(pct, msg):
            progress_calls.append((pct, msg))

        results = correct_khmer_dialogue_grammar(input_lines, progress_callback=_on_progress)
        assert len(results) == 2
        assert results[0] == "ខ្ញុំយល់ដឹងហើយ"
        assert results[1] == "តោះទៅទាំងអស់គ្នា"
        assert len(progress_calls) > 0


def test_clean_khmer_dialogue_typos():
    from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
    assert clean_khmer_dialogue_typos("ប្រសិនបិយខ្ញុំទៅ") == "ប្រសិនបើខ្ញុំទៅ"
    assert clean_khmer_dialogue_typos("ិនមិនអាចធ្វើបាន") == "មិនអាចធ្វើបាន"
    assert clean_khmer_dialogue_typos("អាកខ្វាក់") == "អាខ្វាក់"
    assert clean_khmer_dialogue_typos("យូ៛រ៉ូ") == "យូរ៉ុយ"

"""
Unit tests for Translator & TranslationWorker.
Mocks Gemini REST API calls and verifies successful translation, caching, and fallback error handling.
"""

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QCoreApplication

from downloader_app.core.translator import TranslationWorker, Translator


@pytest.fixture(scope="session")
def qapp():
    """Initializes QCoreApplication for Qt signal testing."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


@pytest.fixture
def mock_gemini_api_key(monkeypatch):
    """Sets a dummy GEMINI_API_KEY environment variable."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-mock-api-key")


def test_translator_success(mock_gemini_api_key, tmp_path):
    """Tests successful translation returned from mocked Gemini REST API."""
    cache_file = tmp_path / "cache.json"
    translator = Translator(cache_file=cache_file)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "រឿង ម្ដាយបង្កើត"}]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = translator.translate_title("Refractory Mom", target_lang="km")

        assert result == "រឿង ម្ដាយបង្កើត"
        assert mock_post.call_count == 1

        # Assert second call uses cache and does NOT trigger HTTP request
        result_cached = translator.translate_title("Refractory Mom", target_lang="km")
        assert result_cached == "រឿង ម្ដាយបង្កើត"
        assert mock_post.call_count == 1  # count stays 1 due to cache hit!


def test_translator_no_api_key_fallback(monkeypatch, tmp_path):
    """Tests fallback to GTX translation when GEMINI_API_KEY is missing."""
    monkeypatch.setattr("downloader_app.core.translator.get_api_key", lambda: None)
    translator = Translator(cache_file=tmp_path / "cache.json")

    result = translator.translate_title("Original Movie Title", target_lang="km")
    assert isinstance(result, str)
    assert len(result) > 0


def test_translator_http_error_fallback(mock_gemini_api_key, tmp_path):
    """Tests fallback to GTX translation when API returns HTTP 500 error."""
    translator = Translator(cache_file=tmp_path / "cache.json")

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    with patch("requests.post", return_value=mock_response):
        result = translator.translate_title("Error Case Title", target_lang="km")
        assert isinstance(result, str)
        assert len(result) > 0


def test_translator_exception_fallback(mock_gemini_api_key, tmp_path):
    """Tests fallback to original title when network exception occurs."""
    translator = Translator(cache_file=tmp_path / "cache.json")

    with patch("requests.post", side_effect=Exception("Connection timed out")), \
         patch("requests.get", side_effect=Exception("GTX connection timed out")):
        result = translator.translate_title("Network Fail Title", target_lang="km")
        assert result == "Network Fail Title"


def test_translation_worker_qthread(qapp, mock_gemini_api_key, tmp_path):
    """Tests non-blocking TranslationWorker QThread execution and signals."""
    cache_file = tmp_path / "cache.json"
    translator = Translator(cache_file=cache_file)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "រឿង ភាគ"}]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_response):
        worker = TranslationWorker("Sample Title", target_lang="km", translator=translator)
        results = []
        worker.finished.connect(results.append)

        worker.start()
        worker.wait(5000)
        qapp.processEvents()

        assert len(results) == 1
        assert results[0] == "រឿង ភាគ"


def test_suggest_titles_success_and_cache(mock_gemini_api_key, tmp_path):
    """Tests suggest_titles returning requested count and verifying cache reuse."""

    cache_file = tmp_path / "cache.json"
    translator = Translator(cache_file=cache_file)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "1. រឿង ភាគទី១\n2. រឿង ភាគទី២\n3. រឿង ភាគទី៣"}]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        suggestions = translator.suggest_titles("Drama Title", target_lang="km", count=3)

        assert len(suggestions) == 3
        assert suggestions[0] == "រឿង ភាគទី១"
        assert suggestions[1] == "រឿង ភាគទី២"
        assert suggestions[2] == "រឿង ភាគទី៣"
        assert mock_post.call_count == 1

        # Second call with same title/count should use cache
        suggestions_cached = translator.suggest_titles("Drama Title", target_lang="km", count=3)
        assert suggestions_cached == ["រឿង ភាគទី១", "រឿង ភាគទី២", "រឿង ភាគទី៣"]
        assert mock_post.call_count == 1  # No extra HTTP call!


def test_title_suggestions_worker_qthread(qapp, mock_gemini_api_key, tmp_path):
    """Tests TitleSuggestionsWorker QThread execution."""
    from downloader_app.core.translator import TitleSuggestionsWorker

    cache_file = tmp_path / "cache.json"
    translator = Translator(cache_file=cache_file)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "1. ជម្រើសទី១\n2. ជម្រើសទី២"}]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_response):
        worker = TitleSuggestionsWorker("Sample Title", target_lang="km", count=2, translator=translator)
        results = []
        worker.finished.connect(results.append)

        worker.start()
        worker.wait(5000)
        qapp.processEvents()

        assert len(results) == 1
        assert results[0] == ["ជម្រើសទី១", "ជម្រើសទី២"]


def test_clean_drama_title():
    from downloader_app.core.translator import clean_drama_title

    assert clean_drama_title("姑妈供我成状元，我用一生报她恩第一季 - Episode 01.mp4") == "姑妈供我成状元，我用一生报她恩第一季"
    assert clean_drama_title("Drama Title_Ep05 (Episodes)") == "Drama Title"
    assert clean_drama_title("Movie Name [1080p].mkv") == "Movie Name"


def test_fallback_title_suggestions(tmp_path):
    from downloader_app.core.translator import Translator

    translator = Translator(cache_file=tmp_path / "cache.json")
    fallbacks = translator._generate_fallback_suggestions("Drama Title", target_lang="km", count=3)

    assert len(fallbacks) == 3


def test_translate_gtx(tmp_path):
    from downloader_app.core.translator import Translator

    translator = Translator(cache_file=tmp_path / "cache.json")
    res = translator._translate_gtx("Hello", target_lang="km")
    assert isinstance(res, str)
    assert len(res) > 0



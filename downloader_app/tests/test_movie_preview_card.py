"""
Unit tests for MoviePreviewCard and UrlInputBar auto-fix behavior.
Verifies inline movie preview card population, dismissal, and debounced text changes.
"""

from unittest.mock import MagicMock, patch

from downloader_app.ui.widgets.movie_preview_card import MoviePreviewCard
from downloader_app.ui.widgets.url_input_bar import UrlInputBar


def test_movie_preview_card_set_data(qapp):
    with patch("downloader_app.ui.widgets.movie_preview_card.AsyncImageLoader"):
        card = MoviePreviewCard()
        sample_data = {
            "title": "测试短剧",
            "cover_url": "https://example.com/poster.jpg",
            "total_episodes": 80,
            "estimated_duration_mins": 160,
            "intro": "测试剧情介绍",
            "tags": ["测试", "古装"],
        }

        card.set_movie_data(sample_data)
        assert card.lbl_title.text() == "测试短剧"
        assert "80" in card.lbl_eps_badge.text()
        assert "160" in card.lbl_dur_badge.text()
        assert card.lbl_intro.text() == "测试剧情介绍"


def test_movie_preview_card_signals(qapp):
    card = MoviePreviewCard()
    sample_data = {"title": "测试电影", "series_id": "12345"}
    card.set_movie_data(sample_data)

    full_movie_spy = MagicMock()
    episodes_spy = MagicMock()
    dismiss_spy = MagicMock()

    card.download_full_movie_selected.connect(full_movie_spy)
    card.download_episodes_selected.connect(episodes_spy)
    card.dismiss_requested.connect(dismiss_spy)

    expected_data = dict(sample_data)
    expected_data["quality"] = "1080p"

    card.btn_full_movie.click()
    full_movie_spy.assert_called_once_with(expected_data)

    card.btn_episodes.click()
    episodes_spy.assert_called_once_with(expected_data)

    card.btn_close.click()
    dismiss_spy.assert_called_once()
    assert not card.isVisible()


def test_url_input_bar_auto_fix(qapp):
    bar = UrlInputBar()
    bar.set_text("糯糯下山，师兄们都慌了第二季")
    assert bar.text() == "糯糯下山，师兄们都慌了第二季"


def test_metadata_card_quality(qapp):
    from downloader_app.ui.widgets.metadata_card import MetadataCard, MetadataModel

    card = MetadataCard()
    model = MetadataModel(title="Test Metadata", series_id="9999")
    card.set_data(model)

    add_spy = MagicMock()
    episodes_spy = MagicMock()
    card.add_requested.connect(add_spy)
    card.download_episodes_requested.connect(episodes_spy)

    card.combo_quality.setCurrentText("720p")
    card.btn_add.click()

    assert add_spy.call_count == 1
    emitted_model = add_spy.call_args[0][0]
    assert emitted_model.selected_quality == "720p"

    card.combo_quality.setCurrentText("480p")
    card.btn_episodes.click()
    assert episodes_spy.call_count == 1
    emitted_model_ep = episodes_spy.call_args[0][0]
    assert emitted_model_ep.selected_quality == "480p"

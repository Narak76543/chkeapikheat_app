"""
Unit tests for EpisodeSelectionCard
"""

import pytest
from PyQt6.QtCore import Qt

from downloader_app.ui.widgets.episode_selection_card import EpisodeSelectionCard


@pytest.fixture
def dummy_movie_data():
    return {
        "title": "Test Drama Series",
        "total_episodes": 78,
        "vid_list": [{"ep": i} for i in range(1, 79)],
        "cover_url": "",
    }


def test_card_init(qtbot, dummy_movie_data):
    card = EpisodeSelectionCard(dummy_movie_data, fetch_suggestions=False)
    qtbot.add_widget(card)

    assert card.total_episodes == 78
    assert len(card.item_cards) == 78
    assert "Download Selected (78) • 1080p" in card.btn_download.text()
    assert card.btn_download.isEnabled()


def test_quality_selection(qtbot, dummy_movie_data):
    card = EpisodeSelectionCard(dummy_movie_data, fetch_suggestions=False)
    qtbot.add_widget(card)

    card.quality_combo.setCurrentText("720p HD")
    assert card.selected_quality == "720p"
    assert "720p" in card.btn_download.text()

    card.quality_combo.setCurrentText("480p SD")
    assert card.selected_quality == "480p"
    assert "480p" in card.btn_download.text()


def test_select_all_deselect_all(qtbot, dummy_movie_data):
    card = EpisodeSelectionCard(dummy_movie_data, fetch_suggestions=False)
    qtbot.add_widget(card)

    card._deselect_all()
    assert all(not item.is_checked() for item in card.item_cards)
    assert "Download Selected (0)" in card.btn_download.text()
    assert not card.btn_download.isEnabled()

    card._select_all()
    assert all(item.is_checked() for item in card.item_cards)
    assert "Download Selected (78)" in card.btn_download.text()
    assert card.btn_download.isEnabled()


def test_range_selection(qtbot, dummy_movie_data):
    card = EpisodeSelectionCard(dummy_movie_data, fetch_suggestions=False)
    qtbot.add_widget(card)

    card.spin_from.setValue(5)
    card.spin_to.setValue(15)

    for i, item in enumerate(card.item_cards, start=1):
        if 5 <= i <= 15:
            assert item.is_checked()
        else:
            assert not item.is_checked()

    assert "Download Selected (11)" in card.btn_download.text()


def test_title_suggestions_and_custom_write_in(qtbot, dummy_movie_data):
    card = EpisodeSelectionCard(dummy_movie_data, fetch_suggestions=False)
    qtbot.add_widget(card)

    # Test candidate suggestions received
    card._on_title_suggestions_received(["រឿងភាគ Test Drama", "Test Drama Khmer"])
    assert card._selected_title == "រឿងភាគ Test Drama"
    assert "រឿងភាគ Test Drama" in card.lbl_preview_files.text()

    # Test custom title selection
    card.edit_custom_title.setText("រឿងភាគ ស្រីស្អាត")
    card._on_use_custom_clicked()
    assert card._selected_title == "រឿងភាគ ស្រីស្អាត"
    assert "រឿងភាគ ស្រីស្អាត" in card.lbl_preview_files.text()


def test_confirm_emits_signal_with_selected_title(qtbot, dummy_movie_data):
    card = EpisodeSelectionCard(dummy_movie_data, fetch_suggestions=False)
    qtbot.add_widget(card)

    received = []
    card.episodes_selected.connect(lambda data: received.append(data))

    card._on_title_suggestions_received(["រឿងភាគ ពិសេស"])
    card.spin_from.setValue(1)
    card.spin_to.setValue(5)
    card.quality_combo.setCurrentText("720p HD")

    card._on_confirm()

    assert len(received) == 1
    assert received[0]["selected_episodes"] == [1, 2, 3, 4, 5]
    assert received[0]["quality"] == "720p"
    assert received[0]["total_episodes"] == 78
    assert received[0]["selected_title"] == "រឿងភាគ ពិសេស"

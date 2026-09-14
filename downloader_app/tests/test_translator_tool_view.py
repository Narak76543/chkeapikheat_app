"""
Unit tests for TranslatorToolView standalone widget
"""

import pytest
from PyQt6.QtCore import Qt

from downloader_app.ui.views.translator_tool_view import TranslatorToolView


def test_translator_tool_view_init(qtbot):
    view = TranslatorToolView()
    qtbot.add_widget(view)
    view.show()

    assert view.stack_widget.currentIndex() == 0
    assert view.single_title_card.isVisible()
    assert not view.batch_folder_card.isVisible()


def test_mode_switching(qtbot):
    view = TranslatorToolView()
    qtbot.add_widget(view)
    view.show()

    view._on_mode_changed(1)
    assert not view.single_title_card.isVisible()
    assert view.batch_folder_card.isVisible()

    view._on_mode_changed(0)
    assert view.single_title_card.isVisible()
    assert not view.batch_folder_card.isVisible()


def test_single_title_translation(qtbot):
    view = TranslatorToolView()
    qtbot.add_widget(view)
    view.show()

    view.edit_single_title.setText("Test Chinese Drama Title")
    view._on_single_suggestions_received(["រឿងភាគ Test Drama", "Test Drama Khmer"])

    assert view.single_sugg_layout.count() == 3  # Header label + 2 buttons


def test_folder_scan_preview(qtbot, tmp_path):
    view = TranslatorToolView()
    qtbot.add_widget(view)
    view.show()

    # Create dummy folder structure
    folder = tmp_path / "TestDramaFolder"
    folder.mkdir()
    subfolder = folder / "Ep 01"
    subfolder.mkdir()
    video_file = folder / "Ep 02.mp4"
    video_file.touch()

    view._scan_folder_for_preview(str(folder))
    assert view.preview_table.rowCount() == 2

"""
Unit tests for SelectableItemGrid and SelectableItemCard widgets
"""

import pytest
from PyQt6.QtCore import Qt

from downloader_app.ui.widgets.selectable_item_grid import (
    SelectableItem,
    SelectableItemCard,
    SelectableItemGrid,
)


@pytest.fixture
def sample_items():
    return [
        SelectableItem(id="item_01", title="Item 01", selected=False),
        SelectableItem(id="item_02", title="Item 02", selected=False),
        SelectableItem(id="item_03", title="Item 03", selected=False),
    ]


def test_grid_default_init(qtbot):
    grid = SelectableItemGrid()
    qtbot.add_widget(grid)

    assert len(grid.items) == 5
    assert len(grid.cards) == 5
    assert not grid.btn_download.isEnabled()
    assert "Selected: 0 / 5" in grid.lbl_counter.text()


def test_custom_items_load(qtbot, sample_items):
    grid = SelectableItemGrid(sample_items)
    qtbot.add_widget(grid)

    assert len(grid.items) == 3
    assert len(grid.cards) == 3
    assert "Selected: 0 / 3" in grid.lbl_counter.text()


def test_select_all_toggle(qtbot, sample_items):
    grid = SelectableItemGrid(sample_items)
    qtbot.add_widget(grid)

    # Click Select all
    grid.btn_select_all.click()

    assert all(item.selected for item in grid.items)
    assert grid.get_selected_ids() == ["item_01", "item_02", "item_03"]
    assert grid.btn_download.isEnabled()
    assert "Selected: 3 / 3" in grid.lbl_counter.text()

    # Click Deselect all
    grid.btn_select_all.click()

    assert all(not item.selected for item in grid.items)
    assert grid.get_selected_ids() == []
    assert not grid.btn_download.isEnabled()
    assert "Selected: 0 / 3" in grid.lbl_counter.text()


def test_card_item_toggling(qtbot, sample_items):
    grid = SelectableItemGrid(sample_items)
    qtbot.add_widget(grid)

    # Toggle item 01
    card1 = grid.cards[0]
    card1.set_selected(True)

    assert grid.get_selected_ids() == ["item_01"]
    assert grid.btn_download.isEnabled()
    assert "Selected: 1 / 3" in grid.lbl_counter.text()

    # Toggle item 02
    card2 = grid.cards[1]
    card2.set_selected(True)

    assert grid.get_selected_ids() == ["item_01", "item_02"]
    assert "Selected: 2 / 3" in grid.lbl_counter.text()


def test_clear_selection(qtbot, sample_items):
    grid = SelectableItemGrid(sample_items)
    qtbot.add_widget(grid)

    grid.btn_select_all.click()
    assert len(grid.get_selected_ids()) == 3

    grid.btn_cancel.click()
    assert len(grid.get_selected_ids()) == 0
    assert not grid.btn_download.isEnabled()


def test_download_requested_signal(qtbot, sample_items):
    grid = SelectableItemGrid(sample_items)
    qtbot.add_widget(grid)

    received_ids = []
    grid.download_requested.connect(lambda ids: received_ids.append(ids))

    grid.btn_select_all.click()
    grid.btn_download.click()

    assert len(received_ids) == 1
    assert received_ids[0] == ["item_01", "item_02", "item_03"]

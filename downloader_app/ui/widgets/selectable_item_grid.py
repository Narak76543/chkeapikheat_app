"""
Selectable Item Grid Widget
Reusable view widget for selecting batch items from a 4-5 column responsive grid.
Includes 3:4 aspect ratio thumbnail cards, One UI header/footer controls, and i18n support.
"""

from dataclasses import dataclass

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.image_loader import AsyncImageLoader
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.selectable_item_grid")


@dataclass
class SelectableItem:
    """Dataclass representing a selectable item in the grid."""

    id: str
    title: str
    thumbnail_path: str | None = None
    selected: bool = False


class SelectableItemCard(QFrame):
    """
    Card item widget with 3:4 aspect ratio thumbnail area (rounded 14px),
    fallback photo icon, checkbox, and elided title label.
    """

    toggled = pyqtSignal(str, bool)

    def __init__(self, item: SelectableItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self.setObjectName("sidebarCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(130)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Thumbnail Area (3:4 aspect ratio: width=118, height=118*4/3 ≈ 157)
        self.thumb_container = QFrame()
        self.thumb_container.setObjectName("metadataPoster")
        self.thumb_container.setFixedSize(118, 157)
        self.thumb_container.setStyleSheet("border-radius: 14px;")

        thumb_layout = QVBoxLayout(self.thumb_container)
        thumb_layout.setContentsMargins(0, 0, 0, 0)

        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setFixedSize(118, 157)

        if self.item.thumbnail_path:
            pm = QPixmap(self.item.thumbnail_path)
            if not pm.isNull():
                self.thumb_label.setPixmap(
                    pm.scaled(
                        118,
                        157,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                self._set_placeholder_icon()
        else:
            self._set_placeholder_icon()

        thumb_layout.addWidget(self.thumb_label)
        layout.addWidget(self.thumb_container)

        # Checkbox + Elided Title Label Row
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(2, 0, 2, 0)
        bottom_row.setSpacing(6)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(self.item.selected)
        self.checkbox.stateChanged.connect(self._on_check_changed)
        bottom_row.addWidget(self.checkbox)

        self.lbl_title = QLabel(self.item.title)
        self.lbl_title.setObjectName("filenameLabel")
        self.lbl_title.setStyleSheet("font-size: 12px; font-weight: 500;")
        self.lbl_title.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        bottom_row.addWidget(self.lbl_title, 1)

        layout.addLayout(bottom_row)

    def _set_placeholder_icon(self) -> None:
        """Sets muted photo placeholder icon."""
        icon = get_icon("file-video", color="#8E8E93", size=36)
        self.thumb_label.setPixmap(icon.pixmap(36, 36))

    def mousePressEvent(self, event) -> None:
        """Clicking anywhere on the card toggles item selection."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.checkbox.setChecked(not self.checkbox.isChecked())
        super().mousePressEvent(event)

    def _on_check_changed(self) -> None:
        self.item.selected = self.checkbox.isChecked()
        self.toggled.emit(self.item.id, self.item.selected)

    def is_selected(self) -> bool:
        return self.checkbox.isChecked()

    def set_selected(self, checked: bool) -> None:
        self.checkbox.setChecked(checked)


class SelectableItemGrid(QWidget):
    """
    Reusable view widget hosting a responsive grid of selectable items,
    header with 'Select all' toggle, and footer with counter and action buttons.
    """

    selection_changed = pyqtSignal(list, int)  # selected_ids, count
    download_requested = pyqtSignal(list)      # selected_ids

    def __init__(self, items: list[SelectableItem] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items: list[SelectableItem] = items or self._get_placeholder_items()
        self.cards: list[SelectableItemCard] = []

        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _get_placeholder_items(self) -> list[SelectableItem]:
        """Generates 5 default placeholder items ("Item 01".."Item 05")."""
        return [
            SelectableItem(id=f"item_{i:02d}", title=f"Item {i:02d}", thumbnail_path=None, selected=False)
            for i in range(1, 6)
        ]

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # ── 1. Header Row ──
        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        self.lbl_title = QLabel(tr("select_items"))
        self.lbl_title.setObjectName("titleLabel")
        self.lbl_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        header_row.addWidget(self.lbl_title)

        header_row.addStretch()

        self.btn_select_all = QPushButton(tr("select_all"))
        self.btn_select_all.setObjectName("secondaryButton")
        self.btn_select_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select_all.clicked.connect(self._toggle_select_all)
        header_row.addWidget(self.btn_select_all)

        layout.addLayout(header_row)

        # ── 2. Responsive Scrollable Item Grid ──
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.scroll_content = QWidget()
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setContentsMargins(8, 8, 8, 8)
        self.grid_layout.setSpacing(12)

        self._rebuild_grid()

        self.scroll_area.setWidget(self.scroll_content)
        layout.addWidget(self.scroll_area, 1)

        # ── 3. Footer Row ──
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(4, 4, 4, 4)
        footer_row.setSpacing(10)

        self.lbl_counter = QLabel()
        self.lbl_counter.setObjectName("metaLabel")
        footer_row.addWidget(self.lbl_counter)

        footer_row.addStretch()

        self.btn_cancel = QPushButton(tr("cancel"))
        self.btn_cancel.setObjectName("secondaryButton")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.clear_selection)
        footer_row.addWidget(self.btn_cancel)

        self.btn_download = QPushButton()
        self.btn_download.setObjectName("primaryButton")
        self.btn_download.setIcon(get_icon("download", color="#FFFFFF", size=16))
        self.btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_download.clicked.connect(self._on_download_clicked)
        footer_row.addWidget(self.btn_download)

        layout.addLayout(footer_row)

        self._update_selection_state()

    def set_items(self, items: list[SelectableItem]) -> None:
        """Populates the grid with a new list of items."""
        self.items = items
        self._rebuild_grid()
        self._update_selection_state()

    def _rebuild_grid(self) -> None:
        """Clears existing cards and rebuilds grid layout."""
        # Clear layout items
        while self.grid_layout.count() > 0:
            child = self.grid_layout.takeAt(0)
            if child and child.widget():
                child.widget().deleteLater()

        self.cards.clear()

        cols = 5
        for i, item in enumerate(self.items):
            card = SelectableItemCard(item, parent=self.scroll_content)
            card.toggled.connect(self._on_item_toggled)
            self.cards.append(card)

            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(card, row, col, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def _on_item_toggled(self, item_id: str, checked: bool) -> None:
        self._update_selection_state()

    def _toggle_select_all(self) -> None:
        """Toggles between select all and deselect all."""
        all_selected = all(item.selected for item in self.items) if self.items else False
        new_state = not all_selected
        for card in self.cards:
            card.set_selected(new_state)
        self._update_selection_state()

    def clear_selection(self) -> None:
        """Resets all item selections."""
        for card in self.cards:
            card.set_selected(False)
        self._update_selection_state()

    def get_selected_ids(self) -> list[str]:
        """Returns list of currently selected item IDs."""
        return [item.id for item in self.items if item.selected]

    def _update_selection_state(self) -> None:
        """Updates header button label, footer counter label, download button state, and emits selection_changed."""
        selected_ids = self.get_selected_ids()
        count = len(selected_ids)
        total = len(self.items)

        # Update Select All / Deselect All header button text
        all_selected = count == total and total > 0
        self.btn_select_all.setText(tr("deselect_all") if all_selected else tr("select_all"))

        # Update Footer Counter Label
        counter_fmt = tr("selected_count")
        self.lbl_counter.setText(counter_fmt.format(n=count, total=total))

        # Update Primary Download Button Label & Enabled State
        btn_fmt = tr("download_selected")
        self.btn_download.setText(btn_fmt.format(n=count))
        self.btn_download.setEnabled(count > 0)

        # Emit Signal
        self.selection_changed.emit(selected_ids, count)

    def _on_download_clicked(self) -> None:
        """Logs selected item IDs and emits download_requested signal."""
        selected_ids = self.get_selected_ids()
        logger.info(f"Download Selected requested for item IDs: {selected_ids}")
        self.download_requested.emit(selected_ids)

    def retranslate_ui(self) -> None:
        """Retranslates header title, action buttons, and footer labels when language changes."""
        self.lbl_title.setText(tr("select_items"))
        self.btn_cancel.setText(tr("cancel"))
        self._update_selection_state()

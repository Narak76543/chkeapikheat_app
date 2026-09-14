"""
Download List Container Widget
Scrollable list holding One UI 9 DownloadRow cards with minimal empty-state display.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from downloader_app.models.download_task import DownloadTask
from downloader_app.ui.resources.icon_helper import get_empty_state_icon
from downloader_app.ui.widgets.download_row import DownloadRow
from downloader_app.utils.i18n import get_i18n_manager, tr


class DownloadList(QWidget):
    """Scrollable container for One UI DownloadRow cards with minimal empty state."""

    pause_requested = pyqtSignal(str)
    resume_requested = pyqtSignal(str)
    cancel_requested = pyqtSignal(str)
    retry_requested = pyqtSignal(str)
    split_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[str, DownloadRow] = {}
        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        # Container inside Scroll Area
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 4, 0, 4)
        self.container_layout.setSpacing(12)  # 12px gap between cards

        # Empty state container
        self.empty_state_widget = QWidget()
        empty_layout = QVBoxLayout(self.empty_state_widget)
        empty_layout.setContentsMargins(20, 60, 20, 60)
        empty_layout.setSpacing(12)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.empty_icon_label = QLabel()
        self.empty_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_icon_label.setPixmap(get_empty_state_icon(size=48).pixmap(48, 48))

        self.empty_text_label = QLabel(tr("no_active_downloads"))
        self.empty_text_label.setObjectName("emptyStateLabel")
        self.empty_text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_layout.addWidget(self.empty_icon_label)
        empty_layout.addWidget(self.empty_text_label)

        self.container_layout.addWidget(self.empty_state_widget)
        self.container_layout.addStretch()

        self.scroll_area.setWidget(self.container)
        main_layout.addWidget(self.scroll_area)

    def add_task(self, task: DownloadTask) -> DownloadRow:
        """Adds a new task card to the list."""
        if task.id in self._rows:
            self._rows[task.id].update_task(task)
            return self._rows[task.id]

        row = DownloadRow(task)
        row.pause_requested.connect(self.pause_requested.emit)
        row.resume_requested.connect(self.resume_requested.emit)
        row.cancel_requested.connect(self.cancel_requested.emit)
        row.retry_requested.connect(self.retry_requested.emit)
        row.split_requested.connect(self.split_requested.emit)

        self._rows[task.id] = row

        # Insert before the stretch at the bottom
        insert_idx = max(0, self.container_layout.count() - 1)
        self.container_layout.insertWidget(insert_idx, row)

        self._update_empty_state_visibility()
        return row

    def update_task(self, task: DownloadTask) -> None:
        """Updates an existing task card."""
        if task.id in self._rows:
            self._rows[task.id].update_task(task)

    def remove_task(self, task_id: str) -> None:
        """Removes a task card from the list."""
        row = self._rows.pop(task_id, None)
        if row:
            self.container_layout.removeWidget(row)
            row.deleteLater()
            self._update_empty_state_visibility()

    def clear(self) -> None:
        """Clears all download rows."""
        for row in list(self._rows.values()):
            self.container_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._update_empty_state_visibility()

    def _update_empty_state_visibility(self) -> None:
        has_items = len(self._rows) > 0
        self.empty_state_widget.setVisible(not has_items)

    def update_theme_icons(self) -> None:
        """Refreshes empty state icon and task row icons for active theme."""
        self.empty_icon_label.setPixmap(get_empty_state_icon(size=48).pixmap(48, 48))
        for row in self._rows.values():
            row.update_theme_icons()

    def retranslate_ui(self) -> None:
        """Updates empty-state label upon language switch."""
        self.empty_text_label.setText(tr("no_active_downloads"))
        self.empty_icon_label.setPixmap(get_empty_state_icon(size=48).pixmap(48, 48))


DownloadListWidget = DownloadList

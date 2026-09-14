"""
Download Row Card Widget
One UI 9 Card representing a single download task.
Includes 48x48 icon placeholder, filename, thick rounded progress bar, speed/size metrics,
status badges, and action buttons (pause, resume, retry, cancel).
"""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from downloader_app.core.config import get_theme
from downloader_app.models.download_task import DownloadTask, TaskStatus
from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.row")


class ElidedLabel(QLabel):
    """QLabel that automatically elides long text with '...' to prevent breaking UI card width."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full_text = text or ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if self._full_text:
            self.setToolTip(self._full_text)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._update_elided()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided()

    def _update_elided(self) -> None:
        if not self._full_text:
            super().setText("")
            return
        metrics = self.fontMetrics()
        w = max(10, self.width())
        elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, w)
        super().setText(elided)


class DownloadRow(QWidget):
    """One UI 9 Card widget for displaying and controlling a single download task."""

    pause_requested = pyqtSignal(str)
    resume_requested = pyqtSignal(str)
    cancel_requested = pyqtSignal(str)
    retry_requested = pyqtSignal(str)
    split_requested = pyqtSignal(str)

    def __init__(self, task: DownloadTask, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.task = task
        self._init_ui()
        self.update_task(task)
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        # Outer layout for padding and card placement
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # One UI 9 Rounded Card
        self.card = QFrame()
        self.card.setObjectName("downloadCard")
        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(14)

        # 1. 48x48 Icon Placeholder
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(48, 48)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setPixmap(get_icon("file-video", size=32).pixmap(32, 32))
        card_layout.addWidget(self.icon_label)

        # 2. Middle Content (Filename, Progress bar, Meta details)
        mid_layout = QVBoxLayout()
        mid_layout.setSpacing(6)

        # Top row: Filename + Status Badge
        name_badge_row = QHBoxLayout()
        name_badge_row.setSpacing(8)

        self.filename_label = ElidedLabel(self.task.filename or self.task.url)
        self.filename_label.setObjectName("filenameLabel")
        name_badge_row.addWidget(self.filename_label, 1)

        self.duration_container = QWidget()
        self.duration_container.setObjectName("metadataTagNeutralPill")
        dur_layout = QHBoxLayout(self.duration_container)
        dur_layout.setContentsMargins(6, 2, 6, 2)
        dur_layout.setSpacing(4)

        self.duration_icon = QLabel()
        self.duration_icon.setFixedSize(13, 13)
        dur_layout.addWidget(self.duration_icon)

        self.duration_label = QLabel()
        dur_layout.addWidget(self.duration_label)

        self.duration_container.setVisible(False)
        name_badge_row.addWidget(self.duration_container)

        self.status_badge = QLabel()
        name_badge_row.addWidget(self.status_badge)
        mid_layout.addLayout(name_badge_row)

        # Thick rounded progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("thickProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(int(self.task.progress_percent))
        self.progress_bar.setTextVisible(False)
        mid_layout.addWidget(self.progress_bar)

        # Meta row: Downloaded / Total & Speed / ETA
        meta_row = QHBoxLayout()
        self.meta_left_label = ElidedLabel()
        self.meta_left_label.setObjectName("metaLabel")

        self.meta_right_label = QLabel()
        self.meta_right_label.setObjectName("metaLabel")
        self.meta_right_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        meta_row.addWidget(self.meta_left_label, 1)
        meta_row.addWidget(self.meta_right_label)
        mid_layout.addLayout(meta_row)

        card_layout.addLayout(mid_layout, 1)

        # 3. Action Buttons (One UI 36px circular pill buttons)
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)

        self.btn_pause = QPushButton()
        self.btn_pause.setObjectName("rowActionButton")
        self.btn_pause.setIcon(get_icon("pause", size=18))
        self.btn_pause.setToolTip(tr("pause"))
        self.btn_pause.clicked.connect(self._on_pause_clicked)
        actions_layout.addWidget(self.btn_pause)

        self.btn_resume = QPushButton()
        self.btn_resume.setObjectName("rowActionButton")
        self.btn_resume.setIcon(get_icon("play", size=18))
        self.btn_resume.setToolTip(tr("resume"))
        self.btn_resume.clicked.connect(self._on_resume_clicked)
        actions_layout.addWidget(self.btn_resume)

        self.btn_retry = QPushButton()
        self.btn_retry.setObjectName("rowActionButton")
        self.btn_retry.setIcon(get_icon("rotate-cw", size=18))
        self.btn_retry.setToolTip(tr("retry"))
        self.btn_retry.clicked.connect(self._on_retry_clicked)
        actions_layout.addWidget(self.btn_retry)

        self.btn_cancel = QPushButton()
        self.btn_cancel.setObjectName("rowActionButton")
        self.btn_cancel.setIcon(get_icon("x", size=18))
        self.btn_cancel.setToolTip(tr("cancel"))
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        actions_layout.addWidget(self.btn_cancel)

        self.btn_split = QPushButton()
        self.btn_split.setObjectName("rowActionButton")
        self.btn_split.setIcon(get_icon("scissors", size=18))
        self.btn_split.setToolTip(tr("split_movie"))
        self.btn_split.clicked.connect(self._on_split_clicked)
        self.btn_split.setVisible(False)
        actions_layout.addWidget(self.btn_split)

        card_layout.addLayout(actions_layout)
        layout.addWidget(self.card)

    def _on_pause_clicked(self) -> None:
        logger.info(f"UI Stub: Pause clicked for task {self.task.id}")
        self.pause_requested.emit(self.task.id)

    def _on_resume_clicked(self) -> None:
        logger.info(f"UI Stub: Resume clicked for task {self.task.id}")
        self.resume_requested.emit(self.task.id)

    def _on_retry_clicked(self) -> None:
        logger.info(f"UI Stub: Retry clicked for task {self.task.id}")
        self.retry_requested.emit(self.task.id)

    def _on_cancel_clicked(self) -> None:
        logger.info(f"UI Stub: Cancel clicked for task {self.task.id}")
        self.cancel_requested.emit(self.task.id)

    def _on_split_clicked(self) -> None:
        file_path = ""
        if self.task.destination_path and self.task.filename:
            file_path = str(Path(self.task.destination_path) / self.task.filename)
        elif self.task.filename:
            file_path = self.task.filename
        logger.info(f"Split requested for video path: {file_path}")
        self.split_requested.emit(file_path)

    def update_task(self, task: DownloadTask) -> None:
        """Refreshes the card display with current task properties."""
        self.task = task
        display_name = task.filename or task.url
        self.filename_label.setText(display_name)
        self.filename_label.setToolTip(task.url)

        if task.duration:
            icon_color = "#D1D5DB" if get_theme() == "dark" else "#4B5563"
            self.duration_icon.setPixmap(
                get_icon("clock", color=icon_color, size=13).pixmap(13, 13)
            )
            self.duration_label.setText(task.duration)
            self.duration_container.setVisible(True)
        else:
            self.duration_container.setVisible(False)

        if (
            task.poster_url
            and getattr(self, "_loaded_poster_url", None) != task.poster_url
        ):
            self._loaded_poster_url = task.poster_url
            from PyQt6.QtCore import QSize

            from downloader_app.utils.image_loader import AsyncImageLoader

            self._image_loader = AsyncImageLoader(
                task.poster_url,
                target_size=QSize(48, 48),
                corner_radius=10,
                parent=self,
            )
            self._image_loader.image_loaded.connect(self.icon_label.setPixmap)
            self._image_loader.start()

        self.progress_bar.setValue(int(task.progress_percent))

        # Update status badge & action buttons visibility
        self._update_status_display()
        self._update_meta_labels()

    def _update_status_display(self) -> None:
        status = self.task.status
        self.btn_split.setVisible(status == TaskStatus.DONE)
        if status == TaskStatus.DOWNLOADING:
            self.status_badge.setText(tr("status_downloading"))
            self.status_badge.setObjectName("statusBadge_downloading")
            self.btn_pause.setVisible(True)
            self.btn_resume.setVisible(False)
            self.btn_retry.setVisible(False)
            self.btn_cancel.setVisible(True)
        elif status == TaskStatus.PAUSED:
            self.status_badge.setText(tr("status_paused"))
            self.status_badge.setObjectName("statusBadge_paused")
            self.btn_pause.setVisible(False)
            self.btn_resume.setVisible(True)
            self.btn_retry.setVisible(False)
            self.btn_cancel.setVisible(True)
        elif status == TaskStatus.DONE:
            self.status_badge.setText(tr("status_done"))
            self.status_badge.setObjectName("statusBadge_done")
            self.btn_pause.setVisible(False)
            self.btn_resume.setVisible(False)
            self.btn_retry.setVisible(False)
            self.btn_cancel.setVisible(False)
        elif status == TaskStatus.ERROR:
            self.status_badge.setText(tr("status_error"))
            self.status_badge.setObjectName("statusBadge_error")
            self.btn_pause.setVisible(False)
            self.btn_resume.setVisible(False)
            self.btn_retry.setVisible(True)
            self.btn_cancel.setVisible(True)
        else:  # QUEUED
            self.status_badge.setText(tr("status_queued"))
            self.status_badge.setObjectName("statusBadge_queued")
            self.btn_pause.setVisible(False)
            self.btn_resume.setVisible(False)
            self.btn_retry.setVisible(False)
            self.btn_cancel.setVisible(True)

        # Force stylesheet re-evaluation for dynamic objectName
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    def _update_meta_labels(self) -> None:
        downloaded = self._format_bytes(self.task.downloaded_bytes)
        total = (
            self._format_bytes(self.task.total_bytes)
            if self.task.total_bytes > 0
            else "--"
        )

        if self.task.status == TaskStatus.DOWNLOADING:
            speed_str = self._format_speed(self.task.speed_bytes_per_sec)
            self.meta_left_label.setText(f"{downloaded} / {total}")
            self.meta_right_label.setText(
                f"{self.task.progress_percent:.1f}% • {speed_str}"
            )
        elif self.task.status == TaskStatus.DONE:
            self.meta_left_label.setText(total)
            self.meta_right_label.setText(f"{tr('status_done')} • 100%")
        elif self.task.status == TaskStatus.ERROR:
            err_msg = self.task.error_message or tr("status_error")
            self.meta_left_label.setText(err_msg)
            self.meta_right_label.setText(f"{self.task.progress_percent:.1f}%")
        else:
            self.meta_left_label.setText(f"{downloaded} / {total}")
            self.meta_right_label.setText(f"{self.task.progress_percent:.1f}%")

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if num_bytes < 1024.0:
                return f"{num_bytes:.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} PB"

    @staticmethod
    def _format_speed(bytes_per_sec: float) -> str:
        for unit in ["B/s", "KB/s", "MB/s", "GB/s"]:
            if bytes_per_sec < 1024.0:
                return f"{bytes_per_sec:.1f} {unit}"
            bytes_per_sec /= 1024.0
        return f"{bytes_per_sec:.1f} TB/s"

    def update_theme_icons(self) -> None:
        """Refreshes all action button icons to match the current theme color."""
        if not self.task.poster_url:
            self.icon_label.setPixmap(get_icon("file-video", size=32).pixmap(32, 32))
        if self.task.duration:
            icon_color = "#D1D5DB" if get_theme() == "dark" else "#4B5563"
            self.duration_icon.setPixmap(
                get_icon("clock", color=icon_color, size=13).pixmap(13, 13)
            )
        self.btn_pause.setIcon(get_icon("pause", size=18))
        self.btn_resume.setIcon(get_icon("play", size=18))
        self.btn_retry.setIcon(get_icon("rotate-cw", size=18))
        self.btn_cancel.setIcon(get_icon("x", size=18))
        self.btn_split.setIcon(get_icon("scissors", size=18))

    def retranslate_ui(self) -> None:
        """Updates tooltips, badges, and localized labels when language changes."""
        self.btn_pause.setToolTip(tr("pause"))
        self.btn_resume.setToolTip(tr("resume"))
        self.btn_retry.setToolTip(tr("retry"))
        self.btn_cancel.setToolTip(tr("cancel"))
        self.btn_split.setToolTip(tr("split_movie"))
        self._update_status_display()
        self._update_meta_labels()


DownloadRowWidget = DownloadRow

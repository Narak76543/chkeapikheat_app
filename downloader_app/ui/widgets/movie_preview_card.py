"""
Movie Preview Card Widget
One UI 9 styled inline card displayed directly underneath the search bar.
Shows the movie poster picture, official title, episode count, duration,
tags, synopsis, and instant download buttons without opening a modal dialog.
"""

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.image_loader import AsyncImageLoader
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.movie_card")


class MoviePreviewCard(QFrame):
    """Inline card displayed beneath the search bar showing movie metadata."""

    download_full_movie_selected = pyqtSignal(dict)
    download_episodes_selected = pyqtSignal(dict)
    dismiss_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("moviePreviewCard")
        self.movie_data: dict = {}
        self._image_loader: AsyncImageLoader | None = None

        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 14, 18, 16)
        main_layout.setSpacing(12)

        # ---------------- Top Bar: Section Title + Dismiss (✕) ----------------
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)

        header_icon = QLabel()
        header_icon.setPixmap(get_icon("film", size=18).pixmap(18, 18))
        top_bar.addWidget(header_icon)

        self.lbl_header = QLabel(tr("movie_details"))
        self.lbl_header.setObjectName("sectionHeaderLabel")
        top_bar.addWidget(self.lbl_header)

        top_bar.addStretch()

        self.btn_close = QPushButton()
        self.btn_close.setObjectName("iconButton")
        self.btn_close.setIcon(get_icon("x", size=16))
        self.btn_close.setToolTip(tr("cancel"))
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self._on_close_clicked)
        top_bar.addWidget(self.btn_close)

        main_layout.addLayout(top_bar)

        # ---------------- Content Row: Poster + Info ----------------
        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        # 1. Poster Image (110x160px with 12px rounded corners)
        self.poster_label = QLabel()
        self.poster_label.setFixedSize(110, 160)
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_label.setObjectName("downloadCard")
        self.poster_label.setText(tr("loading_preview"))
        self.poster_label.setWordWrap(True)
        content_row.addWidget(self.poster_label)

        # 2. Movie Info (Title, Badges, Synopsis, Action Buttons)
        info_col = QVBoxLayout()
        info_col.setSpacing(8)

        # Title
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("titleLabel")
        self.lbl_title.setWordWrap(True)
        info_col.addWidget(self.lbl_title)

        # Badges row: Episodes, Duration, Tags
        self.badges_layout = QHBoxLayout()
        self.badges_layout.setSpacing(8)

        self.lbl_eps_badge = QLabel()
        self.lbl_eps_badge.setObjectName("statusBadge_downloading")
        self.badges_layout.addWidget(self.lbl_eps_badge)

        self.lbl_dur_badge = QLabel()
        self.lbl_dur_badge.setObjectName("statusBadge_paused")
        self.badges_layout.addWidget(self.lbl_dur_badge)

        self.tags_container = QWidget()
        self.tags_layout = QHBoxLayout(self.tags_container)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setSpacing(6)
        self.badges_layout.addWidget(self.tags_container)

        self.badges_layout.addStretch()
        info_col.addLayout(self.badges_layout)

        # Synopsis (Compact scroll area, max 55px height)
        self.synopsis_scroll = QScrollArea()
        self.synopsis_scroll.setWidgetResizable(True)
        self.synopsis_scroll.setFixedHeight(55)
        self.synopsis_scroll.setStyleSheet("background: transparent; border: none;")

        self.lbl_intro = QLabel()
        self.lbl_intro.setObjectName("metaLabel")
        self.lbl_intro.setWordWrap(True)
        self.lbl_intro.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.synopsis_scroll.setWidget(self.lbl_intro)
        info_col.addWidget(self.synopsis_scroll)

        # Action Buttons Row
        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        lbl_qual = QLabel("Quality:")
        lbl_qual.setObjectName("metaLabel")
        lbl_qual.setStyleSheet("font-size: 13px; font-weight: 500;")
        actions_row.addWidget(lbl_qual)

        self.combo_quality = QComboBox()
        self.combo_quality.setObjectName("pillInput")
        self.combo_quality.addItems(["1080p", "720p", "480p", "360p", "Best Quality"])
        self.combo_quality.setStyleSheet("padding: 2px 10px; min-height: 32px; font-size: 13px;")
        actions_row.addWidget(self.combo_quality)

        self.btn_episodes = QPushButton(tr("download_episodes"))
        self.btn_episodes.setObjectName("pillToggle")
        self.btn_episodes.setIcon(get_icon("video", size=16))
        self.btn_episodes.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_episodes.clicked.connect(self._on_download_episodes_clicked)
        actions_row.addWidget(self.btn_episodes)

        self.btn_full_movie = QPushButton(tr("download_full_movie"))
        self.btn_full_movie.setObjectName("primaryButton")
        self.btn_full_movie.setIcon(get_icon("download", color="#FFFFFF", size=16))
        self.btn_full_movie.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_full_movie.clicked.connect(self._on_download_full_movie_clicked)
        actions_row.addWidget(self.btn_full_movie)

        actions_row.addStretch()
        info_col.addLayout(actions_row)

        content_row.addLayout(info_col, 1)
        main_layout.addLayout(content_row)

    def set_movie_data(self, data: dict) -> None:
        """Populates the card with movie metadata and starts poster download."""
        self.movie_data = data
        self.lbl_title.setText(data.get("title", "Movie"))

        # Badges
        total_eps = data.get("total_episodes", 0)
        self.lbl_eps_badge.setText(tr("episodes_count").format(count=total_eps))

        duration_mins = data.get("estimated_duration_mins", 0)
        self.lbl_dur_badge.setText(tr("estimated_duration").format(mins=duration_mins))

        # Clear previous tags
        while self.tags_layout.count() > 0:
            item = self.tags_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        tags = data.get("tags", [])
        for tag in tags[:3]:
            tag_label = QLabel(f"#{tag}")
            tag_label.setObjectName("statusBadge_queued")
            self.tags_layout.addWidget(tag_label)

        intro = data.get("intro") or ""
        self.lbl_intro.setText(intro if intro else tr("synopsis"))

        # Poster Image
        cover_url = data.get("cover_url", "")
        if cover_url:
            self.poster_label.setText(tr("loading_preview"))
            self._image_loader = AsyncImageLoader(
                url=cover_url,
                target_size=QSize(110, 160),
                corner_radius=12,
            )
            self._image_loader.image_loaded.connect(self.poster_label.setPixmap)
            self._image_loader.start()
        else:
            self.poster_label.setPixmap(get_icon("film", size=48).pixmap(48, 48))

    def _on_close_clicked(self) -> None:
        self.setVisible(False)
        self.dismiss_requested.emit()

    def _on_download_full_movie_clicked(self) -> None:
        if self.movie_data:
            data = dict(self.movie_data)
            data["quality"] = self.combo_quality.currentText()
            self.download_full_movie_selected.emit(data)

    def _on_download_episodes_clicked(self) -> None:
        if self.movie_data:
            data = dict(self.movie_data)
            data["quality"] = self.combo_quality.currentText()
            self.download_episodes_selected.emit(data)

    def update_theme_icons(self) -> None:
        """Refreshes icons on theme change."""
        self.btn_close.setIcon(get_icon("x", size=16))
        self.btn_episodes.setIcon(get_icon("video", size=16))
        self.btn_full_movie.setIcon(get_icon("download", color="#FFFFFF", size=16))

    def retranslate_ui(self) -> None:
        """Updates i18n text on language switch."""
        self.lbl_header.setText(tr("movie_details"))
        self.btn_close.setToolTip(tr("cancel"))
        self.btn_episodes.setText(tr("download_episodes"))
        self.btn_full_movie.setText(tr("download_full_movie"))

        if self.movie_data:
            total_eps = self.movie_data.get("total_episodes", 0)
            self.lbl_eps_badge.setText(tr("episodes_count").format(count=total_eps))

            duration_mins = self.movie_data.get("estimated_duration_mins", 0)
            self.lbl_dur_badge.setText(
                tr("estimated_duration").format(mins=duration_mins)
            )

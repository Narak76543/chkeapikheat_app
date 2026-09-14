"""
Movie Info Dialog Module
One UI 9 styled dialog displaying movie poster picture, title, episode count, duration,
tags, and storyline with instant download action buttons.
"""

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
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

logger = setup_logger("downloader.ui.movie_info")


class MovieInfoDialog(QDialog):
    """One UI 9 card dialog displaying detailed movie metadata and poster."""

    download_full_movie_selected = pyqtSignal(dict)
    download_episodes_selected = pyqtSignal(dict)

    def __init__(self, movie_data: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.movie_data = movie_data
        self.setWindowTitle(tr("movie_details"))
        self.setMinimumWidth(620)
        self.setMaximumWidth(700)
        self.setModal(True)

        self._image_loader: AsyncImageLoader | None = None
        self._init_ui()
        self._load_poster()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(18)

        # Dialog Header
        header_row = QHBoxLayout()
        header_icon = QLabel()
        header_icon.setPixmap(get_icon("film", size=24).pixmap(24, 24))
        header_row.addWidget(header_icon)

        self.lbl_header = QLabel(tr("movie_details"))
        self.lbl_header.setObjectName("titleLabel")
        header_row.addWidget(self.lbl_header)
        header_row.addStretch()
        main_layout.addLayout(header_row)

        # ---------------- Main Movie Info Card ----------------
        self.card = QFrame()
        self.card.setObjectName("settingsGroupCard")
        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(20)

        # 1. Left: Poster Image (140x200px)
        self.poster_label = QLabel()
        self.poster_label.setFixedSize(140, 200)
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_label.setObjectName("downloadCard")
        self.poster_label.setText(tr("loading_preview"))
        self.poster_label.setWordWrap(True)
        card_layout.addWidget(self.poster_label)

        # 2. Right: Metadata (Title, Badges, Synopsis)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(10)

        # Title
        self.lbl_title = QLabel(self.movie_data.get("title", "Movie Title"))
        self.lbl_title.setObjectName("titleLabel")
        self.lbl_title.setWordWrap(True)
        info_layout.addWidget(self.lbl_title)

        # Badges row: Total Episodes, Estimated Duration, Tags
        self.badges_layout = QHBoxLayout()
        self.badges_layout.setSpacing(8)

        total_eps = self.movie_data.get("total_episodes", 0)
        eps_text = tr("episodes_count").format(count=total_eps)
        self.lbl_eps_badge = QLabel(eps_text)
        self.lbl_eps_badge.setObjectName("statusBadge_downloading")
        self.badges_layout.addWidget(self.lbl_eps_badge)

        duration_mins = self.movie_data.get("estimated_duration_mins", 0)
        dur_text = tr("estimated_duration").format(mins=duration_mins)
        self.lbl_dur_badge = QLabel(dur_text)
        self.lbl_dur_badge.setObjectName("statusBadge_paused")
        self.badges_layout.addWidget(self.lbl_dur_badge)

        tags = self.movie_data.get("tags", [])
        for tag in tags[:3]:
            tag_label = QLabel(f"#{tag}")
            tag_label.setObjectName("statusBadge_queued")
            self.badges_layout.addWidget(tag_label)

        self.badges_layout.addStretch()
        info_layout.addLayout(self.badges_layout)

        # Synopsis Section
        self.lbl_synopsis_title = QLabel(tr("synopsis"))
        self.lbl_synopsis_title.setObjectName("sectionHeaderLabel")
        info_layout.addWidget(self.lbl_synopsis_title)

        # Scrollable synopsis text
        synopsis_scroll = QScrollArea()
        synopsis_scroll.setWidgetResizable(True)
        synopsis_scroll.setFixedHeight(95)
        synopsis_scroll.setStyleSheet("background: transparent; border: none;")

        self.lbl_intro = QLabel(
            self.movie_data.get("intro") or "No synopsis available."
        )
        self.lbl_intro.setObjectName("metaLabel")
        self.lbl_intro.setWordWrap(True)
        self.lbl_intro.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        synopsis_scroll.setWidget(self.lbl_intro)
        info_layout.addWidget(synopsis_scroll)

        card_layout.addLayout(info_layout, 1)
        main_layout.addWidget(self.card)

        # ---------------- Bottom Action Buttons ----------------
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        self.btn_cancel = QPushButton(tr("cancel"))
        self.btn_cancel.setObjectName("pillToggle")
        self.btn_cancel.clicked.connect(self.reject)
        bottom_row.addWidget(self.btn_cancel)

        bottom_row.addStretch()

        # Download Episodes button (1-3 preview)
        self.btn_episodes = QPushButton(tr("download_episodes"))
        self.btn_episodes.setObjectName("pillToggle")
        self.btn_episodes.setIcon(get_icon("video", size=16))
        self.btn_episodes.clicked.connect(self._on_download_episodes_clicked)
        bottom_row.addWidget(self.btn_episodes)

        # Download Full Movie (1080p)
        self.btn_full_movie = QPushButton(tr("download_full_movie"))
        self.btn_full_movie.setObjectName("primaryButton")
        self.btn_full_movie.setIcon(get_icon("download", color="#FFFFFF", size=18))
        self.btn_full_movie.clicked.connect(self._on_download_full_movie_clicked)
        bottom_row.addWidget(self.btn_full_movie)

        main_layout.addLayout(bottom_row)

    def _load_poster(self) -> None:
        cover_url = self.movie_data.get("cover_url")
        if not cover_url:
            self.poster_label.setPixmap(get_icon("film", size=64).pixmap(64, 64))
            return

        self._image_loader = AsyncImageLoader(
            url=cover_url,
            target_size=QSize(140, 200),
            corner_radius=12,
        )
        self._image_loader.image_loaded.connect(self.poster_label.setPixmap)
        self._image_loader.start()

    def _on_download_full_movie_clicked(self) -> None:
        logger.info(
            f"User selected Download Full Movie for '{self.movie_data.get('title')}'"
        )
        self.download_full_movie_selected.emit(self.movie_data)
        self.accept()

    def _on_download_episodes_clicked(self) -> None:
        logger.info(
            f"User selected Download Episodes for '{self.movie_data.get('title')}'"
        )
        self.download_episodes_selected.emit(self.movie_data)
        self.accept()

    def retranslate_ui(self) -> None:
        """Updates translated strings on language switch."""
        self.setWindowTitle(tr("movie_details"))
        self.lbl_header.setText(tr("movie_details"))
        self.lbl_synopsis_title.setText(tr("synopsis"))
        self.btn_cancel.setText(tr("cancel"))
        self.btn_episodes.setText(tr("download_episodes"))
        self.btn_full_movie.setText(tr("download_full_movie"))

        total_eps = self.movie_data.get("total_episodes", 0)
        self.lbl_eps_badge.setText(tr("episodes_count").format(count=total_eps))

        duration_mins = self.movie_data.get("estimated_duration_mins", 0)
        self.lbl_dur_badge.setText(tr("estimated_duration").format(mins=duration_mins))

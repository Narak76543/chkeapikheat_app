"""
Metadata Card Widget
Compact horizontal card showing search result metadata: poster thumbnail,
title, tag pills, clamped synopsis, and an "Add" download button.

This widget is data-source agnostic — it only renders whatever model is
passed to it via set_data().
"""

from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from downloader_app.core.config import get_theme
from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.metadata_card")


@dataclass
class MetadataModel:
    """Plain data model for the metadata card — no data-source assumptions."""

    title: str = ""
    tags: list[str] = field(default_factory=list)
    synopsis: str = ""
    thumbnail_path: str | None = None
    series_id: str = ""
    raw_url: str = ""
    cover_url: str = ""
    duration: str = ""
    estimated_duration_mins: int = 0
    total_episodes: int = 0
    vid_list: list = field(default_factory=list)
    selected_quality: str = "1080p"


# Tag style types map tag index to a QSS object name for themed coloring.
# Cycles through accent / warning / neutral styles.
_TAG_STYLES = ["metadataTagAccent", "metadataTagWarning", "metadataTagNeutral"]


class MetadataCard(QFrame):
    """Compact horizontal metadata card with poster, info, Add button, and Download Episodes button."""

    add_requested = pyqtSignal(MetadataModel)
    download_episodes_requested = pyqtSignal(MetadataModel)
    title_translated = pyqtSignal(str)  # Emits new translated title string

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metadataCard")
        self._model: MetadataModel | None = None
        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    @property
    def model(self) -> MetadataModel | None:
        return self._model

    def _init_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(14)

        # ── Left: Poster Thumbnail ──
        self.poster_label = QLabel()
        self.poster_label.setObjectName("metadataPoster")
        self.poster_label.setFixedSize(64, 86)
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_label.setScaledContents(False)
        # Show placeholder icon by default
        self._set_placeholder_poster()
        root.addWidget(self.poster_label)

        # ── Center: Title + Translate Action + Tags + Synopsis ──
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        self.title_label = QLabel()
        self.title_label.setObjectName("metadataTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        title_row.addWidget(self.title_label, 1)

        self.btn_translate = QPushButton()
        self.btn_translate.setObjectName("pillToggle")
        self.btn_translate.setIcon(get_icon("rotate-cw", size=14))
        self.btn_translate.setToolTip(tr("translate_title"))
        self.btn_translate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_translate.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        self.btn_translate.setText("EN→KM")
        self.btn_translate.clicked.connect(self._on_translate_clicked)
        title_row.addWidget(self.btn_translate)

        info_layout.addLayout(title_row)

        # Tag pills row
        self.tags_widget = QWidget()
        self.tags_layout = QHBoxLayout(self.tags_widget)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setSpacing(6)
        self.tags_layout.addStretch()
        info_layout.addWidget(self.tags_widget)

        # Synopsis (2-line clamp)
        self.synopsis_label = QLabel()
        self.synopsis_label.setObjectName("metadataSynopsis")
        self.synopsis_label.setWordWrap(True)
        self.synopsis_label.setMaximumHeight(42)
        self.synopsis_label.setTextFormat(Qt.TextFormat.PlainText)
        self.synopsis_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        info_layout.addWidget(self.synopsis_label)

        root.addLayout(info_layout, 1)

        # ── Right: Action Buttons (Quality + Add Download + Download Episodes) ──
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)
        btn_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.combo_quality = QComboBox()
        self.combo_quality.setObjectName("pillInput")
        self.combo_quality.addItems(["1080p", "720p", "480p", "360p", "Best Quality"])
        self.combo_quality.setStyleSheet("padding: 2px 8px; min-height: 28px; font-size: 12px;")
        btn_col.addWidget(self.combo_quality)

        self.btn_add = QPushButton(tr("add_download"))
        self.btn_add.setObjectName("metadataAddButton")
        self.btn_add.setIcon(get_icon("download", color="#FFFFFF", size=16))
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self._on_add_clicked)
        btn_col.addWidget(self.btn_add)

        self.btn_episodes = QPushButton(tr("download_episodes"))
        self.btn_episodes.setObjectName("secondaryButton")
        self.btn_episodes.setIcon(get_icon("film", size=16))
        self.btn_episodes.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_episodes.clicked.connect(self._on_episodes_clicked)
        btn_col.addWidget(self.btn_episodes)

        root.addLayout(btn_col)

    def _set_placeholder_poster(self) -> None:
        """Shows a muted generic image icon as the poster placeholder."""
        icon = get_icon("file-video", color="#6B6B6F", size=28)
        pixmap = icon.pixmap(28, 28)
        self.poster_label.setPixmap(pixmap)

    def set_data(self, model: MetadataModel) -> None:
        """Populates the card with the given metadata model."""
        self._model = model

        # Title
        self.title_label.setText(model.title)

        # Poster
        if model.thumbnail_path:
            pm = QPixmap(model.thumbnail_path)
            if not pm.isNull():
                self.poster_label.setPixmap(
                    pm.scaled(
                        64,
                        86,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                self._set_placeholder_poster()
        elif model.cover_url:
            from PyQt6.QtCore import QSize

            from downloader_app.utils.image_loader import AsyncImageLoader

            self._image_loader = AsyncImageLoader(
                model.cover_url, target_size=QSize(64, 86), corner_radius=10
            )
            self._image_loader.image_loaded.connect(self.poster_label.setPixmap)
            self._image_loader.start()
        else:
            self._set_placeholder_poster()

        # Tags & Duration
        self._rebuild_tags(model.tags, model.duration)

        # Synopsis (2-line clamp via max-height)
        self.synopsis_label.setText(model.synopsis)

        self.setVisible(True)

    def clear_data(self) -> None:
        """Clears the card and hides it."""
        self._model = None
        self.title_label.setText("")
        self.synopsis_label.setText("")
        self._set_placeholder_poster()
        self._clear_tags()
        self.setVisible(False)

    def _rebuild_tags(self, tags: list[str], duration: str = "") -> None:
        """Rebuilds tag pill labels cycling through accent/warning/neutral styles."""
        self._clear_tags()

        if duration:
            dur_pill = QWidget()
            dur_pill.setObjectName("metadataTagAccentPill")
            dur_layout = QHBoxLayout(dur_pill)
            dur_layout.setContentsMargins(6, 2, 8, 2)
            dur_layout.setSpacing(4)

            icon_color = "#93C5FD" if get_theme() == "dark" else "#1259C3"
            icon_lbl = QLabel()
            icon_lbl.setPixmap(
                get_icon("clock", color=icon_color, size=13).pixmap(13, 13)
            )
            dur_layout.addWidget(icon_lbl)

            text_lbl = QLabel(duration)
            dur_layout.addWidget(text_lbl)

            self.tags_layout.insertWidget(self.tags_layout.count() - 1, dur_pill)

        for i, tag_text in enumerate(tags):
            pill = QLabel(tag_text)
            style_name = _TAG_STYLES[i % len(_TAG_STYLES)]
            pill.setObjectName(style_name)
            pill.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            # Insert before the trailing stretch
            self.tags_layout.insertWidget(self.tags_layout.count() - 1, pill)

    def _clear_tags(self) -> None:
        """Removes all tag pill widgets."""
        while self.tags_layout.count() > 1:  # keep the trailing stretch
            item = self.tags_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _on_add_clicked(self) -> None:
        """Emits add_requested with the current model."""
        if self._model:
            self._model.selected_quality = self.combo_quality.currentText()
            logger.info(f"Add requested for: {self._model.title} ({self._model.selected_quality})")
            self.add_requested.emit(self._model)

    def _on_episodes_clicked(self) -> None:
        """Emits download_episodes_requested with the current model."""
        if self._model:
            self._model.selected_quality = self.combo_quality.currentText()
            logger.info(f"Download episodes requested for: {self._model.title} ({self._model.selected_quality})")
            self.download_episodes_requested.emit(self._model)

    def _on_translate_clicked(self) -> None:
        """Triggers translation of the current title into Khmer."""
        if not self._model or not self._model.title:
            return

        from downloader_app.core.translator import TranslationWorker

        self.btn_translate.setEnabled(False)
        self.btn_translate.setText(tr("translating"))

        self._trans_worker = TranslationWorker(
            title=self._model.title, target_lang="km", parent=self
        )
        self._trans_worker.finished.connect(self._on_translation_finished)
        self._trans_worker.start()

    def _on_translation_finished(self, translated_title: str) -> None:
        """Updates model and UI label when title translation completes."""
        self.btn_translate.setEnabled(True)
        self.btn_translate.setText("EN→KM")
        if self._model:
            self._model.title = translated_title
            self.title_label.setText(translated_title)
            self.title_translated.emit(translated_title)

    def update_theme_icons(self) -> None:
        """Refreshes icons when the theme changes."""
        self.btn_add.setIcon(get_icon("download", color="#FFFFFF", size=16))
        self.btn_episodes.setIcon(get_icon("film", size=16))
        self.btn_translate.setIcon(get_icon("rotate-cw", size=14))
        if not self._model or not self._model.thumbnail_path:
            self._set_placeholder_poster()

    def retranslate_ui(self) -> None:
        """Updates translatable labels on language change."""
        self.btn_add.setText(tr("add_download"))
        self.btn_episodes.setText(tr("download_episodes"))
        self.btn_translate.setToolTip(tr("translate_title"))

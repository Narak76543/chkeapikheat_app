"""
Downloads View
Hosts the URL input bar, metadata card, download list, and status bar
as a unified view for the QStackedWidget in the main window.
"""

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from downloader_app.models.download_task import TaskStatus
from downloader_app.ui.widgets.download_list import DownloadList
from downloader_app.ui.widgets.metadata_card import MetadataCard, MetadataModel
from downloader_app.ui.widgets.url_input_bar import UrlInputBar
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.downloads_view")

# Placeholder model for visual testing — will be replaced by real search results
_PLACEHOLDER_MODEL = MetadataModel(
    title="Spirited Away (千と千尋の神隠し)",
    tags=["63 Episodes", "~126 mins", "#Animation"],
    synopsis=(
        "A young girl becomes trapped in a mysterious spirit world and must "
        "find a way to free herself and her parents. A timeless tale of "
        "courage, kindness, and growing up."
    ),
    thumbnail_path=None,
)


class DownloadsView(QWidget):
    """View containing the URL input bar, metadata card, download list, and status bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Title
        self.title_label = QLabel(tr("downloads_title"))
        self.title_label.setObjectName("titleLabel")
        layout.addWidget(self.title_label)

        # URL Input Bar
        self.url_input_bar = UrlInputBar()
        layout.addWidget(self.url_input_bar)

        # Search / Resolution Loading Card (hidden by default, shown while fetching/resolving)
        from PyQt6.QtWidgets import QFrame, QProgressBar

        self.search_loading_card = QFrame()
        self.search_loading_card.setObjectName("sidebarCard")
        search_card_layout = QVBoxLayout(self.search_loading_card)
        search_card_layout.setContentsMargins(14, 10, 14, 12)
        search_card_layout.setSpacing(8)

        msg_row = QHBoxLayout()
        msg_row.setSpacing(8)

        self.search_icon_label = QLabel()
        self.search_icon_label.setFixedSize(18, 18)
        msg_row.addWidget(self.search_icon_label)

        self.search_status_label = QLabel()
        self.search_status_label.setObjectName("metaLabel")
        self.search_status_label.setStyleSheet("color: #4FA0FF; font-weight: 400;")
        msg_row.addWidget(self.search_status_label, 1)

        search_card_layout.addLayout(msg_row)

        self.search_progress_bar = QProgressBar()
        self.search_progress_bar.setObjectName("thickProgressBar")
        self.search_progress_bar.setRange(0, 0)  # Smooth animated pulse
        self.search_progress_bar.setTextVisible(False)
        search_card_layout.addWidget(self.search_progress_bar)

        self.search_loading_card.setVisible(False)
        layout.addWidget(self.search_loading_card)

        # Metadata Card (hidden by default, shown when search result is set)
        self.metadata_card = MetadataCard()
        self.metadata_card.setVisible(False)
        layout.addWidget(self.metadata_card)

        # Inline Episode Selection Card Container
        self.episodes_card_container = QWidget()
        self.episodes_card_layout = QVBoxLayout(self.episodes_card_container)
        self.episodes_card_layout.setContentsMargins(0, 0, 0, 0)
        self.episodes_card_container.setVisible(False)
        layout.addWidget(self.episodes_card_container)

        # Download List (scrollable cards)
        self.download_list = DownloadList()
        layout.addWidget(self.download_list, 1)

        # Bottom Status Bar
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(4, 0, 4, 0)

        self.status_info_label = QLabel()
        self.status_info_label.setObjectName("metaLabel")
        self.update_status_bar()
        bottom_bar.addWidget(self.status_info_label)
        bottom_bar.addStretch()

        self.developer_label = QLabel("Developer : Sarat Narak")
        self.developer_label.setObjectName("metaLabel")
        bottom_bar.addWidget(self.developer_label)

        layout.addLayout(bottom_bar)

    def show_search_loading(self, message: str, icon_name: str = "search") -> None:
        """Shows the loading indicator card with Lucide icon and detailed status message."""
        from downloader_app.ui.resources.icon_helper import get_icon

        icon = get_icon(icon_name, color="#4FA0FF", size=18)
        self.search_icon_label.setPixmap(icon.pixmap(18, 18))
        self.search_status_label.setText(message)
        self.search_loading_card.setVisible(True)

    def hide_search_loading(self) -> None:
        """Hides the loading indicator card."""
        self.search_loading_card.setVisible(False)

    def show_metadata(self, model: MetadataModel) -> None:
        """Shows the metadata card with the given model."""
        self.hide_search_loading()
        self.hide_episode_selection()
        self.metadata_card.set_data(model)

    def hide_metadata(self) -> None:
        """Hides and clears the metadata card."""
        self.hide_search_loading()
        self.metadata_card.clear_data()
        self.hide_episode_selection()

    def show_episode_selection(self, movie_data: dict):
        """Displays inline EpisodeSelectionCard directly inside the view."""
        self.hide_episode_selection()
        from downloader_app.ui.widgets.episode_selection_card import EpisodeSelectionCard

        self.metadata_card.setVisible(False)
        self.download_list.setVisible(False)

        card = EpisodeSelectionCard(movie_data, parent=self)
        card.closed.connect(self.hide_episode_selection)
        self.episodes_card_layout.addWidget(card)
        self.episodes_card_container.setVisible(True)
        return card

    def hide_episode_selection(self) -> None:
        """Hides and clears inline episode selection card."""
        while self.episodes_card_layout.count() > 0:
            item = self.episodes_card_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self.episodes_card_container.setVisible(False)
        if hasattr(self, "metadata_card") and getattr(self.metadata_card, "_model", None):
            self.metadata_card.setVisible(True)
        self.download_list.setVisible(True)

    def update_theme_icons(self) -> None:
        """Refreshes all theme-dependent icons in downloads view."""
        self.url_input_bar.update_theme_icons()
        self.download_list.update_theme_icons()

    def show_placeholder_metadata(self) -> None:
        """Dev-only: shows the hardcoded placeholder model for visual testing."""
        logger.info("Showing placeholder metadata card for visual testing")
        self.show_metadata(_PLACEHOLDER_MODEL)

    def update_status_bar(self) -> None:
        """Updates the bottom status label with active/total download counts."""
        total_tasks = len(self.download_list._rows)
        active_tasks = sum(
            1
            for r in self.download_list._rows.values()
            if r.task.status == TaskStatus.DOWNLOADING
        )
        self.status_info_label.setText(
            f"{tr('active_downloads')}: {active_tasks}  •  {tr('total')}: {total_tasks}"
        )

    def retranslate_ui(self) -> None:
        """Retranslates all labels on language change."""
        self.title_label.setText(tr("downloads_title"))
        self.update_status_bar()

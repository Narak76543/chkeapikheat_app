"""UI Widgets package initialization."""

from downloader_app.ui.widgets.download_list import DownloadListWidget
from downloader_app.ui.widgets.download_row import DownloadRowWidget
from downloader_app.ui.widgets.episode_selector_dialog import EpisodeSelectorDialog
from downloader_app.ui.widgets.metadata_card import MetadataCard
from downloader_app.ui.widgets.movie_preview_card import MoviePreviewCard
from downloader_app.ui.widgets.sidebar_panel import SidebarPanel
from downloader_app.ui.widgets.sidebar_rail import SidebarRail
from downloader_app.ui.widgets.url_input_bar import UrlInputBarWidget

__all__ = [
    "DownloadListWidget",
    "DownloadRowWidget",
    "EpisodeSelectorDialog",
    "MetadataCard",
    "MoviePreviewCard",
    "SidebarPanel",
    "SidebarRail",
    "UrlInputBarWidget",
]

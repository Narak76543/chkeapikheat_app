"""
Main Window Module
One UI 9 inspired desktop download manager interface with left sidebar rail,
QStackedWidget (Downloads / Split Tool), and collapsible right sidebar panel.
Wired to real QueueManager + DownloadWorker for actual downloading.
"""

from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from downloader_app.core.config import AppConfig, get_theme
from downloader_app.core.config import set_language as save_language
from downloader_app.core.config import set_theme as save_theme
from downloader_app.core.queue_manager import QueueManager
from downloader_app.models.download_task import DownloadTask
from downloader_app.ui.views.downloads_view import DownloadsView
from downloader_app.ui.views.dubbing_tool_view import DubbingToolView
from downloader_app.ui.views.split_tool_view import SplitToolView
from downloader_app.ui.widgets.sidebar_panel import SidebarPanel
from downloader_app.ui.widgets.sidebar_rail import SidebarRail
from downloader_app.utils.i18n import get_i18n_manager, set_language, tr
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.main_window")


class MainWindow(QMainWindow):
    """One UI 9 main window with left icon rail, stacked views, and right sidebar."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr("app_title"))
        logo_candidates = [
            Path(__file__).parent / "resources" / "app-logo.png",
            Path(__file__).parent.parent / "resources" / "app-logo.png",
            Path(__file__).parent.parent.parent / "app-logo.png",
        ]
        for cand in logo_candidates:
            if cand.exists():
                self.setWindowIcon(QIcon(str(cand.resolve())))
                break
        self.resize(1280, 800)
        self.setMinimumSize(800, 560)

        # ── Real Queue Manager (handles actual downloads) ──
        config = AppConfig.load()
        # Use 512KB chunks for faster throughput (default was 64KB)
        config.chunk_size_bytes = 512 * 1024
        self.queue_manager = QueueManager(config)
        self.queue_manager.task_added.connect(self._on_task_added)
        self.queue_manager.task_updated.connect(self._on_task_updated)
        self.queue_manager.task_removed.connect(self._on_task_removed)
        self.queue_manager.queue_counts_changed.connect(self._on_counts_changed)

        self._init_ui()
        # Ensure active theme QSS and view icons are fully applied on initial startup
        self.apply_theme(get_theme())
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        # Central widget container
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        # Root horizontal layout: Rail | Stacked Views | (Optional Right Sidebar)
        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Left Sidebar Rail (64px) ──
        self.sidebar_rail = SidebarRail()
        self.sidebar_rail.view_switched.connect(self._on_view_switched)
        self.sidebar_rail.theme_toggled.connect(self.apply_theme)
        self.sidebar_rail.settings_requested.connect(self._toggle_settings)
        root_layout.addWidget(self.sidebar_rail)

        # ── Central Stacked Views ──
        self.view_stack = QStackedWidget()

        # Index 0: Downloads View
        self.downloads_view = DownloadsView()
        self.downloads_view.url_input_bar.url_submitted.connect(
            self._handle_url_submitted
        )
        self.downloads_view.url_input_bar.text_changed_debounced.connect(
            self._handle_title_debounced
        )
        self.downloads_view.url_input_bar.cleared.connect(self._handle_input_cleared)
        self.downloads_view.download_list.pause_requested.connect(
            self._on_pause_requested
        )
        self.downloads_view.download_list.resume_requested.connect(
            self._on_resume_requested
        )
        self.downloads_view.download_list.cancel_requested.connect(
            self._on_cancel_requested
        )
        self.downloads_view.download_list.retry_requested.connect(
            self._on_retry_requested
        )
        self.downloads_view.download_list.split_requested.connect(
            self._on_split_requested
        )
        self.downloads_view.metadata_card.add_requested.connect(
            self._on_metadata_card_add_requested
        )
        self.downloads_view.metadata_card.download_episodes_requested.connect(
            self._on_metadata_card_episodes_requested
        )
        self.view_stack.addWidget(self.downloads_view)

        # Index 1: Split Tool View
        self.split_tool_view = SplitToolView()
        self.split_tool_view.back_requested.connect(
            lambda: self.sidebar_rail.set_active_index(0)
        )
        self.view_stack.addWidget(self.split_tool_view)

        # Index 2: AI Voice Dubber View
        self.dubbing_tool_view = DubbingToolView()
        self.dubbing_tool_view.back_requested.connect(
            lambda: self.sidebar_rail.set_active_index(0)
        )
        self.view_stack.addWidget(self.dubbing_tool_view)

        root_layout.addWidget(self.view_stack, 1)

        # ── Right Collapsible Sidebar Panel ──
        self.sidebar = SidebarPanel(self)
        self.sidebar.setVisible(False)
        self.sidebar.theme_changed.connect(self.apply_theme)
        self.sidebar.language_changed.connect(self.apply_language)
        self.sidebar.download_full_movie_selected.connect(
            self._queue_full_movie_download
        )
        self.sidebar.download_episodes_selected.connect(self._queue_episodes_download)
        root_layout.addWidget(self.sidebar)

    # ── Rail Navigation ──

    def _on_view_switched(self, index: int) -> None:
        """Switches the central QStackedWidget to the selected view."""
        self.view_stack.setCurrentIndex(index)
        logger.info(f"Switched to view index {index}")

    def _toggle_settings(self) -> None:
        """Opens the One UI 9 Settings Dialog."""
        from downloader_app.ui.widgets.settings_dialog import SettingsDialog
        dlg = SettingsDialog(
            parent=self,
            on_theme_changed=self.apply_theme,
            on_language_changed=self.apply_language,
        )
        dlg.exec()

    def _on_split_requested(self, video_path: str) -> None:
        """Opens Video Splitter in the sidebar with the specified video path."""
        self.sidebar.open_video_splitter(video_path)

    # ── Theme & Language ──

    def apply_theme(self, theme_name: str) -> None:
        """Instantly applies light or dark theme QSS across the entire application."""
        save_theme(theme_name)
        qss_filename = f"theme_{theme_name}.qss"
        qss_path = Path(__file__).parent / "resources" / qss_filename
        if qss_path.exists():
            try:
                with open(qss_path, "r", encoding="utf-8") as f:
                    qss_content = f.read()

                icons_dir_posix = (Path(__file__).parent / "resources" / "icons").as_posix()
                qss_content = qss_content.replace("{ICON_DIR}", icons_dir_posix)

                app = QApplication.instance()
                if app:
                    app.setStyleSheet(qss_content)

                # Refresh all icons to match the new theme colors
                self.sidebar_rail.set_current_theme(theme_name)
                self.sidebar_rail.update_theme_icons()
                self.downloads_view.update_theme_icons()
                self.split_tool_view.update_theme_icons()
                self.dubbing_tool_view.update_theme_icons()
                self.sidebar.update_theme_icons()

                logger.info(f"Swapped theme to '{theme_name}'")
            except OSError as e:
                logger.warning(f"Failed to load theme {theme_name}: {e}")

    def apply_language(self, lang_code: str) -> None:
        """Switches active i18n language and notifies all components."""
        save_language(lang_code)
        set_language(lang_code)

    # ── Worker Thread Lifetime Tracking ──

    def _track_worker(self, worker) -> None:
        """Stores a reference to a worker thread so Python GC does not destroy it while running."""
        from PyQt6.QtCore import QTimer

        if not hasattr(self, "_active_workers"):
            self._active_workers = []
        self._active_workers.append(worker)
        worker.finished.connect(
            lambda: QTimer.singleShot(2000, lambda: self._untrack_worker(worker))
        )

    def _untrack_worker(self, worker) -> None:
        if hasattr(self, "_active_workers") and worker in self._active_workers:
            self._active_workers.remove(worker)

    # ── Movie Metadata Fetching ──

    def _handle_title_debounced(self, text: str) -> None:
        """Auto-fetches movie info as user types title."""
        self._start_metadata_fetch(text, auto_fix=True)

    def _handle_url_submitted(self, url: str) -> None:
        """Handles Enter / Add Download: queue directly if URL, else fetch metadata."""
        stripped = url.strip()
        if stripped.startswith(("http://", "https://")):
            # Direct URL — queue it immediately via QueueManager
            self._queue_url_download(stripped)
        else:
            # Treat as movie title search
            self._start_metadata_fetch(stripped, auto_fix=True)

    def _queue_url_download(self, url: str) -> None:
        """Queues a direct URL download through the real QueueManager."""
        dest = self.queue_manager.config.download_dir
        task = self.queue_manager.add(url, destination_path=dest)
        logger.info(f"Queued real download: {task.id} → {url}")
        self.downloads_view.url_input_bar.clear()

    def _start_metadata_fetch(self, query: str, auto_fix: bool = True) -> None:
        logger.info(f"Fetching movie for: {query}")
        msg = tr("searching_movie").format(title=query)
        self.downloads_view.show_search_loading(msg, icon_name="search")

        from downloader_app.core.metadata_fetcher import MovieMetadataFetcherWorker

        worker = MovieMetadataFetcherWorker(query, parent=self)
        self._track_worker(worker)
        worker.metadata_ready.connect(
            lambda data: self._show_movie_details(data, auto_fix=auto_fix)
        )
        worker.error.connect(lambda _: self._on_metadata_error(query))
        worker.start()

    def _show_movie_details(self, data: dict, auto_fix: bool = True) -> None:
        """Shows movie details in the sidebar and auto-fixes the title."""
        self.downloads_view.hide_search_loading()
        self.downloads_view.update_status_bar()
        if auto_fix:
            canonical_title = data.get("title")
            if (
                canonical_title
                and canonical_title != self.downloads_view.url_input_bar.text()
            ):
                logger.info(f"Auto-fixing search bar title to: {canonical_title}")
                self.downloads_view.url_input_bar.set_text(canonical_title)

        # Show MetadataCard directly in DownloadsView (no right sidebar popup)
        from downloader_app.ui.widgets.metadata_card import MetadataModel

        model = MetadataModel(
            title=data.get("title", ""),
            tags=data.get("tags", []),
            synopsis=data.get("intro", ""),
            thumbnail_path=None,
            series_id=data.get("series_id", ""),
            raw_url=data.get("raw_url", ""),
            cover_url=data.get("cover_url", ""),
            duration=data.get("duration_str", ""),
            estimated_duration_mins=data.get("estimated_duration_mins", 0),
            total_episodes=data.get("total_episodes", 0),
            vid_list=data.get("vid_list", []),
        )
        self.downloads_view.show_metadata(model)

    def _handle_input_cleared(self) -> None:
        """Hides metadata card when search input is cleared."""
        self.downloads_view.hide_metadata()
        if self.sidebar.isVisible() and self.sidebar.stack.currentIndex() == 2:
            self.sidebar.close_sidebar()

    def _on_metadata_error(self, query: str) -> None:
        self.downloads_view.hide_search_loading()
        self.downloads_view.update_status_bar()
        if query.startswith(("http://", "https://")):
            self._queue_url_download(query)

    def _on_metadata_card_add_requested(self, model) -> None:
        """Called when Add button on MetadataCard is clicked."""
        data = {
            "series_id": model.series_id,
            "title": model.title,
            "cover_url": model.cover_url,
            "raw_url": model.raw_url,
            "duration": model.duration,
            "estimated_duration_mins": model.estimated_duration_mins,
            "quality": getattr(model, "selected_quality", "1080p"),
        }
        self._queue_full_movie_download(data)

    def _on_metadata_card_episodes_requested(self, model) -> None:
        """Called when Download Episodes button on MetadataCard is clicked."""
        data = {
            "series_id": model.series_id,
            "title": model.title,
            "cover_url": model.cover_url,
            "raw_url": model.raw_url,
            "duration": model.duration,
            "estimated_duration_mins": model.estimated_duration_mins,
            "total_episodes": model.total_episodes,
            "vid_list": model.vid_list,
            "intro": model.synopsis,
            "quality": getattr(model, "selected_quality", "1080p"),
        }
        self._queue_episodes_download(data)

    # ── Download Queueing (Movie sidebar & card actions) ──

    def _resolve_and_queue_ytdlp_full_movie(
        self,
        title: str,
        cover_url: str = "",
        duration: str = "",
        expected_mins: int = 0,
        quality: str = "1080p",
    ) -> None:
        """Searches for full movie compilation video URL and queues it via QueueManager."""
        from downloader_app.core.metadata_fetcher import FullMovieResolverWorker

        msg = tr("resolving_full_movie").format(title=title)
        self.downloads_view.show_search_loading(msg, icon_name="film")

        worker = FullMovieResolverWorker(
            title=title,
            cover_url=cover_url,
            expected_duration_mins=expected_mins,
            parent=self,
        )
        self._track_worker(worker)

        def on_resolved(res: dict):
            self.downloads_view.hide_search_loading()
            full_url = res.get("raw_url")
            if full_url:
                full_title = res.get("title") or title
                dur_str = res.get("duration_str") or duration
                logger.info(f"Queuing full movie compilation from yt-dlp: {full_url} (Quality: {quality})")
                self.queue_manager.add(
                    url=full_url,
                    filename=f"{full_title} [Full Movie].mp4",
                    poster_url=res.get("cover_url") or cover_url,
                    duration=dur_str,
                    quality=quality,
                )
                self.downloads_view.update_status_bar()

        def on_error(msg_err: str):
            self.downloads_view.hide_search_loading()
            logger.debug(f"Full movie compilation search result: {msg_err}")

        worker.movie_resolved.connect(on_resolved)
        worker.error.connect(on_error)
        worker.start()

    def _queue_full_movie_download(self, data: dict) -> None:
        """Queues a full movie download via QueueManager with requested resolution quality."""
        title = data.get("title", "movie")
        cover_url = data.get("cover_url", "")
        raw_url = data.get("raw_url", "")
        duration = data.get("duration") or data.get("duration_str", "")
        expected_mins = data.get("estimated_duration_mins", 0)
        quality = data.get("quality", "1080p")

        if raw_url:
            self.queue_manager.add(
                raw_url,
                filename=f"{title}.mp4",
                poster_url=cover_url,
                duration=duration,
                quality=quality,
            )
        else:
            self._resolve_and_queue_ytdlp_full_movie(
                title, cover_url, duration=duration, expected_mins=expected_mins, quality=quality
            )

        self.sidebar.close_sidebar()

    def _queue_episodes_download(self, data: dict) -> None:
        """Opens inline episode selection card and queues download of each selected episode individually into the queue."""
        from pathlib import Path
        from downloader_app.utils.validators import sanitize_filename

        card = self.downloads_view.show_episode_selection(data)

        def on_episodes_confirmed(res: dict):
            title = res.get("selected_title") or res.get("title", "movie")
            clean_title = sanitize_filename(title)
            cover_url = res.get("cover_url", "")
            raw_url = res.get("raw_url", "")
            series_id = res.get("series_id", "")
            selected_eps = res.get("selected_episodes", [])
            quality = res.get("quality", "1080p")

            if not raw_url and series_id:
                raw_url = f"https://hongguoduanju.com/detail?series_id={series_id}"

            if not selected_eps or not raw_url:
                return

            dest_folder = str(Path(self.queue_manager.config.download_dir) / f"{clean_title} (Episodes)")

            logger.info(f"Queuing {len(selected_eps)} individual episode tasks for '{title}' into {dest_folder} (Quality: {quality})")
            for idx in selected_eps:
                ep_url = f"{raw_url}#ep_{idx}"
                filename = f"{clean_title} - Episode {idx:02d}.mp4"
                self.queue_manager.add(
                    url=ep_url,
                    destination_path=dest_folder,
                    filename=filename,
                    poster_url=cover_url,
                    duration="",
                    single_ep_index=idx,
                    quality=quality,
                )
            self.downloads_view.hide_episode_selection()

        card.episodes_selected.connect(on_episodes_confirmed)
        self.sidebar.close_sidebar()

    # ── QueueManager Signal Handlers ──

    def _on_task_added(self, task: DownloadTask) -> None:
        """Called when QueueManager adds a new task — creates the UI row."""
        self.downloads_view.download_list.add_task(task)
        self.downloads_view.update_status_bar()

    def _on_task_updated(self, task: DownloadTask) -> None:
        """Called when QueueManager updates a task — refreshes the UI row."""
        self.downloads_view.download_list.update_task(task)
        self.downloads_view.update_status_bar()

    def _on_task_removed(self, task_id: str) -> None:
        """Called when QueueManager removes a task — removes the UI row."""
        self.downloads_view.download_list.remove_task(task_id)
        self.downloads_view.update_status_bar()

    def _on_counts_changed(self, active: int, total: int) -> None:
        """Updates status bar when queue counts change."""
        self.downloads_view.status_info_label.setText(
            f"{tr('active_downloads')}: {active}  •  {tr('total')}: {total}"
        )

    # ── Row Action Handlers (wired to real QueueManager) ──

    def _on_pause_requested(self, task_id: str) -> None:
        logger.info(f"Pause requested for task {task_id}")
        self.queue_manager.pause(task_id)

    def _on_resume_requested(self, task_id: str) -> None:
        logger.info(f"Resume requested for task {task_id}")
        self.queue_manager.resume(task_id)

    def _on_retry_requested(self, task_id: str) -> None:
        logger.info(f"Retry requested for task {task_id}")
        self.queue_manager.retry(task_id)

    def _on_cancel_requested(self, task_id: str) -> None:
        logger.info(f"Cancel requested for task {task_id}")
        self.queue_manager.remove(task_id)
        self.downloads_view.update_status_bar()

    # ── Cleanup ──

    def closeEvent(self, event) -> None:
        """Gracefully stops all workers before closing the app."""
        if self.queue_manager.has_active_downloads():
            logger.info("Stopping active downloads before exit...")
            self.queue_manager.cleanup_all()
        event.accept()

    # ── Retranslation ──

    def retranslate_ui(self) -> None:
        """Retranslates all text on language switch."""
        self.setWindowTitle(tr("app_title"))
        self.sidebar_rail.retranslate_ui()
        self.sidebar.retranslate_ui()

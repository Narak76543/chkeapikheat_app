"""
Sidebar Panel Module
One UI 9 styled collapsible right sidebar panel hosting Settings, Video Splitter,
and Movie Details views without opening modal dialogs.
"""

import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from downloader_app.core.config import (
    get_download_folder,
    get_gemini_api_key,
    get_language,
    get_max_concurrent,
    get_theme,
    set_download_folder,
    set_gemini_api_key,
    set_max_concurrent,
)
from downloader_app.core.config import (
    set_language as save_language,
)
from downloader_app.core.config import (
    set_theme as save_theme,
)
from downloader_app.core.video_splitter import VideoSplitterWorker
from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.image_loader import AsyncImageLoader
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.sidebar")


# ---------------------------------------------------------------------------
# 1. Settings View (Embedded in Sidebar)
# ---------------------------------------------------------------------------
class SettingsView(QWidget):
    """Clean One UI 9 settings view embedded within the sidebar."""

    theme_changed = pyqtSignal(str)
    language_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(14)

        # ── 1. AI Services (Gemini) Card ──
        self.lbl_ai_section = QLabel(tr("ai_services"))
        self.lbl_ai_section.setObjectName("sectionHeaderLabel")
        layout.addWidget(self.lbl_ai_section)

        ai_card = QFrame()
        ai_card.setObjectName("sidebarCard")
        ai_card_layout = QVBoxLayout(ai_card)
        ai_card_layout.setContentsMargins(14, 14, 14, 14)
        ai_card_layout.setSpacing(10)

        self.lbl_gemini_key = QLabel(tr("gemini_api_key"))
        self.lbl_gemini_key.setObjectName("metaLabel")
        ai_card_layout.addWidget(self.lbl_gemini_key)

        key_row = QHBoxLayout()
        key_row.setSpacing(6)

        self.key_edit = QLineEdit()
        self.key_edit.setObjectName("urlInput")
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText(tr("gemini_api_key_placeholder"))
        self.key_edit.setFixedHeight(34)
        self.key_edit.setText(get_gemini_api_key())
        self.key_edit.textChanged.connect(self._on_key_text_changed)
        key_row.addWidget(self.key_edit, 1)

        self.btn_toggle_key_vis = QPushButton()
        self.btn_toggle_key_vis.setObjectName("rowActionButton")
        self.btn_toggle_key_vis.setFixedSize(34, 34)
        self.btn_toggle_key_vis.setIcon(get_icon("eye", size=16))
        self.btn_toggle_key_vis.setToolTip("Show / Hide Key")
        self.btn_toggle_key_vis.clicked.connect(self._toggle_key_visibility)
        key_row.addWidget(self.btn_toggle_key_vis)

        ai_card_layout.addLayout(key_row)

        self.lbl_key_status = QLabel()
        self.lbl_key_status.setObjectName("metaLabel")
        if get_gemini_api_key():
            self.lbl_key_status.setText("✓ " + tr("api_key_saved"))
            self.lbl_key_status.setStyleSheet("color: #10B981; font-size: 11px;")
        else:
            self.lbl_key_status.setText(tr("get_api_key_help"))
            self.lbl_key_status.setStyleSheet("color: #8E8E93; font-size: 11px;")
        ai_card_layout.addWidget(self.lbl_key_status)

        layout.addWidget(ai_card)

        # ── 2. Appearance Section ──
        self.lbl_appearance = QLabel(tr("appearance"))
        self.lbl_appearance.setObjectName("sectionHeaderLabel")
        layout.addWidget(self.lbl_appearance)

        app_card = QFrame()
        app_card.setObjectName("sidebarCard")
        app_card_layout = QVBoxLayout(app_card)
        app_card_layout.setContentsMargins(14, 14, 14, 14)
        app_card_layout.setSpacing(14)

        # Theme
        theme_row = QHBoxLayout()
        self.lbl_theme = QLabel(tr("theme"))
        self.lbl_theme.setObjectName("metaLabel")
        theme_row.addWidget(self.lbl_theme)
        theme_row.addStretch()

        self.theme_group = QButtonGroup(self)
        self.btn_light = QPushButton(tr("light_mode"))
        self.btn_light.setObjectName("pillToggle")
        self.btn_light.setCheckable(True)
        self.btn_light.setIcon(get_icon("sun", size=15))

        self.btn_dark = QPushButton(tr("dark_mode"))
        self.btn_dark.setObjectName("pillToggle")
        self.btn_dark.setCheckable(True)
        self.btn_dark.setIcon(get_icon("moon", size=15))

        self.theme_group.addButton(self.btn_light)
        self.theme_group.addButton(self.btn_dark)

        if get_theme() == "dark":
            self.btn_dark.setChecked(True)
        else:
            self.btn_light.setChecked(True)

        self.btn_light.clicked.connect(lambda: self._handle_theme_change("light"))
        self.btn_dark.clicked.connect(lambda: self._handle_theme_change("dark"))

        theme_row.addWidget(self.btn_light)
        theme_row.addWidget(self.btn_dark)
        app_card_layout.addLayout(theme_row)

        # Language
        lang_row = QHBoxLayout()
        self.lbl_language = QLabel(tr("language"))
        self.lbl_language.setObjectName("metaLabel")
        lang_row.addWidget(self.lbl_language)
        lang_row.addStretch()

        self.lang_group = QButtonGroup(self)
        self.btn_en = QPushButton("English")
        self.btn_en.setObjectName("pillToggle")
        self.btn_en.setCheckable(True)

        self.btn_km = QPushButton("ខ្មែរ")
        self.btn_km.setObjectName("pillToggle")
        self.btn_km.setCheckable(True)

        self.lang_group.addButton(self.btn_en)
        self.lang_group.addButton(self.btn_km)

        if get_language() == "km":
            self.btn_km.setChecked(True)
        else:
            self.btn_en.setChecked(True)

        self.btn_en.clicked.connect(lambda: self._handle_language_change("en"))
        self.btn_km.clicked.connect(lambda: self._handle_language_change("km"))

        lang_row.addWidget(self.btn_en)
        lang_row.addWidget(self.btn_km)
        app_card_layout.addLayout(lang_row)
        layout.addWidget(app_card)

        # ── 3. General Section ──
        self.lbl_general = QLabel(tr("general"))
        self.lbl_general.setObjectName("sectionHeaderLabel")
        layout.addWidget(self.lbl_general)

        gen_card = QFrame()
        gen_card.setObjectName("sidebarCard")
        gen_card_layout = QVBoxLayout(gen_card)
        gen_card_layout.setContentsMargins(14, 14, 14, 14)
        gen_card_layout.setSpacing(14)

        # Folder
        folder_vbox = QVBoxLayout()
        folder_vbox.setSpacing(6)
        self.lbl_folder = QLabel(tr("download_folder"))
        self.lbl_folder.setObjectName("metaLabel")
        folder_vbox.addWidget(self.lbl_folder)

        folder_hbox = QHBoxLayout()
        folder_hbox.setSpacing(8)
        self.folder_edit = QLineEdit(get_download_folder())
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setObjectName("urlInput")
        self.folder_edit.setFixedHeight(36)

        self.btn_browse = QPushButton(tr("browse"))
        self.btn_browse.setObjectName("pillToggle")
        self.btn_browse.setIcon(get_icon("folder", size=15))
        self.btn_browse.clicked.connect(self._handle_browse_folder)

        folder_hbox.addWidget(self.folder_edit, 1)
        folder_hbox.addWidget(self.btn_browse)
        folder_vbox.addLayout(folder_hbox)
        gen_card_layout.addLayout(folder_vbox)

        # Concurrency
        concurrency_row = QHBoxLayout()
        self.lbl_concurrent = QLabel(tr("max_concurrent_downloads"))
        self.lbl_concurrent.setObjectName("metaLabel")
        concurrency_row.addWidget(self.lbl_concurrent)
        concurrency_row.addStretch()

        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(1, 10)
        self.spin_concurrent.setValue(get_max_concurrent())
        self.spin_concurrent.setFixedHeight(34)
        self.spin_concurrent.setFixedWidth(70)
        self.spin_concurrent.valueChanged.connect(self._handle_max_concurrent_change)
        concurrency_row.addWidget(self.spin_concurrent)
        gen_card_layout.addLayout(concurrency_row)

        layout.addWidget(gen_card)
        layout.addStretch()

    def _toggle_key_visibility(self) -> None:
        if self.key_edit.echoMode() == QLineEdit.EchoMode.Password:
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_toggle_key_vis.setIcon(get_icon("eye-off", size=16))
        else:
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_toggle_key_vis.setIcon(get_icon("eye", size=16))

    def _on_key_text_changed(self, text: str) -> None:
        set_gemini_api_key(text.strip())
        if text.strip():
            self.lbl_key_status.setText("✓ " + tr("api_key_saved"))
            self.lbl_key_status.setStyleSheet("color: #10B981; font-size: 11px;")
        else:
            self.lbl_key_status.setText(tr("get_api_key_help"))
            self.lbl_key_status.setStyleSheet("color: #8E8E93; font-size: 11px;")

    def _handle_theme_change(self, theme: str) -> None:
        save_theme(theme)
        self.update_theme_icons()
        self.theme_changed.emit(theme)

    def _handle_language_change(self, lang: str) -> None:
        save_language(lang)
        self.language_changed.emit(lang)

    def _handle_browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, tr("download_folder"), get_download_folder()
        )
        if folder:
            set_download_folder(folder)
            self.folder_edit.setText(folder)

    def _handle_max_concurrent_change(self, value: int) -> None:
        set_max_concurrent(value)

    def update_theme_icons(self) -> None:
        self.btn_light.setIcon(get_icon("sun", size=15))
        self.btn_dark.setIcon(get_icon("moon", size=15))
        self.btn_browse.setIcon(get_icon("folder", size=15))
        vis_icon = "eye-off" if self.key_edit.echoMode() == QLineEdit.EchoMode.Normal else "eye"
        self.btn_toggle_key_vis.setIcon(get_icon(vis_icon, size=16))

    def retranslate_ui(self) -> None:
        self.lbl_ai_section.setText(tr("ai_services"))
        self.lbl_gemini_key.setText(tr("gemini_api_key"))
        self.key_edit.setPlaceholderText(tr("gemini_api_key_placeholder"))
        self.lbl_appearance.setText(tr("appearance"))
        self.lbl_theme.setText(tr("theme"))
        self.btn_light.setText(tr("light_mode"))
        self.btn_dark.setText(tr("dark_mode"))
        self.lbl_language.setText(tr("language"))
        self.lbl_general.setText(tr("general"))
        self.lbl_folder.setText(tr("download_folder"))
        self.btn_browse.setText(tr("browse"))
        self.lbl_concurrent.setText(tr("max_concurrent_downloads"))
        self.update_theme_icons()


# ---------------------------------------------------------------------------
# 2. Video Split View (Embedded in Sidebar)
# ---------------------------------------------------------------------------
class VideoSplitView(QWidget):
    """Clean One UI 9 video splitter view embedded within the sidebar."""

    split_completed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.worker: VideoSplitterWorker | None = None
        self._output_dir: str = ""
        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(14)

        # 1. Source Video Card
        self.lbl_src_section = QLabel(tr("source_video"))
        self.lbl_src_section.setObjectName("sectionHeaderLabel")
        layout.addWidget(self.lbl_src_section)

        src_card = QFrame()
        src_card.setObjectName("sidebarCard")
        src_card_layout = QVBoxLayout(src_card)
        src_card_layout.setContentsMargins(14, 14, 14, 14)
        src_card_layout.setSpacing(8)

        self.edit_video_path = QLineEdit()
        self.edit_video_path.setObjectName("urlInput")
        self.edit_video_path.setPlaceholderText(tr("select_video"))
        self.edit_video_path.setFixedHeight(36)
        self.edit_video_path.textChanged.connect(self._on_video_path_changed)

        self.btn_browse_video = QPushButton(tr("browse"))
        self.btn_browse_video.setObjectName("pillToggle")
        self.btn_browse_video.setIcon(get_icon("folder", size=15))
        self.btn_browse_video.clicked.connect(self._handle_browse_video)

        src_row = QHBoxLayout()
        src_row.setSpacing(8)
        src_row.addWidget(self.edit_video_path, 1)
        src_row.addWidget(self.btn_browse_video)
        src_card_layout.addLayout(src_row)
        layout.addWidget(src_card)

        # 2. Minutes Per Episode Card
        self.lbl_duration_section = QLabel(tr("minutes_per_episode"))
        self.lbl_duration_section.setObjectName("sectionHeaderLabel")
        layout.addWidget(self.lbl_duration_section)

        dur_card = QFrame()
        dur_card.setObjectName("sidebarCard")
        dur_card_layout = QVBoxLayout(dur_card)
        dur_card_layout.setContentsMargins(14, 14, 14, 14)
        dur_card_layout.setSpacing(10)

        # Row 1: Spinbox
        spin_row = QHBoxLayout()
        self.spin_minutes = QSpinBox()
        self.spin_minutes.setRange(1, 180)
        self.spin_minutes.setValue(10)
        self.spin_minutes.setSuffix(" mn")
        self.spin_minutes.setFixedHeight(34)
        self.spin_minutes.setFixedWidth(90)
        spin_row.addWidget(self.spin_minutes)
        spin_row.addStretch()
        dur_card_layout.addLayout(spin_row)

        # Row 2: Quick preset pills
        presets_row = QHBoxLayout()
        presets_row.setSpacing(8)
        self.preset_group = QButtonGroup(self)
        for minutes in [5, 10, 15, 20]:
            btn = QPushButton(f"{minutes} mn")
            btn.setObjectName("pillToggle")
            btn.setCheckable(True)
            if minutes == 10:
                btn.setChecked(True)
            btn.clicked.connect(lambda _, m=minutes: self.spin_minutes.setValue(m))
            self.preset_group.addButton(btn)
            presets_row.addWidget(btn)

        presets_row.addStretch()
        dur_card_layout.addLayout(presets_row)
        self.spin_minutes.valueChanged.connect(self._sync_preset_buttons)
        layout.addWidget(dur_card)

        # 3. Output Folder Card
        self.lbl_out_section = QLabel(tr("output_folder"))
        self.lbl_out_section.setObjectName("sectionHeaderLabel")
        layout.addWidget(self.lbl_out_section)

        out_card = QFrame()
        out_card.setObjectName("sidebarCard")
        out_card_layout = QHBoxLayout(out_card)
        out_card_layout.setContentsMargins(14, 14, 14, 14)
        out_card_layout.setSpacing(8)

        self.edit_output_dir = QLineEdit()
        self.edit_output_dir.setObjectName("urlInput")
        self.edit_output_dir.setFixedHeight(36)
        self._update_default_output_dir()
        out_card_layout.addWidget(self.edit_output_dir, 1)

        self.btn_browse_out = QPushButton(tr("browse"))
        self.btn_browse_out.setObjectName("pillToggle")
        self.btn_browse_out.setIcon(get_icon("folder", size=15))
        self.btn_browse_out.clicked.connect(self._handle_browse_output)
        out_card_layout.addWidget(self.btn_browse_out)
        layout.addWidget(out_card)

        # Progress bar & Status
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("thickProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("metaLabel")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_status)

        layout.addStretch()

        # Action Buttons
        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        self.btn_open_folder = QPushButton(tr("open_folder"))
        self.btn_open_folder.setObjectName("pillToggle")
        self.btn_open_folder.setIcon(get_icon("folder", size=15))
        self.btn_open_folder.setVisible(False)
        self.btn_open_folder.clicked.connect(self._handle_open_output_folder)
        actions_row.addWidget(self.btn_open_folder)

        actions_row.addStretch()

        self.btn_start_split = QPushButton(tr("split_now"))
        self.btn_start_split.setObjectName("primaryButton")
        self.btn_start_split.setIcon(get_icon("scissors", color="#FFFFFF", size=16))
        self.btn_start_split.clicked.connect(self._handle_start_split)
        actions_row.addWidget(self.btn_start_split)

        layout.addLayout(actions_row)

    def set_video_path(self, path: str) -> None:
        self.edit_video_path.setText(path)
        self._on_video_path_changed(path)

    def _sync_preset_buttons(self, val: int) -> None:
        for btn in self.preset_group.buttons():
            btn.setChecked(btn.text() == f"{val} mn")

    def _on_video_path_changed(self, path: str) -> None:
        if path and os.path.exists(path):
            video_file = Path(path)
            stem = video_file.stem
            out_dir = video_file.parent / f"{stem}_episodes"
            self.edit_output_dir.setText(str(out_dir))
        else:
            self._update_default_output_dir()

    def _update_default_output_dir(self) -> None:
        base = get_download_folder()
        self.edit_output_dir.setText(str(Path(base) / "episodes_output"))

    def _handle_browse_video(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("select_video"),
            get_download_folder(),
            "Video Files (*.mp4 *.mkv *.mov *.avi *.ts *.webm);;All Files (*.*)",
        )
        if file_path:
            self.set_video_path(file_path)

    def _handle_browse_output(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self, tr("output_folder"), self.edit_output_dir.text()
        )
        if dir_path:
            self.edit_output_dir.setText(dir_path)

    def _handle_start_split(self) -> None:
        video_path = self.edit_video_path.text().strip()
        if not video_path or not os.path.exists(video_path):
            self.lbl_status.setText(tr("file_not_found"))
            self.lbl_status.setStyleSheet("color: #F87171;")
            return

        minutes = self.spin_minutes.value()
        output_dir = self.edit_output_dir.text().strip()
        self._output_dir = output_dir

        self.btn_start_split.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText(tr("splitting_in_progress"))
        self.lbl_status.setStyleSheet("color: #4FA0FF;")

        self.worker = VideoSplitterWorker(video_path, minutes, output_dir, parent=self)
        self.worker.progress_changed.connect(self._on_progress_changed)
        self.worker.finished.connect(self._on_split_finished)
        self.worker.error.connect(self._on_split_error)
        self.worker.start()

    def _on_progress_changed(self, percent: float) -> None:
        self.progress_bar.setValue(int(percent))

    def _on_split_finished(self, out_dir: str, files: list | int) -> None:
        count = len(files) if isinstance(files, list) else files
        self.btn_start_split.setEnabled(True)
        self.progress_bar.setValue(100)
        self.lbl_status.setText(
            f"{tr('split_completed')} ({count} {tr('episodes_generated')})"
        )
        self.lbl_status.setStyleSheet("color: #34D399;")
        self.btn_open_folder.setVisible(True)
        self.split_completed.emit(out_dir)

    def _on_split_error(self, err: str) -> None:
        self.btn_start_split.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status.setText(f"{tr('split_failed')}: {err}")
        self.lbl_status.setStyleSheet("color: #F87171;")

    def _handle_open_output_folder(self) -> None:
        if self._output_dir and os.path.exists(self._output_dir):
            if os.name == "nt":
                os.startfile(self._output_dir)
            else:
                subprocess.Popen(["xdg-open", self._output_dir])

    def update_theme_icons(self) -> None:
        self.btn_browse_video.setIcon(get_icon("folder", size=15))
        self.btn_browse_out.setIcon(get_icon("folder", size=15))
        self.btn_open_folder.setIcon(get_icon("folder", size=15))
        self.btn_start_split.setIcon(get_icon("scissors", color="#FFFFFF", size=16))

    def retranslate_ui(self) -> None:
        self.lbl_src_section.setText(tr("source_video"))
        self.btn_browse_video.setText(tr("browse"))
        self.edit_video_path.setPlaceholderText(tr("select_video"))
        self.lbl_duration_section.setText(tr("minutes_per_episode"))
        self.lbl_out_section.setText(tr("output_folder"))
        self.btn_browse_out.setText(tr("browse"))
        self.btn_start_split.setText(tr("split_now"))
        self.btn_open_folder.setText(tr("open_folder"))


# ---------------------------------------------------------------------------
# 3. Movie Details View (Embedded in Sidebar)
# ---------------------------------------------------------------------------
class MovieDetailsView(QWidget):
    """Clean One UI 9 movie details view embedded within the sidebar."""

    download_full_movie_selected = pyqtSignal(dict)
    download_episodes_selected = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.movie_data: dict = {}
        self._image_loader: AsyncImageLoader | None = None
        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(14)

        # Main details card
        card = QFrame()
        card.setObjectName("sidebarCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(12)

        # Poster Centered (120x175px with 12px rounded corners)
        poster_row = QHBoxLayout()
        poster_row.addStretch()
        self.poster_label = QLabel()
        self.poster_label.setFixedSize(120, 175)
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_label.setObjectName("downloadCard")
        self.poster_label.setText(tr("loading_preview"))
        self.poster_label.setWordWrap(True)
        poster_row.addWidget(self.poster_label)
        poster_row.addStretch()
        card_layout.addLayout(poster_row)

        # Title
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("titleLabel")
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.lbl_title)

        # Badges row: Episodes, Duration, Tags
        self.badges_layout = QHBoxLayout()
        self.badges_layout.setSpacing(6)
        self.badges_layout.addStretch()

        self.lbl_eps_badge = QLabel()
        self.lbl_eps_badge.setObjectName("statusBadge_downloading")
        self.badges_layout.addWidget(self.lbl_eps_badge)

        self.lbl_dur_badge = QLabel()
        self.lbl_dur_badge.setObjectName("statusBadge_paused")
        self.badges_layout.addWidget(self.lbl_dur_badge)

        self.tags_container = QWidget()
        self.tags_layout = QHBoxLayout(self.tags_container)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setSpacing(4)
        self.badges_layout.addWidget(self.tags_container)

        self.badges_layout.addStretch()
        card_layout.addLayout(self.badges_layout)

        # Synopsis Section
        self.lbl_synopsis_title = QLabel(tr("synopsis"))
        self.lbl_synopsis_title.setObjectName("sectionHeaderLabel")
        card_layout.addWidget(self.lbl_synopsis_title)

        self.synopsis_scroll = QScrollArea()
        self.synopsis_scroll.setWidgetResizable(True)
        self.synopsis_scroll.setFixedHeight(90)
        self.synopsis_scroll.setStyleSheet("background: transparent; border: none;")

        self.lbl_intro = QLabel()
        self.lbl_intro.setObjectName("metaLabel")
        self.lbl_intro.setWordWrap(True)
        self.lbl_intro.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.synopsis_scroll.setWidget(self.lbl_intro)
        card_layout.addWidget(self.synopsis_scroll)
        layout.addWidget(card)

        layout.addStretch()

        # Quality Dropdown Row
        qual_row = QHBoxLayout()
        qual_row.setSpacing(6)
        lbl_q = QLabel("Quality:")
        lbl_q.setObjectName("metaLabel")
        lbl_q.setStyleSheet("font-size: 12px; font-weight: 500;")
        qual_row.addWidget(lbl_q)

        self.combo_quality = QComboBox()
        self.combo_quality.setObjectName("pillInput")
        self.combo_quality.addItems(["1080p", "720p", "480p", "360p", "Best Quality"])
        self.combo_quality.setStyleSheet("padding: 2px 8px; min-height: 32px; font-size: 12px;")
        qual_row.addWidget(self.combo_quality, 1)
        layout.addLayout(qual_row)

        # Action Buttons
        self.btn_episodes = QPushButton(tr("download_episodes"))
        self.btn_episodes.setObjectName("pillToggle")
        self.btn_episodes.setIcon(get_icon("video", size=16))
        self.btn_episodes.setStyleSheet("padding: 0 10px; font-size: 12px; font-weight: 500; min-height: 40px;")
        self.btn_episodes.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_episodes.clicked.connect(self._on_download_episodes_clicked)
        layout.addWidget(self.btn_episodes)

        self.btn_full_movie = QPushButton(tr("download_full_movie"))
        self.btn_full_movie.setObjectName("primaryButton")
        self.btn_full_movie.setIcon(get_icon("download", color="#FFFFFF", size=16))
        self.btn_full_movie.setStyleSheet("padding: 0 10px; font-size: 12px; font-weight: 500; min-height: 44px;")
        self.btn_full_movie.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_full_movie.clicked.connect(self._on_download_full_movie_clicked)
        layout.addWidget(self.btn_full_movie)

    def set_movie_data(self, data: dict) -> None:
        self.movie_data = data
        self.lbl_title.setText(data.get("title", "Movie"))

        total_eps = data.get("total_episodes", 0)
        self.lbl_eps_badge.setText(tr("episodes_count").format(count=total_eps))

        dur_str = data.get("duration_str")
        if not dur_str:
            duration_mins = data.get("estimated_duration_mins", 0)
            from downloader_app.core.metadata_fetcher import format_duration

            dur_str = format_duration(duration_mins)
        self.lbl_dur_badge.setText(
            dur_str
            if dur_str
            else tr("estimated_duration").format(
                mins=data.get("estimated_duration_mins", 0)
            )
        )

        while self.tags_layout.count() > 0:
            item = self.tags_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        for tag in data.get("tags", [])[:2]:
            tag_label = QLabel(f"#{tag}")
            tag_label.setObjectName("statusBadge_queued")
            self.tags_layout.addWidget(tag_label)

        intro = data.get("intro") or ""
        self.lbl_intro.setText(intro if intro else tr("synopsis"))

        cover_url = data.get("cover_url", "")
        if cover_url:
            self.poster_label.setText(tr("loading_preview"))
            self._image_loader = AsyncImageLoader(
                url=cover_url,
                target_size=QSize(120, 175),
                corner_radius=12,
            )
            self._image_loader.image_loaded.connect(self.poster_label.setPixmap)
            self._image_loader.start()
        else:
            self.poster_label.setPixmap(get_icon("film", size=48).pixmap(48, 48))

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
        self.btn_episodes.setIcon(get_icon("video", size=16))
        self.btn_full_movie.setIcon(get_icon("download", color="#FFFFFF", size=16))

    def retranslate_ui(self) -> None:
        self.lbl_synopsis_title.setText(tr("synopsis"))
        self.btn_episodes.setText(tr("download_episodes"))
        self.btn_full_movie.setText(tr("download_full_movie"))

        if self.movie_data:
            total_eps = self.movie_data.get("total_episodes", 0)
            self.lbl_eps_badge.setText(tr("episodes_count").format(count=total_eps))
            duration_mins = self.movie_data.get("estimated_duration_mins", 0)
            self.lbl_dur_badge.setText(
                tr("estimated_duration").format(mins=duration_mins)
            )


# ---------------------------------------------------------------------------
# 4. Main Unified Sidebar Panel
# ---------------------------------------------------------------------------
class SidebarPanel(QFrame):
    """
    Collapsible right sidebar panel hosting Settings, Video Splitter,
    and Movie Details with zero modal dialogs.
    """

    closed = pyqtSignal()
    theme_changed = pyqtSignal(str)
    language_changed = pyqtSignal(str)
    download_full_movie_selected = pyqtSignal(dict)
    download_episodes_selected = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebarPanel")
        self.setFixedWidth(380)

        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header Bar (Title + Outline Dismiss ✕)
        header_widget = QWidget()
        header_widget.setObjectName("sidebarHeader")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(18, 16, 18, 12)
        header_layout.setSpacing(10)

        self.header_icon = QLabel()
        self.header_icon.setPixmap(get_icon("settings", size=20).pixmap(20, 20))
        header_layout.addWidget(self.header_icon)

        self.lbl_title = QLabel(tr("settings"))
        self.lbl_title.setObjectName("sidebarTitle")
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch()

        # Circular outline close button (38x38)
        self.btn_close = QPushButton()
        self.btn_close.setObjectName("iconButton")
        self.btn_close.setIcon(get_icon("x", size=18))
        self.btn_close.setToolTip(tr("cancel"))
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.close_sidebar)
        header_layout.addWidget(self.btn_close)

        main_layout.addWidget(header_widget)

        # Stacked views container
        self.stack = QStackedWidget()

        # 0: Settings View
        self.settings_view = SettingsView()
        self.settings_view.theme_changed.connect(self.theme_changed.emit)
        self.settings_view.language_changed.connect(self.language_changed.emit)
        self.stack.addWidget(self.settings_view)

        # 1: Video Splitter View
        self.split_view = VideoSplitView()
        self.stack.addWidget(self.split_view)

        # 2: Movie Details View
        self.movie_view = MovieDetailsView()
        self.movie_view.download_full_movie_selected.connect(
            self.download_full_movie_selected.emit
        )
        self.movie_view.download_episodes_selected.connect(
            self.download_episodes_selected.emit
        )
        self.stack.addWidget(self.movie_view)

        main_layout.addWidget(self.stack, 1)

    def open_settings(self) -> None:
        """Switches to Settings view and shows sidebar."""
        self.stack.setCurrentIndex(0)
        self.header_icon.setPixmap(get_icon("settings", size=20).pixmap(20, 20))
        self.lbl_title.setText(tr("settings"))
        self.setVisible(True)

    def open_video_splitter(self, video_path: str = "") -> None:
        """Switches to Video Splitter view and shows sidebar."""
        self.stack.setCurrentIndex(1)
        if video_path:
            self.split_view.set_video_path(video_path)
        self.header_icon.setPixmap(get_icon("scissors", size=20).pixmap(20, 20))
        self.lbl_title.setText(tr("split_movie"))
        self.setVisible(True)

    def open_movie_details(self, movie_data: dict) -> None:
        """Switches to Movie Details view and shows sidebar."""
        self.stack.setCurrentIndex(2)
        self.movie_view.set_movie_data(movie_data)
        self.header_icon.setPixmap(get_icon("film", size=20).pixmap(20, 20))
        self.lbl_title.setText(tr("movie_details"))
        self.setVisible(True)

    def close_sidebar(self) -> None:
        """Hides the sidebar."""
        self.setVisible(False)
        self.closed.emit()

    def update_theme_icons(self) -> None:
        """Refreshes outline icons on theme switch."""
        self.btn_close.setIcon(get_icon("x", size=18))
        self.settings_view.update_theme_icons()
        self.split_view.update_theme_icons()
        self.movie_view.update_theme_icons()

        # Update header icon
        idx = self.stack.currentIndex()
        if idx == 0:
            self.header_icon.setPixmap(get_icon("settings", size=20).pixmap(20, 20))
        elif idx == 1:
            self.header_icon.setPixmap(get_icon("scissors", size=20).pixmap(20, 20))
        else:
            self.header_icon.setPixmap(get_icon("film", size=20).pixmap(20, 20))

    def retranslate_ui(self) -> None:
        """Updates translated headers on language switch."""
        idx = self.stack.currentIndex()
        if idx == 0:
            self.lbl_title.setText(tr("settings"))
        elif idx == 1:
            self.lbl_title.setText(tr("split_movie"))
        else:
            self.lbl_title.setText(tr("movie_details"))
        self.btn_close.setToolTip(tr("cancel"))

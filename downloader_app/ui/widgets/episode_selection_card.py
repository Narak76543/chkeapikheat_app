"""
Episode Selection Card Widget
One UI 9 inline card widget allowing users to select episode ranges, filter video quality (1080p, 720p, 480p),
view movie & episode poster thumbnails, and select/translate Khmer drama export titles.
"""

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from downloader_app.core.translator import TitleSuggestionsWorker, clean_drama_title
from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import tr
from downloader_app.utils.image_loader import AsyncImageLoader
from downloader_app.utils.logger import setup_logger
from downloader_app.utils.validators import sanitize_filename

logger = setup_logger("downloader.ui.ep_card")


class EpisodeItemCard(QFrame):
    """Compact clickable card item representing an individual episode with mini cover thumbnail."""

    toggled = pyqtSignal(bool)

    def __init__(
        self, ep_num: int, cover_url: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.ep_num = ep_num
        self.cover_url = cover_url
        self.setObjectName("sidebarCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(115, 95)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Mini Poster Thumbnail
        self.poster_label = QLabel()
        self.poster_label.setFixedSize(40, 52)
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_placeholder()

        if self.cover_url:
            self._loader = AsyncImageLoader(
                self.cover_url, target_size=QSize(40, 52), corner_radius=6
            )
            self._loader.image_loaded.connect(self.poster_label.setPixmap)
            self._loader.start()

        layout.addWidget(self.poster_label, 0, Qt.AlignmentFlag.AlignCenter)

        # Bottom Row: Checkbox + Ep Title
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(4)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.stateChanged.connect(self._on_check_changed)
        bottom_row.addWidget(self.checkbox)

        self.lbl_title = QLabel(f"Ep {self.ep_num:02d}")
        self.lbl_title.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #1C1C1E;"
        )
        bottom_row.addWidget(self.lbl_title)

        layout.addLayout(bottom_row)

    def _set_placeholder(self) -> None:
        icon = get_icon("file-video", color="#6B6B6F", size=20)
        self.poster_label.setPixmap(icon.pixmap(20, 20))

    def mousePressEvent(self, event) -> None:
        """Clicking anywhere on the episode card toggles selection."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.checkbox.setChecked(not self.checkbox.isChecked())
        super().mousePressEvent(event)

    def _on_check_changed(self) -> None:
        self.toggled.emit(self.checkbox.isChecked())

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, checked: bool) -> None:
        self.checkbox.setChecked(checked)


class EpisodeSelectionCard(QFrame):
    """Inline card widget for episode selection, quality configuration, and title translation."""

    episodes_selected = pyqtSignal(dict)
    closed = pyqtSignal()

    def __init__(
        self,
        movie_data: dict,
        fetch_suggestions: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("downloadCard")
        self.movie_data = movie_data
        self.selected_quality = "1080p"
        self._selected_title: str = ""
        self._candidate_items: list[str] = []
        self._candidate_buttons: list[QPushButton] = []
        self._sugg_worker: TitleSuggestionsWorker | None = None

        # Calculate exact total episodes
        vid_list = movie_data.get("vid_list", [])
        self.total_episodes = (
            movie_data.get("total_episodes")
            or len(vid_list)
            or 78
        )
        self.item_cards: list[EpisodeItemCard] = []
        self._init_ui()

        # Fetch initial title suggestions
        initial_title = movie_data.get("title", "")
        if initial_title and fetch_suggestions:
            self._start_title_suggestion_worker(initial_title)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── 1. Top Header: Poster + Drama Info + Close Button ──
        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        # Poster Image
        self.poster_label = QLabel()
        self.poster_label.setObjectName("metadataPoster")
        self.poster_label.setFixedSize(70, 95)
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        cover_url = self.movie_data.get("cover_url", "")
        if cover_url:
            self._main_loader = AsyncImageLoader(
                cover_url, target_size=QSize(70, 95), corner_radius=10
            )
            self._main_loader.image_loaded.connect(self.poster_label.setPixmap)
            self._main_loader.start()
        else:
            icon = get_icon("file-video", color="#6B6B6F", size=32)
            self.poster_label.setPixmap(icon.pixmap(32, 32))

        header_row.addWidget(self.poster_label)

        # Info Layout
        info_col = QVBoxLayout()
        info_col.setSpacing(4)

        title_str = self.movie_data.get("title", "Drama Series")
        self.lbl_title = QLabel(title_str)
        self.lbl_title.setObjectName("titleLabel")
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        info_col.addWidget(self.lbl_title)

        meta_str = f"Total Episodes: {self.total_episodes}"
        self.lbl_meta = QLabel(meta_str)
        self.lbl_meta.setObjectName("metaLabel")
        info_col.addWidget(self.lbl_meta)

        intro_str = self.movie_data.get("intro", "")
        if intro_str:
            self.lbl_intro = QLabel(intro_str[:120] + "..." if len(intro_str) > 120 else intro_str)
            self.lbl_intro.setObjectName("metaLabel")
            self.lbl_intro.setWordWrap(True)
            info_col.addWidget(self.lbl_intro)

        header_row.addLayout(info_col, 1)

        # Close / Collapse Button
        btn_close = QPushButton()
        btn_close.setObjectName("iconButton")
        btn_close.setIcon(get_icon("x", size=16))
        btn_close.setToolTip("Close Episode Selection")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self._on_close_clicked)
        header_row.addWidget(btn_close, 0, Qt.AlignmentFlag.AlignTop)

        layout.addLayout(header_row)

        # ── Scrollable Body Container ──
        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; } "
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )

        body_widget = QWidget()
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(0, 0, 8, 0)
        body_layout.setSpacing(12)

        # ── 2. Title Translation Candidate Suggestions Section ──
        self.suggestion_card = QFrame()
        self.suggestion_card.setObjectName("settingsGroupCard")
        sugg_card_layout = QVBoxLayout(self.suggestion_card)
        sugg_card_layout.setContentsMargins(14, 12, 14, 12)
        sugg_card_layout.setSpacing(10)

        # Sugg Header Row
        sugg_header = QHBoxLayout()
        sugg_header.setSpacing(8)

        self.sugg_icon = QLabel()
        self.sugg_icon.setPixmap(get_icon("rotate-cw", size=16).pixmap(16, 16))
        sugg_header.addWidget(self.sugg_icon)

        sugg_title_text = tr("suggested_khmer_titles")
        if sugg_title_text == "suggested_khmer_titles":
            sugg_title_text = "Suggested Khmer Titles"
        self.lbl_sugg_prefix = QLabel(sugg_title_text)
        self.lbl_sugg_prefix.setObjectName("sectionHeaderLabel")
        self.lbl_sugg_prefix.setStyleSheet("font-size: 13px; font-weight: 600;")
        sugg_header.addWidget(self.lbl_sugg_prefix, 1)

        self.combo_sugg_lang = QComboBox()
        self.combo_sugg_lang.setObjectName("pillInput")
        self.combo_sugg_lang.setMinimumWidth(85)
        self.combo_sugg_lang.setStyleSheet("padding: 2px 8px; min-height: 30px; font-size: 12px;")
        khmer_lbl = tr("khmer") if tr("khmer") != "khmer" else "Khmer"
        eng_lbl = tr("english") if tr("english") != "english" else "English"
        self.combo_sugg_lang.addItem(khmer_lbl, "km")
        self.combo_sugg_lang.addItem(eng_lbl, "en")
        self.combo_sugg_lang.currentIndexChanged.connect(self._on_sugg_params_changed)
        sugg_header.addWidget(self.combo_sugg_lang)

        self.combo_count = QComboBox()
        self.combo_count.setObjectName("pillInput")
        self.combo_count.setStyleSheet("padding: 2px 8px; min-height: 30px; font-size: 12px;")
        for i in range(1, 6):
            self.combo_count.addItem(str(i))
        self.combo_count.setCurrentIndex(2)  # Default 3 candidates
        self.combo_count.currentTextChanged.connect(self._on_sugg_params_changed)
        sugg_header.addWidget(self.combo_count)

        self.btn_retranslate = QPushButton()
        self.btn_retranslate.setObjectName("iconButton")
        self.btn_retranslate.setIcon(get_icon("rotate-cw", size=14))
        self.btn_retranslate.setToolTip("Retranslate Title")
        self.btn_retranslate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_retranslate.setFixedSize(30, 30)
        self.btn_retranslate.clicked.connect(self._on_retranslate_clicked)
        sugg_header.addWidget(self.btn_retranslate)

        sugg_card_layout.addLayout(sugg_header)

        # Candidates Container
        self.candidates_container = QWidget()
        self.candidates_layout = QVBoxLayout(self.candidates_container)
        self.candidates_layout.setContentsMargins(0, 0, 0, 0)
        self.candidates_layout.setSpacing(6)
        sugg_card_layout.addWidget(self.candidates_container)

        # Custom Write-in Row
        custom_row = QHBoxLayout()
        custom_row.setSpacing(8)

        self.edit_custom_title = QLineEdit()
        self.edit_custom_title.setObjectName("pillInput")
        self.edit_custom_title.setStyleSheet("padding: 0 12px; min-height: 34px; font-size: 13px;")
        self.edit_custom_title.setPlaceholderText("Or type custom title...")
        self.edit_custom_title.textChanged.connect(self._on_custom_title_changed)
        custom_row.addWidget(self.edit_custom_title, 1)

        self.btn_use_custom = QPushButton("Use Custom")
        self.btn_use_custom.setObjectName("secondaryButton")
        self.btn_use_custom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_use_custom.setStyleSheet("padding: 0 14px; min-height: 34px; font-size: 12px;")
        self.btn_use_custom.clicked.connect(self._on_use_custom_clicked)
        custom_row.addWidget(self.btn_use_custom)

        sugg_card_layout.addLayout(custom_row)

        # Checkbox Row
        chk_label = tr("use_generated_title_in_path")
        if chk_label == "use_generated_title_in_path":
            chk_label = "Use translated Khmer title in folder and file names"
        self.chk_auto_append = QCheckBox(chk_label)
        self.chk_auto_append.setObjectName("metaLabel")
        self.chk_auto_append.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_auto_append.setChecked(True)
        self.chk_auto_append.toggled.connect(self._on_auto_append_toggled)
        sugg_card_layout.addWidget(self.chk_auto_append)

        # Naming Preview Card
        self.naming_preview_card = QFrame()
        self.naming_preview_card.setObjectName("sidebarCard")
        preview_layout = QVBoxLayout(self.naming_preview_card)
        preview_layout.setContentsMargins(12, 10, 12, 10)
        preview_layout.setSpacing(4)

        preview_title_text = tr("naming_preview")
        if preview_title_text == "naming_preview":
            preview_title_text = "Naming Preview"
        self.lbl_preview_title = QLabel(preview_title_text)
        self.lbl_preview_title.setObjectName("metaLabel")
        self.lbl_preview_title.setStyleSheet("font-size: 11px; font-weight: 600;")
        preview_layout.addWidget(self.lbl_preview_title)

        self.lbl_preview_files = QLabel()
        self.lbl_preview_files.setStyleSheet("font-family: 'Consolas', 'Courier New', monospace; font-size: 12px; line-height: 1.4;")
        preview_layout.addWidget(self.lbl_preview_files)

        sugg_card_layout.addWidget(self.naming_preview_card)

        body_layout.addWidget(self.suggestion_card)

        # ── 3. Controls Bar: Quality Selector & Range Inputs ──
        ctrl_card = QFrame()
        ctrl_card.setObjectName("sidebarCard")
        ctrl_layout = QHBoxLayout(ctrl_card)
        ctrl_layout.setContentsMargins(12, 8, 12, 8)
        ctrl_layout.setSpacing(10)

        # Quality Dropdown Group
        ctrl_layout.addWidget(QLabel("Quality:"))

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["1080p Full HD", "720p HD", "480p SD"])
        self.quality_combo.currentTextChanged.connect(self._on_quality_changed)
        ctrl_layout.addWidget(self.quality_combo)

        ctrl_layout.addSpacing(16)

        # Range SpinBoxes
        ctrl_layout.addWidget(QLabel("Range:"))

        self.spin_from = QSpinBox()
        self.spin_from.setRange(1, self.total_episodes)
        self.spin_from.setValue(1)
        self.spin_from.valueChanged.connect(self._on_range_changed)
        ctrl_layout.addWidget(self.spin_from)

        ctrl_layout.addWidget(QLabel("to"))

        self.spin_to = QSpinBox()
        self.spin_to.setRange(1, self.total_episodes)
        self.spin_to.setValue(self.total_episodes)
        self.spin_to.valueChanged.connect(self._on_range_changed)
        ctrl_layout.addWidget(self.spin_to)

        ctrl_layout.addStretch()

        # Presets
        btn_select_all = QPushButton("Select All")
        btn_select_all.setObjectName("secondaryButton")
        btn_select_all.clicked.connect(self._select_all)
        ctrl_layout.addWidget(btn_select_all)

        btn_deselect = QPushButton("Deselect All")
        btn_deselect.setObjectName("secondaryButton")
        btn_deselect.clicked.connect(self._deselect_all)
        ctrl_layout.addWidget(btn_deselect)

        body_layout.addWidget(ctrl_card)

        # ── 4. Grid of Episode Cards with Mini Posters ──
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setContentsMargins(6, 6, 6, 6)
        grid_layout.setSpacing(8)

        cols = 5
        for i in range(1, self.total_episodes + 1):
            item = EpisodeItemCard(ep_num=i, cover_url=cover_url)
            item.toggled.connect(self._update_count_label)
            self.item_cards.append(item)
            row = (i - 1) // cols
            col = (i - 1) % cols
            grid_layout.addWidget(item, row, col)

        body_layout.addWidget(grid_widget)

        body_scroll.setWidget(body_widget)
        layout.addWidget(body_scroll, 1)

        # ── 5. Bottom Action Bar ──
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(10)

        self.lbl_selected_count = QLabel(
            f"Selected: {self.total_episodes} / {self.total_episodes} Episodes"
        )
        self.lbl_selected_count.setObjectName("metaLabel")
        bottom_bar.addWidget(self.lbl_selected_count)

        bottom_bar.addStretch()

        btn_cancel = QPushButton(tr("cancel"))
        btn_cancel.setObjectName("secondaryButton")
        btn_cancel.clicked.connect(self._on_close_clicked)
        bottom_bar.addWidget(btn_cancel)

        self.btn_download = QPushButton(
            f"Download Selected ({self.total_episodes}) • {self.selected_quality}"
        )
        self.btn_download.setObjectName("primaryButton")
        self.btn_download.setIcon(get_icon("download", color="#FFFFFF", size=16))
        self.btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_download.clicked.connect(self._on_confirm)
        bottom_bar.addWidget(self.btn_download)

        layout.addLayout(bottom_bar)

        self._update_naming_preview()

    # ── Title Translation Logic ──

    def _start_title_suggestion_worker(self, raw_title: str) -> None:
        if self._sugg_worker and self._sugg_worker.isRunning():
            self._sugg_worker.quit()
            self._sugg_worker.wait()

        target_lang = self.combo_sugg_lang.currentData() or "km"
        try:
            count = int(self.combo_count.currentText())
        except ValueError:
            count = 3

        cleaned = clean_drama_title(raw_title)
        self._sugg_worker = TitleSuggestionsWorker(
            title=cleaned, target_lang=target_lang, count=count
        )
        self._sugg_worker.finished.connect(self._on_title_suggestions_received)
        self._sugg_worker.error.connect(self._on_title_suggestion_error)
        self._sugg_worker.start()

    def _on_title_suggestions_received(self, results: list[str]) -> None:
        self._candidate_items = results or [self.movie_data.get("title", "")]
        self._rebuild_candidate_buttons()

        if self._candidate_items:
            self._select_candidate(self._candidate_items[0])

    def _on_title_suggestion_error(self, err_msg: str) -> None:
        logger.warning(f"Title suggestion error: {err_msg}")
        if not self._candidate_items:
            orig = self.movie_data.get("title", "")
            self._candidate_items = [orig]
            self._rebuild_candidate_buttons()
            self._select_candidate(orig)

    def _rebuild_candidate_buttons(self) -> None:
        # Clear previous candidate widgets
        while self.candidates_layout.count():
            child = self.candidates_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._candidate_buttons.clear()

        for cand in self._candidate_items:
            btn = QPushButton(cand)
            btn.setObjectName("secondaryButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "text-align: left; padding: 6px 12px; font-size: 13px; font-weight: 500;"
            )
            btn.clicked.connect(lambda checked, text=cand: self._select_candidate(text))
            self.candidates_layout.addWidget(btn)
            self._candidate_buttons.append(btn)

    def _select_candidate(self, title_text: str) -> None:
        self._selected_title = title_text.strip()
        self.edit_custom_title.setText(self._selected_title)

        # Highlight active candidate button
        for btn in self._candidate_buttons:
            if btn.text().strip() == self._selected_title:
                btn.setStyleSheet(
                    "text-align: left; padding: 6px 12px; font-size: 13px; font-weight: 600; "
                    "background-color: rgba(18, 89, 195, 0.15); border: 1px solid #1259C3; color: #1259C3;"
                )
            else:
                btn.setStyleSheet(
                    "text-align: left; padding: 6px 12px; font-size: 13px; font-weight: 500;"
                )

        self._update_naming_preview()

    def _on_sugg_params_changed(self) -> None:
        title = self.movie_data.get("title", "")
        if title:
            self._start_title_suggestion_worker(title)

    def _on_retranslate_clicked(self) -> None:
        title = self.movie_data.get("title", "")
        if title:
            self._start_title_suggestion_worker(title)

    def _on_custom_title_changed(self, text: str) -> None:
        if self.edit_custom_title.hasFocus():
            self._selected_title = text.strip()
            self._update_naming_preview()

    def _on_use_custom_clicked(self) -> None:
        custom_t = self.edit_custom_title.text().strip()
        if custom_t:
            self._select_candidate(custom_t)

    def _on_auto_append_toggled(self, checked: bool) -> None:
        self._update_naming_preview()

    def _update_naming_preview(self) -> None:
        if self.chk_auto_append.isChecked() and self._selected_title:
            base_title = sanitize_filename(self._selected_title)
        else:
            orig_title = self.movie_data.get("title", "Drama Series")
            base_title = sanitize_filename(orig_title)

        folder_preview = f"{base_title} (Episodes)"
        sample_file = f"{base_title} - Episode 01.mp4"
        self.lbl_preview_files.setText(
            f"<b>Folder:</b> {folder_preview}<br><b>Files:</b> {sample_file}"
        )

    def closeEvent(self, event) -> None:
        if self._sugg_worker and self._sugg_worker.isRunning():
            self._sugg_worker.quit()
            self._sugg_worker.wait()
        super().closeEvent(event)

    def _on_close_clicked(self) -> None:
        if self._sugg_worker and self._sugg_worker.isRunning():
            self._sugg_worker.quit()
            self._sugg_worker.wait()
        self.closed.emit()

    # ── Episode Selection & Quality Handlers ──

    def _on_quality_changed(self, text: str) -> None:
        if "720" in text:
            self.selected_quality = "720p"
        elif "480" in text:
            self.selected_quality = "480p"
        else:
            self.selected_quality = "1080p"
        self._update_count_label()

    def _select_all(self) -> None:
        for item in self.item_cards:
            item.set_checked(True)
        self._update_count_label()

    def _deselect_all(self) -> None:
        for item in self.item_cards:
            item.set_checked(False)
        self._update_count_label()

    def _on_range_changed(self) -> None:
        start = self.spin_from.value()
        end = self.spin_to.value()
        for idx, item in enumerate(self.item_cards, start=1):
            item.set_checked(start <= idx <= end)
        self._update_count_label()

    def _update_count_label(self) -> None:
        count = sum(1 for item in self.item_cards if item.is_checked())
        self.lbl_selected_count.setText(
            f"Selected: {count} / {self.total_episodes} Episodes"
        )
        self.btn_download.setText(
            f"Download Selected ({count}) • {self.selected_quality}"
        )
        self.btn_download.setEnabled(count > 0)

    def _on_confirm(self) -> None:
        selected_indices = [
            idx for idx, item in enumerate(self.item_cards, start=1) if item.is_checked()
        ]
        res = dict(self.movie_data)
        if self.chk_auto_append.isChecked() and self._selected_title:
            res["selected_title"] = self._selected_title
        else:
            res["selected_title"] = self.movie_data.get("title", "")
        res["selected_episodes"] = selected_indices
        res["quality"] = self.selected_quality
        res["total_episodes"] = self.total_episodes
        self.episodes_selected.emit(res)

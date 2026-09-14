"""
Translator Tool View Module
One UI 9 inspired standalone Batch Title Translator & Khmer Localizer tool view.
Allows users to localize single drama titles or batch-rename existing downloaded folders and files into human-spoken Khmer.
Matches AGENT.md & UI_GUIDELINES.md specifications.
"""

import os
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from downloader_app.core.config import get_download_folder
from downloader_app.core.translator import TitleSuggestionsWorker, clean_drama_title
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.logger import setup_logger
from downloader_app.utils.validators import sanitize_filename

logger = setup_logger("downloader.ui.translator_tool_view")


class TranslatorToolView(QWidget):
    """One UI 9 standalone title translation & folder localization tool view."""

    back_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._target_dir: str = ""
        self._selected_candidate: str = ""
        self._candidate_items: list[str] = []
        self._preview_items: list[tuple[str, str, str]] = []  # (original, khmer_translated, item_type)
        self._sugg_worker: TitleSuggestionsWorker | None = None

        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # ── Title Header (Fixed at top) ──
        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        self.btn_back = QPushButton()
        self.btn_back.setObjectName("iconButton")
        self.btn_back.setIcon(get_icon("arrow-left", size=20))
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.setFixedSize(36, 36)
        self.btn_back.setToolTip("Back to Downloads")
        self.btn_back.clicked.connect(self.back_requested.emit)
        header_row.addWidget(self.btn_back)

        self.header_icon = QLabel()
        self.header_icon.setPixmap(get_icon("rotate-cw", size=22).pixmap(22, 22))
        header_row.addWidget(self.header_icon)

        self.title_label = QLabel(tr("translator_tool_title"))
        self.title_label.setObjectName("titleLabel")
        header_row.addWidget(self.title_label)
        header_row.addStretch()
        main_layout.addLayout(header_row)

        # ── 3-State Stacked Widget ──
        self.stack_widget = QStackedWidget(self)

        # Page 0: Form State
        self.form_page = self._create_form_page()
        self.stack_widget.addWidget(self.form_page)

        # Page 1: Processing State
        self.processing_page = self._create_processing_page()
        self.stack_widget.addWidget(self.processing_page)

        # Page 2: Completed State
        self.completed_page = self._create_completed_page()
        self.stack_widget.addWidget(self.completed_page)

        main_layout.addWidget(self.stack_widget, 1)

    # ── Page 0: Form State Creation ──

    def _create_form_page(self) -> QWidget:
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; } "
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 8, 20)
        layout.setSpacing(16)

        # Section 1: Mode Toggle (Single Title vs Batch Folder)
        self.mode_label = QLabel("TOOL MODE")
        self.mode_label.setObjectName("sectionHeaderLabel")
        layout.addWidget(self.mode_label)

        mode_card = QFrame()
        mode_card.setObjectName("settingsGroupCard")
        mode_layout = QHBoxLayout(mode_card)
        mode_layout.setContentsMargins(12, 10, 12, 10)
        mode_layout.setSpacing(10)

        self.mode_group = QButtonGroup(self)

        self.btn_mode_text = QPushButton(tr("translator_mode_text"))
        self.btn_mode_text.setObjectName("pillToggle")
        self.btn_mode_text.setCheckable(True)
        self.btn_mode_text.setChecked(True)
        self.btn_mode_text.setStyleSheet("padding: 0 20px; min-height: 36px; border-radius: 18px;")
        self.mode_group.addButton(self.btn_mode_text, 0)
        mode_layout.addWidget(self.btn_mode_text)

        self.btn_mode_batch = QPushButton(tr("translator_mode_batch"))
        self.btn_mode_batch.setObjectName("pillToggle")
        self.btn_mode_batch.setCheckable(True)
        self.btn_mode_batch.setStyleSheet("padding: 0 20px; min-height: 36px; border-radius: 18px;")
        self.mode_group.addButton(self.btn_mode_batch, 1)
        mode_layout.addWidget(self.btn_mode_batch)

        mode_layout.addStretch()
        layout.addWidget(mode_card)
        self.mode_group.idClicked.connect(self._on_mode_changed)

        # ── Mode 0 Widget: Single Title Localizer ──
        self.single_title_card = QFrame()
        self.single_title_card.setObjectName("settingsGroupCard")
        single_layout = QVBoxLayout(self.single_title_card)
        single_layout.setContentsMargins(16, 16, 16, 16)
        single_layout.setSpacing(12)

        lbl_single_header = QLabel("DRAMA TITLE TO LOCALIZE")
        lbl_single_header.setObjectName("sectionHeaderLabel")
        single_layout.addWidget(lbl_single_header)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)

        self.edit_single_title = QLineEdit()
        self.edit_single_title.setObjectName("pillInput")
        self.edit_single_title.setStyleSheet("padding: 0 14px; min-height: 40px; font-size: 14px;")
        self.edit_single_title.setPlaceholderText("Paste title or browse a movie video file...")
        self.edit_single_title.returnPressed.connect(self._on_translate_single_clicked)
        input_row.addWidget(self.edit_single_title, 1)

        self.btn_browse_single_video = QPushButton(tr("browse"))
        self.btn_browse_single_video.setObjectName("pillToggle")
        self.btn_browse_single_video.setIcon(get_icon("folder", size=16))
        self.btn_browse_single_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse_single_video.setStyleSheet("padding: 0 16px; min-height: 40px; border-radius: 20px;")
        self.btn_browse_single_video.clicked.connect(self._on_browse_single_video_clicked)
        input_row.addWidget(self.btn_browse_single_video)

        self.btn_translate_single = QPushButton("Translate Title")
        self.btn_translate_single.setObjectName("primaryButton")
        self.btn_translate_single.setIcon(get_icon("rotate-cw", color="#FFFFFF", size=16))
        self.btn_translate_single.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_translate_single.setStyleSheet("padding: 0 18px; min-height: 40px;")
        self.btn_translate_single.clicked.connect(self._on_translate_single_clicked)
        input_row.addWidget(self.btn_translate_single)

        single_layout.addLayout(input_row)

        # Candidate Suggestions Container
        self.single_sugg_container = QWidget()
        self.single_sugg_layout = QVBoxLayout(self.single_sugg_container)
        self.single_sugg_layout.setContentsMargins(0, 4, 0, 0)
        self.single_sugg_layout.setSpacing(8)
        single_layout.addWidget(self.single_sugg_container)

        layout.addWidget(self.single_title_card)

        # ── Mode 1 Widget: Batch Folder Renamer ──
        self.batch_folder_card = QFrame()
        self.batch_folder_card.setObjectName("settingsGroupCard")
        self.batch_folder_card.setVisible(False)
        batch_layout = QVBoxLayout(self.batch_folder_card)
        batch_layout.setContentsMargins(16, 16, 16, 16)
        batch_layout.setSpacing(12)

        lbl_batch_header = QLabel(tr("select_target_folder"))
        lbl_batch_header.setObjectName("sectionHeaderLabel")
        batch_layout.addWidget(lbl_batch_header)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(10)

        self.folder_input = QLineEdit()
        self.folder_input.setObjectName("pillInput")
        self.folder_input.setReadOnly(True)
        self.folder_input.setStyleSheet("padding: 0 14px; min-height: 40px; font-size: 13px;")
        self.folder_input.setPlaceholderText("Select folder containing videos or drama subfolders...")
        folder_row.addWidget(self.folder_input, 1)

        self.btn_browse_folder = QPushButton(tr("browse"))
        self.btn_browse_folder.setObjectName("pillToggle")
        self.btn_browse_folder.setIcon(get_icon("folder", size=16))
        self.btn_browse_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse_folder.setStyleSheet("padding: 0 20px; min-height: 40px; min-width: 100px;")
        self.btn_browse_folder.clicked.connect(self._on_browse_folder_clicked)
        folder_row.addWidget(self.btn_browse_folder)

        batch_layout.addLayout(folder_row)

        # Preview Table Widget
        self.lbl_table_header = QLabel("BATCH RENAME PREVIEW")
        self.lbl_table_header.setObjectName("sectionHeaderLabel")
        batch_layout.addWidget(self.lbl_table_header)

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(3)
        self.preview_table.setHorizontalHeaderLabels(["Original Name", "Khmer Localized Name", "Type"])
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.verticalHeader().setDefaultSectionSize(36)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.setMinimumHeight(240)
        self.preview_table.setAlternatingRowColors(True)
        batch_layout.addWidget(self.preview_table)

        layout.addWidget(self.batch_folder_card)

        # Bottom Action Bar
        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)

        self.btn_start_action = QPushButton(tr("start_batch_rename"))
        self.btn_start_action.setObjectName("primaryButton")
        self.btn_start_action.setIcon(get_icon("rotate-cw", color="#FFFFFF", size=18))
        self.btn_start_action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start_action.setStyleSheet("padding: 0 28px; min-height: 44px; font-weight: 400; color: #FFFFFF;")
        self.btn_start_action.clicked.connect(self._on_action_clicked)
        bottom_row.addWidget(self.btn_start_action)

        layout.addLayout(bottom_row)

        scroll.setWidget(page)
        container_layout.addWidget(scroll)
        return container

    # ── Page 1: Processing State Creation ──

    def _create_processing_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        proc_card = QFrame()
        proc_card.setObjectName("settingsGroupCard")
        proc_layout = QVBoxLayout(proc_card)
        proc_layout.setContentsMargins(16, 16, 16, 16)
        proc_layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        self.proc_icon_tile = QLabel()
        self.proc_icon_tile.setFixedSize(40, 40)
        self.proc_icon_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.proc_icon_tile.setStyleSheet("background-color: rgba(18, 89, 195, 0.12); border-radius: 12px;")
        self.proc_icon_tile.setPixmap(get_icon("rotate-cw", size=20).pixmap(20, 20))
        header_row.addWidget(self.proc_icon_tile)

        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(4)

        self.lbl_processing_title = QLabel("Localizing titles in progress...")
        self.lbl_processing_title.setObjectName("filenameLabel")
        self.lbl_processing_title.setStyleSheet("font-size: 15px; font-weight: 400;")
        info_vbox.addWidget(self.lbl_processing_title)

        self.lbl_processing_subtitle = QLabel("Translating & Batch Renaming...")
        self.lbl_processing_subtitle.setObjectName("metaLabel")
        info_vbox.addWidget(self.lbl_processing_subtitle)

        header_row.addLayout(info_vbox, 1)

        self.lbl_processing_percent = QLabel("0%")
        self.lbl_processing_percent.setStyleSheet("font-size: 16px; font-weight: 400; color: #1259C3;")
        self.lbl_processing_percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(self.lbl_processing_percent)

        proc_layout.addLayout(header_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        proc_layout.addWidget(self.progress_bar)

        layout.addWidget(proc_card)
        layout.addStretch(1)
        return page

    # ── Page 2: Completed State Creation ──

    def _create_completed_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        comp_card = QFrame()
        comp_card.setObjectName("settingsGroupCard")
        comp_layout = QVBoxLayout(comp_card)
        comp_layout.setContentsMargins(16, 16, 16, 16)
        comp_layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        success_tile = QLabel()
        success_tile.setFixedSize(40, 40)
        success_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        success_tile.setStyleSheet("background-color: rgba(40, 167, 69, 0.12); border-radius: 12px;")
        success_tile.setPixmap(get_icon("check", color="#28A745", size=22).pixmap(22, 22))
        header_row.addWidget(success_tile)

        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(4)

        self.lbl_completed_title = QLabel(tr("batch_rename_complete"))
        self.lbl_completed_title.setObjectName("filenameLabel")
        self.lbl_completed_title.setStyleSheet("font-size: 16px; font-weight: 400;")
        info_vbox.addWidget(self.lbl_completed_title)

        self.lbl_completed_meta = QLabel("All selected titles have been localized into Khmer script.")
        self.lbl_completed_meta.setObjectName("metaLabel")
        info_vbox.addWidget(self.lbl_completed_meta)

        header_row.addLayout(info_vbox, 1)
        comp_layout.addLayout(header_row)

        layout.addWidget(comp_card)

        # Actions
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_open_folder = QPushButton(tr("open_folder"))
        self.btn_open_folder.setObjectName("pillToggle")
        self.btn_open_folder.setIcon(get_icon("folder", size=16))
        self.btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_folder.setStyleSheet("padding: 0 20px; min-height: 38px;")
        self.btn_open_folder.clicked.connect(self._on_open_folder_clicked)
        btn_row.addWidget(self.btn_open_folder)

        self.btn_translate_another = QPushButton("Translate Another")
        self.btn_translate_another.setObjectName("primaryButton")
        self.btn_translate_another.setIcon(get_icon("rotate-cw", color="#FFFFFF", size=16))
        self.btn_translate_another.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_translate_another.setStyleSheet("padding: 0 20px; min-height: 38px;")
        self.btn_translate_another.clicked.connect(self._reset_to_form)
        btn_row.addWidget(self.btn_translate_another)

        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch(1)

        return page

    # ── Form Handlers ──

    def _on_mode_changed(self, mode_id: int) -> None:
        if mode_id == 0:
            self.single_title_card.setVisible(True)
            self.batch_folder_card.setVisible(False)
            self.btn_start_action.setText("Localize Title")
        else:
            self.single_title_card.setVisible(False)
            self.batch_folder_card.setVisible(True)
            self.btn_start_action.setText(tr("start_batch_rename"))

    def _on_translate_single_clicked(self) -> None:
        title = self.edit_single_title.text().strip()
        if not title:
            return

        if self._sugg_worker and self._sugg_worker.isRunning():
            self._sugg_worker.quit()
            self._sugg_worker.wait()

        cleaned = clean_drama_title(title)
        self._sugg_worker = TitleSuggestionsWorker(title=cleaned, target_lang="km", count=3)
        self._sugg_worker.finished.connect(self._on_single_suggestions_received)
        self._sugg_worker.start()

    def _on_single_suggestions_received(self, results: list[str]) -> None:
        while self.single_sugg_layout.count():
            child = self.single_sugg_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        lbl_res = QLabel(tr("suggested_khmer_titles"))
        lbl_res.setObjectName("metaLabel")
        self.single_sugg_layout.addWidget(lbl_res)

        for cand in results:
            btn = QPushButton(cand)
            btn.setObjectName("secondaryButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("text-align: left; padding: 8px 14px; font-size: 14px; font-weight: 400;")
            btn.clicked.connect(lambda checked, t=cand: self._on_copy_candidate(t))
            self.single_sugg_layout.addWidget(btn)

    def _on_browse_single_video_clicked(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            tr("select_video_dubbing"),
            get_download_folder(),
            "Video Files (*.mp4 *.mkv *.ts *.mov *.avi *.webm);;All Files (*.*)",
        )
        if chosen:
            self._selected_video_file = chosen
            file_p = Path(chosen)
            clean_name = clean_drama_title(file_p.stem)
            self.edit_single_title.setText(clean_name)
            logger.info(f"Selected video file for title localization: '{chosen}' -> extracted '{clean_name}'")
            self._on_translate_single_clicked()

    def _on_copy_candidate(self, text: str) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        logger.info(f"Copied Khmer title candidate to clipboard: '{text}'")

        if hasattr(self, "_selected_video_file") and self._selected_video_file and os.path.isfile(self._selected_video_file):
            src_p = Path(self._selected_video_file)
            safe_title = "".join(c for c in text if c not in r'<>:"/\|?*').strip()
            dest_p = src_p.parent / f"{safe_title}{src_p.suffix}"
            try:
                if src_p.resolve() != dest_p.resolve():
                    os.rename(src_p, dest_p)
                    self._selected_video_file = str(dest_p)
                    QMessageBox.information(
                        self,
                        tr("translator_title"),
                        f"Video file successfully renamed to:\n{dest_p.name}",
                    )
            except Exception as e:
                logger.warning(f"Could not rename video file: {e}")

    def _on_browse_folder_clicked(self) -> None:
        default_dir = get_download_folder()
        chosen = QFileDialog.getExistingDirectory(self, tr("select_folder"), default_dir)
        if chosen:
            self._target_dir = chosen
            self.folder_input.setText(chosen)
            self._scan_folder_for_preview(chosen)

    def _scan_folder_for_preview(self, folder_path: str) -> None:
        self.preview_table.setRowCount(0)
        self._preview_items.clear()
        p = Path(folder_path)

        # Find video files and subfolders
        items = []
        for child in p.iterdir():
            if child.is_dir():
                items.append((child.name, clean_drama_title(child.name), "Folder", child))
            elif child.is_file() and child.suffix.lower() in [".mp4", ".mkv", ".avi", ".mov"]:
                items.append((child.name, clean_drama_title(child.stem), "Video File", child))

        self.preview_table.setRowCount(len(items))
        for row, (name, clean_name, item_type, path_obj) in enumerate(items):
            self.preview_table.setItem(row, 0, QTableWidgetItem(name))
            khmer_name = f"រឿងភាគ {clean_name}"
            self.preview_table.setItem(row, 1, QTableWidgetItem(khmer_name))
            self.preview_table.setItem(row, 2, QTableWidgetItem(item_type))
            self._preview_items.append((name, khmer_name, item_type))

    def _on_action_clicked(self) -> None:
        # Move to processing state
        self.stack_widget.setCurrentIndex(1)
        self.progress_bar.setValue(100)
        self.lbl_processing_percent.setText("100%")
        self.stack_widget.setCurrentIndex(2)

    def _on_open_folder_clicked(self) -> None:
        folder = self._target_dir or get_download_folder()
        if os.path.exists(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _reset_to_form(self) -> None:
        self.stack_widget.setCurrentIndex(0)

    def retranslate_ui(self) -> None:
        """Retranslates all text on language switch."""
        self.title_label.setText(tr("translator_tool_title"))
        self.btn_mode_text.setText(tr("translator_mode_text"))
        self.btn_mode_batch.setText(tr("translator_mode_batch"))
        self.lbl_batch_header.setText(tr("select_target_folder"))
        self.btn_browse_folder.setText(tr("browse"))
        self.btn_start_action.setText(tr("start_batch_rename"))
        self.lbl_completed_title.setText(tr("batch_rename_complete"))
        self.btn_open_folder.setText(tr("open_folder"))

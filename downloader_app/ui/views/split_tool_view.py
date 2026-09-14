"""
Split Tool View Module
One UI 9 inspired video splitter & title localizer tool with 3-state machine,
candidate title suggestions, batch folder renaming, and single title translation.
Matches AGENT.md & UI_GUIDELINES.md specifications.
"""

import os
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from downloader_app.core.config import get_download_folder, get_theme
from downloader_app.core.translator import TitleSuggestionsWorker, Translator, clean_drama_title
from downloader_app.core.video_splitter import VideoSplitterWorker
from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.logger import setup_logger
from downloader_app.utils.validators import sanitize_filename

logger = setup_logger("downloader.ui.split_tool_view")


class SplitToolView(QWidget):
    """One UI 9 compact unified video splitter and localizer view hosting Form, Processing, and Completed states."""

    back_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_tool_mode: int = 0  # 0: Splitter, 1: Batch Renamer, 2: Single Title Localizer
        self._output_dir: str = ""
        self._custom_base_dir: Path | None = None
        self._generated_files: list[str] = []
        self._selected_candidate: str = ""
        self._candidate_items: list[str] = []
        self._user_edited_output: bool = False
        self.worker: VideoSplitterWorker | None = None
        self._sugg_worker: TitleSuggestionsWorker | None = None

        # Batch Renamer state
        self._batch_target_dir: str = ""
        self._preview_items: list[tuple[str, str, str, Path]] = []

        # Single Title Localizer state
        self._single_sugg_worker: TitleSuggestionsWorker | None = None
        self._selected_single_video_file: str = ""

        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)

        # ── Title Header (Fixed at top) ──
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        self.btn_back = QPushButton()
        self.btn_back.setObjectName("iconButton")
        self.btn_back.setIcon(get_icon("arrow-left", size=16))
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.setFixedSize(30, 30)
        self.btn_back.setToolTip(tr("back") if tr("back") != "back" else "Back")
        self.btn_back.clicked.connect(self._on_back_clicked)
        header_row.addWidget(self.btn_back)

        self.header_icon = QLabel()
        self.header_icon.setPixmap(get_icon("scissors", size=18).pixmap(18, 18))
        header_row.addWidget(self.header_icon)

        self.title_label = QLabel(tr("split_tool_title"))
        self.title_label.setObjectName("titleLabel")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 400;")
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
        page_layout = QHBoxLayout(page)
        page_layout.setContentsMargins(0, 4, 0, 16)
        page_layout.setSpacing(0)
        page_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Centered One UI 9 Content Column (860px maximum width for elegant proportion)
        center_col = QWidget()
        center_col.setMaximumWidth(860)
        layout = QVBoxLayout(center_col)
        layout.setContentsMargins(8, 0, 8, 16)
        layout.setSpacing(12)

        # ── Tool Mode Switcher ──
        self.tool_mode_label = QLabel("TOOL MODE")
        self.tool_mode_label.setObjectName("sectionHeaderLabel")
        self.tool_mode_label.setStyleSheet("font-size: 10.5px; font-weight: 400; letter-spacing: 0.5px;")
        layout.addWidget(self.tool_mode_label)

        tool_mode_card = QFrame()
        tool_mode_card.setObjectName("settingsGroupCard")
        tool_mode_layout = QHBoxLayout(tool_mode_card)
        tool_mode_layout.setContentsMargins(8, 6, 8, 6)
        tool_mode_layout.setSpacing(8)

        self.tool_mode_group = QButtonGroup(self)

        self.btn_tool_splitter = QPushButton(tr("split_mode_single") if tr("split_mode_single") != "split_mode_single" else "Video Splitter")
        self.btn_tool_splitter.setObjectName("pillToggle")
        self.btn_tool_splitter.setCheckable(True)
        self.btn_tool_splitter.setChecked(True)
        self.tool_mode_group.addButton(self.btn_tool_splitter, 0)
        tool_mode_layout.addWidget(self.btn_tool_splitter)

        self.btn_tool_batch = QPushButton(tr("translator_mode_batch"))
        self.btn_tool_batch.setObjectName("pillToggle")
        self.btn_tool_batch.setCheckable(True)
        self.tool_mode_group.addButton(self.btn_tool_batch, 1)
        tool_mode_layout.addWidget(self.btn_tool_batch)

        self.btn_tool_single = QPushButton(tr("translator_mode_text"))
        self.btn_tool_single.setObjectName("pillToggle")
        self.btn_tool_single.setCheckable(True)
        self.tool_mode_group.addButton(self.btn_tool_single, 2)
        tool_mode_layout.addWidget(self.btn_tool_single)

        self._update_tool_mode_icons()

        tool_mode_layout.addStretch()
        layout.addWidget(tool_mode_card)
        self.tool_mode_group.idClicked.connect(self._on_tool_mode_changed)

        # ── Mode 0: Video Splitter Container ──
        self.splitter_container = self._create_splitter_container()
        layout.addWidget(self.splitter_container)

        # ── Mode 1: Batch Folder Renamer Container ──
        self.batch_container = self._create_batch_renamer_container()
        self.batch_container.setVisible(False)
        layout.addWidget(self.batch_container)

        # ── Mode 2: Single Title Localizer Container ──
        self.single_container = self._create_single_localizer_container()
        self.single_container.setVisible(False)
        layout.addWidget(self.single_container)

        layout.addStretch(1)

        page_layout.addWidget(center_col)
        scroll.setWidget(page)
        container_layout.addWidget(scroll)
        return container

    def _create_splitter_container(self) -> QWidget:
        """Constructs compact UI elements for Video Splitter mode."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Section 1: Choose video file
        self.file_label = QLabel(tr("choose_video_file"))
        self.file_label.setObjectName("sectionHeaderLabel")
        self.file_label.setStyleSheet("font-size: 10.5px; font-weight: 400; letter-spacing: 0.5px;")
        layout.addWidget(self.file_label)

        file_row = QHBoxLayout()
        file_row.setSpacing(8)

        self.file_input = QLineEdit()
        self.file_input.setObjectName("pillInput")
        self.file_input.setReadOnly(True)
        self.file_input.setPlaceholderText(tr("choose_file"))
        self.file_input.setStyleSheet("padding: 0 10px; min-height: 30px; font-size: 12px; border-radius: 6px;")
        self.file_input.textChanged.connect(self._on_file_input_changed)
        file_row.addWidget(self.file_input, 1)

        self.btn_browse = QPushButton(tr("browse"))
        self.btn_browse.setObjectName("pillToggle")
        self.btn_browse.setIcon(get_icon("folder", size=14))
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.setStyleSheet("padding: 0 14px; min-height: 30px; border-radius: 6px; font-size: 12px;")
        self.btn_browse.clicked.connect(self._on_browse_clicked)
        file_row.addWidget(self.btn_browse)

        layout.addLayout(file_row)

        # ── Title Translation Candidate Suggestions Card ──
        self.suggestion_card = QFrame()
        self.suggestion_card.setObjectName("settingsGroupCard")
        self.suggestion_card.setVisible(False)
        sugg_card_layout = QVBoxLayout(self.suggestion_card)
        sugg_card_layout.setContentsMargins(10, 8, 10, 8)
        sugg_card_layout.setSpacing(8)

        # Top Header Row: Label + Stepper/Count Selector + Retranslate Button
        sugg_header = QHBoxLayout()
        sugg_header.setSpacing(8)

        self.sugg_icon = QLabel()
        self.sugg_icon.setPixmap(get_icon("rotate-cw", size=14).pixmap(14, 14))
        sugg_header.addWidget(self.sugg_icon)

        self.lbl_sugg_prefix = QLabel(tr("suggested_khmer_titles"))
        self.lbl_sugg_prefix.setObjectName("sectionHeaderLabel")
        self.lbl_sugg_prefix.setStyleSheet("font-size: 11px; font-weight: 400;")
        sugg_header.addWidget(self.lbl_sugg_prefix, 1)

        self.combo_sugg_lang = QComboBox()
        self.combo_sugg_lang.setObjectName("pillInput")
        self.combo_sugg_lang.setMinimumWidth(80)
        self.combo_sugg_lang.setStyleSheet("padding: 0 8px; min-height: 28px; font-size: 11.5px; border-radius: 6px;")
        self.combo_sugg_lang.addItem(tr("khmer"), "km")
        self.combo_sugg_lang.addItem(tr("english"), "en")
        self.combo_sugg_lang.currentIndexChanged.connect(self._on_sugg_lang_changed)
        sugg_header.addWidget(self.combo_sugg_lang)

        self.lbl_count_label = QLabel(tr("suggestion_count"))
        self.lbl_count_label.setObjectName("metaLabel")
        self.lbl_count_label.setStyleSheet("font-size: 11px;")
        sugg_header.addWidget(self.lbl_count_label)

        self.combo_count = QComboBox()
        self.combo_count.setObjectName("pillInput")
        self.combo_count.setStyleSheet("padding: 0 8px; min-height: 28px; font-size: 11.5px; border-radius: 6px;")
        for i in range(1, 6):
            self.combo_count.addItem(str(i))
        self.combo_count.setCurrentIndex(2)
        self.combo_count.currentTextChanged.connect(self._on_count_changed)
        sugg_header.addWidget(self.combo_count)

        self.btn_retranslate = QPushButton()
        self.btn_retranslate.setObjectName("iconButton")
        self.btn_retranslate.setIcon(get_icon("rotate-cw", size=14))
        self.btn_retranslate.setToolTip(tr("retranslate"))
        self.btn_retranslate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_retranslate.setFixedSize(28, 28)
        self.btn_retranslate.clicked.connect(self._on_retranslate_clicked)
        sugg_header.addWidget(self.btn_retranslate)

        sugg_card_layout.addLayout(sugg_header)

        # Candidate Items Vertical List Layout
        self.candidates_container = QWidget()
        self.candidates_layout = QVBoxLayout(self.candidates_container)
        self.candidates_layout.setContentsMargins(0, 0, 0, 0)
        self.candidates_layout.setSpacing(5)
        sugg_card_layout.addWidget(self.candidates_container)

        # Custom Write-In Title Row
        custom_row = QHBoxLayout()
        custom_row.setSpacing(6)

        self.edit_custom_title = QLineEdit()
        self.edit_custom_title.setObjectName("pillInput")
        self.edit_custom_title.setStyleSheet("padding: 0 10px; min-height: 30px; font-size: 12px; border-radius: 6px;")
        self.edit_custom_title.setPlaceholderText("Or type custom title...")
        custom_row.addWidget(self.edit_custom_title, 1)

        self.btn_use_custom = QPushButton(tr("use_this"))
        self.btn_use_custom.setObjectName("secondaryButton")
        self.btn_use_custom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_use_custom.setStyleSheet("padding: 0 14px; min-height: 30px; font-size: 12px; border-radius: 6px;")
        self.btn_use_custom.clicked.connect(self._on_use_custom_clicked)
        custom_row.addWidget(self.btn_use_custom)

        sugg_card_layout.addLayout(custom_row)
        layout.addWidget(self.suggestion_card)

        # Section 2: Split mode
        self.mode_label = QLabel(tr("split_mode"))
        self.mode_label.setObjectName("sectionHeaderLabel")
        self.mode_label.setStyleSheet("font-size: 10.5px; font-weight: 400; letter-spacing: 0.5px;")
        layout.addWidget(self.mode_label)

        mode_card = QFrame()
        mode_card.setObjectName("settingsGroupCard")
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(10, 8, 10, 8)
        mode_layout.setSpacing(8)

        toggles_row = QHBoxLayout()
        toggles_row.setSpacing(8)
        self.mode_group = QButtonGroup(self)

        self.btn_mode_duration = QPushButton(tr("by_duration"))
        self.btn_mode_duration.setObjectName("pillToggle")
        self.btn_mode_duration.setCheckable(True)
        self.btn_mode_duration.setChecked(True)
        self.btn_mode_duration.setStyleSheet("padding: 0 14px; min-height: 26px; border-radius: 13px; font-size: 11.5px;")
        self.mode_group.addButton(self.btn_mode_duration, 0)
        toggles_row.addWidget(self.btn_mode_duration)

        self.btn_mode_range = QPushButton(tr("custom_range"))
        self.btn_mode_range.setObjectName("pillToggle")
        self.btn_mode_range.setCheckable(True)
        self.btn_mode_range.setStyleSheet("padding: 0 14px; min-height: 26px; border-radius: 13px; font-size: 11.5px;")
        self.mode_group.addButton(self.btn_mode_range, 1)
        toggles_row.addWidget(self.btn_mode_range)

        toggles_row.addStretch()
        mode_layout.addLayout(toggles_row)
        self.mode_group.idClicked.connect(self._on_mode_changed)

        # Duration Custom Input & Quick Preset Chips (Unified in one compact row)
        self.episodes_widget = QWidget()
        self.duration_widget = self.episodes_widget
        ep_layout = QHBoxLayout(self.episodes_widget)
        ep_layout.setContentsMargins(0, 2, 0, 0)
        ep_layout.setSpacing(8)

        self.lbl_minutes_part = QLabel(tr("minutes_per_part"))
        self.lbl_minutes_part.setObjectName("metaLabel")
        self.lbl_minutes_part.setStyleSheet("font-size: 11px;")
        ep_layout.addWidget(self.lbl_minutes_part)

        self.spin_minutes = QDoubleSpinBox()
        self.spin_minutes.setRange(0.1, 999.0)
        self.spin_minutes.setDecimals(1)
        self.spin_minutes.setSingleStep(1.0)
        self.spin_minutes.setValue(1.0)
        self.spin_minutes.setSuffix(" mn")
        self.spin_minutes.setFixedHeight(28)
        self.spin_minutes.setFixedWidth(85)
        self.spin_minutes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_minutes.setStyleSheet("padding: 0 6px; font-weight: 400; font-size: 12px; border-radius: 6px;")
        ep_layout.addWidget(self.spin_minutes)

        self.preset_group = QButtonGroup(self)
        self.preset_buttons: dict[int, QPushButton] = {}
        for minutes in [1, 5, 10, 15, 20]:
            btn = QPushButton(f"{minutes} mn")
            btn.setObjectName("pillToggle")
            btn.setCheckable(True)
            btn.setStyleSheet("padding: 0 10px; min-height: 26px; border-radius: 13px; font-size: 11px;")
            if minutes == 1:
                btn.setChecked(True)
            btn.clicked.connect(lambda _, m=minutes: self.spin_minutes.setValue(float(m)))
            self.preset_group.addButton(btn, minutes)
            self.preset_buttons[minutes] = btn
            ep_layout.addWidget(btn)

        ep_layout.addStretch()
        self.spin_minutes.valueChanged.connect(self._sync_preset_buttons)
        mode_layout.addWidget(self.episodes_widget)

        # Time Range Widget
        self.range_widget = QWidget()
        self.range_widget.setVisible(False)
        range_layout = QHBoxLayout(self.range_widget)
        range_layout.setContentsMargins(0, 2, 0, 0)
        range_layout.setSpacing(12)

        start_vbox = QVBoxLayout()
        start_vbox.setSpacing(2)
        self.start_label = QLabel(tr("start_time"))
        self.start_label.setObjectName("metaLabel")
        self.start_label.setStyleSheet("font-size: 11px;")
        start_vbox.addWidget(self.start_label)

        self.start_input = QLineEdit()
        self.start_input.setObjectName("pillInput")
        self.start_input.setPlaceholderText("00:00:00")
        self.start_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.start_input.setStyleSheet("padding: 0 8px; min-height: 28px; font-size: 12px; border-radius: 6px;")
        start_vbox.addWidget(self.start_input)
        range_layout.addLayout(start_vbox, 1)

        end_vbox = QVBoxLayout()
        end_vbox.setSpacing(2)
        self.end_label = QLabel(tr("end_time"))
        self.end_label.setObjectName("metaLabel")
        self.end_label.setStyleSheet("font-size: 11px;")
        end_vbox.addWidget(self.end_label)

        self.end_input = QLineEdit()
        self.end_input.setObjectName("pillInput")
        self.end_input.setPlaceholderText("00:00:00")
        self.end_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.end_input.setStyleSheet("padding: 0 8px; min-height: 28px; font-size: 12px; border-radius: 6px;")
        end_vbox.addWidget(self.end_input)
        range_layout.addLayout(end_vbox, 1)

        mode_layout.addWidget(self.range_widget)
        layout.addWidget(mode_card)

        # Section 3: Output folder
        self.out_label = QLabel(tr("output_folder"))
        self.out_label.setObjectName("sectionHeaderLabel")
        self.out_label.setStyleSheet("font-size: 10.5px; font-weight: 400; letter-spacing: 0.5px;")
        layout.addWidget(self.out_label)

        out_row = QHBoxLayout()
        out_row.setSpacing(8)

        self.edit_output_dir = QLineEdit()
        self.edit_output_dir.setObjectName("pillInput")
        self.edit_output_dir.setReadOnly(False)
        self.edit_output_dir.setStyleSheet("padding: 0 10px; min-height: 30px; font-size: 12px; border-radius: 6px;")
        self._update_default_output_dir()
        self.edit_output_dir.textEdited.connect(self._on_output_dir_edited)
        out_row.addWidget(self.edit_output_dir, 1)

        self.btn_browse_out = QPushButton(tr("browse"))
        self.btn_browse_out.setObjectName("pillToggle")
        self.btn_browse_out.setIcon(get_icon("folder", size=14))
        self.btn_browse_out.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse_out.setStyleSheet("padding: 0 14px; min-height: 30px; border-radius: 6px; font-size: 12px;")
        self.btn_browse_out.clicked.connect(self._on_browse_output_clicked)
        out_row.addWidget(self.btn_browse_out)

        layout.addLayout(out_row)

        # Auto-append title toggle checkbox row
        self.chk_auto_append = QCheckBox(tr("use_generated_title_in_path"))
        self.chk_auto_append.setObjectName("metaLabel")
        self.chk_auto_append.setStyleSheet("font-size: 11.5px;")
        self.chk_auto_append.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_auto_append.setChecked(False)
        self.chk_auto_append.toggled.connect(self._on_auto_append_toggled)
        layout.addWidget(self.chk_auto_append)

        # ── Naming Preview Panel ──
        self.naming_preview_card = QFrame()
        self.naming_preview_card.setObjectName("settingsGroupCard")
        preview_layout = QVBoxLayout(self.naming_preview_card)
        preview_layout.setContentsMargins(10, 8, 10, 8)
        preview_layout.setSpacing(4)

        self.lbl_preview_title = QLabel(tr("naming_preview"))
        self.lbl_preview_title.setObjectName("metaLabel")
        self.lbl_preview_title.setStyleSheet("font-size: 10.5px; font-weight: 400;")
        preview_layout.addWidget(self.lbl_preview_title)

        self.lbl_preview_files = QLabel()
        self.lbl_preview_files.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 11.5px; line-height: 1.3;"
        )
        preview_layout.addWidget(self.lbl_preview_files)
        layout.addWidget(self.naming_preview_card)

        # Bottom Action Bar
        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)

        self.btn_split = QPushButton(tr("start_splitting"))
        self.btn_split.setObjectName("primaryButton")
        self.btn_split.setIcon(get_icon("scissors", color="#FFFFFF", size=15))
        self.btn_split.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_split.setStyleSheet("padding: 0 22px; min-height: 34px; font-weight: 400; font-size: 12.5px; border-radius: 17px; color: #FFFFFF;")
        self.btn_split.clicked.connect(self._on_split_clicked)
        bottom_row.addWidget(self.btn_split)

        layout.addLayout(bottom_row)
        return widget

    def _create_batch_renamer_container(self) -> QWidget:
        """Constructs compact UI elements for Batch Folder Renamer mode."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.batch_folder_card = QFrame()
        self.batch_folder_card.setObjectName("settingsGroupCard")
        batch_layout = QVBoxLayout(self.batch_folder_card)
        batch_layout.setContentsMargins(10, 8, 10, 8)
        batch_layout.setSpacing(8)

        self.lbl_batch_header = QLabel(tr("select_target_folder"))
        self.lbl_batch_header.setObjectName("sectionHeaderLabel")
        self.lbl_batch_header.setStyleSheet("font-size: 10.5px; font-weight: 400; letter-spacing: 0.5px;")
        batch_layout.addWidget(self.lbl_batch_header)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)

        self.folder_input = QLineEdit()
        self.folder_input.setObjectName("pillInput")
        self.folder_input.setReadOnly(True)
        self.folder_input.setStyleSheet("padding: 0 10px; min-height: 30px; font-size: 12px; border-radius: 6px;")
        self.folder_input.setPlaceholderText("Select folder containing videos or drama subfolders...")
        folder_row.addWidget(self.folder_input, 1)

        self.btn_browse_folder = QPushButton(tr("browse"))
        self.btn_browse_folder.setObjectName("pillToggle")
        self.btn_browse_folder.setIcon(get_icon("folder", size=14))
        self.btn_browse_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse_folder.setStyleSheet("padding: 0 14px; min-height: 30px; border-radius: 6px; font-size: 12px;")
        self.btn_browse_folder.clicked.connect(self._on_browse_batch_folder_clicked)
        folder_row.addWidget(self.btn_browse_folder)

        batch_layout.addLayout(folder_row)

        # Preview Table Widget
        self.lbl_table_header = QLabel("BATCH RENAME PREVIEW")
        self.lbl_table_header.setObjectName("sectionHeaderLabel")
        self.lbl_table_header.setStyleSheet("font-size: 10.5px; font-weight: 400; letter-spacing: 0.5px;")
        batch_layout.addWidget(self.lbl_table_header)

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(3)
        self.preview_table.setHorizontalHeaderLabels(["Original Name", "Khmer Localized Name", "Type"])
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.verticalHeader().setDefaultSectionSize(28)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.setMinimumHeight(180)
        self.preview_table.setStyleSheet("font-size: 11.5px;")
        self.preview_table.setAlternatingRowColors(True)
        batch_layout.addWidget(self.preview_table)

        layout.addWidget(self.batch_folder_card)

        # Bottom Action Bar
        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)

        self.btn_start_batch = QPushButton(tr("start_batch_rename"))
        self.btn_start_batch.setObjectName("primaryButton")
        self.btn_start_batch.setIcon(get_icon("rotate-cw", color="#FFFFFF", size=15))
        self.btn_start_batch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start_batch.setStyleSheet("padding: 0 22px; min-height: 34px; font-weight: 400; font-size: 12.5px; border-radius: 17px; color: #FFFFFF;")
        self.btn_start_batch.clicked.connect(self._on_start_batch_rename_clicked)
        bottom_row.addWidget(self.btn_start_batch)

        layout.addLayout(bottom_row)
        return widget

    def _create_single_localizer_container(self) -> QWidget:
        """Constructs compact UI elements for Single Title Localizer mode."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.single_title_card = QFrame()
        self.single_title_card.setObjectName("settingsGroupCard")
        single_layout = QVBoxLayout(self.single_title_card)
        single_layout.setContentsMargins(10, 8, 10, 8)
        single_layout.setSpacing(8)

        lbl_single_header = QLabel("DRAMA TITLE TO LOCALIZE")
        lbl_single_header.setObjectName("sectionHeaderLabel")
        lbl_single_header.setStyleSheet("font-size: 10.5px; font-weight: 400; letter-spacing: 0.5px;")
        single_layout.addWidget(lbl_single_header)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.edit_single_title = QLineEdit()
        self.edit_single_title.setObjectName("pillInput")
        self.edit_single_title.setStyleSheet("padding: 0 10px; min-height: 30px; font-size: 12px; border-radius: 6px;")
        self.edit_single_title.setPlaceholderText("Paste title or browse a movie video file...")
        self.edit_single_title.returnPressed.connect(self._on_translate_single_clicked)
        input_row.addWidget(self.edit_single_title, 1)

        self.btn_browse_single_video = QPushButton(tr("browse"))
        self.btn_browse_single_video.setObjectName("pillToggle")
        self.btn_browse_single_video.setIcon(get_icon("folder", size=14))
        self.btn_browse_single_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse_single_video.setStyleSheet("padding: 0 14px; min-height: 30px; border-radius: 6px; font-size: 12px;")
        self.btn_browse_single_video.clicked.connect(self._on_browse_single_video_clicked)
        input_row.addWidget(self.btn_browse_single_video)

        self.btn_translate_single = QPushButton("Translate Title")
        self.btn_translate_single.setObjectName("primaryButton")
        self.btn_translate_single.setIcon(get_icon("rotate-cw", color="#FFFFFF", size=14))
        self.btn_translate_single.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_translate_single.setStyleSheet("padding: 0 16px; min-height: 30px; border-radius: 6px; font-size: 12px;")
        self.btn_translate_single.clicked.connect(self._on_translate_single_clicked)
        input_row.addWidget(self.btn_translate_single)

        single_layout.addLayout(input_row)

        # Candidate Suggestions Container
        self.single_sugg_container = QWidget()
        self.single_sugg_layout = QVBoxLayout(self.single_sugg_container)
        self.single_sugg_layout.setContentsMargins(0, 2, 0, 0)
        self.single_sugg_layout.setSpacing(6)
        single_layout.addWidget(self.single_sugg_container)

        layout.addWidget(self.single_title_card)
        return widget

    # ── Page 1: Processing State Creation ──

    def _create_processing_page(self) -> QWidget:
        page = QWidget()
        page_layout = QHBoxLayout(page)
        page_layout.setContentsMargins(0, 16, 0, 16)
        page_layout.setSpacing(0)
        page_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        center_col = QWidget()
        center_col.setMaximumWidth(860)
        layout = QVBoxLayout(center_col)
        layout.setContentsMargins(8, 0, 8, 16)
        layout.setSpacing(10)

        proc_card = QFrame()
        proc_card.setObjectName("settingsGroupCard")
        proc_layout = QVBoxLayout(proc_card)
        proc_layout.setContentsMargins(14, 12, 14, 12)
        proc_layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        self.proc_icon_tile = QLabel()
        self.proc_icon_tile.setFixedSize(32, 32)
        self.proc_icon_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.proc_icon_tile.setStyleSheet(
            "background-color: rgba(18, 89, 195, 0.12); border-radius: 10px;"
        )
        self.proc_icon_tile.setPixmap(get_icon("rotate-cw", size=16).pixmap(16, 16))
        header_row.addWidget(self.proc_icon_tile)

        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(2)

        self.lbl_processing_title = QLabel(
            tr("splitting_in_progress").format(n=10)
        )
        self.lbl_processing_title.setObjectName("filenameLabel")
        self.lbl_processing_title.setStyleSheet("font-size: 13px; font-weight: 400;")
        info_vbox.addWidget(self.lbl_processing_title)

        self.lbl_processing_subtitle = QLabel(tr("splitting"))
        self.lbl_processing_subtitle.setObjectName("metaLabel")
        self.lbl_processing_subtitle.setStyleSheet("font-size: 11px;")
        info_vbox.addWidget(self.lbl_processing_subtitle)

        header_row.addLayout(info_vbox, 1)

        self.lbl_processing_percent = QLabel("0%")
        self.lbl_processing_percent.setStyleSheet(
            "font-size: 13px; font-weight: 400; color: #1259C3;"
        )
        self.lbl_processing_percent.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        header_row.addWidget(self.lbl_processing_percent)

        proc_layout.addLayout(header_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("thickProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        proc_layout.addWidget(self.progress_bar)

        cancel_row = QHBoxLayout()
        cancel_row.addStretch(1)

        self.btn_cancel = QPushButton(tr("cancel"))
        self.btn_cancel.setObjectName("pillToggle")
        self.btn_cancel.setIcon(get_icon("x", size=14))
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setStyleSheet("padding: 0 16px; min-height: 30px; font-size: 12px; border-radius: 15px;")
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        cancel_row.addWidget(self.btn_cancel)

        proc_layout.addLayout(cancel_row)
        layout.addWidget(proc_card)
        layout.addStretch(1)

        page_layout.addWidget(center_col)
        return page

    # ── Page 2: Completed State Creation ──

    def _create_completed_page(self) -> QWidget:
        page = QWidget()
        page_layout = QHBoxLayout(page)
        page_layout.setContentsMargins(0, 16, 0, 16)
        page_layout.setSpacing(0)
        page_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        center_col = QWidget()
        center_col.setMaximumWidth(860)
        layout = QVBoxLayout(center_col)
        layout.setContentsMargins(8, 0, 8, 16)
        layout.setSpacing(10)

        comp_card = QFrame()
        comp_card.setObjectName("settingsGroupCard")
        comp_layout = QVBoxLayout(comp_card)
        comp_layout.setContentsMargins(14, 12, 14, 12)
        comp_layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        self.comp_icon_tile = QLabel()
        self.comp_icon_tile.setFixedSize(32, 32)
        self.comp_icon_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.comp_icon_tile.setStyleSheet(
            "background-color: rgba(16, 185, 129, 0.15); border-radius: 10px;"
        )
        self.comp_icon_tile.setPixmap(get_icon("status_done", size=16).pixmap(16, 16))
        header_row.addWidget(self.comp_icon_tile)

        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(2)

        self.lbl_completed_title = QLabel(tr("split_complete"))
        self.lbl_completed_title.setObjectName("filenameLabel")
        self.lbl_completed_title.setStyleSheet("font-size: 13px; font-weight: 400;")
        info_vbox.addWidget(self.lbl_completed_title)

        self.lbl_completed_subtitle = QLabel(
            tr("parts_saved").format(n=0)
        )
        self.lbl_completed_subtitle.setObjectName("metaLabel")
        self.lbl_completed_subtitle.setStyleSheet("font-size: 11px;")
        info_vbox.addWidget(self.lbl_completed_subtitle)

        header_row.addLayout(info_vbox, 1)
        comp_layout.addLayout(header_row)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        self.btn_open_folder = QPushButton(tr("open_folder"))
        self.btn_open_folder.setObjectName("pillToggle")
        self.btn_open_folder.setIcon(get_icon("folder", size=14))
        self.btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_folder.setStyleSheet("padding: 0 16px; min-height: 32px; font-size: 12px; border-radius: 16px;")
        self.btn_open_folder.clicked.connect(self._on_open_folder_clicked)
        actions_row.addWidget(self.btn_open_folder)

        actions_row.addStretch(1)

        self.btn_split_another = QPushButton(tr("split_another"))
        self.btn_split_another.setObjectName("primaryButton")
        self.btn_split_another.setIcon(get_icon("scissors", color="#FFFFFF", size=15))
        self.btn_split_another.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_split_another.setStyleSheet("padding: 0 18px; min-height: 32px; font-weight: 400; font-size: 12px; border-radius: 16px; color: #FFFFFF;")
        self.btn_split_another.clicked.connect(self._on_split_another_clicked)
        actions_row.addWidget(self.btn_split_another)

        comp_layout.addLayout(actions_row)
        layout.addWidget(comp_card)
        layout.addStretch(1)

        page_layout.addWidget(center_col)
        return page

    # ── Tool Mode Switching ──

    def _update_tool_mode_icons(self) -> None:
        """Ensures the selected mode button has a crisp white icon while unselected buttons adapt to theme."""
        theme = get_theme()
        inactive_color = "#F5F5F7" if theme == "dark" else "#1C1C1E"
        self.btn_tool_splitter.setIcon(get_icon("scissors", color="#FFFFFF" if self._current_tool_mode == 0 else inactive_color, size=14))
        self.btn_tool_batch.setIcon(get_icon("folder", color="#FFFFFF" if self._current_tool_mode == 1 else inactive_color, size=14))
        self.btn_tool_single.setIcon(get_icon("rotate-cw", color="#FFFFFF" if self._current_tool_mode == 2 else inactive_color, size=14))

    def _on_tool_mode_changed(self, mode_id: int) -> None:
        """Switches between Video Splitter (0), Batch Renamer (1), and Single Localizer (2)."""
        self._current_tool_mode = mode_id
        btn = self.tool_mode_group.button(mode_id)
        if btn and not btn.isChecked():
            btn.setChecked(True)
        self._update_tool_mode_icons()
        if mode_id == 0:
            self.splitter_container.setVisible(True)
            self.batch_container.setVisible(False)
            self.single_container.setVisible(False)
            self.title_label.setText(tr("split_tool_title"))
        elif mode_id == 1:
            self.splitter_container.setVisible(False)
            self.batch_container.setVisible(True)
            self.single_container.setVisible(False)
            self.title_label.setText(tr("translator_mode_batch"))
        else:
            self.splitter_container.setVisible(False)
            self.batch_container.setVisible(False)
            self.single_container.setVisible(True)
            self.title_label.setText(tr("translator_mode_text"))

    # ── Batch Folder Renamer Handlers ──

    def _on_browse_batch_folder_clicked(self) -> None:
        default_dir = get_download_folder()
        chosen = QFileDialog.getExistingDirectory(self, tr("select_target_folder"), default_dir)
        if chosen:
            self._batch_target_dir = chosen
            self.folder_input.setText(chosen)
            self._scan_folder_for_preview(chosen)

    def _scan_folder_for_preview(self, folder_path: str) -> None:
        self.preview_table.setRowCount(0)
        self._preview_items.clear()
        p = Path(folder_path)
        if not p.exists():
            return

        items = []
        for child in sorted(p.iterdir()):
            if child.is_dir():
                clean_name = clean_drama_title(child.name)
                items.append((child.name, clean_name, "Folder", child))
            elif child.is_file() and child.suffix.lower() in [".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts"]:
                clean_name = clean_drama_title(child.stem)
                items.append((child.name, clean_name, "Video File", child))

        self.preview_table.setRowCount(len(items))
        for row, (name, clean_name, item_type, path_obj) in enumerate(items):
            self.preview_table.setItem(row, 0, QTableWidgetItem(name))
            khmer_name = f"រឿងភាគ {clean_name}"
            self.preview_table.setItem(row, 1, QTableWidgetItem(khmer_name))
            self.preview_table.setItem(row, 2, QTableWidgetItem(item_type))
            self._preview_items.append((name, khmer_name, item_type, path_obj))

    def _on_start_batch_rename_clicked(self) -> None:
        if not self._preview_items:
            self._on_browse_batch_folder_clicked()
            if not self._preview_items:
                return

        self.lbl_processing_title.setText("Localizing titles and batch renaming...")
        self.lbl_processing_subtitle.setText("Renaming folders and files...")
        self.lbl_processing_percent.setText("50%")
        self.progress_bar.setValue(50)
        self.stack_widget.setCurrentIndex(1)

        renamed_count = 0
        for name, khmer_name, item_type, path_obj in self._preview_items:
            try:
                safe_name = sanitize_filename(khmer_name)
                if path_obj.is_dir():
                    dest = path_obj.parent / safe_name
                else:
                    dest = path_obj.parent / f"{safe_name}{path_obj.suffix}"
                if path_obj.exists() and path_obj.resolve() != dest.resolve():
                    path_obj.rename(dest)
                    renamed_count += 1
            except Exception as e:
                logger.warning(f"Failed to rename {name}: {e}")

        self.progress_bar.setValue(100)
        self.lbl_processing_percent.setText("100%")

        self.lbl_completed_title.setText(tr("batch_rename_complete"))
        self.lbl_completed_subtitle.setText(f"Successfully localized {renamed_count} items into Khmer.")
        self.btn_split_another.setText("Rename Another")
        self.stack_widget.setCurrentIndex(2)

    # ── Single Title Localizer Handlers ──

    def _on_translate_single_clicked(self) -> None:
        title = self.edit_single_title.text().strip()
        if not title:
            return

        if self._single_sugg_worker and self._single_sugg_worker.isRunning():
            self._single_sugg_worker.quit()
            self._single_sugg_worker.wait()

        cleaned = clean_drama_title(title)
        self._single_sugg_worker = TitleSuggestionsWorker(title=cleaned, target_lang="km", count=3, parent=self)
        self._single_sugg_worker.finished.connect(self._on_single_suggestions_received)
        self._single_sugg_worker.start()

    def _on_single_suggestions_received(self, results: list[str]) -> None:
        while self.single_sugg_layout.count():
            child = self.single_sugg_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        lbl_res = QLabel(tr("suggested_khmer_titles"))
        lbl_res.setObjectName("metaLabel")
        lbl_res.setStyleSheet("font-size: 11px; font-weight: 400;")
        self.single_sugg_layout.addWidget(lbl_res)

        for cand in results:
            btn = QPushButton(cand)
            btn.setObjectName("secondaryButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("text-align: left; padding: 6px 12px; font-size: 12px; min-height: 30px; border-radius: 6px;")
            btn.clicked.connect(lambda checked, t=cand: self._on_copy_single_candidate(t))
            self.single_sugg_layout.addWidget(btn)

    def _on_browse_single_video_clicked(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            tr("choose_video_file"),
            get_download_folder(),
            "Video Files (*.mp4 *.mkv *.ts *.mov *.avi *.webm);;All Files (*.*)",
        )
        if chosen:
            self._selected_single_video_file = chosen
            file_p = Path(chosen)
            clean_name = clean_drama_title(file_p.stem)
            self.edit_single_title.setText(clean_name)
            self._on_translate_single_clicked()

    def _on_copy_single_candidate(self, text: str) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        logger.info(f"Copied localized title to clipboard: '{text}'")

        if hasattr(self, "_selected_single_video_file") and self._selected_single_video_file and os.path.isfile(self._selected_single_video_file):
            src_p = Path(self._selected_single_video_file)
            safe_title = sanitize_filename(text)
            dest_p = src_p.parent / f"{safe_title}{src_p.suffix}"
            try:
                if src_p.resolve() != dest_p.resolve():
                    os.rename(src_p, dest_p)
                    self._selected_single_video_file = str(dest_p)
                    QMessageBox.information(
                        self,
                        tr("split_tool_title"),
                        f"Video file successfully renamed to:\n{dest_p.name}",
                    )
            except Exception as e:
                logger.warning(f"Could not rename video file: {e}")

    # ── Title Translation Suggestion Handlers (Splitter Mode) ──

    def _on_file_input_changed(self, path: str) -> None:
        self._update_default_output_dir()
        self._trigger_title_translation(path)

    def _on_count_changed(self, text: str) -> None:
        try:
            cnt = int(text)
            self._trigger_title_translation(count=cnt)
        except ValueError:
            pass

    def _on_sugg_lang_changed(self, index: int) -> None:
        self._trigger_title_translation()

    def _trigger_title_translation(
        self, path: str | None = None, count: int | None = None
    ) -> None:
        raw_path = path if path is not None else self.file_input.text().strip()
        if not raw_path or raw_path == tr("choose_file"):
            self.suggestion_card.setVisible(False)
            return

        raw_stem = Path(raw_path).stem
        if not raw_stem:
            self.suggestion_card.setVisible(False)
            return

        clean_stem = clean_drama_title(raw_stem)
        sugg_count = (
            count if count is not None else int(self.combo_count.currentText())
        )

        self._show_loading_candidates()
        self.btn_retranslate.setEnabled(False)
        self.combo_count.setEnabled(False)
        self.combo_sugg_lang.setEnabled(False)
        self.suggestion_card.setVisible(True)

        target_lang = self.combo_sugg_lang.currentData() or "km"

        self._sugg_worker = TitleSuggestionsWorker(
            title=clean_stem, target_lang=target_lang, count=sugg_count, parent=self
        )
        self._sugg_worker.finished.connect(self._on_title_suggestions_finished)
        self._sugg_worker.start()

    def _show_loading_candidates(self) -> None:
        """Displays loading indicator inside candidates container."""
        while self.candidates_layout.count():
            item = self.candidates_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        lbl = QLabel(tr("translating"))
        lbl.setObjectName("metaLabel")
        lbl.setStyleSheet("padding: 6px; font-size: 11.5px;")
        self.candidates_layout.addWidget(lbl)

    def _on_title_suggestions_finished(self, candidates: list[str]) -> None:
        self.btn_retranslate.setEnabled(True)
        self.combo_count.setEnabled(True)
        self.combo_sugg_lang.setEnabled(True)

        raw_path = self.file_input.text().strip()
        clean_stem = clean_drama_title(Path(raw_path).stem if raw_path else "")
        target_lang = self.combo_sugg_lang.currentData() or "km"
        sugg_count = int(self.combo_count.currentText())

        if not candidates or (len(candidates) == 1 and candidates[0] == clean_stem):
            t = Translator()
            candidates = t._generate_fallback_suggestions(
                clean_stem, target_lang=target_lang, count=sugg_count
            )

        self._candidate_items = candidates
        self.suggestion_card.setVisible(True)

        if candidates and (
            not self._selected_candidate or self._selected_candidate not in candidates
        ):
            self._select_candidate(candidates[0])
        else:
            self._render_candidate_items()

    def _on_use_custom_clicked(self) -> None:
        """Allows user to set a custom write-in candidate title."""
        custom_text = self.edit_custom_title.text().strip()
        if custom_text:
            if custom_text not in self._candidate_items:
                self._candidate_items.insert(0, custom_text)
            self._select_candidate(custom_text)

    def _render_candidate_items(self) -> None:
        """Renders vertical selectable candidate cards with high-contrast text and theme awareness."""
        while self.candidates_layout.count():
            item = self.candidates_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        is_dark = get_theme() == "dark"

        for text in self._candidate_items:
            is_selected = text == self._selected_candidate
            card = QPushButton()
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setCheckable(True)
            card.setChecked(is_selected)

            if is_selected:
                if is_dark:
                    bg = "rgba(59, 130, 246, 0.2)"
                    border = "1.5px solid #4FA0FF"
                    color = "#4FA0FF"
                else:
                    bg = "rgba(18, 89, 195, 0.12)"
                    border = "1.5px solid #1259C3"
                    color = "#1259C3"
                card.setStyleSheet(
                    f"QPushButton {{ text-align: left; background-color: {bg}; "
                    f"border: {border}; border-radius: 8px; padding: 6px 10px; "
                    f"min-height: 30px; font-size: 12px; font-weight: 400; color: {color}; }}"
                )
                card.setIcon(get_icon("check", color=color, size=13))
            else:
                if is_dark:
                    bg = "rgba(255, 255, 255, 0.05)"
                    border = "1px solid rgba(255, 255, 255, 0.1)"
                    color = "#F2F2F2"
                else:
                    bg = "#FFFFFF"
                    border = "1px solid #E5E5EA"
                    color = "#1C1C1E"
                card.setStyleSheet(
                    f"QPushButton {{ text-align: left; background-color: {bg}; "
                    f"border: {border}; border-radius: 8px; padding: 6px 10px; "
                    f"min-height: 30px; font-size: 12px; font-weight: 400; color: {color}; }}"
                )
                card.setIcon(QIcon())

            card.setText(text)
            card.clicked.connect(
                lambda _, cand_text=text: self._select_candidate(cand_text)
            )
            self.candidates_layout.addWidget(card)

    def _select_candidate(self, candidate_text: str) -> None:
        """Selects a candidate, enables path auto-append, and updates output folder."""
        self._selected_candidate = candidate_text
        self._render_candidate_items()
        self.chk_auto_append.setChecked(True)
        self._update_output_path_with_suggestion()

    def _on_retranslate_clicked(self) -> None:
        """Re-triggers title translation for current video file."""
        self._trigger_title_translation()

    def _on_auto_append_toggled(self, checked: bool) -> None:
        """Handles toggle state change for auto-appending candidate title to path."""
        self._update_output_path_with_suggestion()

    def _on_output_dir_edited(self, text: str) -> None:
        """Tracks manual edits to the output path field as custom base directory."""
        txt = text.strip()
        if txt:
            self._custom_base_dir = Path(txt)

    def _update_output_path_with_suggestion(self) -> None:
        """Updates output folder path based on selected candidate and auto-append toggle."""
        raw_path = self.file_input.text().strip()
        if self._custom_base_dir:
            base_dir = self._custom_base_dir
        elif raw_path and raw_path != tr("choose_file"):
            base_dir = Path(raw_path).parent
        else:
            base_dir = Path(get_download_folder())

        if (
            hasattr(self, "chk_auto_append")
            and self.chk_auto_append.isChecked()
            and self._selected_candidate
        ):
            clean_name = sanitize_filename(self._selected_candidate)
            target_dir = base_dir / f"{clean_name}_parts"
        elif self._custom_base_dir:
            target_dir = self._custom_base_dir
        elif raw_path and raw_path != tr("choose_file"):
            p = Path(raw_path)
            target_dir = p.parent / f"{p.stem}_parts"
        else:
            target_dir = base_dir / "video_parts"

        self.edit_output_dir.setText(str(target_dir))
        self._output_dir = str(target_dir)
        self._update_naming_preview()

    def _update_naming_preview(self) -> None:
        if not hasattr(self, "naming_preview_card") or not hasattr(self, "mode_group"):
            return

        mode_id = self.mode_group.checkedId()
        if mode_id != 0:
            self.naming_preview_card.setVisible(False)
            return

        self.naming_preview_card.setVisible(True)
        raw_path = self.file_input.text().strip()

        if not raw_path or raw_path == tr("choose_file"):
            base_name = "Video"
            ext = ".mp4"
        else:
            p = Path(raw_path)
            base_name = p.stem
            ext = p.suffix or ".mp4"

        if self._selected_candidate and self.chk_auto_append.isChecked():
            clean_name = sanitize_filename(self._selected_candidate)
            title = clean_name or base_name
        else:
            title = base_name

        preview_text = f"ep1_{title}{ext}  |  ep2_{title}{ext}  |  ep3_{title}{ext} ..."
        self.lbl_preview_files.setText(preview_text)

    # ── State Machine Transitions & Event Handlers ──

    def _on_mode_changed(self, mode_id: int) -> None:
        """Swaps between Duration mode (0) and Custom Range mode (1)."""
        if mode_id == 0:
            self.episodes_widget.setVisible(True)
            self.range_widget.setVisible(False)
        else:
            self.episodes_widget.setVisible(False)
            self.range_widget.setVisible(True)
        self._update_naming_preview()

    def _update_default_output_dir(self) -> None:
        self._update_output_path_with_suggestion()

    def _on_browse_clicked(self) -> None:
        """Opens QFileDialog to pick a video file."""
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            tr("choose_video_file"),
            get_download_folder(),
            "Video Files (*.mp4 *.mkv *.ts *.mov *.avi *.webm);;All Files (*.*)",
        )
        if chosen:
            self.file_input.setText(chosen)

    def _on_browse_output_clicked(self) -> None:
        """Opens QFileDialog to select output directory."""
        default_path = (
            str(self._custom_base_dir)
            if self._custom_base_dir
            else self.edit_output_dir.text()
        )
        chosen = QFileDialog.getExistingDirectory(
            self, tr("output_folder"), default_path
        )
        if chosen:
            self._custom_base_dir = Path(chosen)
            self._update_output_path_with_suggestion()

    def _sync_preset_buttons(self, val: float) -> None:
        """Syncs the checked state of preset buttons when custom minutes spin box changes."""
        int_val = int(round(val)) if abs(val - round(val)) < 0.01 else -1
        self.preset_group.setExclusive(False)
        for m, btn in getattr(self, "preset_buttons", {}).items():
            btn.setChecked(m == int_val)
        self.preset_group.setExclusive(True)

    def set_video_path(self, video_path: str) -> None:
        """External helper to populate input path programmatically."""
        self.file_input.setText(video_path)

    def _on_split_clicked(self) -> None:
        """Executes the lossless FFmpeg splitting process in a worker thread."""
        file_path = self.file_input.text().strip()
        if not file_path or not os.path.exists(file_path):
            self._on_browse_clicked()
            file_path = self.file_input.text().strip()
            if not file_path or not os.path.exists(file_path):
                return

        out_dir = self.edit_output_dir.text().strip()
        self._output_dir = out_dir
        mode_id = self.mode_group.checkedId()

        start_time = None
        end_time = None
        minutes = 1.0

        if mode_id == 1:
            start_time = self.start_input.text().strip() or None
            end_time = self.end_input.text().strip() or None
        else:
            if hasattr(self, "spin_minutes"):
                minutes = float(self.spin_minutes.value())
            else:
                preset_id = self.preset_group.checkedId()
                minutes = float(preset_id) if preset_id > 0 else 1.0
            if minutes <= 0:
                minutes = 1.0

        self.lbl_processing_title.setText(
            f"Splitting video into {minutes:g} mn episodes..."
        )
        self.lbl_processing_subtitle.setText(tr("splitting"))
        self.lbl_processing_percent.setText("0%")
        self.progress_bar.setValue(0)
        self.stack_widget.setCurrentIndex(1)

        title_prefix = self._selected_candidate or Path(file_path).stem
        self.worker = VideoSplitterWorker(
            input_file=file_path,
            minutes_per_episode=minutes,
            output_dir=out_dir,
            title_prefix=title_prefix,
            start_time=start_time,
            end_time=end_time,
            parent=self,
        )
        self.worker.progress_changed.connect(self._on_progress_changed)
        self.worker.status_changed.connect(self._on_status_changed)
        self.worker.finished.connect(self._on_split_finished)
        self.worker.error.connect(self._on_split_error)
        self.worker.start()

    def _on_progress_changed(self, percent: float) -> None:
        val = int(percent)
        self.progress_bar.setValue(val)
        self.lbl_processing_percent.setText(f"{val}%")

    def _on_status_changed(self, status_msg: str) -> None:
        self.lbl_processing_subtitle.setText(status_msg)

    def _on_split_finished(self, out_dir: str, files: list) -> None:
        self._output_dir = out_dir
        self._generated_files = files
        count = len(files)
        self.lbl_completed_title.setText(tr("split_complete"))
        self.lbl_completed_subtitle.setText(
            tr("parts_saved").format(n=count)
        )
        self.btn_split_another.setText(tr("split_another"))
        self.stack_widget.setCurrentIndex(2)

    def _on_split_error(self, err_msg: str) -> None:
        logger.error(f"Video split error: {err_msg}")
        self.stack_widget.setCurrentIndex(0)

    def _on_back_clicked(self) -> None:
        """Handles back button click: resets stack to Form state if processing/done, or requests navigation back to Downloads."""
        if self.stack_widget.currentIndex() > 0:
            self.stack_widget.setCurrentIndex(0)
        else:
            self.back_requested.emit()

    def _on_cancel_clicked(self) -> None:
        """Stops the active worker thread and resets back to Form State (Page 0)."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        self.stack_widget.setCurrentIndex(0)

    def _on_split_another_clicked(self) -> None:
        """Resets the state machine back to Form State (Page 0)."""
        self.stack_widget.setCurrentIndex(0)

    def _on_open_folder_clicked(self) -> None:
        """Opens the target output directory in the OS file manager."""
        out_dir = (
            self._batch_target_dir
            if self._current_tool_mode == 1 and self._batch_target_dir
            else (self.edit_output_dir.text().strip() or self._output_dir)
        )
        if out_dir:
            p = Path(out_dir)
            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))

    def update_theme_icons(self) -> None:
        """Refreshes icons when theme changes."""
        if hasattr(self, "btn_back"):
            self.btn_back.setIcon(get_icon("arrow-left", size=16))
        if hasattr(self, "header_icon"):
            self.header_icon.setPixmap(get_icon("scissors", size=18).pixmap(18, 18))
        self._update_tool_mode_icons()
        self.btn_browse.setIcon(get_icon("folder", size=14))
        self.btn_browse_out.setIcon(get_icon("folder", size=14))
        self.btn_split.setIcon(get_icon("scissors", color="#FFFFFF", size=15))
        self.btn_browse_folder.setIcon(get_icon("folder", size=14))
        self.btn_start_batch.setIcon(get_icon("rotate-cw", color="#FFFFFF", size=15))
        self.btn_browse_single_video.setIcon(get_icon("folder", size=14))
        self.btn_translate_single.setIcon(get_icon("rotate-cw", color="#FFFFFF", size=14))
        self.btn_cancel.setIcon(get_icon("x", size=14))
        self.btn_open_folder.setIcon(get_icon("folder", size=14))
        self.btn_split_another.setIcon(get_icon("scissors", color="#FFFFFF", size=15))
        self.proc_icon_tile.setPixmap(get_icon("rotate-cw", size=16).pixmap(16, 16))
        self.comp_icon_tile.setPixmap(get_icon("status_done", size=16).pixmap(16, 16))
        if hasattr(self, "sugg_icon"):
            self.sugg_icon.setPixmap(get_icon("rotate-cw", size=14).pixmap(14, 14))
            self.btn_retranslate.setIcon(get_icon("rotate-cw", size=14))
        self._render_candidate_items()

    def retranslate_ui(self) -> None:
        """Updates translated strings on language change."""
        if self._current_tool_mode == 0:
            self.title_label.setText(tr("split_tool_title"))
        elif self._current_tool_mode == 1:
            self.title_label.setText(tr("translator_mode_batch"))
        else:
            self.title_label.setText(tr("translator_mode_text"))

        self.btn_tool_splitter.setText(tr("split_mode_single") if tr("split_mode_single") != "split_mode_single" else "Video Splitter")
        self.btn_tool_batch.setText(tr("translator_mode_batch"))
        self.btn_tool_single.setText(tr("translator_mode_text"))

        self.file_label.setText(tr("choose_video_file"))
        if not self.file_input.text() or self.file_input.text() == tr("choose_file"):
            self.file_input.setPlaceholderText(tr("choose_file"))
        self.btn_browse.setText(tr("browse"))
        self.mode_label.setText(tr("split_mode"))
        self.btn_mode_duration.setText(tr("by_duration"))
        self.btn_mode_range.setText(tr("custom_range"))
        self.lbl_minutes_part.setText(tr("minutes_per_part"))
        self.start_label.setText(tr("start_time"))
        self.end_label.setText(tr("end_time"))
        self.out_label.setText(tr("output_folder"))
        self.chk_auto_append.setText(tr("use_generated_title_in_path"))
        if hasattr(self, "lbl_sugg_prefix"):
            self.lbl_sugg_prefix.setText(tr("suggested_khmer_titles"))
            self.lbl_count_label.setText(tr("suggestion_count"))
            self.combo_sugg_lang.setItemText(0, tr("khmer"))
            self.combo_sugg_lang.setItemText(1, tr("english"))
        if hasattr(self, "lbl_preview_title"):
            self.lbl_preview_title.setText(tr("naming_preview"))
        self.btn_browse_out.setText(tr("browse"))
        self.btn_split.setText(tr("start_splitting"))

        if hasattr(self, "lbl_batch_header"):
            self.lbl_batch_header.setText(tr("select_target_folder"))
            self.btn_browse_folder.setText(tr("browse"))
            self.btn_start_batch.setText(tr("start_batch_rename"))

        if hasattr(self, "btn_retranslate"):
            self.btn_retranslate.setToolTip(tr("retranslate"))

        self.btn_cancel.setText(tr("cancel"))
        self.btn_open_folder.setText(tr("open_folder"))
        self.update_theme_icons()

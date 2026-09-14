"""
Settings Dialog Module
One UI 9 styled grouped-card modal settings dialog with live Gemini API Key management,
connection testing, theme/language toggling, and downloads preferences.
"""

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
import requests

from downloader_app.core.config import (
    get_download_folder,
    get_gemini_api_key,
    get_language,
    get_max_concurrent,
    get_theme,
    set_download_folder,
    set_gemini_api_key,
    set_language as save_language,
    set_max_concurrent,
    set_theme as save_theme,
)
from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.settings_dialog")


class ApiKeyTesterWorker(QThread):
    """Background worker to validate a Gemini API Key without freezing the UI."""

    result_ready = pyqtSignal(bool, str)

    def __init__(self, api_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.api_key = api_key.strip()

    def run(self) -> None:
        if not self.api_key:
            self.result_ready.emit(False, "API Key is empty")
            return

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}"
        try:
            resp = requests.get(endpoint, timeout=8)
            if resp.status_code == 200:
                self.result_ready.emit(True, tr("api_key_valid"))
            elif resp.status_code == 429:
                self.result_ready.emit(False, "Rate limited / Quota exceeded (HTTP 429)")
            elif resp.status_code in (400, 403):
                self.result_ready.emit(False, f"Invalid API Key (HTTP {resp.status_code})")
            else:
                self.result_ready.emit(False, f"Server response: HTTP {resp.status_code}")
        except requests.exceptions.Timeout:
            self.result_ready.emit(False, "Connection timed out")
        except Exception as e:
            self.result_ready.emit(False, str(e))


class SettingsDialog(QDialog):
    """Modern One UI 9 modal settings dialog with compact grouped card layout."""

    def __init__(
        self,
        parent: QWidget | None = None,
        on_theme_changed: Callable[[str], None] | None = None,
        on_language_changed: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_theme_changed = on_theme_changed
        self.on_language_changed = on_language_changed
        self.tester_worker: ApiKeyTesterWorker | None = None

        self.setWindowTitle(tr("settings"))
        self.setFixedWidth(440)
        self.setModal(True)

        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 14, 18, 16)
        main_layout.setSpacing(10)

        # ── Dialog Header Bar ──
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        self.header_icon = QLabel()
        self.header_icon.setPixmap(get_icon("settings", size=18).pixmap(18, 18))
        header_row.addWidget(self.header_icon)

        self.header_label = QLabel(tr("settings"))
        self.header_label.setObjectName("titleLabel")
        self.header_label.setStyleSheet("font-size: 15px; font-weight: 400;")
        header_row.addWidget(self.header_label)
        header_row.addStretch()

        self.btn_close_top = QPushButton()
        self.btn_close_top.setObjectName("iconButton")
        self.btn_close_top.setFixedSize(28, 28)
        self.btn_close_top.setIcon(get_icon("x", size=13))
        self.btn_close_top.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close_top.clicked.connect(self.accept)
        header_row.addWidget(self.btn_close_top)

        main_layout.addLayout(header_row)

        # ── 1. AI Services & Speech Card (Gemini) ──
        self.lbl_ai_section = QLabel(tr("ai_services"))
        self.lbl_ai_section.setObjectName("sectionHeaderLabel")
        self.lbl_ai_section.setStyleSheet("font-size: 10.5px; font-weight: 400; letter-spacing: 0.5px;")
        main_layout.addWidget(self.lbl_ai_section)

        ai_card = QFrame()
        ai_card.setObjectName("settingsGroupCard")
        ai_card_layout = QVBoxLayout(ai_card)
        ai_card_layout.setContentsMargins(12, 10, 12, 10)
        ai_card_layout.setSpacing(8)

        self.lbl_gemini_key = QLabel(tr("gemini_api_key"))
        self.lbl_gemini_key.setObjectName("filenameLabel")
        self.lbl_gemini_key.setStyleSheet("font-size: 12px; font-weight: 400;")
        ai_card_layout.addWidget(self.lbl_gemini_key)

        # Key input + Eye visibility toggle + Test button row
        key_input_row = QHBoxLayout()
        key_input_row.setSpacing(6)

        self.key_edit = QLineEdit()
        self.key_edit.setObjectName("settingsInput")
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText(tr("gemini_api_key_placeholder"))
        self.key_edit.setFixedHeight(30)
        self.key_edit.setStyleSheet("font-size: 12px; padding: 0 8px; border-radius: 6px;")
        self.key_edit.setText(get_gemini_api_key())
        self.key_edit.textChanged.connect(self._on_key_text_changed)
        key_input_row.addWidget(self.key_edit, 1)

        self.btn_toggle_key_vis = QPushButton()
        self.btn_toggle_key_vis.setObjectName("rowActionButton")
        self.btn_toggle_key_vis.setFixedSize(30, 30)
        self.btn_toggle_key_vis.setIcon(get_icon("eye", size=15))
        self.btn_toggle_key_vis.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_key_vis.setToolTip("Show / Hide API Key")
        self.btn_toggle_key_vis.clicked.connect(self._toggle_key_visibility)
        key_input_row.addWidget(self.btn_toggle_key_vis)

        self.btn_test_key = QPushButton(tr("test_api_key"))
        self.btn_test_key.setObjectName("secondaryButton")
        self.btn_test_key.setFixedHeight(30)
        self.btn_test_key.setStyleSheet("font-size: 11.5px; padding: 0 10px; border-radius: 15px;")
        self.btn_test_key.setIcon(get_icon("rotate-cw", size=12))
        self.btn_test_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_key.clicked.connect(self._handle_test_api_key)
        key_input_row.addWidget(self.btn_test_key)

        ai_card_layout.addLayout(key_input_row)

        # Status & Link info row
        info_row = QHBoxLayout()
        info_row.setSpacing(6)

        self.lbl_key_status = QLabel()
        self.lbl_key_status.setObjectName("metaLabel")
        current_k = get_gemini_api_key()
        if current_k:
            self.lbl_key_status.setText("✓ " + tr("api_key_saved"))
            self.lbl_key_status.setStyleSheet("color: #10B981; font-weight: 400; font-size: 11px;")
        else:
            self.lbl_key_status.setText(tr("get_api_key_help"))
            self.lbl_key_status.setStyleSheet("color: #8E8E93; font-size: 11px;")
        info_row.addWidget(self.lbl_key_status)
        info_row.addStretch()

        self.btn_ai_studio_link = QPushButton("Google AI Studio ↗")
        self.btn_ai_studio_link.setObjectName("pillToggle")
        self.btn_ai_studio_link.setFixedHeight(22)
        self.btn_ai_studio_link.setStyleSheet("font-size: 10.5px; padding: 0 7px; border-radius: 11px;")
        self.btn_ai_studio_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai_studio_link.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://aistudio.google.com/app/apikey"))
        )
        info_row.addWidget(self.btn_ai_studio_link)

        ai_card_layout.addLayout(info_row)
        main_layout.addWidget(ai_card)

        # ── 2. Appearance Group Card ──
        self.appearance_header = QLabel(tr("appearance"))
        self.appearance_header.setObjectName("sectionHeaderLabel")
        self.appearance_header.setStyleSheet("font-size: 10.5px; font-weight: 400; letter-spacing: 0.5px;")
        main_layout.addWidget(self.appearance_header)

        appearance_card = QFrame()
        appearance_card.setObjectName("settingsGroupCard")
        app_layout = QVBoxLayout(appearance_card)
        app_layout.setContentsMargins(12, 10, 12, 10)
        app_layout.setSpacing(8)

        # Theme row
        theme_row = QHBoxLayout()
        self.theme_label = QLabel(tr("theme"))
        self.theme_label.setObjectName("filenameLabel")
        self.theme_label.setStyleSheet("font-size: 12px; font-weight: 400;")
        theme_row.addWidget(self.theme_label)
        theme_row.addStretch()

        self.combo_theme = QComboBox()
        self.combo_theme.setObjectName("pillInput")
        self.combo_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_theme.setFixedHeight(28)
        self.combo_theme.setFixedWidth(145)
        self.combo_theme.addItem(get_icon("sun", size=13), tr("light_mode"), "light")
        self.combo_theme.addItem(get_icon("moon", size=13), tr("dark_mode"), "dark")

        current_theme = get_theme()
        if current_theme == "dark":
            self.combo_theme.setCurrentIndex(1)
        else:
            self.combo_theme.setCurrentIndex(0)

        self.combo_theme.currentIndexChanged.connect(self._on_theme_combo_changed)
        theme_row.addWidget(self.combo_theme)
        app_layout.addLayout(theme_row)

        # Language row
        lang_row = QHBoxLayout()
        self.lang_label = QLabel(tr("language"))
        self.lang_label.setObjectName("filenameLabel")
        self.lang_label.setStyleSheet("font-size: 12px; font-weight: 400;")
        lang_row.addWidget(self.lang_label)
        lang_row.addStretch()

        self.combo_lang = QComboBox()
        self.combo_lang.setObjectName("pillInput")
        self.combo_lang.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_lang.setFixedHeight(28)
        self.combo_lang.setFixedWidth(145)
        self.combo_lang.addItem("English", "en")
        self.combo_lang.addItem("ខ្មែរ (Khmer)", "km")

        current_lang = get_language()
        if current_lang == "km":
            self.combo_lang.setCurrentIndex(1)
        else:
            self.combo_lang.setCurrentIndex(0)

        self.combo_lang.currentIndexChanged.connect(self._on_language_combo_changed)
        lang_row.addWidget(self.combo_lang)
        app_layout.addLayout(lang_row)

        main_layout.addWidget(appearance_card)

        # ── 3. General / Downloads Group Card ──
        self.general_header = QLabel(tr("general"))
        self.general_header.setObjectName("sectionHeaderLabel")
        self.general_header.setStyleSheet("font-size: 10.5px; font-weight: 400; letter-spacing: 0.5px;")
        main_layout.addWidget(self.general_header)

        general_card = QFrame()
        general_card.setObjectName("settingsGroupCard")
        gen_layout = QVBoxLayout(general_card)
        gen_layout.setContentsMargins(12, 10, 12, 10)
        gen_layout.setSpacing(8)

        # Download Folder
        folder_vbox = QVBoxLayout()
        folder_vbox.setSpacing(4)
        self.folder_label = QLabel(tr("download_folder"))
        self.folder_label.setObjectName("filenameLabel")
        self.folder_label.setStyleSheet("font-size: 12px; font-weight: 400;")
        folder_vbox.addWidget(self.folder_label)

        folder_hbox = QHBoxLayout()
        folder_hbox.setSpacing(6)
        self.folder_edit = QLineEdit(get_download_folder())
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setObjectName("settingsInput")
        self.folder_edit.setFixedHeight(30)
        self.folder_edit.setStyleSheet("font-size: 12px; padding: 0 8px; border-radius: 6px;")

        self.btn_browse = QPushButton(tr("browse"))
        self.btn_browse.setObjectName("secondaryButton")
        self.btn_browse.setFixedHeight(30)
        self.btn_browse.setStyleSheet("font-size: 11.5px; padding: 0 10px; border-radius: 15px;")
        self.btn_browse.setIcon(get_icon("folder", size=12))
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.clicked.connect(self._handle_browse_folder)

        folder_hbox.addWidget(self.folder_edit, 1)
        folder_hbox.addWidget(self.btn_browse)
        folder_vbox.addLayout(folder_hbox)
        gen_layout.addLayout(folder_vbox)

        # Max Concurrent Downloads
        concurrent_row = QHBoxLayout()
        self.concurrent_label = QLabel(tr("max_concurrent_downloads"))
        self.concurrent_label.setObjectName("filenameLabel")
        self.concurrent_label.setStyleSheet("font-size: 12px; font-weight: 400;")
        concurrent_row.addWidget(self.concurrent_label)
        concurrent_row.addStretch()

        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(1, 10)
        self.spin_concurrent.setValue(get_max_concurrent())
        self.spin_concurrent.setSuffix(" tasks")
        self.spin_concurrent.setFixedHeight(28)
        self.spin_concurrent.setFixedWidth(95)
        self.spin_concurrent.setStyleSheet("font-size: 11.5px; padding: 0 4px;")
        self.spin_concurrent.valueChanged.connect(self._handle_max_concurrent_change)
        concurrent_row.addWidget(self.spin_concurrent)
        gen_layout.addLayout(concurrent_row)

        main_layout.addWidget(general_card)
        main_layout.addSpacing(2)

        # ── Bottom Action Row ──
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addStretch()

        self.btn_close = QPushButton(tr("close"))
        self.btn_close.setObjectName("primaryButton")
        self.btn_close.setFixedHeight(30)
        self.btn_close.setStyleSheet("font-size: 12px; font-weight: 400; min-width: 80px; padding: 0 16px; border-radius: 15px;")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self._handle_save_and_close)
        bottom_row.addWidget(self.btn_close)
        main_layout.addLayout(bottom_row)

    def _toggle_key_visibility(self) -> None:
        """Toggles between masked password mode and plain text visibility for API key."""
        if self.key_edit.echoMode() == QLineEdit.EchoMode.Password:
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_toggle_key_vis.setIcon(get_icon("eye-off", size=15))
        else:
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_toggle_key_vis.setIcon(get_icon("eye", size=15))

    def _on_key_text_changed(self, text: str) -> None:
        """Saves API key immediately into settings/env whenever modified."""
        set_gemini_api_key(text.strip())
        if text.strip():
            self.lbl_key_status.setText("✓ " + tr("api_key_saved"))
            self.lbl_key_status.setStyleSheet("color: #10B981; font-weight: 400; font-size: 11px;")
        else:
            self.lbl_key_status.setText(tr("get_api_key_help"))
            self.lbl_key_status.setStyleSheet("color: #8E8E93; font-size: 11px;")

    def _handle_test_api_key(self) -> None:
        """Tests the entered API key against the Gemini API."""
        key = self.key_edit.text().strip()
        if not key:
            self.lbl_key_status.setText("❌ " + tr("api_key_invalid"))
            self.lbl_key_status.setStyleSheet("color: #EF4444; font-weight: 400; font-size: 11px;")
            return

        self.btn_test_key.setEnabled(False)
        self.lbl_key_status.setText(tr("testing_api_key"))
        self.lbl_key_status.setStyleSheet("color: #1259C3; font-size: 11px;")

        self.tester_worker = ApiKeyTesterWorker(key, parent=self)
        self.tester_worker.result_ready.connect(self._on_test_result)
        self.tester_worker.start()

    def _on_test_result(self, success: bool, msg: str) -> None:
        self.btn_test_key.setEnabled(True)
        if success:
            self.lbl_key_status.setText("✓ " + msg)
            self.lbl_key_status.setStyleSheet("color: #10B981; font-weight: 400; font-size: 11px;")
        else:
            self.lbl_key_status.setText("❌ " + msg)
            self.lbl_key_status.setStyleSheet("color: #EF4444; font-weight: 400; font-size: 11px;")

    def _on_theme_combo_changed(self, index: int) -> None:
        """Handles theme combo selection change."""
        theme = self.combo_theme.itemData(index)
        if theme and theme != get_theme():
            self._handle_theme_change(theme)

    def _on_language_combo_changed(self, index: int) -> None:
        """Handles language combo selection change."""
        lang = self.combo_lang.itemData(index)
        if lang and lang != get_language():
            self._handle_language_change(lang)

    def _handle_theme_change(self, theme: str) -> None:
        save_theme(theme)
        self._update_icons()
        if self.on_theme_changed:
            self.on_theme_changed(theme)

    def _handle_language_change(self, lang: str) -> None:
        save_language(lang)
        if self.on_language_changed:
            self.on_language_changed(lang)

    def _handle_browse_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, tr("select_folder"), self.folder_edit.text()
        )
        if chosen:
            self.folder_edit.setText(chosen)
            set_download_folder(chosen)

    def _handle_max_concurrent_change(self, value: int) -> None:
        set_max_concurrent(value)

    def _handle_save_and_close(self) -> None:
        """Ensures all values are written before dialog accept."""
        set_gemini_api_key(self.key_edit.text().strip())
        set_max_concurrent(self.spin_concurrent.value())
        self.accept()

    def _update_icons(self) -> None:
        """Refreshes all icons to match current light/dark theme colors."""
        self.header_icon.setPixmap(get_icon("settings", size=18).pixmap(18, 18))
        self.btn_close_top.setIcon(get_icon("x", size=13))
        self.btn_browse.setIcon(get_icon("folder", size=12))
        self.btn_test_key.setIcon(get_icon("rotate-cw", size=12))
        vis_icon = "eye-off" if self.key_edit.echoMode() == QLineEdit.EchoMode.Normal else "eye"
        self.btn_toggle_key_vis.setIcon(get_icon(vis_icon, size=15))
        self.combo_theme.setItemIcon(0, get_icon("sun", size=13))
        self.combo_theme.setItemIcon(1, get_icon("moon", size=13))

    def retranslate_ui(self) -> None:
        """Dynamically re-applies translations to all labels and buttons."""
        self.setWindowTitle(tr("settings"))
        self.header_label.setText(tr("settings"))
        self.lbl_ai_section.setText(tr("ai_services"))
        self.lbl_gemini_key.setText(tr("gemini_api_key"))
        self.key_edit.setPlaceholderText(tr("gemini_api_key_placeholder"))
        self.btn_test_key.setText(tr("test_api_key"))
        self.appearance_header.setText(tr("appearance"))
        self.theme_label.setText(tr("theme"))
        self.combo_theme.blockSignals(True)
        self.combo_theme.setItemText(0, tr("light_mode"))
        self.combo_theme.setItemText(1, tr("dark_mode"))
        self.combo_theme.blockSignals(False)
        self.lang_label.setText(tr("language"))
        self.combo_lang.blockSignals(True)
        current_lang = get_language()
        self.combo_lang.setCurrentIndex(1 if current_lang == "km" else 0)
        self.combo_lang.blockSignals(False)
        self.general_header.setText(tr("general"))
        self.folder_label.setText(tr("download_folder"))
        self.btn_browse.setText(tr("browse"))
        self.concurrent_label.setText(tr("max_concurrent_downloads"))
        self.btn_close.setText(tr("close"))
        self._update_icons()

"""
Sidebar Rail Widget
64px vertical icon rail with view switcher buttons (Downloads / Split Tool)
and pinned bottom actions (Theme toggle / Settings).
"""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from downloader_app.core.config import get_theme
from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.sidebar_rail")


class SidebarRail(QFrame):
    """64px icon rail with view switcher and pinned bottom actions."""

    view_switched = pyqtSignal(int)  # 0 = Downloads, 1 = Split Tool
    theme_toggled = pyqtSignal(str)  # "light" or "dark"
    settings_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebarRail")
        self.setFixedWidth(64)
        self._current_theme = get_theme()
        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 16, 10, 16)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # ── App Logo Branding ──
        logo_path = Path(__file__).parent.parent / "resources" / "app-logo.png"
        if logo_path.exists():
            self.logo_label = QLabel(self)
            self.logo_label.setObjectName("appLogoLabel")
            self.logo_label.setFixedSize(40, 40)
            self.logo_label.setToolTip(tr("app_title"))
            pixmap = QPixmap(str(logo_path)).scaled(
                40,
                40,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.logo_label.setPixmap(pixmap)
            self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.logo_label)
            layout.addSpacing(6)

        # ── Top Section: View Switcher Buttons ──
        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self.btn_downloads = self._make_rail_button("download", tr("downloads_title"))
        self.btn_downloads.setChecked(True)
        self.btn_group.addButton(self.btn_downloads, 0)
        layout.addWidget(self.btn_downloads)

        self.btn_split = self._make_rail_button("scissors", tr("split_tool_title"))
        self.btn_group.addButton(self.btn_split, 1)
        layout.addWidget(self.btn_split)

        self.btn_dubbing = self._make_rail_button("film", tr("dubbing_tool_title"))
        self.btn_group.addButton(self.btn_dubbing, 2)
        layout.addWidget(self.btn_dubbing)

        self.btn_group.idClicked.connect(self._on_view_button_clicked)

        # ── Stretch Spacer ──
        layout.addStretch(1)

        # ── Bottom Section: Theme Toggle + Settings ──
        theme_icon = "moon" if self._current_theme == "light" else "sun"
        self.btn_theme = self._make_rail_button(theme_icon, tr("theme"))
        self.btn_theme.setCheckable(False)
        self.btn_theme.clicked.connect(self._on_theme_clicked)
        layout.addWidget(self.btn_theme)

        self.btn_settings = self._make_rail_button("settings", tr("settings"))
        self.btn_settings.setCheckable(False)
        self.btn_settings.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.btn_settings)

    def _make_rail_button(self, icon_name: str, tooltip: str) -> QPushButton:
        """Creates a 44x44 checkable icon button for the rail."""
        btn = QPushButton()
        btn.setObjectName("railButton")
        btn.setCheckable(True)
        btn.setIcon(get_icon(icon_name, size=20))
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(44, 44)
        return btn

    def set_active_index(self, index: int) -> None:
        """Programmatically checks the rail button for the given index."""
        button = self.btn_group.button(index)
        if button:
            button.setChecked(True)
            self._on_view_button_clicked(index)

    def _on_view_button_clicked(self, button_id: int) -> None:
        """Emits view_switched when a view button is clicked and refreshes active icon styling."""
        logger.info(f"Rail view switched to index {button_id}")
        self.update_theme_icons()
        self.view_switched.emit(button_id)

    def _on_theme_clicked(self) -> None:
        """Toggles theme between light and dark, swaps icon immediately."""
        if self._current_theme == "light":
            self._current_theme = "dark"
        else:
            self._current_theme = "light"

        self.theme_toggled.emit(self._current_theme)
        self.update_theme_icons()

    def _update_theme_icon(self) -> None:
        """Updates the theme button icon to match the current theme."""
        icon_name = "moon" if self._current_theme == "light" else "sun"
        is_dark = self._current_theme == "dark"
        icon_color = "#F5F5F7" if is_dark else "#1C1C1E"
        self.btn_theme.setIcon(get_icon(icon_name, color=icon_color, size=20))

    def set_current_theme(self, theme: str) -> None:
        """Called externally when theme changes — updates icon accordingly."""
        self._current_theme = theme
        self.update_theme_icons()

    def update_theme_icons(self) -> None:
        """Refreshes all rail icons when the theme palette changes or view changes."""
        is_dark = get_theme() == "dark"
        active_color = "#4FA0FF" if is_dark else "#1259C3"
        inactive_color = "#F5F5F7" if is_dark else "#1C1C1E"

        checked_btn = self.btn_group.checkedButton()
        is_dl_active = checked_btn == self.btn_downloads
        is_split_active = checked_btn == self.btn_split
        is_dub_active = checked_btn == self.btn_dubbing

        self.btn_downloads.setIcon(
            get_icon("download", color=active_color if is_dl_active else inactive_color, size=20)
        )
        self.btn_split.setIcon(
            get_icon("scissors", color=active_color if is_split_active else inactive_color, size=20)
        )
        self.btn_dubbing.setIcon(
            get_icon("film", color=active_color if is_dub_active else inactive_color, size=20)
        )
        self._update_theme_icon()
        self.btn_settings.setIcon(get_icon("settings", color=inactive_color, size=20))

    def retranslate_ui(self) -> None:
        """Updates tooltips on language change."""
        if hasattr(self, "logo_label"):
            self.logo_label.setToolTip(tr("app_title"))
        self.btn_downloads.setToolTip(tr("downloads_title"))
        self.btn_split.setToolTip(tr("split_tool_title"))
        self.btn_dubbing.setToolTip(tr("dubbing_tool_title"))
        self.btn_theme.setToolTip(tr("theme"))
        self.btn_settings.setToolTip(tr("settings"))

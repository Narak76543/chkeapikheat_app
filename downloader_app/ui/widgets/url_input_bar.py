"""
URL Input Bar Widget
One UI 9 pill input bar with 'Add Download' button, debounce typing detection,
and auto-fix text support.
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.input_bar")


class UrlInputBar(QWidget):
    """One UI 9 input bar with pill styling, debounced auto-search, and touch-friendly 44px button."""

    url_submitted = pyqtSignal(str)
    text_changed_debounced = pyqtSignal(str)
    cleared = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(600)
        self._debounce_timer.timeout.connect(self._on_debounce_timeout)

        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # URL / Title Input field
        self.input_field = QLineEdit()
        self.input_field.setObjectName("urlInput")
        self.input_field.setPlaceholderText(tr("url_placeholder"))
        self.input_field.setClearButtonEnabled(True)
        self.input_field.textChanged.connect(self._on_text_changed)
        self.input_field.returnPressed.connect(self._handle_submit)
        layout.addWidget(self.input_field, 1)

        # 44px FETCH Pill Button
        self.btn_add = QPushButton(tr("fetch"))
        self.btn_add.setObjectName("primaryButton")
        self.btn_add.setIcon(get_icon("download", color="#FFFFFF", size=18))
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self._handle_submit)
        layout.addWidget(self.btn_add)

    def update_theme_icons(self) -> None:
        """Refreshes button icons on theme change."""
        self.btn_add.setIcon(get_icon("download", color="#FFFFFF", size=18))

    def _on_text_changed(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            self._debounce_timer.stop()
            self.cleared.emit()
            return

        # Start debounce timer for typing (min 2 characters)
        if len(cleaned) >= 2:
            self._debounce_timer.start(600)

    def _on_debounce_timeout(self) -> None:
        text = self.input_field.text().strip()
        if len(text) >= 2:
            logger.info(f"Debounced movie search trigger: {text}")
            self.text_changed_debounced.emit(text)

    def _handle_submit(self) -> None:
        self._debounce_timer.stop()
        url = self.input_field.text().strip()
        if url:
            logger.info(f"URL / Movie submitted: {url}")
            self.url_submitted.emit(url)

    def set_text(self, text: str) -> None:
        """Sets the text (e.g. for auto-fixing movie title) without triggering typing search."""
        self._debounce_timer.stop()
        self.input_field.blockSignals(True)
        self.input_field.setText(text)
        self.input_field.blockSignals(False)

    def text(self) -> str:
        return self.input_field.text().strip()

    def clear(self) -> None:
        self.input_field.clear()

    def retranslate_ui(self) -> None:
        """Updates placeholder and button label on language change."""
        self.input_field.setPlaceholderText(tr("url_placeholder"))
        self.btn_add.setText(tr("fetch"))


UrlInputBarWidget = UrlInputBar

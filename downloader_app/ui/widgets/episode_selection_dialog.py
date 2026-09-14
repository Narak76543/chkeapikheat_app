"""
Episode Selection Dialog Widget
One UI 9 modal dialog allowing users to pick episode ranges or select specific episodes for batch downloading.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import tr
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.ep_dialog")


class EpisodeSelectionDialog(QDialog):
    """Modal dialog to select episode range or specific episodes to download."""

    episodes_selected = pyqtSignal(dict)

    def __init__(self, movie_data: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.movie_data = movie_data
        self.total_episodes = (
            movie_data.get("total_episodes")
            or len(movie_data.get("vid_list", []))
            or 94
        )
        self.checkboxes: list[QCheckBox] = []

        self.setWindowTitle(tr("download_episodes"))
        self.setMinimumSize(520, 580)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header Title
        title_str = self.movie_data.get("title", "Drama Series")
        lbl_title = QLabel(f"Download Episodes — {title_str}")
        lbl_title.setObjectName("titleLabel")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(lbl_title)

        # Quick Range Controls Card
        range_card = QFrame()
        range_card.setObjectName("sidebarCard")
        range_layout = QHBoxLayout(range_card)
        range_layout.setContentsMargins(12, 10, 12, 10)
        range_layout.setSpacing(8)

        range_layout.addWidget(QLabel("Range:"))

        self.spin_from = QSpinBox()
        self.spin_from.setRange(1, self.total_episodes)
        self.spin_from.setValue(1)
        self.spin_from.valueChanged.connect(self._on_range_changed)
        range_layout.addWidget(self.spin_from)

        range_layout.addWidget(QLabel("to"))

        self.spin_to = QSpinBox()
        self.spin_to.setRange(1, self.total_episodes)
        self.spin_to.setValue(self.total_episodes)
        self.spin_to.valueChanged.connect(self._on_range_changed)
        range_layout.addWidget(self.spin_to)

        btn_select_all = QPushButton("Select All")
        btn_select_all.setObjectName("secondaryButton")
        btn_select_all.clicked.connect(self._select_all)
        range_layout.addWidget(btn_select_all)

        btn_deselect = QPushButton("Deselect All")
        btn_deselect.setObjectName("secondaryButton")
        btn_deselect.clicked.connect(self._deselect_all)
        range_layout.addWidget(btn_deselect)

        layout.addWidget(range_card)

        # Scrollable Grid of Episode Checkboxes
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        grid_layout = QGridLayout(scroll_widget)
        grid_layout.setContentsMargins(8, 8, 8, 8)
        grid_layout.setSpacing(10)

        cols = 4
        for i in range(1, self.total_episodes + 1):
            chk = QCheckBox(f"Ep {i:02d}")
            chk.setChecked(True)
            chk.stateChanged.connect(self._update_count_label)
            self.checkboxes.append(chk)
            row = (i - 1) // cols
            col = (i - 1) % cols
            grid_layout.addWidget(chk, row, col)

        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area, 1)

        # Bottom Action Bar
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
        btn_cancel.clicked.connect(self.reject)
        bottom_bar.addWidget(btn_cancel)

        self.btn_download = QPushButton(f"Download Selected ({self.total_episodes})")
        self.btn_download.setObjectName("primaryButton")
        self.btn_download.setIcon(get_icon("download", color="#FFFFFF", size=16))
        self.btn_download.clicked.connect(self._on_confirm)
        bottom_bar.addWidget(self.btn_download)

        layout.addLayout(bottom_bar)

    def _select_all(self) -> None:
        for chk in self.checkboxes:
            chk.setChecked(True)

    def _deselect_all(self) -> None:
        for chk in self.checkboxes:
            chk.setChecked(False)

    def _on_range_changed(self) -> None:
        start = self.spin_from.value()
        end = self.spin_to.value()
        for idx, chk in enumerate(self.checkboxes, start=1):
            chk.setChecked(start <= idx <= end)

    def _update_count_label(self) -> None:
        count = sum(1 for chk in self.checkboxes if chk.isChecked())
        self.lbl_selected_count.setText(
            f"Selected: {count} / {self.total_episodes} Episodes"
        )
        self.btn_download.setText(f"Download Selected ({count})")
        self.btn_download.setEnabled(count > 0)

    def _on_confirm(self) -> None:
        selected_indices = [
            idx for idx, chk in enumerate(self.checkboxes, start=1) if chk.isChecked()
        ]
        res = dict(self.movie_data)
        res["selected_episodes"] = selected_indices
        self.episodes_selected.emit(res)
        self.accept()

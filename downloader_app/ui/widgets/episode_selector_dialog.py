"""
Episode Selector Dialog
Interactive dialog showing drama info and episode selection for batch downloading.
"""

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class EpisodeSelectorDialog(QDialog):
    """
    Dialog displaying drama metadata and allowing users to select which episodes to download.
    """

    def __init__(self, drama_info: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.drama_info = drama_info
        self.selected_episodes: list[int] = []
        self.download_full_season_movie = False

        self.setWindowTitle(f"Episodes: {drama_info.get('title', 'Short Drama')}")
        self.resize(650, 520)
        self.setStyleSheet("""
            QDialog {
                background-color: #222222;
                color: #e0e0e0;
            }
            QLabel {
                color: #e0e0e0;
            }
            QGroupBox {
                border: 1px solid #444444;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: 400;
                color: #2a82da;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                background-color: #333333;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #444444;
            }
            QPushButton#primaryBtn {
                background-color: #2a82da;
                border: none;
                font-weight: 400;
            }
            QPushButton#primaryBtn:hover {
                background-color: #3b93eb;
            }
            QCheckBox {
                color: #dddddd;
                padding: 4px;
            }
            QLineEdit {
                background-color: #1a1a1a;
                border: 1px solid #444444;
                border-radius: 4px;
                color: #ffffff;
                padding: 6px;
            }
        """)

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header Info: Title, Total EPs, Tags
        title = self.drama_info.get("title", "Unknown Title")
        total_eps = self.drama_info.get("total_episodes", 0)
        accessible_eps = self.drama_info.get("accessible_episodes", 3)
        tags = self.drama_info.get("tags", [])
        tags_str = f" | Tags: {', '.join(tags)}" if tags else ""

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 17px; font-weight: 400; color: #ffffff;")
        title_label.setWordWrap(True)
        main_layout.addWidget(title_label)

        meta_label = QLabel(
            f"Total Episodes: {total_eps} | Free Web Preview: EP 01 – {accessible_eps:02d}{tags_str}"
        )
        meta_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        main_layout.addWidget(meta_label)

        # Options Box: Single/Batch EPs vs Full Continuous Movie
        mode_group = QGroupBox("Download Options")
        mode_layout = QVBoxLayout(mode_group)

        self.radio_web_eps = QRadioButton(
            f"Download Individual Episode Streams (EP 01 - {accessible_eps:02d})"
        )
        self.radio_web_eps.setChecked(True)
        mode_layout.addWidget(self.radio_web_eps)

        self.radio_full_movie = QRadioButton(
            "Download Full Season (All Episodes Continuous Full-HD Movie)"
        )
        mode_layout.addWidget(self.radio_full_movie)

        main_layout.addWidget(mode_group)

        # Episode Checkbox Grid
        self.episodes_group = QGroupBox("Select Individual Episodes")
        ep_layout = QVBoxLayout(self.episodes_group)

        # Quick Select Buttons & Range Input
        quick_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All Available")
        select_all_btn.clicked.connect(self._select_all_available)
        quick_layout.addWidget(select_all_btn)

        clear_btn = QPushButton("Clear Selection")
        clear_btn.clicked.connect(self._clear_selection)
        quick_layout.addWidget(clear_btn)

        quick_layout.addSpacing(10)
        quick_layout.addWidget(QLabel("Range (e.g. 1-3):"))
        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText(f"1-{accessible_eps}")
        self.range_input.setMaximumWidth(90)
        self.range_input.returnPressed.connect(self._apply_range)
        quick_layout.addWidget(self.range_input)

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_range)
        quick_layout.addWidget(apply_btn)
        quick_layout.addStretch()

        ep_layout.addLayout(quick_layout)

        # Scroll Area for Episode Checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "background-color: #1a1a1a; border: none; border-radius: 4px;"
        )

        scroll_widget = QWidget()
        self.grid_layout = QGridLayout(scroll_widget)
        self.grid_layout.setSpacing(6)

        self.checkboxes: dict[int, QCheckBox] = {}
        columns = 5
        vids = self.drama_info.get("vid_list", [])
        display_count = max(total_eps, len(vids))

        for ep_num in range(1, display_count + 1):
            is_free = ep_num <= accessible_eps
            label = f"EP {ep_num:02d}" if is_free else f"EP {ep_num:02d} (App)"
            cb = QCheckBox(label)
            if is_free:
                cb.setChecked(True)
                cb.setStyleSheet("color: #ffffff; font-weight: 500;")
            else:
                cb.setChecked(False)
                cb.setStyleSheet("color: #777777;")

            row = (ep_num - 1) // columns
            col = (ep_num - 1) % columns
            self.grid_layout.addWidget(cb, row, col)
            self.checkboxes[ep_num] = cb

        scroll.setWidget(scroll_widget)
        ep_layout.addWidget(scroll)
        main_layout.addWidget(self.episodes_group, 1)

        # Radio button toggle handler
        self.radio_full_movie.toggled.connect(self._on_mode_toggled)

        # Bottom Buttons
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(cancel_btn)

        self.confirm_btn = QPushButton("Queue Selected Downloads")
        self.confirm_btn.setObjectName("primaryBtn")
        self.confirm_btn.clicked.connect(self._on_confirm)
        bottom_layout.addWidget(self.confirm_btn)

        main_layout.addLayout(bottom_layout)

    def _on_mode_toggled(self, full_movie_checked: bool) -> None:
        self.episodes_group.setEnabled(not full_movie_checked)
        if full_movie_checked:
            self.confirm_btn.setText("Queue Full Season Movie")
        else:
            self.confirm_btn.setText("Queue Selected Downloads")

    def _select_all_available(self) -> None:
        accessible_eps = self.drama_info.get("accessible_episodes", 3)
        for ep_num, cb in self.checkboxes.items():
            cb.setChecked(ep_num <= accessible_eps)

    def _clear_selection(self) -> None:
        for cb in self.checkboxes.values():
            cb.setChecked(False)

    def _apply_range(self) -> None:
        text = self.range_input.text().strip()
        if not text:
            return
        self._clear_selection()
        for part in text.split(","):
            part = part.strip()
            if "-" in part:
                try:
                    s, e = part.split("-", 1)
                    for n in range(int(s), int(e) + 1):
                        if n in self.checkboxes:
                            self.checkboxes[n].setChecked(True)
                except ValueError:
                    pass
            elif part.isdigit() and int(part) in self.checkboxes:
                self.checkboxes[int(part)].setChecked(True)

    def _on_confirm(self) -> None:
        if self.radio_full_movie.isChecked():
            self.download_full_season_movie = True
            self.accept()
            return

        self.selected_episodes = [
            ep_num for ep_num, cb in self.checkboxes.items() if cb.isChecked()
        ]
        if not self.selected_episodes:
            QMessageBox.warning(
                self, "No Selection", "Please select at least one episode to download."
            )
            return

        self.accept()

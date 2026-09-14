"""
Video Split Dialog Module
One UI 9 styled dialog allowing the user to split a movie into episodes by minutes
(e.g., 10 minutes per episode) with presets and folder export.
"""

import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from downloader_app.core.config import get_download_folder
from downloader_app.core.video_splitter import VideoSplitterWorker
from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.split_dialog")


class VideoSplitDialog(QDialog):
    """One UI 9 dialog for configuring and executing movie splitting into episodes."""

    def __init__(
        self,
        video_path: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.initial_video_path = video_path or ""
        self.worker: VideoSplitterWorker | None = None
        self._output_dir: str = ""

        self.setWindowTitle(tr("split_movie"))
        self.setMinimumWidth(520)
        self.setModal(True)

        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Header
        header_row = QHBoxLayout()
        header_icon = QLabel()
        header_icon.setPixmap(get_icon("scissors", size=24).pixmap(24, 24))
        header_row.addWidget(header_icon)

        self.title_label = QLabel(tr("split_movie"))
        self.title_label.setObjectName("titleLabel")
        header_row.addWidget(self.title_label)
        header_row.addStretch()
        main_layout.addLayout(header_row)

        # ---------------- 1. Source Video Card ----------------
        self.lbl_src_section = QLabel(tr("source_video"))
        self.lbl_src_section.setObjectName("sectionHeaderLabel")
        main_layout.addWidget(self.lbl_src_section)

        src_card = QFrame()
        src_card.setObjectName("settingsGroupCard")
        src_layout = QHBoxLayout(src_card)
        src_layout.setContentsMargins(16, 14, 16, 14)
        src_layout.setSpacing(10)

        self.edit_video_path = QLineEdit(self.initial_video_path)
        self.edit_video_path.setObjectName("urlInput")
        self.edit_video_path.setPlaceholderText(tr("select_video"))
        self.edit_video_path.setFixedHeight(40)
        self.edit_video_path.textChanged.connect(self._on_video_path_changed)
        src_layout.addWidget(self.edit_video_path, 1)

        self.btn_browse_video = QPushButton(tr("browse"))
        self.btn_browse_video.setObjectName("pillToggle")
        self.btn_browse_video.setIcon(get_icon("folder", size=16))
        self.btn_browse_video.clicked.connect(self._handle_browse_video)
        src_layout.addWidget(self.btn_browse_video)

        main_layout.addWidget(src_card)

        # ---------------- 2. Duration / Minutes per Episode Card ----------------
        self.lbl_duration_section = QLabel(tr("minutes_per_episode"))
        self.lbl_duration_section.setObjectName("sectionHeaderLabel")
        main_layout.addWidget(self.lbl_duration_section)

        duration_card = QFrame()
        duration_card.setObjectName("settingsGroupCard")
        dur_layout = QVBoxLayout(duration_card)
        dur_layout.setContentsMargins(16, 16, 16, 16)
        dur_layout.setSpacing(12)

        # Spinbox and presets row
        controls_row = QHBoxLayout()
        controls_row.setSpacing(10)

        self.spin_minutes = QSpinBox()
        self.spin_minutes.setRange(1, 180)
        self.spin_minutes.setValue(10)  # Default: 10 minutes per episode
        self.spin_minutes.setSuffix(" mn")
        self.spin_minutes.setFixedHeight(38)
        self.spin_minutes.setFixedWidth(100)
        controls_row.addWidget(self.spin_minutes)

        # Preset pills: 5, 10, 15, 20
        self.preset_group = QButtonGroup(self)
        for minutes in [5, 10, 15, 20]:
            btn = QPushButton(f"{minutes} mn")
            btn.setObjectName("pillToggle")
            btn.setCheckable(True)
            if minutes == 10:
                btn.setChecked(True)
            btn.clicked.connect(lambda _, m=minutes: self.spin_minutes.setValue(m))
            self.preset_group.addButton(btn)
            controls_row.addWidget(btn)

        controls_row.addStretch()
        dur_layout.addLayout(controls_row)

        self.spin_minutes.valueChanged.connect(self._sync_preset_buttons)
        main_layout.addWidget(duration_card)

        # ---------------- 3. Output Folder Card ----------------
        self.lbl_out_section = QLabel(tr("output_folder"))
        self.lbl_out_section.setObjectName("sectionHeaderLabel")
        main_layout.addWidget(self.lbl_out_section)

        out_card = QFrame()
        out_card.setObjectName("settingsGroupCard")
        out_layout = QHBoxLayout(out_card)
        out_layout.setContentsMargins(16, 14, 16, 14)
        out_layout.setSpacing(10)

        self.edit_output_dir = QLineEdit()
        self.edit_output_dir.setObjectName("urlInput")
        self.edit_output_dir.setFixedHeight(40)
        self._update_default_output_dir()
        out_layout.addWidget(self.edit_output_dir, 1)

        self.btn_browse_out = QPushButton(tr("browse"))
        self.btn_browse_out.setObjectName("pillToggle")
        self.btn_browse_out.setIcon(get_icon("folder", size=16))
        self.btn_browse_out.clicked.connect(self._handle_browse_output)
        out_layout.addWidget(self.btn_browse_out)

        main_layout.addWidget(out_card)

        # ---------------- Progress Bar & Status ----------------
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("thickProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("metaLabel")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.lbl_status)

        main_layout.addStretch()

        # ---------------- Bottom Action Buttons ----------------
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        self.btn_open_folder = QPushButton(tr("open_folder"))
        self.btn_open_folder.setObjectName("pillToggle")
        self.btn_open_folder.setIcon(get_icon("folder", size=16))
        self.btn_open_folder.setVisible(False)
        self.btn_open_folder.clicked.connect(self._handle_open_output_folder)
        bottom_row.addWidget(self.btn_open_folder)

        bottom_row.addStretch()

        self.btn_cancel = QPushButton(tr("cancel"))
        self.btn_cancel.setObjectName("pillToggle")
        self.btn_cancel.clicked.connect(self._handle_cancel)
        bottom_row.addWidget(self.btn_cancel)

        self.btn_split = QPushButton(tr("split_now"))
        self.btn_split.setObjectName("primaryButton")
        self.btn_split.setIcon(get_icon("scissors", color="#FFFFFF", size=18))
        self.btn_split.clicked.connect(self._handle_start_split)
        bottom_row.addWidget(self.btn_split)

        main_layout.addLayout(bottom_row)

    def _sync_preset_buttons(self, val: int) -> None:
        for btn in self.preset_group.buttons():
            btn.setChecked(btn.text().startswith(str(val)))

    def _on_video_path_changed(self) -> None:
        self._update_default_output_dir()

    def _update_default_output_dir(self) -> None:
        raw_path = self.edit_video_path.text().strip()
        if raw_path:
            p = Path(raw_path)
            default_dir = p.parent / f"{p.stem}_Episodes"
        else:
            default_dir = Path(get_download_folder()) / "Split_Episodes"
        self.edit_output_dir.setText(str(default_dir))

    def _handle_browse_video(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            tr("select_video"),
            get_download_folder(),
            "Video Files (*.mp4 *.mkv *.ts *.mov *.avi *.webm);;All Files (*.*)",
        )
        if chosen:
            self.edit_video_path.setText(chosen)

    def _handle_browse_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, tr("output_folder"), self.edit_output_dir.text()
        )
        if chosen:
            self.edit_output_dir.setText(chosen)

    def _handle_start_split(self) -> None:
        video_path = self.edit_video_path.text().strip()
        if not video_path or not os.path.exists(video_path):
            self.lbl_status.setText(tr("select_video"))
            return

        out_dir = self.edit_output_dir.text().strip()
        minutes = self.spin_minutes.value()

        # Disable buttons and start progress
        self.btn_split.setEnabled(False)
        self.btn_browse_video.setEnabled(False)
        self.btn_browse_out.setEnabled(False)
        self.spin_minutes.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(15)
        self.lbl_status.setText(f"{tr('splitting')} ({minutes} mn per ep)")

        self.worker = VideoSplitterWorker(
            input_file=video_path,
            minutes_per_episode=minutes,
            output_dir=out_dir,
        )
        self.worker.progress_changed.connect(self._on_progress_changed)
        self.worker.finished.connect(self._on_split_finished)
        self.worker.error.connect(self._on_split_error)
        self.worker.start()

    def _on_progress_changed(self, percent: float) -> None:
        self.progress_bar.setValue(int(percent))

    def _on_split_finished(self, out_dir: str, files: list[str]) -> None:
        self._output_dir = out_dir
        self.progress_bar.setValue(100)
        self.lbl_status.setText(
            f"{tr('split_completed')} ({len(files)} {tr('episodes_generated')})"
        )
        self.btn_split.setEnabled(True)
        self.btn_split.setText(tr("close"))
        self.btn_split.clicked.disconnect()
        self.btn_split.clicked.connect(self.accept)
        self.btn_open_folder.setVisible(True)

    def _on_split_error(self, err_msg: str) -> None:
        self.progress_bar.setVisible(False)
        self.lbl_status.setText(f"{tr('status_error')}: {err_msg}")
        self.btn_split.setEnabled(True)
        self.btn_browse_video.setEnabled(True)
        self.btn_browse_out.setEnabled(True)
        self.spin_minutes.setEnabled(True)

    def _handle_open_output_folder(self) -> None:
        if self._output_dir and os.path.exists(self._output_dir):
            if os.name == "nt":
                os.startfile(self._output_dir)
            else:
                subprocess.run(["xdg-open", self._output_dir], check=False)

    def _handle_cancel(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        self.reject()

    def retranslate_ui(self) -> None:
        """Dynamically re-applies translations on language switch."""
        self.setWindowTitle(tr("split_movie"))
        self.title_label.setText(tr("split_movie"))
        self.lbl_src_section.setText(tr("source_video"))
        self.lbl_duration_section.setText(tr("minutes_per_episode"))
        self.lbl_out_section.setText(tr("output_folder"))
        self.btn_browse_video.setText(tr("browse"))
        self.btn_browse_out.setText(tr("browse"))
        self.btn_open_folder.setText(tr("open_folder"))
        self.btn_cancel.setText(tr("cancel"))
        if not (self.worker and not self.worker.isRunning()):
            self.btn_split.setText(tr("split_now"))

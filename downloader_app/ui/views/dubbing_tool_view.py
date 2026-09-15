"""
Dubbing Tool View Module
One UI 9 AI Voice Dubbing view supporting automated Chinese subtitle extraction,
Gemini Khmer translation, VoxCPM2 TTS audio clip generation, and FFmpeg audio sync.
"""

import math
import os
from pathlib import Path
import re
import struct
import wave

from PyQt6.QtCore import QEvent, QPointF, QRectF, QSizeF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QIntValidator,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem, QVideoWidget
except ImportError:
    QAudioOutput = None
    QMediaPlayer = None
    QGraphicsVideoItem = None
    QVideoWidget = None

from downloader_app.core.config import get_download_folder, get_theme
from downloader_app.core.dubbing_mixer import DubbingMixerWorker
from downloader_app.core.subtitle_burner import auto_wrap_khmer_text, split_subtitle_into_timed_chunks
from downloader_app.core.subtitle_extractor import SubtitleExtractorWorker, SubtitleItem
from downloader_app.core.translator import SubtitleTranslationWorker
from downloader_app.core.tts_voxcpm import VoxCPM2DubbingWorker
from downloader_app.ui.resources.icon_helper import get_icon
from downloader_app.ui.widgets.color_picker_dialog import SubtitleColorPickerDialog
from downloader_app.utils.i18n import get_i18n_manager, tr
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.ui.dubbing_tool_view")


class IOSSwitch(QWidget):
    """Modern iOS/OneUI styled rounded pill toggle switch."""

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None, checked=False):
        super().__init__(parent)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, val: bool) -> None:
        if self._checked != val:
            self._checked = val
            self.toggled.emit(val)
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#2563EB") if self._checked else QColor("#CBD5E1")
        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 11, 11)

        knob_x = self.width() - 19 if self._checked else 3
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawEllipse(knob_x, 3, 16, 16)


class QuickActionButton(QPushButton):
    """Clean One UI action card button with icon on top and label below."""

    def __init__(self, icon_name: str, label_text: str, bg_style: str, text_color: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ {bg_style} border-radius: 12px; outline: none; }} "
            f"QPushButton:hover {{ opacity: 0.92; }}"
        )
        self.setMinimumHeight(78)
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(4, 8, 4, 8)
        vbox.setSpacing(5)
        vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ic_lbl = QLabel()
        ic_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        ic_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic_lbl.setPixmap(get_icon(icon_name, color=text_color, size=22).pixmap(22, 22))
        vbox.addWidget(ic_lbl)

        txt_lbl = QLabel(label_text)
        txt_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        txt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        txt_lbl.setStyleSheet(f"color: {text_color}; font-size: 11px; font-weight: 600; line-height: 1.2;")
        vbox.addWidget(txt_lbl)


class HeroGraphicWidget(QWidget):
    """Stylized 3D-styled video card graphic with playhead, waveforms, and floating badges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(210, 115)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Soft card shadow / glow
        card_rect = QRectF(18, 10, 138, 95)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(59, 130, 246, 25)))
        painter.drawRoundedRect(card_rect.adjusted(-3, -3, 3, 3), 16, 16)

        # Main video player card (vibrant blue gradient)
        grad = QLinearGradient(card_rect.topLeft(), card_rect.bottomRight())
        grad.setColorAt(0.0, QColor("#3B82F6"))
        grad.setColorAt(1.0, QColor("#60A5FA"))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(card_rect, 14, 14)

        # Play circle in center
        cx = card_rect.center().x()
        cy = card_rect.center().y() - 8
        painter.setBrush(QBrush(QColor(255, 255, 255, 70)))
        painter.drawEllipse(QPointF(cx, cy), 16, 16)
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        play_path = QPainterPath()
        play_path.moveTo(cx - 4, cy - 6)
        play_path.lineTo(cx + 6, cy)
        play_path.lineTo(cx - 4, cy + 6)
        play_path.closeSubpath()
        painter.drawPath(play_path)

        # Waveform line across bottom of card
        painter.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
        wave_y = card_rect.bottom() - 16
        import math
        for x in range(int(card_rect.left()) + 12, int(card_rect.right()) - 12, 3):
            amp = (math.sin(x * 0.3) * 0.5 + math.cos(x * 0.15) * 0.5) * 7 + 2
            painter.drawLine(x, int(wave_y - amp), x, int(wave_y + amp))

        # Floating soundwave badge on the left
        sound_rect = QRectF(2, 42, 28, 28)
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.setPen(QPen(QColor("#E2E8F0"), 1))
        painter.drawRoundedRect(sound_rect, 14, 14)
        painter.setPen(QPen(QColor("#3B82F6"), 2))
        scx = sound_rect.center().x()
        scy = sound_rect.center().y()
        for ox, oh in [(-4, 5), (0, 11), (4, 7)]:
            painter.drawLine(int(scx + ox), int(scy - oh / 2), int(scx + ox), int(scy + oh / 2))

        # Floating language badges on the right
        badges = [
            (146, 8, "🇺🇸", "EN"),
            (156, 42, "🇰🇭", "KH"),
            (146, 76, "🇯🇵", "JP"),
        ]
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        for bx, by, flag, code in badges:
            b_rect = QRectF(bx, by, 50, 20)
            painter.setBrush(QBrush(QColor("#FFFFFF")))
            painter.setPen(QPen(QColor("#E2E8F0"), 1))
            painter.drawRoundedRect(b_rect, 10, 10)
            painter.setPen(QPen(QColor("#1E293B")))
            painter.drawText(int(bx + 5), int(by + 14), f"{flag} {code}")


class DropZoneFrame(QFrame):
    """Modern studio drag-and-drop placeholder frame for video importing."""

    def __init__(self, parent=None, on_dropped=None):
        super().__init__(parent)
        self.setObjectName("videoPlaceholder")
        self.setAcceptDrops(True)
        self.on_dropped = on_dropped
        self._is_drag_active = False

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                video_exts = {".mp4", ".mkv", ".ts", ".mov", ".avi", ".webm"}
                if os.path.isdir(path) or any(path.lower().endswith(ext) for ext in video_exts):
                    self._is_drag_active = True
                    self._apply_drag_style()
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._is_drag_active = False
        self._apply_drag_style()
        event.accept()

    def dropEvent(self, event):
        self._is_drag_active = False
        self._apply_drag_style()
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                if self.on_dropped:
                    self.on_dropped(path)
                event.acceptProposedAction()
                return
        event.ignore()

    def _apply_drag_style(self):
        is_dark = get_theme() == "dark"
        if self._is_drag_active:
            if is_dark:
                self.setStyleSheet(
                    "QFrame#videoPlaceholder { background-color: rgba(99, 102, 241, 0.12); border: 2px dashed #818CF8; border-radius: 12px; } "
                    "QFrame#videoPlaceholder QLabel { background: transparent; border: none; outline: none; } "
                    "QFrame#videoPlaceholder QPushButton { outline: none; }"
                )
            else:
                self.setStyleSheet(
                    "QFrame#videoPlaceholder { background-color: rgba(18, 89, 195, 0.08); border: 2px dashed #1259C3; border-radius: 12px; } "
                    "QFrame#videoPlaceholder QLabel { background: transparent; border: none; outline: none; } "
                    "QFrame#videoPlaceholder QPushButton { outline: none; }"
                )
        else:
            if is_dark:
                self.setStyleSheet(
                    "QFrame#videoPlaceholder { background-color: #0B1120; border: 2px dashed #334155; border-radius: 12px; } "
                    "QFrame#videoPlaceholder QLabel { background: transparent; border: none; outline: none; } "
                    "QFrame#videoPlaceholder QPushButton { outline: none; }"
                )
            else:
                self.setStyleSheet(
                    "QFrame#videoPlaceholder { background-color: #F8FAFC; border: 2px dashed #CBD5E1; border-radius: 12px; } "
                    "QFrame#videoPlaceholder QLabel { background: transparent; border: none; outline: none; } "
                    "QFrame#videoPlaceholder QPushButton { outline: none; }"
                )


class StudioTimelineWidget(QWidget):
    """Custom Studio Timeline widget with T1 subtitle timing blocks, A1 audio waveform visualization, and playhead scrubber."""

    position_changed = pyqtSignal(int)  # ms position clicked/dragged

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(115)
        self.setMouseTracking(True)
        self._duration_ms = 270000  # Default 4:30 duration
        self._position_ms = 0
        self._zoom_level = 100
        self._subtitle_items = []
        self._is_scrubbing = False

    def set_duration(self, ms: int):
        self._duration_ms = max(1000, ms)
        self.update()

    def set_position(self, ms: int):
        self._position_ms = max(0, min(self._duration_ms, ms))
        self.update()

    def set_subtitles(self, items):
        self._subtitle_items = items
        self.update()

    def set_zoom(self, val: int):
        self._zoom_level = val
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        is_dark = get_theme() == "dark"

        w = self.width()
        h = self.height()

        # Background canvas
        bg_color = QColor("#0F172A") if is_dark else QColor("#F8FAFC")
        painter.fillRect(0, 0, w, h, bg_color)

        header_w = 40
        track_w = max(1, w - header_w)

        # ── 1. Time Ruler Header (Top 22px) ──
        ruler_h = 22
        ruler_bg = QColor("#1E293B") if is_dark else QColor("#EEF2FF")
        painter.fillRect(header_w, 0, track_w, ruler_h, ruler_bg)

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QPen(QColor("#94A3B8") if is_dark else QColor("#64748B")))

        num_ticks = 10
        step_ms = self._duration_ms / num_ticks
        for i in range(num_ticks + 1):
            cur_ms = i * step_ms
            x = header_w + (i / num_ticks) * track_w
            secs = int(cur_ms // 1000)
            mins = secs // 60
            secs = secs % 60
            time_str = f"{mins:02d}:{secs:02d}"
            painter.drawLine(int(x), ruler_h - 5, int(x), ruler_h)
            painter.drawText(int(x) - 16, 14, time_str)

        # ── 2. Track T1 (Subtitle Text Blocks) Row ──
        t1_y = 26
        t1_h = 36
        # Header T1 tile
        hdr_t1_bg = QColor("#6366F1")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(hdr_t1_bg))
        painter.drawRoundedRect(4, t1_y + 2, 32, t1_h - 4, 6, 6)
        painter.setPen(QPen(QColor("#FFFFFF")))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(12, t1_y + 22, "T1")

        # T1 track lane bg
        lane_t1_bg = QColor("#1E1B4B") if is_dark else QColor("#F1F5F9")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(lane_t1_bg))
        painter.drawRoundedRect(header_w, t1_y, track_w, t1_h, 6, 6)

        # Render subtitle items on T1 track
        painter.setFont(QFont("Segoe UI", 8))
        if self._subtitle_items:
            for item in self._subtitle_items:
                start_x = header_w + (item.start_ms / self._duration_ms) * track_w
                end_x = header_w + (item.end_ms / self._duration_ms) * track_w
                item_w = max(24, end_x - start_x)

                pill_bg = QColor("#818CF8") if is_dark else QColor("#EDE9FE")
                painter.setPen(QPen(QColor("#C4B5FD"), 1))
                painter.setBrush(QBrush(pill_bg))
                painter.drawRoundedRect(int(start_x), t1_y + 3, int(item_w), t1_h - 6, 6, 6)

                painter.setPen(QPen(QColor("#1E1B4B") if not is_dark else QColor("#FFFFFF")))
                txt = item.khmer_text or item.text or ""
                elided_txt = painter.fontMetrics().elidedText(txt, Qt.TextElideMode.ElideRight, int(item_w) - 8)
                painter.drawText(int(start_x) + 6, t1_y + 22, elided_txt)
        else:
            demo_blocks = [
                (0, 18000, "Hello everyone,"),
                (20000, 42000, "this is an AI voice dubber."),
                (45000, 75000, "It can translate and dub your video"),
                (80000, 110000, "into multiple languages."),
            ]
            for start_ms, end_ms, txt in demo_blocks:
                start_x = header_w + (start_ms / self._duration_ms) * track_w
                end_x = header_w + (end_ms / self._duration_ms) * track_w
                item_w = max(24, end_x - start_x)

                pill_bg = QColor("#818CF8") if is_dark else QColor("#EDE9FE")
                painter.setPen(QPen(QColor("#C4B5FD"), 1))
                painter.setBrush(QBrush(pill_bg))
                painter.drawRoundedRect(int(start_x), t1_y + 3, int(item_w), t1_h - 6, 6, 6)

                painter.setPen(QPen(QColor("#1E1B4B") if not is_dark else QColor("#FFFFFF")))
                elided_txt = painter.fontMetrics().elidedText(txt, Qt.TextElideMode.ElideRight, int(item_w) - 8)
                painter.drawText(int(start_x) + 6, t1_y + 22, elided_txt)

        # ── 3. Track A1 (Audio Waveform Visualizer) Row ──
        a1_y = 66
        a1_h = 36
        # Header A1 tile
        hdr_a1_bg = QColor("#10B981")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(hdr_a1_bg))
        painter.drawRoundedRect(4, a1_y + 2, 32, a1_h - 4, 6, 6)
        painter.setPen(QPen(QColor("#FFFFFF")))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(12, a1_y + 22, "A1")

        # A1 track lane bg
        lane_a1_bg = QColor("#064E3B") if is_dark else QColor("#D1FAE5")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(lane_a1_bg))
        painter.drawRoundedRect(header_w, a1_y, track_w, a1_h, 6, 6)

        # Audio Waveform Spikes
        wave_color = QColor("#34D399") if is_dark else QColor("#059669")
        painter.setPen(QPen(wave_color, 1.5))
        mid_y = a1_y + (a1_h / 2)
        step_px = 3
        import math

        for x_pos in range(header_w + 2, header_w + int(track_w) - 2, step_px):
            amp = (math.sin(x_pos * 0.08) * 0.4 + math.cos(x_pos * 0.15) * 0.5 + 0.3) * (a1_h * 0.35)
            painter.drawLine(x_pos, int(mid_y - amp), x_pos, int(mid_y + amp))

        # ── 4. Scrubbable Playhead Line ──
        play_x = header_w + (self._position_ms / self._duration_ms) * track_w
        painter.setPen(QPen(QColor("#2563EB"), 2))
        painter.drawLine(int(play_x), 0, int(play_x), h)

        # Playhead top handle
        painter.setBrush(QBrush(QColor("#2563EB")))
        painter.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath()
        path.moveTo(play_x - 6, 0)
        path.lineTo(play_x + 6, 0)
        path.lineTo(play_x, 8)
        path.closeSubpath()
        painter.drawPath(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_scrubbing = True
            self._update_scrub_pos(event.pos().x())

    def mouseMoveEvent(self, event):
        if self._is_scrubbing:
            self._update_scrub_pos(event.pos().x())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_scrubbing = False

    def _update_scrub_pos(self, x: int):
        header_w = 40
        track_w = max(1, self.width() - header_w)
        ratio = max(0.0, min(1.0, (x - header_w) / track_w))
        target_ms = int(ratio * self._duration_ms)
        self.set_position(target_ms)
        self.position_changed.emit(target_ms)


class SubtitleOverlayItem(QGraphicsObject):
    """Rich Subtitle & Blur Mask overlay item with independent Mask Panel and Subtitle Text positioning & resizing."""

    box_geometry_changed = pyqtSignal(int, int)
    mask_geometry_changed = pyqtSignal(int, int)
    box_position_changed = pyqtSignal(float, float)
    mask_position_changed = pyqtSignal(float, float)
    sub_position_changed = pyqtSignal(float, float)

    HANDLE_NONE = 0
    HANDLE_MASK_TOP = 1
    HANDLE_MASK_BOTTOM = 2
    HANDLE_MASK_LEFT = 3
    HANDLE_MASK_RIGHT = 4
    HANDLE_MASK_TOP_LEFT = 5
    HANDLE_MASK_TOP_RIGHT = 6
    HANDLE_MASK_BOTTOM_LEFT = 7
    HANDLE_MASK_BOTTOM_RIGHT = 8
    HANDLE_MASK_BODY = 9
    HANDLE_SUB_BODY = 10

    # Backwards compatibility constants
    HANDLE_TOP = 1
    HANDLE_BOTTOM = 2
    HANDLE_LEFT = 3
    HANDLE_RIGHT = 4
    HANDLE_TOP_LEFT = 5
    HANDLE_TOP_RIGHT = 6
    HANDLE_BOTTOM_LEFT = 7
    HANDLE_BOTTOM_RIGHT = 8
    HANDLE_BODY = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setZValue(100)
        self.setAcceptHoverEvents(True)
        self._text = ""
        self._blur_enabled = True
        self._burn_enabled = True
        self._font_variant = "Bold"
        self._font_size_pt = 30
        self._sub_text_color = "#FFFFFF"
        self._bg_box_w_scale = 100
        self._bg_box_h_scale = 100
        self._bg_box_color = "#FFFFFF"
        self._bg_box_opacity = 100

        # Independent positions
        self._mask_pos_x_ratio: float | None = None
        self._mask_pos_y_ratio: float | None = None
        self._sub_pos_x_ratio: float | None = None
        self._sub_pos_y_ratio: float | None = None

        self._target_rect = QRectF(0, 0, 100, 50)

        # Interactive mouse resize & drag state
        self._is_mask_hovered = False
        self._is_sub_hovered = False
        self._is_dragging = False
        self._drag_target = self.HANDLE_NONE  # MASK_BODY, SUB_BODY, or resize handle
        self._drag_start_pos = None
        self._drag_start_w_scale = 100
        self._drag_start_h_scale = 100
        self._drag_start_mask_x = 0.5
        self._drag_start_mask_y = 0.76
        self._drag_start_sub_x = 0.5
        self._drag_start_sub_y = 0.88
        self._cached_base_w = 100.0
        self._cached_base_h = 50.0

    @property
    def _pos_x_ratio(self) -> float | None:
        return self._mask_pos_x_ratio

    @_pos_x_ratio.setter
    def _pos_x_ratio(self, val: float | None) -> None:
        self._mask_pos_x_ratio = val

    @property
    def _pos_y_ratio(self) -> float | None:
        return self._mask_pos_y_ratio

    @_pos_y_ratio.setter
    def _pos_y_ratio(self, val: float | None) -> None:
        self._mask_pos_y_ratio = val

    @property
    def _is_hovered(self) -> bool:
        return self._is_mask_hovered or self._is_sub_hovered

    @_is_hovered.setter
    def _is_hovered(self, val: bool) -> None:
        self._is_mask_hovered = val

    @property
    def _active_handle(self) -> int:
        return self._drag_target

    @_active_handle.setter
    def _active_handle(self, val: int) -> None:
        self._drag_target = val

    @property
    def _is_moving_pos(self) -> bool:
        return self._drag_target == self.HANDLE_MASK_BODY

    @_is_moving_pos.setter
    def _is_moving_pos(self, val: bool) -> None:
        if val:
            self._drag_target = self.HANDLE_MASK_BODY

    def set_subtitle(
        self,
        text: str,
        blur_enabled: bool = True,
        burn_enabled: bool = True,
        font_variant: str = "Bold",
        font_size_pt: int = 30,
        sub_text_color: str = "#FFFFFF",
        bg_box_scale: int | None = None,
        bg_box_w_scale: int = 100,
        bg_box_h_scale: int = 100,
        bg_box_color: str = "#FFFFFF",
        bg_box_opacity: int = 100,
        pos_x_ratio: float | None = None,
        pos_y_ratio: float | None = None,
        mask_pos_x_ratio: float | None = None,
        mask_pos_y_ratio: float | None = None,
        sub_pos_x_ratio: float | None = None,
        sub_pos_y_ratio: float | None = None,
    ):
        self._text = text.strip() if text else ""
        self._blur_enabled = blur_enabled
        self._burn_enabled = burn_enabled
        self._font_variant = font_variant
        self._font_size_pt = font_size_pt
        self._sub_text_color = sub_text_color
        self._bg_box_w_scale = bg_box_w_scale
        self._bg_box_h_scale = bg_box_scale if bg_box_scale is not None else bg_box_h_scale
        self._bg_box_color = bg_box_color
        self._bg_box_opacity = bg_box_opacity

        actual_mask_x = mask_pos_x_ratio if mask_pos_x_ratio is not None else pos_x_ratio
        actual_mask_y = mask_pos_y_ratio if mask_pos_y_ratio is not None else pos_y_ratio
        if actual_mask_x is not None:
            self._mask_pos_x_ratio = actual_mask_x
        if actual_mask_y is not None:
            self._mask_pos_y_ratio = actual_mask_y

        if sub_pos_x_ratio is not None:
            self._sub_pos_x_ratio = sub_pos_x_ratio
        if sub_pos_y_ratio is not None:
            self._sub_pos_y_ratio = sub_pos_y_ratio

        self.update()

    def text(self) -> str:
        return self._text

    def isHidden(self) -> bool:
        return not bool((self._text and self._burn_enabled) or self._blur_enabled)

    def set_target_rect(self, rect: QRectF):
        self.prepareGeometryChange()
        self._target_rect = rect
        self.update()

    def boundingRect(self) -> QRectF:
        return self._target_rect

    def _compute_mask_geometry(self) -> tuple[QRectF, float, float, float, float, float]:
        w = self._target_rect.width()
        h = self._target_rect.height()
        if w < 50 or h < 30:
            return QRectF(), 100.0, 50.0, 8.0, 16.0, 12.0

        is_portrait = h > w
        if is_portrait:
            base_w = max(60.0, w * 0.94)
            base_h = max(36.0, h * 0.22)
            default_y = self._target_rect.y() + (h * 0.68)
            corner_r = max(6.0, 16.0 * (min(w, h) / 1080.0))
            pad_x = max(8.0, 32.0 * (w / 1080.0))
            pad_y = max(6.0, 16.0 * (h / 1920.0))
        else:
            base_w = max(60.0, w * 0.88)
            base_h = max(36.0, h * 0.18)
            default_y = self._target_rect.y() + (h * 0.76)
            corner_r = max(6.0, 12.0 * (h / 720.0))
            pad_x = max(8.0, 28.0 * (w / 1280.0))
            pad_y = max(6.0, 12.0 * (h / 720.0))

        w_mult = max(0.20, min(2.5, float(self._bg_box_w_scale) / 100.0))
        h_mult = max(0.20, min(3.5, float(self._bg_box_h_scale) / 100.0))

        box_w = max(30.0, min(w, base_w * w_mult))
        box_h = max(15.0, min(h, base_h * h_mult))

        if self._mask_pos_x_ratio is not None:
            box_cx = self._target_rect.x() + (w * self._mask_pos_x_ratio)
            box_x = box_cx - (box_w / 2.0)
        else:
            box_x = self._target_rect.x() + (w - box_w) / 2.0

        if self._mask_pos_y_ratio is not None:
            box_cy = self._target_rect.y() + (h * self._mask_pos_y_ratio)
            box_y = box_cy - (box_h / 2.0)
        else:
            box_y = default_y - ((box_h - base_h) / 2.0)

        box_y = max(self._target_rect.y(), min(self._target_rect.bottom() - box_h, box_y))
        box_x = max(self._target_rect.x(), min(self._target_rect.right() - box_w, box_x))

        mask_rect = QRectF(box_x, box_y, box_w, box_h)
        return mask_rect, base_w, base_h, corner_r, pad_x, pad_y

    def _compute_box_geometry(self) -> tuple[QRectF, float, float, float, float, float]:
        """Backwards compatibility alias for _compute_mask_geometry."""
        return self._compute_mask_geometry()

    def _compute_sub_geometry(self) -> tuple[QRectF, str, QFont, int]:
        w = self._target_rect.width()
        h = self._target_rect.height()
        if w < 50 or h < 30 or not self._text:
            return QRectF(), "", QFont(), 12

        is_portrait = h > w
        default_y_ratio = 0.82 if is_portrait else 0.88
        sub_x_ratio = self._sub_pos_x_ratio if self._sub_pos_x_ratio is not None else 0.5
        sub_y_ratio = self._sub_pos_y_ratio if self._sub_pos_y_ratio is not None else default_y_ratio

        formatted_lines = []
        for raw_l in self._text.strip().split("\n"):
            formatted_lines.append(auto_wrap_khmer_text(raw_l.strip(), max_chars_per_line=28 if is_portrait else 38))
        wrapped_text = "\n".join(formatted_lines)

        scale_factor = max(0.55, min(2.5, h / 360.0))
        base_px = max(10, int(round((self._font_size_pt / 30.0) * 15.0 * scale_factor)))
        target_px = base_px

        variant_clean = str(self._font_variant).strip().lower()
        if "italic" in variant_clean:
            font_weight = QFont.Weight.Normal
            is_italic = True
        elif "regular" in variant_clean or "normal" in variant_clean:
            font_weight = QFont.Weight.Normal
            is_italic = False
        elif "semibold" in variant_clean or "demi" in variant_clean:
            font_weight = QFont.Weight.DemiBold
            is_italic = False
        else:  # Bold
            font_weight = QFont.Weight.Bold
            is_italic = False

        max_avail_w = max(100.0, w * (0.94 if is_portrait else 0.90))
        max_avail_h = max(30.0, h * 0.40)

        while target_px > 10:
            f_test = QFont("Google Sans", target_px, font_weight)
            f_test.setItalic(is_italic)
            f_test.setStyleHint(QFont.StyleHint.SansSerif)
            fm = QFontMetrics(f_test)
            max_line_w = max((fm.horizontalAdvance(line) for line in wrapped_text.split("\n")), default=0)
            total_text_h = fm.height() * len(wrapped_text.split("\n"))
            if max_line_w <= max_avail_w and total_text_h <= max_avail_h:
                break
            target_px -= 1

        font = QFont("Google Sans", target_px, font_weight)
        font.setItalic(is_italic)
        font.setStyleHint(QFont.StyleHint.SansSerif)

        fm = QFontMetrics(font)
        max_line_w = max((fm.horizontalAdvance(line) for line in wrapped_text.split("\n")), default=60)
        total_text_h = fm.height() * len(wrapped_text.split("\n"))

        sub_w = min(w, max(80.0, max_line_w + 24.0))
        sub_h = min(h, max(28.0, total_text_h + 16.0))

        sub_cx = self._target_rect.x() + (w * sub_x_ratio)
        sub_cy = self._target_rect.y() + (h * sub_y_ratio)

        sub_x = sub_cx - (sub_w / 2.0)
        sub_y = sub_cy - (sub_h / 2.0)

        sub_x = max(self._target_rect.x(), min(self._target_rect.right() - sub_w, sub_x))
        sub_y = max(self._target_rect.y(), min(self._target_rect.bottom() - sub_h, sub_y))

        sub_rect = QRectF(sub_x, sub_y, sub_w, sub_h)
        return sub_rect, wrapped_text, font, target_px

    def _get_mask_handle_at(self, pos: QPointF, mask_rect: QRectF) -> int:
        if mask_rect.isEmpty():
            return self.HANDLE_NONE

        m = 14.0  # Pixel margin for grab handles
        x, y = pos.x(), pos.y()
        bx, by, bw, bh = mask_rect.x(), mask_rect.y(), mask_rect.width(), mask_rect.height()
        br, bb = bx + bw, by + bh

        if x < bx - m or x > br + m or y < by - m or y > bb + m:
            return self.HANDLE_NONE

        near_left = abs(x - bx) <= m
        near_right = abs(x - br) <= m
        near_top = abs(y - by) <= m
        near_bottom = abs(y - bb) <= m

        if near_top and near_left:
            return self.HANDLE_MASK_TOP_LEFT
        if near_top and near_right:
            return self.HANDLE_MASK_TOP_RIGHT
        if near_bottom and near_left:
            return self.HANDLE_MASK_BOTTOM_LEFT
        if near_bottom and near_right:
            return self.HANDLE_MASK_BOTTOM_RIGHT

        if near_top and bx <= x <= br:
            return self.HANDLE_MASK_TOP
        if near_bottom and bx <= x <= br:
            return self.HANDLE_MASK_BOTTOM
        if near_left and by <= y <= bb:
            return self.HANDLE_MASK_LEFT
        if near_right and by <= y <= bb:
            return self.HANDLE_MASK_RIGHT

        if mask_rect.contains(pos):
            return self.HANDLE_MASK_BODY

        return self.HANDLE_NONE

    def _get_handle_at(self, pos: QPointF, box_rect: QRectF) -> int:
        """Backwards compatibility helper."""
        return self._get_mask_handle_at(pos, box_rect)

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent):
        pos = event.pos()
        mask_rect, _, _, _, _, _ = self._compute_mask_geometry()
        sub_rect, _, _, _ = self._compute_sub_geometry()

        mask_handle = self._get_mask_handle_at(pos, mask_rect) if self._blur_enabled else self.HANDLE_NONE
        is_on_sub = bool(self._burn_enabled and self._text and sub_rect.contains(pos))

        # Check Subtitle Text first
        if is_on_sub:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._is_sub_hovered = True
            self._is_mask_hovered = False
            self.update()
            return

        self._is_sub_hovered = False

        if mask_handle in (self.HANDLE_MASK_TOP, self.HANDLE_MASK_BOTTOM):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif mask_handle in (self.HANDLE_MASK_LEFT, self.HANDLE_MASK_RIGHT):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif mask_handle in (self.HANDLE_MASK_TOP_LEFT, self.HANDLE_MASK_BOTTOM_RIGHT):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif mask_handle in (self.HANDLE_MASK_TOP_RIGHT, self.HANDLE_MASK_BOTTOM_LEFT):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif mask_handle == self.HANDLE_MASK_BODY:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.unsetCursor()

        new_mask_hov = mask_handle != self.HANDLE_NONE
        if new_mask_hov != self._is_mask_hovered:
            self._is_mask_hovered = new_mask_hov
            self.update()

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        self._is_mask_hovered = False
        self._is_sub_hovered = False
        self.unsetCursor()
        self.update()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if self._target_rect.isEmpty():
            super().mousePressEvent(event)
            return

        pos = event.pos()
        w = max(1.0, self._target_rect.width())
        h = max(1.0, self._target_rect.height())
        is_portrait = h > w

        mask_rect, base_w, base_h, _, _, _ = self._compute_mask_geometry()
        sub_rect, _, _, _ = self._compute_sub_geometry()

        is_on_sub = bool(self._burn_enabled and self._text and sub_rect.contains(pos))
        mask_handle = self._get_mask_handle_at(pos, mask_rect) if self._blur_enabled else self.HANDLE_NONE

        # 1. Click on Subtitle Text -> Drag Subtitle anywhere!
        if is_on_sub and event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._is_dragging = True
            self._drag_target = self.HANDLE_SUB_BODY
            self._drag_start_pos = pos
            default_sub_y = 0.82 if is_portrait else 0.88
            self._drag_start_sub_x = self._sub_pos_x_ratio if self._sub_pos_x_ratio is not None else 0.5
            self._drag_start_sub_y = self._sub_pos_y_ratio if self._sub_pos_y_ratio is not None else default_sub_y
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
            event.accept()
            return

        # 2. Right-Click Drag OR Left-Click on Mask Body -> Move Mask anywhere!
        if (event.button() == Qt.MouseButton.RightButton and self._blur_enabled) or (
            event.button() == Qt.MouseButton.LeftButton and mask_handle == self.HANDLE_MASK_BODY
        ):
            self._is_dragging = True
            self._drag_target = self.HANDLE_MASK_BODY
            self._drag_start_pos = pos
            self._drag_start_mask_x = self._mask_pos_x_ratio if self._mask_pos_x_ratio is not None else 0.5
            self._drag_start_mask_y = self._mask_pos_y_ratio if self._mask_pos_y_ratio is not None else (0.68 if is_portrait else 0.76)
            self._cached_base_w = base_w
            self._cached_base_h = base_h
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
            event.accept()
            return

        # 3. Left-Click on Mask Resize Handles -> Resize Mask Width & Height!
        if event.button() == Qt.MouseButton.LeftButton and mask_handle != self.HANDLE_NONE:
            self._is_dragging = True
            self._drag_target = mask_handle
            self._drag_start_pos = pos
            self._drag_start_w_scale = self._bg_box_w_scale
            self._drag_start_h_scale = self._bg_box_h_scale
            self._cached_base_w = base_w
            self._cached_base_h = base_h
            self.update()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if self._is_dragging and self._drag_start_pos is not None:
            delta = event.pos() - self._drag_start_pos
            w = max(1.0, self._target_rect.width())
            h = max(1.0, self._target_rect.height())

            # 1. Moving Subtitle Text
            if self._drag_target == self.HANDLE_SUB_BODY:
                delta_x = delta.x() / w
                delta_y = delta.y() / h
                new_x = max(0.04, min(0.96, self._drag_start_sub_x + delta_x))
                new_y = max(0.04, min(0.96, self._drag_start_sub_y + delta_y))
                self._sub_pos_x_ratio = new_x
                self._sub_pos_y_ratio = new_y
                self.update()
                self.sub_position_changed.emit(new_x, new_y)
                event.accept()
                return

            # 2. Moving Mask Panel
            if self._drag_target == self.HANDLE_MASK_BODY:
                delta_x = delta.x() / w
                delta_y = delta.y() / h
                new_x = max(0.02, min(0.98, self._drag_start_mask_x + delta_x))
                new_y = max(0.02, min(0.98, self._drag_start_mask_y + delta_y))
                self._mask_pos_x_ratio = new_x
                self._mask_pos_y_ratio = new_y
                self.update()
                self.mask_position_changed.emit(new_x, new_y)
                self.box_position_changed.emit(new_x, new_y)
                event.accept()
                return

            # 3. Resizing Mask Panel
            bw = max(10.0, self._cached_base_w)
            bh = max(10.0, self._cached_base_h)

            new_w_scale = self._drag_start_w_scale
            new_h_scale = self._drag_start_h_scale
            handle = self._drag_target

            if handle == self.HANDLE_MASK_TOP:
                delta_h_px = -delta.y() * 2.0
                new_h_scale = int(round(self._drag_start_h_scale + (delta_h_px / bh) * 100.0))
            elif handle == self.HANDLE_MASK_BOTTOM:
                delta_h_px = delta.y() * 2.0
                new_h_scale = int(round(self._drag_start_h_scale + (delta_h_px / bh) * 100.0))
            elif handle == self.HANDLE_MASK_LEFT:
                delta_w_px = -delta.x() * 2.0
                new_w_scale = int(round(self._drag_start_w_scale + (delta_w_px / bw) * 100.0))
            elif handle == self.HANDLE_MASK_RIGHT:
                delta_w_px = delta.x() * 2.0
                new_w_scale = int(round(self._drag_start_w_scale + (delta_w_px / bw) * 100.0))
            elif handle == self.HANDLE_MASK_TOP_LEFT:
                delta_w_px = -delta.x() * 2.0
                delta_h_px = -delta.y() * 2.0
                new_w_scale = int(round(self._drag_start_w_scale + (delta_w_px / bw) * 100.0))
                new_h_scale = int(round(self._drag_start_h_scale + (delta_h_px / bh) * 100.0))
            elif handle == self.HANDLE_MASK_TOP_RIGHT:
                delta_w_px = delta.x() * 2.0
                delta_h_px = -delta.y() * 2.0
                new_w_scale = int(round(self._drag_start_w_scale + (delta_w_px / bw) * 100.0))
                new_h_scale = int(round(self._drag_start_h_scale + (delta_h_px / bh) * 100.0))
            elif handle == self.HANDLE_MASK_BOTTOM_LEFT:
                delta_w_px = -delta.x() * 2.0
                delta_h_px = delta.y() * 2.0
                new_w_scale = int(round(self._drag_start_w_scale + (delta_w_px / bw) * 100.0))
                new_h_scale = int(round(self._drag_start_h_scale + (delta_h_px / bh) * 100.0))
            elif handle == self.HANDLE_MASK_BOTTOM_RIGHT:
                delta_w_px = delta.x() * 2.0
                delta_h_px = delta.y() * 2.0
                new_w_scale = int(round(self._drag_start_w_scale + (delta_w_px / bw) * 100.0))
                new_h_scale = int(round(self._drag_start_h_scale + (delta_h_px / bh) * 100.0))

            new_w_scale = max(20, min(250, new_w_scale))
            new_h_scale = max(20, min(350, new_h_scale))

            self._bg_box_w_scale = new_w_scale
            self._bg_box_h_scale = new_h_scale
            self.update()
            self.mask_geometry_changed.emit(new_w_scale, new_h_scale)
            self.box_geometry_changed.emit(new_w_scale, new_h_scale)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if self._is_dragging:
            self._is_dragging = False
            self._drag_target = self.HANDLE_NONE
            self.unsetCursor()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paint(self, painter: QPainter, option, widget=None):
        if self._target_rect.isEmpty():
            return
        if not self._blur_enabled and not (self._text and self._burn_enabled):
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self._target_rect.width()
        h = self._target_rect.height()
        is_portrait = h > w

        # ── 1. Background Mask Panel (Dedicated to Covering Chinese Subtitles) ──
        mask_rect, _, _, corner_r, _, _ = self._compute_mask_geometry()
        if self._blur_enabled and not mask_rect.isEmpty():
            col = QColor(self._bg_box_color) if QColor.isValidColor(self._bg_box_color) else QColor("#FFFFFF")
            alpha = max(0, min(255, int(round((self._bg_box_opacity / 100.0) * 255.0))))
            col.setAlpha(alpha)

            if col.lightness() > 180:
                stroke_color = QColor(200, 205, 215, max(30, int(round((self._bg_box_opacity / 100.0) * 70.0))))
            else:
                stroke_alpha = max(0, min(100, int(round((self._bg_box_opacity / 100.0) * 55.0))))
                stroke_color = QColor(255, 255, 255, stroke_alpha)

            painter.setPen(QPen(stroke_color, 1.5))
            painter.setBrush(QBrush(col))
            painter.drawRoundedRect(mask_rect, corner_r, corner_r)

        # ── 2. Independent Subtitle Text (Rendered Anywhere across the Video) ──
        sub_rect, wrapped_text, font, _ = self._compute_sub_geometry()
        if self._burn_enabled and self._text and not sub_rect.isEmpty():
            painter.setFont(font)
            flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
            text_col = QColor(self._sub_text_color) if QColor.isValidColor(self._sub_text_color) else QColor("#FFFFFF")
            painter.setPen(text_col)
            painter.drawText(sub_rect, int(flags), wrapped_text)

        # ── 3. Interactive Controls for Mask Panel (8 Handles + Dashed Outline + HUD) ──
        if self._blur_enabled and (self._is_mask_hovered or (self._is_dragging and self._drag_target != self.HANDLE_SUB_BODY)):
            accent_col = QColor(99, 102, 241) if get_theme() == "dark" else QColor(18, 89, 195)
            pen_outline = QPen(accent_col, 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen_outline)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(mask_rect, corner_r, corner_r)

            # 4 Corner Grab Dots & 4 Edge Grab Dots
            handle_brush = QBrush(QColor(255, 255, 255))
            handle_pen = QPen(accent_col, 1.5)
            painter.setBrush(handle_brush)
            painter.setPen(handle_pen)

            bx, by, bw, bh = mask_rect.x(), mask_rect.y(), mask_rect.width(), mask_rect.height()
            for cx, cy in [(bx, by), (bx + bw, by), (bx, by + bh), (bx + bw, by + bh)]:
                painter.drawEllipse(QPointF(cx, cy), 4.5, 4.5)

            for ex, ey in [(bx + bw / 2.0, by), (bx + bw / 2.0, by + bh), (bx, by + bh / 2.0), (bx + bw, by + bh / 2.0)]:
                painter.drawEllipse(QPointF(ex, ey), 3.5, 3.5)

            # HUD Badge for Mask
            if self._is_dragging and self._drag_target != self.HANDLE_SUB_BODY:
                if self._drag_target == self.HANDLE_MASK_BODY:
                    cur_x_pct = int(round((self._mask_pos_x_ratio if self._mask_pos_x_ratio is not None else 0.5) * 100.0))
                    cur_y_pct = int(round((self._mask_pos_y_ratio if self._mask_pos_y_ratio is not None else (0.68 if is_portrait else 0.76)) * 100.0))
                    hud_text = f"🛡️ Mask: X: {cur_x_pct}%   Y: {cur_y_pct}%"
                else:
                    hud_text = f"↔ W: {self._bg_box_w_scale}%   •   ↕ H: {self._bg_box_h_scale}%"

                hud_font = QFont("Google Sans", 10, QFont.Weight.Bold)
                fm_hud = QFontMetrics(hud_font)
                hud_w = fm_hud.horizontalAdvance(hud_text) + 24.0
                hud_h = 24.0
                hud_x = bx + (bw - hud_w) / 2.0
                hud_y = max(self._target_rect.y() + 4.0, by - hud_h - 6.0)
                hud_rect = QRectF(hud_x, hud_y, hud_w, hud_h)

                painter.setPen(QPen(QColor(255, 255, 255, 50), 1.0))
                painter.setBrush(QBrush(QColor(15, 23, 42, 235)))
                painter.drawRoundedRect(hud_rect, 12.0, 12.0)
                painter.setFont(hud_font)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(hud_rect, int(Qt.AlignmentFlag.AlignCenter), hud_text)

        # ── 4. Interactive Controls for Subtitle Text (Hover Box + Move HUD) ──
        if self._burn_enabled and self._text and (self._is_sub_hovered or (self._is_dragging and self._drag_target == self.HANDLE_SUB_BODY)):
            sub_col = QColor(245, 158, 11)  # Amber / Warm accent for text
            painter.setPen(QPen(sub_col, 1.2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(sub_rect, 6.0, 6.0)

            # Subtitle Drag HUD
            if self._is_dragging and self._drag_target == self.HANDLE_SUB_BODY:
                cur_sx_pct = int(round((self._sub_pos_x_ratio if self._sub_pos_x_ratio is not None else 0.5) * 100.0))
                cur_sy_pct = int(round((self._sub_pos_y_ratio if self._sub_pos_y_ratio is not None else (0.82 if is_portrait else 0.88)) * 100.0))
                hud_text = f"💬 Subtitle: X: {cur_sx_pct}%   Y: {cur_sy_pct}%"

                hud_font = QFont("Google Sans", 10, QFont.Weight.Bold)
                fm_hud = QFontMetrics(hud_font)
                hud_w = fm_hud.horizontalAdvance(hud_text) + 24.0
                hud_h = 24.0
                hud_x = sub_rect.x() + (sub_rect.width() - hud_w) / 2.0
                hud_y = max(self._target_rect.y() + 4.0, sub_rect.y() - hud_h - 6.0)
                hud_rect = QRectF(hud_x, hud_y, hud_w, hud_h)

                painter.setPen(QPen(QColor(255, 255, 255, 50), 1.0))
                painter.setBrush(QBrush(QColor(15, 23, 42, 235)))
                painter.drawRoundedRect(hud_rect, 12.0, 12.0)
                painter.setFont(hud_font)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(hud_rect, int(Qt.AlignmentFlag.AlignCenter), hud_text)


class StudioVideoPlayerView(QGraphicsView):
    """Modern studio video viewport with hardware-accelerated subtitle & blur mask overlay."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.viewport().setMouseTracking(True)
        self.setStyleSheet("background-color: #000000; border-radius: 12px; border: none;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )

        self.video_item = QGraphicsVideoItem()
        self.scene.addItem(self.video_item)

        self.overlay_item = SubtitleOverlayItem()
        self.scene.addItem(self.overlay_item)

        self._video_native_size = QSizeF(1920, 1080)
        self.video_item.nativeSizeChanged.connect(self._on_native_size_changed)

    def _on_native_size_changed(self, size: QSizeF):
        if size.isValid() and size.width() > 0 and size.height() > 0:
            self._video_native_size = size
            self._relayout_scene()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_scene()

    def _relayout_scene(self):
        vw = self.viewport().width()
        vh = self.viewport().height()
        if vw <= 0 or vh <= 0:
            return

        self.scene.setSceneRect(0, 0, vw, vh)

        native_w = self._video_native_size.width()
        native_h = self._video_native_size.height()
        if native_w <= 0 or native_h <= 0:
            native_w, native_h = 16, 9

        aspect = native_w / native_h
        target_w = vw
        target_h = vw / aspect

        if target_h > vh:
            target_h = vh
            target_w = vh * aspect

        x = (vw - target_w) / 2.0
        y = (vh - target_h) / 2.0

        video_rect = QRectF(x, y, target_w, target_h)
        self.video_item.setSize(QSizeF(target_w, target_h))
        self.video_item.setPos(x, y)

        self.overlay_item.set_target_rect(video_rect)

    def set_subtitle(
        self,
        text: str,
        blur_enabled: bool = True,
        burn_enabled: bool = True,
        font_variant: str = "Bold",
        font_size_pt: int = 30,
        sub_text_color: str = "#FFFFFF",
        bg_box_scale: int | None = None,
        bg_box_w_scale: int = 100,
        bg_box_h_scale: int = 100,
        bg_box_color: str = "#FFFFFF",
        bg_box_opacity: int = 100,
        pos_x_ratio: float | None = None,
        pos_y_ratio: float | None = None,
        mask_pos_x_ratio: float | None = None,
        mask_pos_y_ratio: float | None = None,
        sub_pos_x_ratio: float | None = None,
        sub_pos_y_ratio: float | None = None,
    ):
        self.overlay_item.set_subtitle(
            text,
            blur_enabled=blur_enabled,
            burn_enabled=burn_enabled,
            font_variant=font_variant,
            font_size_pt=font_size_pt,
            sub_text_color=sub_text_color,
            bg_box_scale=bg_box_scale,
            bg_box_w_scale=bg_box_w_scale,
            bg_box_h_scale=bg_box_h_scale,
            bg_box_color=bg_box_color,
            bg_box_opacity=bg_box_opacity,
            pos_x_ratio=pos_x_ratio,
            pos_y_ratio=pos_y_ratio,
            mask_pos_x_ratio=mask_pos_x_ratio,
            mask_pos_y_ratio=mask_pos_y_ratio,
            sub_pos_x_ratio=sub_pos_x_ratio,
            sub_pos_y_ratio=sub_pos_y_ratio,
        )

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                if path and os.path.exists(path):
                    parent = self.parent()
                    while parent:
                        if hasattr(parent, "_on_file_or_folder_dropped"):
                            parent._on_file_or_folder_dropped(path)
                            event.acceptProposedAction()
                            return
                        parent = parent.parent()
        super().dropEvent(event)


class InteractiveTimelineWidget(QWidget):
    """
    Interactive Studio Timeline with CapCut-style Playhead Scrubber.
    Allows user to click or drag the playhead cursor forward and backward
    to scrub and seek video playback in real time.
    """
    seekRequested = pyqtSignal(float)  # seconds

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(84)
        self.setMaximumHeight(96)
        self.setMouseTracking(True)

        self._duration: float = 270.0  # default 4:30.00
        self._current_pos: float = 0.0
        self._zoom: float = 1.0
        self._is_dragging: bool = False
        self._header_width: float = 40.0
        self._subtitles: list = []
        self._audio_clips: list[str] = []
        self._waveform_cache: dict[str, list[float]] = {}
        self._is_dark: bool = False

    def set_duration(self, dur_sec: float) -> None:
        if dur_sec > 0:
            self._duration = dur_sec
            self.update()

    def set_position(self, pos_sec: float) -> None:
        if not self._is_dragging:
            self._current_pos = max(0.0, min(self._duration, pos_sec))
            self.update()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = max(0.1, min(5.0, zoom))
        self.update()

    def set_subtitles(self, items: list) -> None:
        self._subtitles = items or []
        self.update()

    def set_audio_clips(self, audio_clips: list[str] | None, subtitle_items: list | None = None) -> None:
        """Sets the generated voice audio clips list to render waveforms on track A1."""
        self._audio_clips = list(audio_clips) if audio_clips else []
        if subtitle_items is not None:
            self._subtitles = subtitle_items
        self.update()

    def _extract_audio_peaks(self, clip_path: str, num_peaks: int = 100) -> list[float]:
        """Extracts normalized peak amplitudes [0.0..1.0] from a WAV audio file."""
        if not clip_path or not os.path.isfile(clip_path):
            return []
        try:
            with wave.open(clip_path, "rb") as wf:
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                n_frames = wf.getnframes()
                if n_frames == 0:
                    return []
                max_read = min(n_frames, 44100 * 30)
                raw_data = wf.readframes(max_read)
                if sampwidth == 2:
                    total_samples = len(raw_data) // 2
                    fmt = f"<{total_samples}h"
                    samples = struct.unpack(fmt, raw_data)
                    if n_channels > 1:
                        samples = samples[::n_channels]
                    max_val = 32768.0
                elif sampwidth == 1:
                    samples = [b - 128 for b in raw_data[::n_channels]]
                    max_val = 128.0
                else:
                    return []

                if not samples:
                    return []

                step = max(1, len(samples) // max(1, num_peaks))
                peaks = []
                for i in range(0, len(samples), step):
                    chunk = samples[i : i + step]
                    if chunk:
                        peak = max(abs(s) for s in chunk) / max_val
                        peaks.append(min(1.0, peak))
                    if len(peaks) >= num_peaks:
                        break

                max_p = max(peaks) if peaks else 0.0
                if max_p > 0.05:
                    norm_factor = 1.0 / max_p
                    return [min(1.0, max(0.12, p * norm_factor)) for p in peaks]
                return peaks
        except Exception:
            return []

    def _synthesize_speech_peaks(self, seed: int = 0, num_peaks: int = 60) -> list[float]:
        """Generates realistic human speech waveform envelope with natural syllabic cadence."""
        peaks = []
        for i in range(num_peaks):
            rel = i / max(1, num_peaks - 1)
            fade = min(1.0, rel * 10.0) * min(1.0, (1.0 - rel) * 10.0)
            syl = math.sin((i + seed * 11) * 0.25) * 0.45 + math.sin((i + seed * 5) * 0.5) * 0.3 + 0.45
            harm = math.sin((i + seed) * 1.5) * 0.2 + 0.8
            p = max(0.12, min(1.0, syl * harm * fade))
            peaks.append(p)
        return peaks

    def _get_clip_peaks(self, clip_path: str, index: int = 0, num_peaks: int = 100) -> list[float]:
        """Returns cached or freshly extracted/synthesized waveform peaks for an audio clip."""
        cache_key = f"{clip_path}_{num_peaks}" if clip_path else f"synth_{index}_{num_peaks}"
        if cache_key in self._waveform_cache:
            return self._waveform_cache[cache_key]

        peaks = []
        if clip_path and os.path.isfile(clip_path):
            peaks = self._extract_audio_peaks(clip_path, num_peaks=num_peaks)
        if not peaks:
            peaks = self._synthesize_speech_peaks(seed=index, num_peaks=num_peaks)

        self._waveform_cache[cache_key] = peaks
        return peaks

    def set_theme_is_dark(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def _time_to_x(self, t: float) -> float:
        avail_w = max(10.0, self.width() - self._header_width - 16)
        ratio = max(0.0, min(1.0, t / max(0.1, self._duration)))
        return self._header_width + 8 + ratio * avail_w

    def _x_to_time(self, x: float) -> float:
        avail_w = max(10.0, self.width() - self._header_width - 16)
        rel_x = max(0.0, min(avail_w, x - self._header_width - 8))
        return (rel_x / avail_w) * self._duration

    def _format_timecode(self, sec: float) -> str:
        m, s = divmod(int(sec), 60)
        ms = int((sec - int(sec)) * 100)
        return f"{m:02d}:{s:02d}.{ms:02d}"

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            x = event.position().x()
            if x >= self._header_width:
                self._is_dragging = True
                new_pos = self._x_to_time(x)
                self._current_pos = new_pos
                self.seekRequested.emit(new_pos)
                self.update()

    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        if self._is_dragging:
            new_pos = self._x_to_time(x)
            self._current_pos = new_pos
            self.seekRequested.emit(new_pos)
            self.update()
        else:
            if x >= self._header_width:
                hover_t = self._x_to_time(x)
                self.setToolTip(f"Seek: {self._format_timecode(hover_t)}")
                playhead_x = self._time_to_x(self._current_pos)
                if abs(x - playhead_x) < 8:
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                else:
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        hw = self._header_width
        avail_w = max(10.0, w - hw - 16)

        is_dark = self._is_dark
        card_bg = QColor("#161618") if is_dark else QColor("#FFFFFF")
        text_color = QColor("#8E8E93") if is_dark else QColor("#64748B")
        border_color = QColor("#2C2C2E") if is_dark else QColor("#E5E7EB")

        # 1. Ruler & Canvas Background
        ruler_h = 24
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(card_bg)
        painter.drawRect(0, 0, w, h)

        # Ruler line at bottom of ruler
        painter.setPen(QPen(border_color, 1))
        painter.drawLine(int(hw), ruler_h, w - 8, ruler_h)

        # Smart ticks
        dur = max(1.0, self._duration)
        if dur <= 30:
            major_step = 5.0
            minor_step = 1.0
        elif dur <= 120:
            major_step = 15.0
            minor_step = 5.0
        elif dur <= 300:
            major_step = 30.0
            minor_step = 10.0
        elif dur <= 900:
            major_step = 60.0
            minor_step = 15.0
        else:
            major_step = 300.0
            minor_step = 60.0

        ruler_font = QFont("Segoe UI", 8)
        painter.setFont(ruler_font)

        # Minor ticks
        painter.setPen(QPen(QColor("#3A3A3C" if is_dark else "#CBD5E1"), 1))
        t = 0.0
        while t <= dur:
            tx = self._time_to_x(t)
            painter.drawLine(int(tx), ruler_h - 4, int(tx), ruler_h)
            t += minor_step

        # Major ticks and labels
        t = 0.0
        while t <= dur:
            tx = self._time_to_x(t)
            painter.setPen(QPen(QColor("#48484A" if is_dark else "#94A3B8"), 1.2))
            painter.drawLine(int(tx), ruler_h - 8, int(tx), ruler_h)

            m, s = divmod(int(t), 60)
            lbl = f"{m:02d}:{s:02d}"
            painter.setPen(text_color)
            painter.drawText(QRectF(tx - 24, 2, 48, 14), Qt.AlignmentFlag.AlignCenter, lbl)
            t += major_step

        # 2. Track Lanes (T1 & A1)
        t1_y = 28
        t1_h = 24
        a1_y = 56
        a1_h = 24

        badge_font = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(badge_font)

        # T1 Header Badge
        t1_badge_rect = QRectF(4, t1_y, hw - 8, t1_h)
        painter.setPen(QPen(QColor(167, 139, 250, 180) if not is_dark else QColor(139, 92, 246, 180), 1))
        painter.setBrush(QColor(245, 243, 255) if not is_dark else QColor(46, 16, 101, 140))
        painter.drawRoundedRect(t1_badge_rect, 5, 5)
        painter.setPen(QColor("#7C3AED" if not is_dark else "#A78BFA"))
        painter.drawText(t1_badge_rect, Qt.AlignmentFlag.AlignCenter, "T1")

        # A1 Header Badge (matching user reference image)
        a1_badge_rect = QRectF(4, a1_y, hw - 8, a1_h)
        painter.setPen(QPen(QColor("#86EFAC") if not is_dark else QColor(5, 150, 105, 180), 1))
        painter.setBrush(QColor("#DCFCE7") if not is_dark else QColor(6, 78, 59, 140))
        painter.drawRoundedRect(a1_badge_rect, 5, 5)
        painter.setPen(QColor("#059669" if not is_dark else "#34D399"))
        painter.drawText(a1_badge_rect, Qt.AlignmentFlag.AlignCenter, "A1")

        # Track T1 Background Lane
        t1_lane_rect = QRectF(hw + 8, t1_y, avail_w, t1_h)
        painter.setPen(QPen(QColor(124, 58, 237, 50) if not is_dark else QColor(124, 58, 237, 30), 1))
        painter.setBrush(QColor(124, 58, 237, 14) if not is_dark else QColor(124, 58, 237, 20))
        painter.drawRoundedRect(t1_lane_rect, 4, 4)

        # Track A1 Background Lane
        a1_lane_rect = QRectF(hw + 8, a1_y, avail_w, a1_h)
        painter.setPen(QPen(QColor(5, 150, 105, 50) if not is_dark else QColor(5, 150, 105, 30), 1))
        painter.setBrush(QColor(5, 150, 105, 14) if not is_dark else QColor(5, 150, 105, 20))
        painter.drawRoundedRect(a1_lane_rect, 4, 4)

        # Render Subtitle Blocks on T1 if present
        if self._subtitles:
            sub_font = QFont("Noto Sans Khmer", 7)
            painter.setFont(sub_font)
            for it in self._subtitles:
                s_start = getattr(it, "start_seconds", 0.0)
                s_end = getattr(it, "end_seconds", 0.0)
                s_text = getattr(it, "text", "")
                sx1 = self._time_to_x(s_start)
                sx2 = self._time_to_x(s_end)
                sw = max(4.0, sx2 - sx1)
                sub_block = QRectF(sx1, t1_y + 1.5, sw, t1_h - 3)
                painter.setPen(QPen(QColor(167, 139, 250, 200) if not is_dark else QColor(139, 92, 246, 180), 1))
                painter.setBrush(QColor(237, 233, 254) if not is_dark else QColor(76, 29, 149, 120))
                painter.drawRoundedRect(sub_block, 4, 4)
                if sw > 28 and s_text:
                    painter.setPen(QColor("#5B21B6" if not is_dark else "#EDE9FE"))
                    clip_text = s_text[:14] + ("..." if len(s_text) > 14 else "")
                    painter.drawText(sub_block.adjusted(4, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, clip_text)
        else:
            painter.setPen(QPen(QColor(124, 58, 237, 100), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(124, 58, 237, 18))
            painter.drawRoundedRect(t1_lane_rect.adjusted(1, 1, -1, -1), 3, 3)

        # Render Audio Waves on Track A1 (matching user reference image)
        has_audio = bool(self._audio_clips and any(self._audio_clips))
        if has_audio and self._subtitles:
            clip_fill = QColor(209, 250, 229, 230) if not is_dark else QColor(6, 78, 59, 180)
            clip_border = QColor("#6EE7B7") if not is_dark else QColor("#10B981")
            bar_color = QColor("#059669") if not is_dark else QColor("#34D399")
            bar_pen = QPen(bar_color, 1.2)
            bar_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

            for idx, it in enumerate(self._subtitles):
                c_path = self._audio_clips[idx] if idx < len(self._audio_clips) else ""
                s_start = getattr(it, "start_seconds", 0.0)
                s_end = getattr(it, "end_seconds", 0.0)
                sx1 = self._time_to_x(s_start)
                sx2 = self._time_to_x(s_end)
                clip_w = max(6.0, sx2 - sx1)

                clip_rect = QRectF(sx1, a1_y + 1.5, clip_w, a1_h - 3)
                painter.setPen(QPen(clip_border, 1.2))
                painter.setBrush(clip_fill)
                painter.drawRoundedRect(clip_rect, 4, 4)

                pitch = 3.2
                start_bar_x = clip_rect.left() + 3.5
                end_bar_x = clip_rect.right() - 3.5
                mid_y = clip_rect.center().y()
                max_amp = max(2.0, (clip_rect.height() / 2.0) - 2.0)

                num_bars = int(max(1, (end_bar_x - start_bar_x) / pitch))
                peaks = self._get_clip_peaks(clip_path=c_path, index=idx, num_peaks=num_bars)

                painter.setPen(bar_pen)
                curr_bx = start_bar_x
                for p_idx in range(num_bars):
                    p_val = peaks[p_idx] if p_idx < len(peaks) else 0.2
                    bar_h = max_amp * max(0.12, min(1.0, p_val))
                    bx_i = int(round(curr_bx))
                    painter.drawLine(bx_i, int(round(mid_y - bar_h)), bx_i, int(round(mid_y + bar_h)))
                    curr_bx += pitch
        elif self._subtitles and not has_audio:
            # Subtle placeholder blocks on A1 indicating voice will generate here
            for it in self._subtitles:
                s_start = getattr(it, "start_seconds", 0.0)
                s_end = getattr(it, "end_seconds", 0.0)
                sx1 = self._time_to_x(s_start)
                sx2 = self._time_to_x(s_end)
                clip_w = max(6.0, sx2 - sx1)
                placeholder_rect = QRectF(sx1, a1_y + 1.5, clip_w, a1_h - 3)
                painter.setPen(QPen(QColor(5, 150, 105, 80) if not is_dark else QColor(5, 150, 105, 60), 1, Qt.PenStyle.DashLine))
                painter.setBrush(QColor(5, 150, 105, 12) if not is_dark else QColor(5, 150, 105, 15))
                painter.drawRoundedRect(placeholder_rect, 4, 4)
        else:
            painter.setPen(QPen(QColor(5, 150, 105, 100), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(5, 150, 105, 18))
            painter.drawRoundedRect(a1_lane_rect.adjusted(1, 1, -1, -1), 3, 3)

        # 3. Interactive Playhead Scrubber Cursor (matching user reference image)
        px = self._time_to_x(self._current_pos)
        px_int = int(round(px))

        needle_color = QColor("#1259C3") if not is_dark else QColor("#FFFFFF")
        needle_shadow = QColor(0, 0, 0, 80) if is_dark else QColor(18, 89, 195, 40)

        # Glow / Shadow
        painter.setPen(QPen(needle_shadow, 3.5))
        painter.drawLine(px_int, 14, px_int, int(a1_y + a1_h + 1))

        # Core Needle
        painter.setPen(QPen(needle_color, 2))
        painter.drawLine(px_int, 14, px_int, int(a1_y + a1_h + 1))

        # Handle badge (U-shaped)
        handle_w = 11.0
        handle_h = 14.0
        hx = px - (handle_w / 2.0)
        hy = 1.5

        path = QPainterPath()
        r = handle_w / 2.0
        path.moveTo(hx, hy)
        path.lineTo(hx + handle_w, hy)
        path.lineTo(hx + handle_w, hy + handle_h - r)
        path.arcTo(hx, hy + handle_h - handle_w, handle_w, handle_w, 0, -180)
        path.lineTo(hx, hy)
        path.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawPath(path.translated(0, 1.0))

        painter.setPen(QPen(QColor("#0E469C" if not is_dark else "#3B82F6"), 1.2))
        painter.setBrush(QColor("#1259C3" if not is_dark else "#FFFFFF"))
        painter.drawPath(path)

        inner_w = handle_w - 4.5
        inner_h = handle_h - 4.5
        ix = px - (inner_w / 2.0)
        iy = hy + 1.5
        ir = inner_w / 2.0
        inner_path = QPainterPath()
        inner_path.moveTo(ix, iy)
        inner_path.lineTo(ix + inner_w, iy)
        inner_path.lineTo(ix + inner_w, iy + inner_h - ir)
        inner_path.arcTo(ix, iy + inner_h - inner_w, inner_w, inner_w, 0, -180)
        inner_path.lineTo(ix, iy)
        inner_path.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF" if not is_dark else "#121214"))
        painter.drawPath(inner_path)

        painter.end()


class DubbingToolView(QWidget):
    """AI Voice Dubbing View hosting Form, Preview Studio, Processing, and Completed states."""

    back_requested = pyqtSignal()

    @property
    def video_sub_overlay(self):
        if hasattr(self, "video_player_view") and self.video_player_view and hasattr(self.video_player_view, "overlay_item"):
            return self.video_player_view.overlay_item
        return None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._output_video: str = ""
        self._subtitle_items: list[SubtitleItem] = []
        self._audio_clips: list[str] = []
        self._batch_video_files: list[str] = []
        self._current_batch_index: int = 0
        self._is_batch_mode: bool = False
        self._current_bg_color: str = "#FFFFFF"
        self._current_sub_color: str = "#FFFFFF"
        self._current_bg_w_scale: int = 100
        self._current_bg_h_scale: int = 100
        self._current_bg_opacity: int = 100
        self._current_pos_x_ratio: float | None = None
        self._current_pos_y_ratio: float | None = None
        self._current_mask_pos_x_ratio: float | None = None
        self._current_mask_pos_y_ratio: float | None = None
        self._current_sub_pos_x_ratio: float | None = None
        self._current_sub_pos_y_ratio: float | None = None

        self.extractor_worker = None
        self.translator_worker = None
        self.tts_worker = None
        self.mixer_worker = None

        self.media_player = None
        self.audio_output = None
        self.preview_audio_player = None
        self.preview_audio_output = None
        if QMediaPlayer and QAudioOutput:
            try:
                self.media_player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.media_player.setAudioOutput(self.audio_output)

                self.preview_audio_player = QMediaPlayer(self)
                self.preview_audio_output = QAudioOutput(self)
                self.preview_audio_player.setAudioOutput(self.preview_audio_output)
                self.preview_audio_player.playbackStateChanged.connect(self._on_preview_audio_state_changed)
            except Exception as e:
                logger.warning(f"Could not initialize QMediaPlayer: {e}")
                self.media_player = None
                self.audio_output = None
                self.preview_audio_player = None
                self.preview_audio_output = None

        self.setAcceptDrops(True)
        self._init_ui()
        get_i18n_manager().language_changed.connect(self.retranslate_ui)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                video_exts = {".mp4", ".mkv", ".ts", ".mov", ".avi", ".webm"}
                if os.path.isdir(path) or Path(path).suffix.lower() in video_exts:
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                if path and os.path.exists(path):
                    self._on_file_or_folder_dropped(path)
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)

    def closeEvent(self, event) -> None:
        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
                self.media_player.setAudioOutput(None)
            except Exception:
                pass
        if hasattr(self, "preview_audio_player") and self.preview_audio_player:
            try:
                self.preview_audio_player.stop()
                self.preview_audio_player.setAudioOutput(None)
            except Exception:
                pass
        super().closeEvent(event)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 10, 14, 10)
        main_layout.setSpacing(10)

        # ── Title Header (Subtle / Hidden by default in tabbed studio view) ──
        self.header_widget = QWidget()
        header_row = QHBoxLayout(self.header_widget)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        self.btn_back = QPushButton()
        self.btn_back.setObjectName("iconButton")
        self.btn_back.setIcon(get_icon("arrow-left", size=20))
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.setFixedSize(36, 36)
        self.btn_back.clicked.connect(self._on_back_clicked)
        header_row.addWidget(self.btn_back)

        self.header_icon = QLabel()
        self.header_icon.setPixmap(get_icon("film", size=22).pixmap(22, 22))
        header_row.addWidget(self.header_icon)

        self.title_label = QLabel(tr("dubbing_tool_title"))
        self.title_label.setObjectName("titleLabel")
        header_row.addWidget(self.title_label)
        header_row.addStretch()
        self.header_widget.setVisible(False)
        main_layout.addWidget(self.header_widget)

        # ── Sleek Non-blocking One UI Toast Notification Banner ──
        self.toast_banner = QFrame()
        self.toast_banner.setObjectName("toastBanner")
        tb_layout = QHBoxLayout(self.toast_banner)
        tb_layout.setContentsMargins(16, 8, 16, 8)
        tb_layout.setSpacing(10)

        self.lbl_toast_icon = QLabel()
        self.lbl_toast_icon.setFixedSize(18, 18)
        tb_layout.addWidget(self.lbl_toast_icon)

        self.lbl_toast_msg = QLabel()
        self.lbl_toast_msg.setStyleSheet("font-size: 13px; font-weight: 400;")
        tb_layout.addWidget(self.lbl_toast_msg, 1)

        self.btn_toast_close = QPushButton()
        self.btn_toast_close.setObjectName("iconButton")
        self.btn_toast_close.setIcon(get_icon("x", size=14))
        self.btn_toast_close.setFixedSize(22, 22)
        self.btn_toast_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toast_close.clicked.connect(lambda: self.toast_banner.setVisible(False))
        tb_layout.addWidget(self.btn_toast_close)

        self.toast_banner.setVisible(False)
        main_layout.addWidget(self.toast_banner)

        # ── 4-State Stacked Widget ──
        self.stack_widget = QStackedWidget(self)

        self.preview_page = self._create_preview_page()
        self.stack_widget.addWidget(self.preview_page)

        self.processing_page = self._create_processing_page()
        self.stack_widget.addWidget(self.processing_page)

        self.completed_page = self._create_completed_page()
        self.stack_widget.addWidget(self.completed_page)

        main_layout.addWidget(self.stack_widget, 1)

        # Default to Dialogue Studio UI (Index 0)
        # Initialize with clean placeholder state (No Video / Dialogue loaded)
        self._open_preview_studio([])

    def _create_preview_page(self) -> QWidget:
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        # Internal state fields (hidden / managed cleanly without cluttering the UI)
        self.file_input = QLineEdit()
        self.file_input.setVisible(False)
        self.srt_input = QLineEdit()
        self.srt_input.setVisible(False)
        self.srt_input.textChanged.connect(self._on_srt_text_changed)

        self.btn_browse = QPushButton(tr("browse"))
        self.btn_browse.clicked.connect(self._on_browse_clicked)
        self.btn_browse.setVisible(False)

        self.btn_browse_folder = QPushButton(tr("browse_folder"))
        self.btn_browse_folder.clicked.connect(self._on_browse_folder_clicked)
        self.btn_browse_folder.setVisible(False)

        self.folder_info_label = QLabel()
        self.folder_info_label.setObjectName("metaLabel")
        self.folder_info_label.setVisible(False)

        # =========================================================================
        # 1. TOP UNIFIED STUDIO TOOLBAR CARD (2 Clean Rows matching media_1789419142021.png)
        # =========================================================================
        settings_card = QFrame()
        settings_card.setObjectName("settingsGroupCard")
        settings_vbox = QVBoxLayout(settings_card)
        settings_vbox.setContentsMargins(10, 8, 10, 8)
        settings_vbox.setSpacing(8)

        # ── Row 1: Video & Subtitle Source, Voice, Mode, Aspect & Subtitle Mode ──
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)

        # 0. Back / Reset Studio to Import Screen
        self.btn_back_studio = QPushButton()
        self.btn_back_studio.setObjectName("pillToggle")
        self.btn_back_studio.setIcon(get_icon("arrow-left", size=11))
        self.btn_back_studio.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back_studio.setFixedSize(26, 26)
        self.btn_back_studio.setToolTip("Back / New Project (Reset to Import Screen)")
        self.btn_back_studio.clicked.connect(self._on_back_clicked)
        row1.addWidget(self.btn_back_studio)

        # 1. Open Video Button
        self.btn_open_video = QPushButton("+ Video")
        self.btn_open_video.setObjectName("pillToggle")
        self.btn_open_video.setIcon(get_icon("film", size=11))
        self.btn_open_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_video.setToolTip("Open another video to edit / dub")
        self.btn_open_video.clicked.connect(self._on_browse_clicked)
        row1.addWidget(self.btn_open_video)

        # 2. Browse SRT & Clear SRT
        self.btn_browse_srt = QPushButton("+ SRT")
        self.btn_browse_srt.setObjectName("pillToggle")
        self.btn_browse_srt.setIcon(get_icon("folder", size=11))
        self.btn_browse_srt.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse_srt.setToolTip("Import custom .srt subtitle file (optional)")
        self.btn_browse_srt.clicked.connect(self._on_browse_srt_clicked)
        row1.addWidget(self.btn_browse_srt)

        self.btn_clear_srt = QPushButton()
        self.btn_clear_srt.setObjectName("pillToggle")
        self.btn_clear_srt.setIcon(get_icon("x", size=10))
        self.btn_clear_srt.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_srt.setFixedSize(24, 24)
        self.btn_clear_srt.setToolTip(tr("clear_srt_tooltip"))
        self.btn_clear_srt.clicked.connect(self._on_clear_srt_clicked)
        self.btn_clear_srt.setVisible(False)
        row1.addWidget(self.btn_clear_srt)

        # 3. Voice Selection Dropdown & Listen / Upload sample
        self.combo_voice = QComboBox()
        self.combo_voice.setObjectName("pillInput")
        self.combo_voice.setMinimumWidth(110)
        self.combo_voice.setMaximumWidth(130)
        self.combo_voice.addItem(get_icon("user", size=11), "Piseth", "km-KH-PisethNeural")
        self.combo_voice.addItem(get_icon("user", size=11), "Sreymom", "km-KH-SreymomNeural")
        self.combo_voice.addItem(get_icon("mic", size=11), "Sdach Game", "sdach_game")
        self.combo_voice.addItem(get_icon("mic", size=11), "Harvard", "harvard")
        self.combo_voice.addItem(get_icon("user", size=11), "Clone Voice", "custom_clone")
        self.combo_voice.currentIndexChanged.connect(self._on_voice_combo_changed)
        row1.addWidget(self.combo_voice)

        self.btn_play_sample = QPushButton()
        self.btn_play_sample.setObjectName("pillToggle")
        self.btn_play_sample.setIcon(get_icon("play", size=11))
        self.btn_play_sample.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play_sample.setFixedSize(26, 26)
        self.btn_play_sample.setToolTip(tr("listen_sample"))
        self.btn_play_sample.clicked.connect(self._on_play_voice_sample_clicked)
        row1.addWidget(self.btn_play_sample)

        self.btn_upload_sample = QPushButton()
        self.btn_upload_sample.setObjectName("pillToggle")
        self.btn_upload_sample.setIcon(get_icon("mic", size=11))
        self.btn_upload_sample.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_upload_sample.setFixedSize(26, 26)
        self.btn_upload_sample.setToolTip(tr("upload_sample"))
        self.btn_upload_sample.clicked.connect(self._on_upload_voice_sample_clicked)
        row1.addWidget(self.btn_upload_sample)

        # 4. Mode Group: Ducking / Replace
        self.mode_group = QButtonGroup(self)
        self.btn_mode_ducking = QPushButton("Ducking")
        self.btn_mode_ducking.setObjectName("pillToggle")
        self.btn_mode_ducking.setCheckable(True)
        self.btn_mode_ducking.setChecked(True)
        self.btn_mode_ducking.setToolTip("Voiceover: keep background audio with auto-ducking")
        self.mode_group.addButton(self.btn_mode_ducking, 0)
        row1.addWidget(self.btn_mode_ducking)

        self.btn_mode_replace = QPushButton("Replace")
        self.btn_mode_replace.setObjectName("pillToggle")
        self.btn_mode_replace.setCheckable(True)
        self.btn_mode_replace.setToolTip("Full Audio Replace: mute original audio and replace with dubbed voice")
        self.mode_group.addButton(self.btn_mode_replace, 1)
        row1.addWidget(self.btn_mode_replace)

        self.mode_group.idClicked.connect(self._on_mode_changed)

        # 5. Aspect Ratio Selector
        self.combo_aspect_ratio = QComboBox()
        self.combo_aspect_ratio.setObjectName("pillInput")
        self.combo_aspect_ratio.setMinimumWidth(135)
        self.combo_aspect_ratio.setMaximumWidth(155)
        self.combo_aspect_ratio.addItem(get_icon("video", size=11), "16:9 / Original", "original")
        self.combo_aspect_ratio.addItem(get_icon("video", size=11), "9:16 (Blur BG)", "9:16_blur")
        self.combo_aspect_ratio.addItem(get_icon("video", size=11), "9:16 (Crop)", "9:16_crop")
        self.combo_aspect_ratio.addItem(get_icon("video", size=11), "1:1 (Square)", "1:1")
        self.combo_aspect_ratio.addItem(get_icon("video", size=11), "4:3 (Standard)", "4:3")
        self.combo_aspect_ratio.currentIndexChanged.connect(self._on_aspect_ratio_changed)
        self.combo_aspect_ratio.setToolTip("Target Video Aspect Ratio")
        row1.addWidget(self.combo_aspect_ratio)

        # 6. Subtitle Mode Selector - Removed per user request
        self.combo_subtitle_mode = None

        row1.addStretch(1)
        settings_vbox.addLayout(row1)

        # ── Row 2: Subtitle Burn, Font, Size, Color, BG Mask, BG Color, W/H/Op Scales ──
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(6)

        # Subtitle Toggle
        self.chk_burn_subtitles = QPushButton("Sub")
        self.chk_burn_subtitles.setObjectName("pillToggle")
        self.chk_burn_subtitles.setCheckable(True)
        self.chk_burn_subtitles.setChecked(False)
        self.chk_burn_subtitles.setIcon(get_icon("file-video", size=11))
        self.chk_burn_subtitles.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_burn_subtitles.setToolTip("Burn styled Khmer subtitles (Google Sans) onto the video")
        self.chk_burn_subtitles.clicked.connect(self._on_sub_style_toggled)
        row2.addWidget(self.chk_burn_subtitles)

        # Font Variant
        self.combo_font_variant = QComboBox()
        self.combo_font_variant.setObjectName("pillInput")
        self.combo_font_variant.setMinimumWidth(76)
        self.combo_font_variant.setMaximumWidth(86)
        self.combo_font_variant.addItem("Regular", "Regular")
        self.combo_font_variant.addItem("Italic", "Italic")
        self.combo_font_variant.addItem("SemiBold", "SemiBold")
        self.combo_font_variant.addItem("Bold", "Bold")
        self.combo_font_variant.setCurrentIndex(3)
        self.combo_font_variant.currentIndexChanged.connect(self._on_sub_style_toggled)
        self.combo_font_variant.setToolTip("Font Variant: Regular, Italic, SemiBold, Bold")
        row2.addWidget(self.combo_font_variant)

        # Sub Size
        self.combo_sub_size = QComboBox()
        self.combo_sub_size.setObjectName("pillInput")
        self.combo_sub_size.setEditable(True)
        self.combo_sub_size.setMinimumWidth(56)
        self.combo_sub_size.setMaximumWidth(64)
        self.combo_sub_size.setValidator(QIntValidator(10, 150, self))
        for sz in [16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 40, 44, 48, 56, 64]:
            self.combo_sub_size.addItem(str(sz), sz)
        default_size_idx = self.combo_sub_size.findData(30)
        if default_size_idx >= 0:
            self.combo_sub_size.setCurrentIndex(default_size_idx)
        else:
            self.combo_sub_size.setEditText("30")
        self.combo_sub_size.currentIndexChanged.connect(self._on_sub_size_changed)
        self.combo_sub_size.editTextChanged.connect(self._on_sub_size_changed)
        self.combo_sub_size.setToolTip("Subtitle font size number (pt)")
        row2.addWidget(self.combo_sub_size)

        # Subtitle Color Swatch
        self.btn_sub_color = QPushButton()
        self.btn_sub_color.setObjectName("pillToggle")
        self.btn_sub_color.setFixedSize(26, 26)
        self.btn_sub_color.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sub_color.setToolTip("Subtitle Text Color (Click to customize)")
        self.btn_sub_color.clicked.connect(self._on_sub_color_clicked)
        row2.addWidget(self.btn_sub_color)

        # Background Box Toggle
        self.chk_blur_subtitles = QPushButton("BG")
        self.chk_blur_subtitles.setObjectName("pillToggle")
        self.chk_blur_subtitles.setCheckable(True)
        self.chk_blur_subtitles.setChecked(False)
        self.chk_blur_subtitles.setIcon(get_icon("video", size=11))
        self.chk_blur_subtitles.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_blur_subtitles.setToolTip("Use (ON) or None Use (OFF) background box behind subtitles")
        self.chk_blur_subtitles.clicked.connect(self._on_sub_style_toggled)
        row2.addWidget(self.chk_blur_subtitles)

        # BG Color Swatch
        self.btn_bg_color = QPushButton()
        self.btn_bg_color.setObjectName("pillToggle")
        self.btn_bg_color.setFixedSize(26, 26)
        self.btn_bg_color.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bg_color.setToolTip("Subtitle Background Color (Click to customize)")
        self.btn_bg_color.clicked.connect(self._on_bg_color_clicked)
        row2.addWidget(self.btn_bg_color)

        # BG Width Scale (W)
        # BG Width Scale (W) & BG Height Scale (H) - Removed per user request
        self.combo_bg_w_size = None
        self.combo_bg_h_size = None
        self.combo_bg_size = None

        # BG Opacity (Op)
        self.combo_bg_opacity = QComboBox()
        self.combo_bg_opacity.setObjectName("pillInput")
        self.combo_bg_opacity.setEditable(True)
        self.combo_bg_opacity.setMinimumWidth(84)
        self.combo_bg_opacity.setMaximumWidth(92)
        self.combo_bg_opacity.setValidator(QIntValidator(0, 100, self))
        for op in [100, 90, 80, 70, 50, 30, 0]:
            self.combo_bg_opacity.addItem(f"Op:{op}%", op)
        self.combo_bg_opacity.setCurrentIndex(0)
        self.combo_bg_opacity.currentIndexChanged.connect(self._on_bg_opacity_changed)
        self.combo_bg_opacity.editTextChanged.connect(self._on_bg_opacity_changed)
        self.combo_bg_opacity.setToolTip("Background Box Opacity / Transparency (%)")
        row2.addWidget(self.combo_bg_opacity)

        row2.addStretch(1)
        settings_vbox.addLayout(row2)

        main_layout.addWidget(settings_card)
        self._update_toolbar_button_styles()

        # =========================================================================
        # 2. MAIN HORIZONTAL SPLITTER (Left: Video Player, Right: Subtitle & Timeline)
        # =========================================================================
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── LEFT PANEL: Video Player Column ──
        left_card = QFrame()
        left_card.setObjectName("settingsGroupCard")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)

        # Header: Video File Name Title
        header_left = QHBoxLayout()
        header_left.setSpacing(8)
        self.lbl_video_icon = QLabel()
        self.lbl_video_icon.setPixmap(get_icon("video", size=16).pixmap(16, 16))
        header_left.addWidget(self.lbl_video_icon)

        self.lbl_video_title = QLabel("No Video Loaded")
        self.lbl_video_title.setObjectName("filenameLabel")
        self.lbl_video_title.setStyleSheet("font-size: 13px; font-weight: 400; color: #9CA3AF;")
        header_left.addWidget(self.lbl_video_title, 1)

        self.btn_change_video = QPushButton("Change Video")
        self.btn_change_video.setObjectName("pillToggle")
        self.btn_change_video.setIcon(get_icon("folder", size=11))
        self.btn_change_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_change_video.setToolTip("Open another video or series folder")
        self.btn_change_video.clicked.connect(self._on_browse_clicked)
        self.btn_change_video.setVisible(False)
        header_left.addWidget(self.btn_change_video)

        left_layout.addLayout(header_left)

        # Video Player Viewport Container
        self.player_container = QWidget()
        self.player_container.setStyleSheet("background-color: transparent; border-radius: 12px;")
        self.player_container.installEventFilter(self)
        pc_layout = QVBoxLayout(self.player_container)
        pc_layout.setContentsMargins(0, 0, 0, 0)

        self.video_player_view = None
        if QGraphicsVideoItem and self.media_player:
            self.video_player_view = StudioVideoPlayerView(self.player_container)
            self.video_widget = self.video_player_view
            self.media_player.setVideoOutput(self.video_player_view.video_item)
            pc_layout.addWidget(self.video_player_view)

            self.media_player.positionChanged.connect(self._on_player_position_changed)
            self.media_player.durationChanged.connect(self._on_player_duration_changed)
        elif QVideoWidget and self.media_player:
            self.video_widget = QVideoWidget()
            self.video_widget.setStyleSheet("border-radius: 12px; background-color: #000000;")
            self.media_player.setVideoOutput(self.video_widget)
            pc_layout.addWidget(self.video_widget)

            self.media_player.positionChanged.connect(self._on_player_position_changed)
            self.media_player.durationChanged.connect(self._on_player_duration_changed)

        # Interactive Placeholder Overlay inside video viewport area when No Video is Loaded
        self.video_placeholder = DropZoneFrame(self.player_container, on_dropped=self._on_file_or_folder_dropped)
        placeholder_layout = QVBoxLayout(self.video_placeholder)
        placeholder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.setContentsMargins(24, 28, 24, 28)
        placeholder_layout.setSpacing(14)

        self.lbl_plus_tile = QLabel()
        self.lbl_plus_tile.setFixedSize(64, 64)
        self.lbl_plus_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_plus_tile.setStyleSheet(
            "background-color: rgba(18, 89, 195, 0.08); border-radius: 32px; border: 1px solid rgba(18, 89, 195, 0.18); outline: none;"
        )
        self.lbl_plus_tile.setPixmap(get_icon("film", color="#1259C3", size=32).pixmap(32, 32))
        placeholder_layout.addWidget(self.lbl_plus_tile, 0, Qt.AlignmentFlag.AlignCenter)

        self.lbl_import_hint = QLabel("Import Video or Folder")
        self.lbl_import_hint.setStyleSheet("font-size: 16px; font-weight: 400; color: #0F172A; border: none; outline: none;")
        self.lbl_import_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(self.lbl_import_hint)

        self.lbl_import_subhint = QLabel("Select a single video file or an entire episode series folder")
        self.lbl_import_subhint.setStyleSheet("font-size: 12px; font-weight: 400; color: #64748B; border: none; outline: none;")
        self.lbl_import_subhint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(self.lbl_import_subhint)

        import_btn_row = QHBoxLayout()
        import_btn_row.setSpacing(12)
        import_btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_overlay_video = QPushButton("Import Video")
        self.btn_overlay_video.setIcon(get_icon("file-video", color="#FFFFFF", size=15))
        self.btn_overlay_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_overlay_video.setStyleSheet(
            "QPushButton { background-color: #1259C3; color: #FFFFFF; border: none; outline: none; border-radius: 16px; "
            "padding: 6px 20px; min-height: 32px; font-weight: 400; font-size: 13px; } "
            "QPushButton:hover { background-color: #0E469C; } "
            "QPushButton:pressed { background-color: #0B377B; }"
        )
        self.btn_overlay_video.clicked.connect(self._on_browse_clicked)
        import_btn_row.addWidget(self.btn_overlay_video)

        self.btn_overlay_folder = QPushButton("Import Folder")
        self.btn_overlay_folder.setIcon(get_icon("folder", color="#1E293B", size=15))
        self.btn_overlay_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_overlay_folder.setStyleSheet(
            "QPushButton { background-color: #FFFFFF; color: #1E293B; border: 1px solid #CBD5E1; "
            "outline: none; border-radius: 16px; padding: 6px 20px; min-height: 32px; font-weight: 400; font-size: 13px; } "
            "QPushButton:hover { background-color: #F8FAFC; border-color: #94A3B8; } "
            "QPushButton:pressed { background-color: #E2E8F0; }"
        )
        self.btn_overlay_folder.clicked.connect(self._on_browse_folder_clicked)
        import_btn_row.addWidget(self.btn_overlay_folder)

        placeholder_layout.addLayout(import_btn_row)
        pc_layout.addWidget(self.video_placeholder)

        left_layout.addWidget(self.player_container, 1)

        # Live Subtitle Display Banner
        self.live_sub_label = QLabel("No Subtitles Loaded")
        self.live_sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.live_sub_label.setWordWrap(True)
        self.live_sub_label.setStyleSheet(
            "background-color: rgba(18, 89, 195, 0.12); border: 1px solid rgba(18, 89, 195, 0.25); "
            "border-radius: 8px; padding: 6px 10px; font-size: 13px; font-weight: 400; color: #FFFFFF;"
        )
        left_layout.addWidget(self.live_sub_label)

        # Time Display Bar
        time_bar = QHBoxLayout()
        self.lbl_cur_time = QLabel("00:00.00")
        self.lbl_cur_time.setStyleSheet("font-size: 12px; font-weight: 400; color: #4F46E5;")
        time_bar.addWidget(self.lbl_cur_time)
        time_bar.addStretch(1)
        self.lbl_total_time = QLabel("00:00.00")
        self.lbl_total_time.setStyleSheet("font-size: 12px; font-weight: 400; color: #6B7280;")
        time_bar.addWidget(self.lbl_total_time)
        left_layout.addLayout(time_bar)

        # Controls Row Bar (Play, Stop, Aspect, Volume Slider)
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(6)

        self.btn_play_pause = QPushButton()
        self.btn_play_pause.setObjectName("iconButton")
        self.btn_play_pause.setIcon(get_icon("play", size=16))
        self.btn_play_pause.setFixedSize(30, 30)
        self.btn_play_pause.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play_pause.clicked.connect(self._toggle_playback)
        ctrl_bar.addWidget(self.btn_play_pause)

        self.btn_stop = QPushButton()
        self.btn_stop.setObjectName("iconButton")
        self.btn_stop.setIcon(get_icon("pause", size=16))
        self.btn_stop.setFixedSize(30, 30)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.clicked.connect(self._stop_playback)
        ctrl_bar.addWidget(self.btn_stop)

        ctrl_bar.addStretch(1)

        self.lbl_vol_icon = QLabel()
        self.lbl_vol_icon.setPixmap(get_icon("status_done", size=14).pixmap(14, 14))
        ctrl_bar.addWidget(self.lbl_vol_icon)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setFixedWidth(90)
        self.seek_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.seek_slider.sliderMoved.connect(self._on_seek_slider_moved)
        ctrl_bar.addWidget(self.seek_slider)

        left_layout.addLayout(ctrl_bar)
        main_splitter.addWidget(left_card)

        # ── RIGHT PANEL: Subtitle Data Table & Timeline Editor ──
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # Top Section: Subtitle Data Table Card
        sub_card = QFrame()
        sub_card.setObjectName("settingsGroupCard")
        sub_layout = QVBoxLayout(sub_card)
        sub_layout.setContentsMargins(12, 10, 12, 10)
        sub_layout.setSpacing(8)

        # Subtitle Data Header Row
        sub_header = QHBoxLayout()
        sub_header.setSpacing(8)

        self.lbl_sub_icon = QLabel()
        self.lbl_sub_icon.setPixmap(get_icon("file-video", size=16).pixmap(16, 16))
        sub_header.addWidget(self.lbl_sub_icon)

        self.lbl_sub_title = QLabel("Subtitle Data")
        sub_header.addWidget(self.lbl_sub_title)

        sub_header.addStretch(1)

        self.dialogue_search = None

        self.btn_export_srt = QPushButton(tr("export_srt"))
        self.btn_export_srt.setObjectName("pillToggle")
        self.btn_export_srt.setIcon(get_icon("download", size=14))
        self.btn_export_srt.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export_srt.setStyleSheet("padding: 0 14px; min-height: 28px; font-size: 12px; font-weight: 400; border-radius: 14px;")
        self.btn_export_srt.clicked.connect(self._on_export_srt_clicked)
        sub_header.addWidget(self.btn_export_srt)

        sub_layout.addLayout(sub_header)

        # Subtitle Table matching image columns: [ ], START, END, KHMER TEXT (EDITABLE), VOICE PROFILE, AUDIO STATUS
        self.dialogue_table = QTableWidget()
        self.dialogue_table.setColumnCount(6)
        self.dialogue_table.setHorizontalHeaderLabels([
            "☑",
            "START",
            "END",
            "KHMER TEXT (EDITABLE)",
            "VOICE PROFILE",
            "AUDIO STATUS",
        ])
        self.dialogue_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.dialogue_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.dialogue_table.verticalHeader().setVisible(False)
        self.dialogue_table.setShowGrid(False)
        self.dialogue_table.setAlternatingRowColors(True)
        self.dialogue_table.cellDoubleClicked.connect(self._on_table_row_double_clicked)
        self.dialogue_table.cellClicked.connect(self._on_table_row_clicked)

        header = self.dialogue_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 36)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 85)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(2, 85)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(4, 130)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(5, 110)

        sub_layout.addWidget(self.dialogue_table, 1)
        right_splitter.addWidget(sub_card)

        # Bottom Section: Timeline Editor & Action Bar Card
        tl_card = QFrame()
        tl_card.setObjectName("settingsGroupCard")
        tl_layout = QVBoxLayout(tl_card)
        tl_layout.setContentsMargins(12, 10, 12, 10)
        tl_layout.setSpacing(8)

        # Timeline Editor Controls Header Bar
        tl_bar = QHBoxLayout()
        tl_bar.setSpacing(10)

        self.lbl_tl_title = QLabel("Timeline Editor")
        tl_bar.addWidget(self.lbl_tl_title)

        self.lbl_zoom = QLabel("Zoom:")
        tl_bar.addWidget(self.lbl_zoom)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 200)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(90)
        tl_bar.addWidget(self.zoom_slider)

        self.lbl_zoom_val = QLabel("100%")
        tl_bar.addWidget(self.lbl_zoom_val)

        tl_bar.addStretch(1)

        # Action Buttons: Transcribe (green), Scan Subtitles (OCR) (amber), Generate Selected Audio (purple), and Final Render (blue)
        self.btn_retranscribe = QPushButton("Transcribe")
        self.btn_retranscribe.setIcon(get_icon("rotate-cw", color="#FFFFFF", size=13))
        self.btn_retranscribe.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_retranscribe.setStyleSheet(
            "background-color: #059669; color: #FFFFFF; font-size: 11.5px; font-weight: 400; "
            "border-radius: 14px; padding: 0 12px; min-height: 28px; max-height: 28px; outline: none; border: none;"
        )
        self.btn_retranscribe.clicked.connect(self._on_force_retranscribe_clicked)
        tl_bar.addWidget(self.btn_retranscribe)

        self.btn_scan_ocr = QPushButton("Scan Subtitles (OCR)")
        self.btn_scan_ocr.setIcon(get_icon("eye", color="#FFFFFF", size=13))
        self.btn_scan_ocr.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan_ocr.setStyleSheet(
            "background-color: #D97706; color: #FFFFFF; font-size: 11.5px; font-weight: 400; "
            "border-radius: 14px; padding: 0 12px; min-height: 28px; max-height: 28px; outline: none; border: none;"
        )
        self.btn_scan_ocr.clicked.connect(self._on_scan_ocr_clicked)
        tl_bar.addWidget(self.btn_scan_ocr)

        self.btn_generate_audio = QPushButton("Generate Audio")
        self.btn_generate_audio.setIcon(get_icon("user", color="#FFFFFF", size=13))
        self.btn_generate_audio.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_generate_audio.setStyleSheet(
            "background-color: #7C3AED; color: #FFFFFF; font-size: 11.5px; font-weight: 400; "
            "border-radius: 14px; padding: 0 12px; min-height: 28px; max-height: 28px; outline: none; border: none;"
        )
        self.btn_generate_audio.clicked.connect(self._on_generate_audio_clicked)
        tl_bar.addWidget(self.btn_generate_audio)

        self.btn_final_render = QPushButton(tr("final_render"))
        self.btn_final_render.setObjectName("primaryButton")
        self.btn_final_render.setIcon(get_icon("film", color="#FFFFFF", size=13))
        self.btn_final_render.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_final_render.setStyleSheet(
            "background-color: #1259C3; color: #FFFFFF; font-size: 11.5px; font-weight: 400; "
            "border-radius: 14px; padding: 0 14px; min-height: 28px; max-height: 28px; outline: none; border: none;"
        )
        self.btn_final_render.clicked.connect(self._on_final_render_clicked)
        tl_bar.addWidget(self.btn_final_render)

        self.btn_start = self.btn_final_render

        tl_layout.addLayout(tl_bar)

        # Timeline Tracks Visualizer (Interactive Ruler + T1 Subtitle Track + A1 Audio Track + Playhead Scrubber)
        self.timeline_widget = InteractiveTimelineWidget()
        self.timeline_widget.seekRequested.connect(self._on_timeline_seek)
        self.timeline_visualizer = self.timeline_widget
        self.ruler_labels = []
        tl_layout.addWidget(self.timeline_widget)

        self.zoom_slider.valueChanged.connect(self._on_timeline_zoom_changed)
        right_splitter.addWidget(tl_card)

        # Set right splitter sizes (70% table, 30% timeline) and remove black divider line
        right_splitter.setSizes([420, 180])
        right_splitter.setHandleWidth(12)
        right_splitter.setStyleSheet("QSplitter::handle { background-color: transparent; border: none; }")
        main_splitter.addWidget(right_splitter)

        # Set main splitter sizes (360px left, remainder right) and remove black divider line
        main_splitter.setSizes([360, 850])
        main_splitter.setHandleWidth(12)
        main_splitter.setStyleSheet("QSplitter::handle { background-color: transparent; border: none; }")
        main_layout.addWidget(main_splitter, 1)

        # ── Bottom Status Bar ──
        status_bar = QHBoxLayout()
        status_bar.setContentsMargins(6, 4, 6, 4)
        status_bar.setSpacing(12)

        self.lbl_system_status = QLabel("System Ready")
        self.lbl_system_status.setStyleSheet("font-size: 12px; font-weight: 400;")
        status_bar.addWidget(self.lbl_system_status)

        self.lbl_project_info = QLabel("No Project Loaded")
        self.lbl_project_info.setStyleSheet("font-size: 12px; font-weight: 400; color: #6B7280;")
        status_bar.addWidget(self.lbl_project_info, 1)

        # Compact In-Studio Progress Bar (Hidden when idle)
        self.proc_card = QFrame()
        self.proc_card.setObjectName("compactStatusProgress")
        proc_layout = QHBoxLayout(self.proc_card)
        proc_layout.setContentsMargins(0, 0, 0, 0)
        proc_layout.setSpacing(8)

        self.proc_icon_tile = QLabel()
        self.proc_icon_tile.setFixedSize(16, 16)
        self.proc_icon_tile.setPixmap(get_icon("rotate-cw", size=14).pixmap(14, 14))
        proc_layout.addWidget(self.proc_icon_tile)

        self.lbl_proc_subtitle = QLabel("Processing...")
        self.lbl_proc_subtitle.setStyleSheet("font-size: 12px; font-weight: 400; color: #1259C3;")
        proc_layout.addWidget(self.lbl_proc_subtitle)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("thickProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setFixedWidth(160)
        self.progress_bar.setTextVisible(False)
        proc_layout.addWidget(self.progress_bar)

        self.lbl_proc_percent = QLabel("0%")
        self.lbl_proc_percent.setStyleSheet(
            "font-size: 12px; font-weight: 400; color: #1259C3; min-width: 32px;"
        )
        proc_layout.addWidget(self.lbl_proc_percent)

        self.lbl_proc_title = QLabel("")  # Retained for compatibility

        self.proc_card.setVisible(False)
        status_bar.addWidget(self.proc_card)

        self.lbl_mem_usage = QLabel("Memory Usage: Normal")
        self.lbl_mem_usage.setStyleSheet("font-size: 12px; font-weight: 400; color: #6B7280;")
        status_bar.addWidget(self.lbl_mem_usage)

        main_layout.addLayout(status_bar)

        self._apply_theme_styles()
        return container

    def _create_processing_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(20, 20, 20, 20)

        # Center card vertically and horizontally
        page_layout.addStretch(1)

        center_hbox = QHBoxLayout()
        center_hbox.addStretch(1)

        proc_card = QFrame()
        proc_card.setObjectName("settingsGroupCard")
        proc_card.setFixedWidth(780)
        proc_card.setStyleSheet(
            "QFrame#settingsGroupCard { border-radius: 20px; padding: 24px; }"
        )
        proc_layout = QVBoxLayout(proc_card)
        proc_layout.setContentsMargins(28, 28, 28, 28)
        proc_layout.setSpacing(20)

        # ── Header Row: Big Icon Tile + Titles + Big Percentage ──
        header_row = QHBoxLayout()
        header_row.setSpacing(16)

        self.proc_icon_tile_page = QLabel()
        self.proc_icon_tile_page.setFixedSize(52, 52)
        self.proc_icon_tile_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.proc_icon_tile_page.setStyleSheet(
            "background-color: rgba(18, 89, 195, 0.12); border-radius: 16px;"
        )
        self.proc_icon_tile_page.setPixmap(get_icon("rotate-cw", color="#1259C3", size=24).pixmap(24, 24))
        header_row.addWidget(self.proc_icon_tile_page)

        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(4)

        self.lbl_proc_title_page = QLabel("Rendering Khmer Dubbed Video")
        self.lbl_proc_title_page.setObjectName("titleLabel")
        self.lbl_proc_title_page.setStyleSheet("font-size: 18px; font-weight: 500;")
        info_vbox.addWidget(self.lbl_proc_title_page)

        self.lbl_proc_filename_page = QLabel("")
        self.lbl_proc_filename_page.setStyleSheet(
            "background-color: rgba(18, 89, 195, 0.08); color: #1259C3; "
            "border-radius: 8px; padding: 3px 10px; font-size: 12px; font-weight: 400;"
        )
        self.lbl_proc_filename_page.setVisible(False)
        info_vbox.addWidget(self.lbl_proc_filename_page)

        header_row.addLayout(info_vbox, 1)

        self.lbl_proc_percent_page = QLabel("0%")
        self.lbl_proc_percent_page.setStyleSheet(
            "font-size: 28px; font-weight: 500; color: #1259C3;"
        )
        self.lbl_proc_percent_page.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(self.lbl_proc_percent_page)

        proc_layout.addLayout(header_row)

        # ── 4-Step Pipeline Stepper ──
        stepper_frame = QFrame()
        stepper_frame.setObjectName("settingsGroupCard")
        stepper_frame.setStyleSheet(
            "background-color: rgba(0, 0, 0, 0.02); border: 1px solid rgba(0, 0, 0, 0.06); "
            "border-radius: 12px; padding: 6px 10px;"
        )
        stepper_layout = QHBoxLayout(stepper_frame)
        stepper_layout.setContentsMargins(6, 6, 6, 6)
        stepper_layout.setSpacing(8)

        self.step_labels = []
        step_names = [
            ("1. Speech STT", "mic"),
            ("2. Translate", "globe"),
            ("3. Voice Dub", "user"),
            ("4. Video Sync", "film"),
        ]
        for s_name, s_icon in step_names:
            step_box = QFrame()
            sb_layout = QHBoxLayout(step_box)
            sb_layout.setContentsMargins(8, 6, 8, 6)
            sb_layout.setSpacing(6)

            icon_lbl = QLabel()
            icon_lbl.setPixmap(get_icon(s_icon, size=14).pixmap(14, 14))
            sb_layout.addWidget(icon_lbl)

            txt_lbl = QLabel(s_name)
            txt_lbl.setStyleSheet("font-size: 12px; font-weight: 400; color: #6B7280;")
            sb_layout.addWidget(txt_lbl)

            step_box.setStyleSheet(
                "background-color: transparent; border-radius: 8px; border: 1px solid transparent;"
            )
            self.step_labels.append((step_box, icon_lbl, txt_lbl))
            stepper_layout.addWidget(step_box, 1)

        proc_layout.addWidget(stepper_frame)

        # ── Progress Bar & Detail Subtitle ──
        progress_vbox = QVBoxLayout()
        progress_vbox.setSpacing(8)

        self.progress_bar_page = QProgressBar()
        self.progress_bar_page.setObjectName("thickProgressBar")
        self.progress_bar_page.setRange(0, 100)
        self.progress_bar_page.setValue(0)
        self.progress_bar_page.setFixedHeight(10)
        self.progress_bar_page.setTextVisible(False)
        progress_vbox.addWidget(self.progress_bar_page)

        self.lbl_proc_subtitle_page = QLabel("Preparing audio and subtitle tracks...")
        self.lbl_proc_subtitle_page.setObjectName("metaLabel")
        self.lbl_proc_subtitle_page.setStyleSheet("font-size: 13px; font-weight: 400; color: #6B7280;")
        progress_vbox.addWidget(self.lbl_proc_subtitle_page)

        proc_layout.addLayout(progress_vbox)

        # ── Cancel Action Button ──
        action_row = QHBoxLayout()
        action_row.addStretch(1)

        self.btn_cancel_render = QPushButton("Cancel Render")
        self.btn_cancel_render.setObjectName("pillToggle")
        self.btn_cancel_render.setIcon(get_icon("x", size=15))
        self.btn_cancel_render.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel_render.setStyleSheet(
            "padding: 0 20px; min-height: 36px; border-radius: 16px; font-weight: 400;"
        )
        self.btn_cancel_render.clicked.connect(self._on_cancel_render_clicked)
        action_row.addWidget(self.btn_cancel_render)

        proc_layout.addLayout(action_row)

        center_hbox.addWidget(proc_card)
        center_hbox.addStretch(1)

        page_layout.addLayout(center_hbox)
        page_layout.addStretch(1)
        return page

    def _create_completed_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(20, 20, 20, 20)

        # Center card vertically and horizontally
        page_layout.addStretch(1)

        center_hbox = QHBoxLayout()
        center_hbox.addStretch(1)

        comp_card = QFrame()
        comp_card.setObjectName("settingsGroupCard")
        comp_card.setFixedWidth(780)
        comp_card.setStyleSheet(
            "QFrame#settingsGroupCard { border-radius: 20px; padding: 24px; }"
        )
        comp_layout = QVBoxLayout(comp_card)
        comp_layout.setContentsMargins(28, 28, 28, 28)
        comp_layout.setSpacing(22)

        header_row = QHBoxLayout()
        header_row.setSpacing(16)

        self.comp_icon_tile = QLabel()
        self.comp_icon_tile.setFixedSize(52, 52)
        self.comp_icon_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.comp_icon_tile.setStyleSheet(
            "background-color: rgba(16, 185, 129, 0.15); border-radius: 16px;"
        )
        self.comp_icon_tile.setPixmap(get_icon("status_done", color="#10B981", size=26).pixmap(26, 26))
        header_row.addWidget(self.comp_icon_tile)

        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(4)

        self.lbl_comp_title = QLabel(tr("dubbing_complete"))
        self.lbl_comp_title.setObjectName("titleLabel")
        self.lbl_comp_title.setStyleSheet("font-size: 20px; font-weight: 500; color: #10B981;")
        info_vbox.addWidget(self.lbl_comp_title)

        self.lbl_comp_subtitle = QLabel("Khmer voice dubbed video rendered successfully.")
        self.lbl_comp_subtitle.setObjectName("metaLabel")
        self.lbl_comp_subtitle.setStyleSheet("font-size: 13px; font-weight: 400; color: #6B7280;")
        info_vbox.addWidget(self.lbl_comp_subtitle)

        header_row.addLayout(info_vbox, 1)
        comp_layout.addLayout(header_row)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)

        self.btn_play_video = QPushButton("Play Video")
        self.btn_play_video.setObjectName("primaryButton")
        self.btn_play_video.setIcon(get_icon("play", color="#FFFFFF", size=16))
        self.btn_play_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play_video.setStyleSheet(
            "padding: 0 24px; min-height: 40px; border-radius: 18px; font-weight: 400; color: #FFFFFF; background-color: #1259C3;"
        )
        self.btn_play_video.clicked.connect(self._on_play_completed_video_clicked)
        actions_row.addWidget(self.btn_play_video)

        self.btn_open_folder = QPushButton(tr("open_folder"))
        self.btn_open_folder.setObjectName("pillToggle")
        self.btn_open_folder.setIcon(get_icon("folder", size=16))
        self.btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_folder.setStyleSheet("padding: 0 20px; min-height: 40px; border-radius: 18px; font-weight: 400;")
        self.btn_open_folder.clicked.connect(self._on_open_folder_clicked)
        actions_row.addWidget(self.btn_open_folder)

        self.btn_dub_another = QPushButton(tr("dub_another"))
        self.btn_dub_another.setObjectName("pillToggle")
        self.btn_dub_another.setIcon(get_icon("rotate-cw", size=16))
        self.btn_dub_another.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dub_another.setStyleSheet("padding: 0 20px; min-height: 40px; border-radius: 18px; font-weight: 400;")
        self.btn_dub_another.clicked.connect(lambda: self.stack_widget.setCurrentIndex(0))
        actions_row.addWidget(self.btn_dub_another)

        actions_row.addStretch(1)

        comp_layout.addLayout(actions_row)
        center_hbox.addWidget(comp_card)
        center_hbox.addStretch(1)

        page_layout.addLayout(center_hbox)
        page_layout.addStretch(1)
        return page

    # ── Event Handlers & Pipeline Execution ──

    def _update_stepper_state(self, step_num: int) -> None:
        if not hasattr(self, "step_labels"):
            return
        for idx, (box, icon_lbl, txt_lbl) in enumerate(self.step_labels, start=1):
            if idx < step_num:
                box.setStyleSheet(
                    "background-color: rgba(16, 185, 129, 0.1); border-radius: 8px; "
                    "border: 1px solid rgba(16, 185, 129, 0.3);"
                )
                txt_lbl.setStyleSheet("font-size: 12px; font-weight: 400; color: #10B981;")
                icon_lbl.setPixmap(get_icon("status_done", color="#10B981", size=14).pixmap(14, 14))
            elif idx == step_num:
                box.setStyleSheet(
                    "background-color: rgba(18, 89, 195, 0.12); border-radius: 8px; "
                    "border: 1px solid rgba(18, 89, 195, 0.4);"
                )
                txt_lbl.setStyleSheet("font-size: 12px; font-weight: 500; color: #1259C3;")
                icon_lbl.setPixmap(get_icon("rotate-cw", color="#1259C3", size=14).pixmap(14, 14))
            else:
                box.setStyleSheet(
                    "background-color: transparent; border-radius: 8px; "
                    "border: 1px solid rgba(156, 163, 175, 0.2);"
                )
                txt_lbl.setStyleSheet("font-size: 12px; font-weight: 400; color: #9CA3AF;")

    def _on_cancel_render_clicked(self) -> None:
        if hasattr(self, "tts_worker") and self.tts_worker and self.tts_worker.isRunning():
            try:
                self.tts_worker.terminate()
            except Exception:
                pass
        if hasattr(self, "mixer_worker") and self.mixer_worker and self.mixer_worker.isRunning():
            try:
                if hasattr(self.mixer_worker, "stop"):
                    self.mixer_worker.stop()
                self.mixer_worker.terminate()
            except Exception:
                pass
        if hasattr(self, "extractor_worker") and self.extractor_worker and self.extractor_worker.isRunning():
            try:
                self.extractor_worker.terminate()
            except Exception:
                pass
        if hasattr(self, "translator_worker") and self.translator_worker and self.translator_worker.isRunning():
            try:
                self.translator_worker.terminate()
            except Exception:
                pass
        self.proc_card.setVisible(False)
        self.stack_widget.setCurrentIndex(0)
        if hasattr(self, "lbl_system_status"):
            self.lbl_system_status.setText("Rendering cancelled by user.")

    def _on_play_completed_video_clicked(self) -> None:
        if self._output_video and Path(self._output_video).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._output_video).resolve())))

    def _on_back_clicked(self) -> None:
        if self.stack_widget.currentIndex() > 0:
            self.stack_widget.setCurrentIndex(0)
        elif self.file_input.text().strip() or (hasattr(self, "_batch_video_files") and self._batch_video_files):
            # If a video is currently loaded in the studio, reset to the Drop Zone import page
            self.file_input.clear()
            self.srt_input.clear()
            self._batch_video_files.clear()
            self._is_batch_mode = False
            if hasattr(self, "media_player") and self.media_player:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            self._open_preview_studio([])
        else:
            self.back_requested.emit()

    def _update_video_preview_state(self, target_file: str = "") -> None:
        video_path = target_file.strip() if target_file else self.file_input.text().strip()
        if video_path and os.path.exists(video_path) and os.path.isfile(video_path):
            if hasattr(self, "video_placeholder") and self.video_placeholder:
                self.video_placeholder.setVisible(False)
            if hasattr(self, "video_widget") and self.video_widget:
                self.video_widget.setVisible(True)
            if hasattr(self, "btn_change_video") and self.btn_change_video:
                self.btn_change_video.setVisible(True)
            if hasattr(self, "media_player") and self.media_player:
                self.media_player.setSource(QUrl.fromLocalFile(video_path))
                self.media_player.pause()
        elif video_path and os.path.exists(video_path) and os.path.isdir(video_path):
            if hasattr(self, "_batch_video_files") and self._batch_video_files:
                first_vid = self._batch_video_files[0]
                if os.path.exists(first_vid):
                    if hasattr(self, "video_placeholder") and self.video_placeholder:
                        self.video_placeholder.setVisible(False)
                    if hasattr(self, "video_widget") and self.video_widget:
                        self.video_widget.setVisible(True)
                    if hasattr(self, "btn_change_video") and self.btn_change_video:
                        self.btn_change_video.setVisible(True)
                    if hasattr(self, "media_player") and self.media_player:
                        self.media_player.setSource(QUrl.fromLocalFile(first_vid))
                        self.media_player.pause()
                    self._sync_player_audio_mode()
                    return
            if hasattr(self, "video_placeholder") and self.video_placeholder:
                self.video_placeholder.setVisible(True)
            if hasattr(self, "video_widget") and self.video_widget:
                self.video_widget.setVisible(False)
            if hasattr(self, "btn_change_video") and self.btn_change_video:
                self.btn_change_video.setVisible(False)
        else:
            if hasattr(self, "video_placeholder") and self.video_placeholder:
                self.video_placeholder.setVisible(True)
            if hasattr(self, "video_widget") and self.video_widget:
                self.video_widget.setVisible(False)
            if hasattr(self, "btn_change_video") and self.btn_change_video:
                self.btn_change_video.setVisible(False)
        self._sync_player_audio_mode()

    def _set_video_title_text(self, text: str) -> None:
        if hasattr(self, "lbl_video_title") and self.lbl_video_title:
            self.lbl_video_title.setToolTip(text)
            clean_t = text.strip()
            if len(clean_t) > 30:
                self.lbl_video_title.setText(clean_t[:27] + "...")
            else:
                self.lbl_video_title.setText(clean_t)

    def _on_file_or_folder_dropped(self, path_str: str) -> None:
        if not path_str or not os.path.exists(path_str):
            return
        p = Path(path_str)
        if p.is_dir():
            self.file_input.setText(str(p.resolve()))
            self.srt_input.clear()
            video_exts = {".mp4", ".mkv", ".avi", ".ts", ".mov", ".webm"}
            found_files = []
            for item in p.iterdir():
                if item.is_file() and item.suffix.lower() in video_exts and not item.name.endswith("_KhmerDubbed.mp4"):
                    found_files.append(str(item.resolve()))

            import re
            def natural_sort_key(s: str):
                return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]

            found_files.sort(key=natural_sort_key)

            if found_files:
                self._batch_video_files = found_files
                self._is_batch_mode = True
                self._current_batch_index = 0
                first_vid = found_files[0]
                first_p = Path(first_vid)

                self._set_video_title_text(f"Folder ({len(found_files)} episodes) - {first_p.name}")
                if hasattr(self, "lbl_project_info"):
                    self.lbl_project_info.setText(f"Project: {p.name} ({len(found_files)} episodes)")

                self._update_video_preview_state(first_vid)

                msg = tr("folder_mode_info").replace("{count}", str(len(found_files)))
                if hasattr(self, "folder_info_label"):
                    self.folder_info_label.setText(msg)
                    self.folder_info_label.setVisible(True)
                logger.info(f"Folder batch drop: {len(found_files)} episode videos found in '{path_str}'")
            else:
                self._batch_video_files = []
                self._set_video_title_text("No Video Files Found")
                if hasattr(self, "folder_info_label"):
                    self.folder_info_label.setText(f"No episode video files found in '{p.name}'")
                    self.folder_info_label.setVisible(True)
                self._update_video_preview_state("")
        elif p.is_file():
            self._batch_video_files = [str(p.resolve())]
            self._is_batch_mode = False
            self.file_input.setText(str(p.resolve()))
            if hasattr(self, "folder_info_label"):
                self.folder_info_label.setVisible(False)
            self.srt_input.clear()

            self._set_video_title_text(p.name)
            if hasattr(self, "lbl_project_info"):
                self.lbl_project_info.setText(f"Project: {p.name}")

            self._update_video_preview_state(str(p.resolve()))

            # Reset previous subtitles, audio clips, table & timeline for clean new video project
            self._subtitle_items = []
            self._audio_clips = None
            if hasattr(self, "timeline_widget") and self.timeline_widget:
                self.timeline_widget.set_subtitles([])
                self.timeline_widget.set_audio_clips([], [])
            if hasattr(self, "dialogue_table"):
                self.dialogue_table.setRowCount(0)
            if hasattr(self, "lbl_dialogue_count"):
                self.lbl_dialogue_count.setText("0 items")
            if hasattr(self, "lbl_preview_stats"):
                self.lbl_preview_stats.setText("0 items • Speech ~ 00:00")
            self._set_active_subtitle_text("")

            sidecar = self._find_sidecar_subtitle(p)
            if sidecar:
                self.srt_input.setText(str(sidecar))

    def _find_sidecar_subtitle(self, video_p: Path) -> Path | None:
        stem = video_p.stem
        parent = video_p.parent
        candidates = [
            video_p.with_suffix(".srt"),
            parent / f"{stem}_KhmerDub.srt",
            parent / f"{stem}.km.srt",
            parent / f"{stem}.zh-Hans.srt",
            parent / f"{stem}.zh-Hant.srt",
            parent / f"{stem}.zh.srt",
            parent / f"{stem}.en.srt",
            parent / f"{stem}_khmer.srt",
            parent / f"{stem}_Khmer.srt",
            video_p.with_suffix(".vtt"),
            parent / f"{stem}.zh-Hans.vtt",
            parent / f"{stem}.zh-Hant.vtt",
            parent / f"{stem}.zh.vtt",
            parent / f"{stem}.en.vtt",
        ]
        for ext_pattern in (f"{stem}*.srt", f"{stem}*.vtt"):
            for matched in parent.glob(ext_pattern):
                if matched not in candidates:
                    candidates.append(matched)
        for cand in candidates:
            if cand.exists():
                return cand.resolve()
        return None

    def _on_browse_clicked(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            tr("select_video_dubbing"),
            get_download_folder(),
            "Video Files (*.mp4 *.mkv *.ts *.mov *.avi *.webm);;All Files (*.*)",
        )
        if chosen:
            self._batch_video_files = [chosen]
            self._is_batch_mode = False
            self.file_input.setText(chosen)
            if hasattr(self, "folder_info_label"):
                self.folder_info_label.setVisible(False)
            self.srt_input.clear()

            video_p = Path(chosen)
            self._set_video_title_text(video_p.name)
            if hasattr(self, "lbl_project_info"):
                self.lbl_project_info.setText(f"Project: {video_p.name}")

            self._update_video_preview_state(chosen)

            # Reset previous subtitles, audio clips, table & timeline for clean new video project
            self._subtitle_items = []
            self._audio_clips = None
            if hasattr(self, "timeline_widget") and self.timeline_widget:
                self.timeline_widget.set_subtitles([])
                self.timeline_widget.set_audio_clips([], [])
            if hasattr(self, "dialogue_table"):
                self.dialogue_table.setRowCount(0)
            if hasattr(self, "lbl_dialogue_count"):
                self.lbl_dialogue_count.setText("0 items")
            if hasattr(self, "lbl_preview_stats"):
                self.lbl_preview_stats.setText("0 items • Speech ~ 00:00")
            self._set_active_subtitle_text("")

            sidecar = self._find_sidecar_subtitle(video_p)
            if sidecar:
                self.srt_input.setText(str(sidecar))

    def _on_browse_folder_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("select_folder"),
            get_download_folder(),
        )
        if folder:
            self.file_input.setText(folder)
            self.srt_input.clear()
            p = Path(folder)
            video_exts = {".mp4", ".mkv", ".avi", ".ts", ".mov", ".webm"}
            found_files = []
            for item in p.iterdir():
                if item.is_file() and item.suffix.lower() in video_exts and not item.name.endswith("_KhmerDubbed.mp4"):
                    found_files.append(str(item.resolve()))

            import re
            def natural_sort_key(s: str):
                return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]

            found_files.sort(key=natural_sort_key)

            if found_files:
                self._batch_video_files = found_files
                self._is_batch_mode = True
                self._current_batch_index = 0
                first_vid = found_files[0]
                first_p = Path(first_vid)

                self._set_video_title_text(f"Folder ({len(found_files)} episodes) - {first_p.name}")
                if hasattr(self, "lbl_project_info"):
                    self.lbl_project_info.setText(f"Project: {p.name} ({len(found_files)} episodes)")

                self._update_video_preview_state(first_vid)

                msg = tr("folder_mode_info").replace("{count}", str(len(found_files)))
                if hasattr(self, "folder_info_label"):
                    self.folder_info_label.setText(msg)
                    self.folder_info_label.setVisible(True)
                logger.info(f"Folder batch selection: {len(found_files)} episode videos found in '{folder}'")
            else:
                self._batch_video_files = []
                self._set_video_title_text("No Video Files Found")
                if hasattr(self, "folder_info_label"):
                    self.folder_info_label.setText(f"No episode video files found in '{p.name}'")
                    self.folder_info_label.setVisible(True)
                self._update_video_preview_state("")

    def _on_srt_text_changed(self, text: str) -> None:
        text = text.strip()
        if hasattr(self, "btn_browse_srt") and self.btn_browse_srt:
            if text and os.path.exists(text):
                srt_name = Path(text).name
                if len(srt_name) > 10:
                    srt_name = srt_name[:8] + "..."
                self.btn_browse_srt.setText(f"SRT: {srt_name}")
                self.btn_browse_srt.setToolTip(f"Active Subtitle File: {text}\nClick to choose another .srt")
                if hasattr(self, "btn_clear_srt") and self.btn_clear_srt:
                    self.btn_clear_srt.setVisible(True)
            else:
                self.btn_browse_srt.setText("+ SRT")
                self.btn_browse_srt.setToolTip("Import custom .srt subtitle file (optional)")
                if hasattr(self, "btn_clear_srt") and self.btn_clear_srt:
                    self.btn_clear_srt.setVisible(False)

    def _sync_timeline_audio_clips(self) -> None:
        """Auto-detects existing generated voice audio clips on disk and updates timeline widget."""
        if not hasattr(self, "timeline_widget") or not self.timeline_widget:
            return
        if hasattr(self, "_audio_clips") and self._audio_clips and any(self._audio_clips):
            self.timeline_widget.set_audio_clips(self._audio_clips, self._subtitle_items)
            return

        current_file = self._get_current_video_path()
        if current_file and self._subtitle_items:
            video_path = Path(current_file)
            clips_dir = video_path.parent / f"{video_path.stem}_voxcpm_clips"
            if clips_dir.exists():
                found_clips = []
                for it in self._subtitle_items:
                    clip_f = clips_dir / f"clip_{it.index:04d}.wav"
                    if clip_f.exists() and clip_f.stat().st_size > 500:
                        found_clips.append(str(clip_f))
                    else:
                        found_clips.append("")
                if any(found_clips):
                    self._audio_clips = found_clips
                    self.timeline_widget.set_audio_clips(self._audio_clips, self._subtitle_items)
                    return
        self.timeline_widget.set_audio_clips(getattr(self, "_audio_clips", None), self._subtitle_items)

    def _on_clear_srt_clicked(self) -> None:
        self.srt_input.clear()
        self._subtitle_items = []
        self._audio_clips = None
        if hasattr(self, "timeline_widget") and self.timeline_widget:
            self.timeline_widget.set_subtitles([])
            self.timeline_widget.set_audio_clips([], [])
        if hasattr(self, "dialogue_table"):
            self.dialogue_table.setRowCount(0)
        if hasattr(self, "lbl_dialogue_count"):
            self.lbl_dialogue_count.setText("0 items")
        if hasattr(self, "lbl_preview_stats"):
            self.lbl_preview_stats.setText("0 items • Speech ~ 00:00")
        self._show_toast("Cleared subtitle data.", icon_name="trash", is_success=True)

    def _on_browse_srt_clicked(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            tr("choose_srt_file"),
            get_download_folder(),
            "Subtitle Files (*.srt *.vtt);;All Files (*.*)",
        )
        if chosen and os.path.exists(chosen):
            self.srt_input.setText(chosen)
            self._load_imported_srt(chosen)

    def _load_imported_srt(self, srt_path: str) -> None:
        """Parses an imported SRT / VTT file and populates Dialogue Studio preview immediately."""
        if not srt_path or not os.path.exists(srt_path):
            return

        from downloader_app.core.subtitle_extractor import parse_srt_content
        content = ""
        for enc in ["utf-8-sig", "utf-8", "gbk", "latin1"]:
            try:
                with open(srt_path, "r", encoding=enc) as f:
                    content = f.read()
                break
            except Exception:
                continue

        if not content:
            self._show_toast("Failed to read subtitle file (empty or unsupported encoding).", icon_name="alert-circle", is_success=False)
            return

        items = parse_srt_content(content)
        if not items:
            self._show_toast("No valid subtitle dialogue lines found in SRT file.", icon_name="alert-circle", is_success=False)
            return

        logger.info(f"Loaded {len(items)} subtitle items from '{srt_path}'.")

        # Check if already in Khmer or needs translation
        khmer_count = sum(1 for it in items if any("\u1780" <= ch <= "\u17ff" for ch in it.text))
        has_foreign = any(re.search(r"[\u4e00-\u9fff]", it.text) for it in items)

        if khmer_count >= max(1, len(items) // 2) or not has_foreign:
            self._open_preview_studio(items)
            self._show_toast(f"Successfully loaded {len(items)} subtitle lines!", icon_name="status_done", is_success=True)
        else:
            fname = Path(srt_path).name
            self.proc_card.setVisible(True)
            self.lbl_proc_subtitle.setText(f"Translating {len(items)} lines from {fname} to Khmer...")
            self.progress_bar.setValue(25)
            self.lbl_proc_percent.setText("25%")

            self.translator_worker = SubtitleTranslationWorker(
                subtitle_items=items, target_lang="km", parent=self
            )
            self.translator_worker.progress_changed.connect(
                lambda pct, msg: self._update_progress(25 + (pct * 0.7), f"Translating: {msg}")
            )
            self.translator_worker.finished.connect(self._on_translation_finished)
            self.translator_worker.error.connect(self._on_pipeline_error)
            self.translator_worker.start()

    def _on_start_dubbing_clicked(self) -> None:
        video_path = self.file_input.text().strip()

        if not self._batch_video_files:
            if video_path and os.path.isfile(video_path):
                self._batch_video_files = [video_path]
            elif video_path and os.path.isdir(video_path):
                self._on_browse_folder_clicked()
            else:
                self._on_browse_clicked()
                return

        if not self._batch_video_files:
            return

        self._is_batch_mode = len(self._batch_video_files) > 1
        self._current_batch_index = 0

        self.proc_card.setVisible(True)
        self._process_next_batch_item()

    def _on_force_retranscribe_clicked(self) -> None:
        video_path = self._get_current_video_path()
        if not video_path or not os.path.isfile(video_path):
            video_path = self.file_input.text().strip()
        if not video_path or not os.path.isfile(video_path):
            return
        video_p = Path(video_path)
        khmer_cache = video_p.parent / f"{video_p.stem}_KhmerDub.srt"
        try:
            if khmer_cache.exists():
                khmer_cache.unlink()
        except OSError:
            pass
        self.srt_input.clear()
        self._batch_video_files = [video_path]
        self._is_batch_mode = False
        self._current_batch_index = 0
        self.proc_card.setVisible(True)
        self._process_next_batch_item()

    def _on_scan_ocr_clicked(self) -> None:
        video_path = self._get_current_video_path()
        if not video_path or not os.path.isfile(video_path):
            video_path = self.file_input.text().strip()
        if not video_path or not os.path.isfile(video_path):
            QMessageBox.warning(self, tr("warning"), "Please select a valid video file first.")
            return

        crop_ratio = None
        overlay = getattr(self, "video_preview_overlay", None)
        if not overlay and hasattr(self, "video_player_view") and self.video_player_view:
            overlay = getattr(self.video_player_view, "overlay_item", None)

        if overlay:
            try:
                mask_rect, _, _, _, _, _ = overlay._compute_mask_geometry()
                tr = overlay._target_rect
                if tr.width() > 0 and tr.height() > 0 and mask_rect.isValid():
                    xr = max(0.0, min(1.0, (mask_rect.x() - tr.x()) / tr.width()))
                    yr = max(0.0, min(1.0, (mask_rect.y() - tr.y()) / tr.height()))
                    wr = max(0.1, min(1.0, mask_rect.width() / tr.width()))
                    hr = max(0.1, min(1.0, mask_rect.height() / tr.height()))
                    # Add generous safety margin on each side to ensure subtitle characters are never clipped
                    xr = max(0.0, xr - 0.04)
                    wr = min(1.0 - xr, wr + 0.08)
                    yr = max(0.0, yr - 0.08)
                    hr = min(1.0 - yr, hr + 0.16)
                    crop_ratio = (xr, yr, wr, hr)
            except Exception as e:
                logger.warning(f"Failed to compute crop ratio from overlay: {e}")

        if hasattr(self, "proc_card"):
            self.proc_card.setVisible(True)
        if hasattr(self, "lbl_proc_title") and self.lbl_proc_title:
            self.lbl_proc_title.setText("Scanning Screen Subtitles (Vision OCR)")

        if hasattr(self, "btn_scan_ocr"):
            self.btn_scan_ocr.setEnabled(False)
        if hasattr(self, "btn_retranscribe"):
            self.btn_retranscribe.setEnabled(False)

        self._update_progress(5.0, "Launching Vision AI OCR Subtitle Scan...")

        from downloader_app.core.subtitle_extractor import SubtitleOCRWorker
        self._ocr_worker = SubtitleOCRWorker(
            video_path=video_path,
            crop_box_ratio=crop_ratio,
            target_lang="km",
            parent=self,
        )
        self._ocr_worker.progress_changed.connect(
            lambda pct, msg: self._update_progress(pct, msg)
        )
        self._ocr_worker.finished.connect(self._on_ocr_scan_finished)
        self._ocr_worker.error.connect(self._on_ocr_error)
        self._ocr_worker.start()

    def _on_ocr_scan_finished(self, items: list) -> None:
        if hasattr(self, "proc_card"):
            self.proc_card.setVisible(False)
        if hasattr(self, "btn_scan_ocr"):
            self.btn_scan_ocr.setEnabled(True)
        if hasattr(self, "btn_retranscribe"):
            self.btn_retranscribe.setEnabled(True)
        if hasattr(self, "live_sub_label") and self.live_sub_label:
            self.live_sub_label.setText(f"✅ Vision OCR Complete! Loaded {len(items)} dialogue items.")
        self._on_subtitles_extracted(items)

    def _on_ocr_error(self, err_msg: str) -> None:
        if hasattr(self, "proc_card"):
            self.proc_card.setVisible(False)
        if hasattr(self, "btn_scan_ocr"):
            self.btn_scan_ocr.setEnabled(True)
        if hasattr(self, "btn_retranscribe"):
            self.btn_retranscribe.setEnabled(True)
        if hasattr(self, "live_sub_label") and self.live_sub_label:
            self.live_sub_label.setText(f"⚠️ OCR Failed: {err_msg[:60]}")
        self._on_pipeline_error(err_msg)

    def _process_next_batch_item(self) -> None:
        if self._current_batch_index >= len(self._batch_video_files):
            logger.info(f"All {len(self._batch_video_files)} episode videos dubbed successfully.")
            self.proc_card.setVisible(False)
            if hasattr(self, "lbl_system_status"):
                self.lbl_system_status.setText("All episode videos dubbed successfully!")
            if self._is_batch_mode:
                if hasattr(self, "lbl_comp_subtitle"):
                    self.lbl_comp_subtitle.setText(f"Successfully dubbed all {len(self._batch_video_files)} episode videos!")
                self._show_toast(
                    f"Successfully dubbed all {len(self._batch_video_files)} episode videos!",
                    icon_name="film",
                    is_success=True,
                )
            return

        video_path = self._batch_video_files[self._current_batch_index]
        if not os.path.exists(video_path):
            logger.warning(f"Video file missing: {video_path}, skipping to next in batch...")
            self._current_batch_index += 1
            self._process_next_batch_item()
            return

        total_batch = len(self._batch_video_files)
        v_name = Path(video_path).name

        self.proc_card.setVisible(True)
        if self._is_batch_mode:
            batch_msg = tr("batch_dubbing_progress").replace("{current}", str(self._current_batch_index + 1)).replace("{total}", str(total_batch)).replace("{filename}", v_name)
            self.lbl_proc_title.setText(batch_msg)
        else:
            self.lbl_proc_title.setText(tr("dubbing_in_progress"))

        self.lbl_proc_subtitle.setText(f"[{v_name}] Step 1/4: Listening to dialogue...")
        if hasattr(self, "lbl_proc_subtitle_page"):
            self.lbl_proc_subtitle_page.setText(f"Step 1/4: Listening to dialogue in {v_name}...")
        pct = int(((self._current_batch_index) / total_batch) * 100) if self._is_batch_mode else 10
        self.progress_bar.setValue(pct)
        self.lbl_proc_percent.setText(f"{pct}%")

        video_p = Path(video_path)
        srt_path = self.srt_input.text().strip() if not self._is_batch_mode else ""

        self.extractor_worker = SubtitleExtractorWorker(
            video_path,
            srt_path=srt_path if srt_path else None,
            ignore_sidecar=True,
            parent=self,
        )
        self.extractor_worker.progress_changed.connect(
            lambda pct, msg: self._update_progress(pct * 0.3, f"[{v_name}] Step 1/4: {msg}")
        )
        self.extractor_worker.finished.connect(self._on_subtitles_extracted)
        self.extractor_worker.error.connect(self._on_pipeline_error)
        self.extractor_worker.start()

    def _on_subtitles_extracted(self, items: list[SubtitleItem]) -> None:
        try:
            from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
            for it in items:
                it.text = clean_khmer_dialogue_typos(it.text)
        except Exception:
            pass
        self._subtitle_items = items

        # Check if items are already in Khmer
        khmer_count = sum(1 for it in items if any("\u1780" <= ch <= "\u17ff" for ch in it.text))
        if items and khmer_count >= max(1, len(items) // 2):
            logger.info(f"Subtitles are already in Khmer ({khmer_count}/{len(items)} items).")
            if self._is_batch_mode:
                self._execute_tts_and_mux(items)
            else:
                self._open_preview_studio(items)
            return

        v_name = Path(self._batch_video_files[self._current_batch_index] if self._batch_video_files else "").name
        self.lbl_proc_subtitle.setText(f"[{v_name}] Step 2/4: Translating dialogue to Khmer...")
        if not self._is_batch_mode:
            self.progress_bar.setValue(30)
            self.lbl_proc_percent.setText("30%")

        # Step 2: Translate via Gemini
        self.translator_worker = SubtitleTranslationWorker(
            subtitle_items=items, target_lang="km", parent=self
        )
        self.translator_worker.progress_changed.connect(
            lambda pct, msg: self._update_progress(30 + (pct * 0.2), f"[{v_name}] Step 2/4: {msg}")
        )
        self.translator_worker.finished.connect(self._on_translation_finished)
        self.translator_worker.error.connect(self._on_pipeline_error)
        self.translator_worker.start()

    def _on_translation_finished(self, translated_items: list[SubtitleItem]) -> None:
        try:
            from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
            for it in translated_items:
                it.text = clean_khmer_dialogue_typos(it.text)
        except Exception:
            pass
        self._subtitle_items = translated_items
        if self._is_batch_mode:
            self._execute_tts_and_mux(translated_items)
        else:
            logger.info(f"Dialogue translation finished ({len(translated_items)} items). Opening Dialogue Studio Preview.")
            self._open_preview_studio(translated_items)

    # ── Dialogue Studio & Preview Methods ──

    def _open_preview_studio(self, items: list[SubtitleItem]) -> None:
        try:
            from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
            for it in items:
                it.text = clean_khmer_dialogue_typos(it.text)
        except Exception:
            pass
        self._subtitle_items = items
        self.proc_card.setVisible(False)

        # Update stats
        voice_key, ref_sample, voice_name = self._get_selected_voice_info()
        if hasattr(self, "lbl_preview_voice"):
            self.lbl_preview_voice.setText(voice_name)

        total_sec = sum(it.duration_seconds for it in items)
        mins = int(total_sec // 60)
        secs = int(total_sec % 60)
        if hasattr(self, "lbl_preview_stats"):
            self.lbl_preview_stats.setText(
                f"{len(items)} {tr('dialogue_lines_count').replace('{count}', str(len(items)))} • "
                f"Speech ~ {mins:02d}:{secs:02d}"
            )
        if hasattr(self, "lbl_dialogue_count"):
            self.lbl_dialogue_count.setText(f"{len(items)} items")

        # Update video title / project info label
        video_path = self.file_input.text().strip()
        if video_path:
            v_name = Path(video_path).name
            if hasattr(self, "lbl_video_title"):
                self.lbl_video_title.setText(v_name)
            if hasattr(self, "lbl_project_info"):
                self.lbl_project_info.setText(f"Project: {v_name}")
        else:
            if hasattr(self, "lbl_video_title"):
                self.lbl_video_title.setText("No Video Loaded")
            if hasattr(self, "lbl_project_info"):
                self.lbl_project_info.setText("No Project Loaded")

        # Load video into media player and toggle viewport placeholder
        self._update_video_preview_state(video_path)

        # Update timeline widget with subtitles & duration
        if hasattr(self, "timeline_widget") and self.timeline_widget:
            self.timeline_widget.set_subtitles(self._subtitle_items)
            if self.media_player and self.media_player.duration() > 0:
                self.timeline_widget.set_duration(self.media_player.duration() / 1000.0)
            elif items:
                max_end = max(it.end_seconds for it in items)
                self.timeline_widget.set_duration(max(60.0, max_end + 5.0))
            self._sync_timeline_audio_clips()

        # Populate 6-column dialogue table: ☑, START, END, KHMER TEXT (EDITABLE), VOICE PROFILE, AUDIO STATUS
        self.dialogue_table.setRowCount(len(items))
        voice_key, ref_sample, voice_code = self._get_selected_voice_info()

        for r, it in enumerate(items):
            # Col 0: Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Checked)
            self.dialogue_table.setItem(r, 0, chk_item)

            # Col 1: START timestamp (MM:SS.ms)
            s_m, s_s = divmod(int(it.start_seconds), 60)
            s_ms = int(round((it.start_seconds - int(it.start_seconds)) * 100))
            start_item = QTableWidgetItem(f"{s_m:02d}:{s_s:02d}.{s_ms:02d}")
            start_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            start_item.setFlags(start_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.dialogue_table.setItem(r, 1, start_item)

            # Col 2: END timestamp (MM:SS.ms)
            e_m, e_s = divmod(int(it.end_seconds), 60)
            e_ms = int(round((it.end_seconds - int(it.end_seconds)) * 100))
            end_item = QTableWidgetItem(f"{e_m:02d}:{e_s:02d}.{e_ms:02d}")
            end_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            end_item.setFlags(end_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.dialogue_table.setItem(r, 2, end_item)

            # Col 3: KHMER TEXT (EDITABLE)
            txt_item = QTableWidgetItem(it.text)
            txt_item.setFlags(txt_item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.dialogue_table.setItem(r, 3, txt_item)

            # Col 4: VOICE PROFILE
            v_item = QTableWidgetItem(voice_code)
            v_item.setFlags(v_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.dialogue_table.setItem(r, 4, v_item)

            # Col 5: AUDIO STATUS
            has_clip = False
            if hasattr(self, "_audio_clips") and self._audio_clips and r < len(self._audio_clips):
                cp = self._audio_clips[r]
                if cp and Path(cp).exists() and Path(cp).stat().st_size > 500:
                    has_clip = True

            if has_clip:
                status_item = QTableWidgetItem("Audio Ready")
                status_color = "#34D399" if get_theme() == "dark" else "#059669"
            else:
                status_item = QTableWidgetItem("Pending")
                status_color = "#9CA3AF"

            status_item.setForeground(QColor(status_color))
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.dialogue_table.setItem(r, 5, status_item)

        if items:
            self.dialogue_table.selectRow(0)
            self._set_active_subtitle_text(items[0].text)
        else:
            self._set_active_subtitle_text("")

    def _get_current_font_size(self) -> int:
        if not hasattr(self, "combo_sub_size") or not self.combo_sub_size:
            return 30
        text = self.combo_sub_size.currentText().strip()
        match = re.search(r"\d+", text)
        if match:
            try:
                return max(10, min(150, int(match.group(0))))
            except Exception:
                pass
        val = self.combo_sub_size.currentData()
        if isinstance(val, int) and val > 0:
            return val
        return 30

    def _get_current_font_variant(self) -> str:
        if not hasattr(self, "combo_font_variant") or not self.combo_font_variant:
            return "Bold"
        text = self.combo_font_variant.currentText().strip()
        if text:
            return text
        val = self.combo_font_variant.currentData()
        if isinstance(val, str) and val.strip():
            return val.strip()
        return "Bold"

    def _get_current_bg_w_size(self) -> int:
        if not hasattr(self, "combo_bg_w_size") or not self.combo_bg_w_size:
            return getattr(self, "_current_bg_w_scale", 100)
        text = self.combo_bg_w_size.currentText().strip()
        match = re.search(r"\d+", text)
        if match:
            try:
                val = max(30, min(200, int(match.group(0))))
                self._current_bg_w_scale = val
                return val
            except Exception:
                pass
        val = self.combo_bg_w_size.currentData()
        if isinstance(val, int) and val > 0:
            self._current_bg_w_scale = val
            return val
        return getattr(self, "_current_bg_w_scale", 100)

    def _get_current_bg_h_size(self) -> int:
        if not hasattr(self, "combo_bg_h_size") or not self.combo_bg_h_size:
            return getattr(self, "_current_bg_h_scale", 100)
        text = self.combo_bg_h_size.currentText().strip()
        match = re.search(r"\d+", text)
        if match:
            try:
                val = max(30, min(250, int(match.group(0))))
                self._current_bg_h_scale = val
                return val
            except Exception:
                pass
        val = self.combo_bg_h_size.currentData()
        if isinstance(val, int) and val > 0:
            self._current_bg_h_scale = val
            return val
        return getattr(self, "_current_bg_h_scale", 100)

    def _get_current_bg_size(self) -> int:
        return self._get_current_bg_h_size()

    def _get_current_bg_color(self) -> str:
        return getattr(self, "_current_bg_color", "#FFFFFF")

    def _get_current_bg_opacity(self) -> int:
        if not hasattr(self, "combo_bg_opacity") or not self.combo_bg_opacity:
            return getattr(self, "_current_bg_opacity", 100)
        text = self.combo_bg_opacity.currentText().strip()
        match = re.search(r"\d+", text)
        if match:
            try:
                val = max(0, min(100, int(match.group(0))))
                self._current_bg_opacity = val
                return val
            except Exception:
                pass
        val = self.combo_bg_opacity.currentData()
        if isinstance(val, int) and 0 <= val <= 100:
            self._current_bg_opacity = val
            return val
        return getattr(self, "_current_bg_opacity", 100)

    def _on_sub_size_changed(self, *args) -> None:
        self._refresh_video_sub_overlay_style()

    def _on_sub_style_toggled(self) -> None:
        self._update_toolbar_button_styles()
        self._refresh_video_sub_overlay_style()

    def _get_current_sub_color(self) -> str:
        return getattr(self, "_current_sub_color", "#FFFFFF")

    def _on_sub_color_clicked(self) -> None:
        init_color = self._get_current_sub_color()
        dialog = SubtitleColorPickerDialog(current_color=init_color, title="Select Subtitle Text Color", parent=self)
        dialog.color_selected.connect(self._on_sub_color_chosen)
        dialog.exec()

    def _on_sub_color_chosen(self, hex_color: str) -> None:
        self._current_sub_color = hex_color.upper()
        self._update_toolbar_button_styles()
        self._refresh_video_sub_overlay_style()

    def _on_bg_color_clicked(self) -> None:
        init_color = self._get_current_bg_color()
        dialog = SubtitleColorPickerDialog(current_color=init_color, title="Select Mask Panel Color", parent=self)
        dialog.color_selected.connect(self._on_bg_color_chosen)
        dialog.exec()

    def _on_bg_color_chosen(self, hex_color: str) -> None:
        self._current_bg_color = hex_color.upper()
        self._update_toolbar_button_styles()
        self._refresh_video_sub_overlay_style()

    def _on_bg_size_changed(self, *args) -> None:
        self._get_current_bg_w_size()
        self._get_current_bg_h_size()
        self._refresh_video_sub_overlay_style()

    def _on_box_interactively_resized(self, w_scale: int, h_scale: int) -> None:
        self._current_bg_w_scale = w_scale
        self._current_bg_h_scale = h_scale
        if hasattr(self, "combo_bg_w_size") and self.combo_bg_w_size:
            self.combo_bg_w_size.blockSignals(True)
            self.combo_bg_w_size.setEditText(f"W:{w_scale}%")
            self.combo_bg_w_size.blockSignals(False)
        if hasattr(self, "combo_bg_h_size") and self.combo_bg_h_size:
            self.combo_bg_h_size.blockSignals(True)
            self.combo_bg_h_size.setEditText(f"H:{h_scale}%")
            self.combo_bg_h_size.blockSignals(False)

    def _on_mask_interactively_moved(self, pos_x_ratio: float, pos_y_ratio: float) -> None:
        self._current_mask_pos_x_ratio = pos_x_ratio
        self._current_mask_pos_y_ratio = pos_y_ratio
        self._current_pos_x_ratio = pos_x_ratio
        self._current_pos_y_ratio = pos_y_ratio

    def _on_sub_interactively_moved(self, pos_x_ratio: float, pos_y_ratio: float) -> None:
        self._current_sub_pos_x_ratio = pos_x_ratio
        self._current_sub_pos_y_ratio = pos_y_ratio

    def _on_box_interactively_moved(self, pos_x_ratio: float, pos_y_ratio: float) -> None:
        self._on_mask_interactively_moved(pos_x_ratio, pos_y_ratio)

    def _on_bg_opacity_changed(self, *args) -> None:
        self._get_current_bg_opacity()
        self._refresh_video_sub_overlay_style()

    def _get_current_aspect_ratio(self) -> str:
        if not hasattr(self, "combo_aspect_ratio") or not self.combo_aspect_ratio:
            return "original"
        data = self.combo_aspect_ratio.currentData()
        if data:
            return str(data)
        text = self.combo_aspect_ratio.currentText().strip().lower()
        if "crop" in text:
            return "9:16_crop"
        if "9:16" in text or "tiktok" in text or "reel" in text:
            return "9:16_blur"
        return "original"

    def _on_aspect_ratio_changed(self, *args) -> None:
        self._refresh_video_sub_overlay_style()

    def _get_current_subtitle_mode(self) -> str:
        if not hasattr(self, "combo_subtitle_mode") or not self.combo_subtitle_mode:
            return "full"
        data = self.combo_subtitle_mode.currentData()
        if data:
            return str(data)
        text = self.combo_subtitle_mode.currentText().strip().lower()
        if "1-2" in text or "1_word" in text:
            return "1_word"
        if "3-4" in text or "phrase" in text:
            return "short_phrase"
        if "compact" in text:
            return "compact_line"
        return "full"

    def _on_subtitle_mode_changed(self, *args) -> None:
        self._refresh_video_sub_overlay_style()

    def _refresh_video_sub_overlay_style(self) -> None:
        cur_text = ""
        if hasattr(self, "dialogue_table") and self.dialogue_table.rowCount() > 0:
            selected = self.dialogue_table.selectedItems()
            if selected:
                row = selected[0].row()
                if 0 <= row < len(self._subtitle_items):
                    cur_text = self._subtitle_items[row].text
        if not cur_text and hasattr(self, "live_sub_label"):
            t = self.live_sub_label.text()
            if t and t != "No Subtitles Loaded":
                cur_text = t
        self._set_active_subtitle_text(cur_text)

    def _set_active_subtitle_text(self, text: str) -> None:
        text = text.strip() if text else ""
        if hasattr(self, "live_sub_label"):
            self.live_sub_label.setText(text if text else "No Subtitles Loaded")

        burn_active = self.chk_burn_subtitles.isChecked() if hasattr(self, "chk_burn_subtitles") else False
        blur_active = self.chk_blur_subtitles.isChecked() if hasattr(self, "chk_blur_subtitles") else False
        font_pt = self._get_current_font_size()
        font_variant = self._get_current_font_variant()
        bg_w_scale = self._get_current_bg_w_size()
        bg_h_scale = self._get_current_bg_h_size()
        bg_color = self._get_current_bg_color()
        sub_color = self._get_current_sub_color()
        bg_opacity = self._get_current_bg_opacity()

        mask_x = getattr(self, "_current_mask_pos_x_ratio", getattr(self, "_current_pos_x_ratio", None))
        mask_y = getattr(self, "_current_mask_pos_y_ratio", getattr(self, "_current_pos_y_ratio", None))
        sub_x = getattr(self, "_current_sub_pos_x_ratio", None)
        sub_y = getattr(self, "_current_sub_pos_y_ratio", None)

        if hasattr(self, "video_player_view") and self.video_player_view:
            if text and text != "No Subtitles Loaded" and burn_active:
                self.video_player_view.set_subtitle(
                    text,
                    blur_enabled=blur_active,
                    burn_enabled=True,
                    font_variant=font_variant,
                    font_size_pt=font_pt,
                    sub_text_color=sub_color,
                    bg_box_w_scale=bg_w_scale,
                    bg_box_h_scale=bg_h_scale,
                    bg_box_color=bg_color,
                    bg_box_opacity=bg_opacity,
                    mask_pos_x_ratio=mask_x,
                    mask_pos_y_ratio=mask_y,
                    sub_pos_x_ratio=sub_x,
                    sub_pos_y_ratio=sub_y,
                )
            else:
                self.video_player_view.set_subtitle(
                    "",
                    blur_enabled=blur_active,
                    burn_enabled=False,
                    font_variant=font_variant,
                    font_size_pt=font_pt,
                    sub_text_color=sub_color,
                    bg_box_w_scale=bg_w_scale,
                    bg_box_h_scale=bg_h_scale,
                    bg_box_color=bg_color,
                    bg_box_opacity=bg_opacity,
                    mask_pos_x_ratio=mask_x,
                    mask_pos_y_ratio=mask_y,
                    sub_pos_x_ratio=sub_x,
                    sub_pos_y_ratio=sub_y,
                )

    def _toggle_playback(self) -> None:
        if not self.media_player:
            return
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            if hasattr(self, "preview_audio_player_1") and self.preview_audio_player_1:
                self.preview_audio_player_1.pause()
            if hasattr(self, "preview_audio_player_2") and self.preview_audio_player_2:
                self.preview_audio_player_2.pause()
            if hasattr(self, "btn_play_pause"):
                self.btn_play_pause.setIcon(get_icon("play", size=16))
        else:
            self.media_player.play()
            if hasattr(self, "preview_audio_player_1") and self.preview_audio_player_1:
                if self.preview_audio_player_1.playbackState() == QMediaPlayer.PlaybackState.PausedState:
                    self.preview_audio_player_1.play()
            if hasattr(self, "preview_audio_player_2") and self.preview_audio_player_2:
                if self.preview_audio_player_2.playbackState() == QMediaPlayer.PlaybackState.PausedState:
                    self.preview_audio_player_2.play()
            if hasattr(self, "btn_play_pause"):
                self.btn_play_pause.setIcon(get_icon("pause", size=16))

    def _toggle_playback(self) -> None:
        if not self.media_player:
            return
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            if hasattr(self, "preview_audio_player") and self.preview_audio_player:
                self.preview_audio_player.pause()
            if hasattr(self, "btn_play_pause"):
                self.btn_play_pause.setIcon(get_icon("play", size=16))
        else:
            self.media_player.play()
            if hasattr(self, "preview_audio_player") and self.preview_audio_player:
                if self.preview_audio_player.playbackState() == QMediaPlayer.PlaybackState.PausedState:
                    self.preview_audio_player.play()
            if hasattr(self, "btn_play_pause"):
                self.btn_play_pause.setIcon(get_icon("pause", size=16))

    def _stop_playback(self) -> None:
        if self.media_player:
            self.media_player.stop()
            if hasattr(self, "preview_audio_player") and self.preview_audio_player:
                self.preview_audio_player.stop()
            if hasattr(self, "btn_play_pause"):
                self.btn_play_pause.setIcon(get_icon("play", size=16))

    def _on_player_position_changed(self, pos_ms: int) -> None:
        if hasattr(self, "seek_slider") and not self.seek_slider.isSliderDown():
            dur_ms = self.media_player.duration() if self.media_player else 0
            if dur_ms > 0:
                self.seek_slider.setValue(int((pos_ms / dur_ms) * 1000))

        cur_sec = pos_ms / 1000.0
        dur_sec = (self.media_player.duration() / 1000.0) if self.media_player else 0
        c_m, c_s = divmod(int(cur_sec), 60)
        c_ms = int(round((cur_sec - int(cur_sec)) * 100))
        d_m, d_s = divmod(int(dur_sec), 60)
        d_ms = int(round((dur_sec - int(dur_sec)) * 100))
        if hasattr(self, "lbl_cur_time"):
            self.lbl_cur_time.setText(f"{c_m:02d}:{c_s:02d}.{c_ms:02d}")
        if hasattr(self, "lbl_total_time"):
            self.lbl_total_time.setText(f"{d_m:02d}:{d_s:02d}.{d_ms:02d}")
        if hasattr(self, "lbl_time_display"):
            self.lbl_time_display.setText(f"{c_m:02d}:{c_s:02d} / {d_m:02d}:{d_s:02d}")
        if hasattr(self, "timeline_widget") and self.timeline_widget:
            self.timeline_widget.set_position(cur_sec)

        # Update live subtitle banner & sync Khmer speech audio clip playback during live video playback
        cur_row = -1
        mode = self._get_current_subtitle_mode()

        for r, it in enumerate(self._subtitle_items):
            if it.start_seconds <= cur_sec <= it.end_seconds:
                cur_row = r
                if mode != "full":
                    timed_chunks = split_subtitle_into_timed_chunks(it, subtitle_mode=mode)
                    active_text = it.text
                    for chunk in timed_chunks:
                        if chunk.start_seconds <= cur_sec <= chunk.end_seconds:
                            active_text = chunk.text
                            break
                    self._set_active_subtitle_text(active_text)
                else:
                    self._set_active_subtitle_text(it.text)
                break

        if cur_row == -1:
            self._set_active_subtitle_text("")

        if (
            cur_row != -1
            and getattr(self, "_last_played_preview_index", -1) != cur_row
            and self.media_player
            and self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ):
            self._last_played_preview_index = cur_row
            if hasattr(self, "_audio_clips") and self._audio_clips and cur_row < len(self._audio_clips):
                if self._audio_clips[cur_row] and os.path.exists(self._audio_clips[cur_row]):
                    self._play_khmer_audio_preview(cur_row)

    def _on_player_duration_changed(self, dur_ms: int) -> None:
        dur_sec = dur_ms / 1000.0
        d_m, d_s = divmod(int(dur_sec), 60)
        d_ms = int(round((dur_sec - int(dur_sec)) * 100))
        if hasattr(self, "lbl_total_time"):
            self.lbl_total_time.setText(f"{d_m:02d}:{d_s:02d}.{d_ms:02d}")
        if hasattr(self, "lbl_time_display"):
            self.lbl_time_display.setText(f"00:00 / {d_m:02d}:{d_s:02d}")
        if hasattr(self, "timeline_widget") and self.timeline_widget:
            self.timeline_widget.set_duration(dur_sec)

    def _on_seek_slider_moved(self, val: int) -> None:
        if self.media_player:
            self._last_played_preview_index = -1
            if hasattr(self, "preview_audio_player") and self.preview_audio_player:
                self.preview_audio_player.stop()
            dur_ms = self.media_player.duration()
            if dur_ms > 0:
                pos_ms = int((val / 1000.0) * dur_ms)
                self.media_player.setPosition(pos_ms)

    def _on_timeline_seek(self, sec: float) -> None:
        """Handles scrubbing and seeking from the interactive studio timeline."""
        if self.media_player:
            self._last_played_preview_index = -1
            if hasattr(self, "preview_audio_player") and self.preview_audio_player:
                self.preview_audio_player.stop()
            pos_ms = int(sec * 1000)
            self.media_player.setPosition(pos_ms)
            dur_ms = self.media_player.duration()
            if dur_ms > 0:
                if hasattr(self, "seek_slider") and not self.seek_slider.isSliderDown():
                    self.seek_slider.setValue(int((pos_ms / dur_ms) * 1000))
            self._on_player_position_changed(pos_ms)

    def _on_timeline_zoom_changed(self, val: int) -> None:
        if hasattr(self, "lbl_zoom_val") and self.lbl_zoom_val:
            self.lbl_zoom_val.setText(f"{val}%")
        if hasattr(self, "timeline_widget") and self.timeline_widget:
            self.timeline_widget.set_zoom(val / 100.0)

    def _seek_to_seconds(self, sec: float) -> None:
        if self.media_player:
            self._last_played_preview_index = -1
            if hasattr(self, "preview_audio_player") and self.preview_audio_player:
                self.preview_audio_player.stop()
            self.media_player.setPosition(int(sec * 1000))
            self.media_player.play()
            if hasattr(self, "btn_play_pause"):
                self.btn_play_pause.setIcon(get_icon("pause", size=16))

    def _on_table_row_clicked(self, row: int, col: int) -> None:
        if 0 <= row < len(self._subtitle_items):
            it = self._subtitle_items[row]
            if self.media_player:
                self._last_played_preview_index = -1
                self.media_player.setPosition(int(it.start_seconds * 1000))
            self._set_active_subtitle_text(it.text)
            self._play_khmer_audio_preview(row)

    def _on_mode_changed(self, mode_id: int) -> None:
        self._update_toolbar_button_styles()
        self._sync_player_audio_mode()

    def _sync_player_audio_mode(self) -> None:
        if hasattr(self, "audio_output") and self.audio_output:
            mode_id = self.mode_group.checkedId() if hasattr(self, "mode_group") and self.mode_group else 0
            if mode_id == 1:
                # Full Audio Replace: completely mute original video background sound
                self.audio_output.setMuted(True)
                self.audio_output.setVolume(0.0)
            else:
                # Voiceover (Keep BG Audio / Ducking): normal background level
                self.audio_output.setMuted(False)
                self.audio_output.setVolume(0.7)

    def _on_preview_audio_state_changed(self, state) -> None:
        if hasattr(self, "audio_output") and self.audio_output:
            mode_id = self.mode_group.checkedId() if hasattr(self, "mode_group") and self.mode_group else 0
            if mode_id == 1:
                self.audio_output.setMuted(True)
                self.audio_output.setVolume(0.0)
            else:
                if state == QMediaPlayer.PlaybackState.StoppedState:
                    self.audio_output.setVolume(0.7)

    def _play_khmer_audio_preview(self, row: int) -> None:
        if not hasattr(self, "_subtitle_items") or not self._subtitle_items:
            return
        if 0 <= row < len(self._subtitle_items):
            it = self._subtitle_items[row]
            clip_path = None
            if hasattr(self, "_audio_clips") and self._audio_clips and row < len(self._audio_clips):
                c = self._audio_clips[row]
                if c and os.path.exists(c) and os.path.getsize(c) > 500:
                    clip_path = c

            if not clip_path and it.text.strip():
                # On-demand synthesis for instant single-line preview
                current_file = self._get_current_video_path()
                video_path = Path(current_file) if current_file else Path.cwd()
                clips_dir = video_path.parent / f"{video_path.stem}_voxcpm_clips"
                clips_dir.mkdir(parents=True, exist_ok=True)
                target_clip = clips_dir / f"clip_{it.index:04d}.wav"

                voice_key, ref_sample, voice_label = self._get_selected_voice_info()

                from downloader_app.core.tts_voxcpm import VoxCPM2Client
                client = VoxCPM2Client()
                if row + 1 < len(self._subtitle_items):
                    gap = self._subtitle_items[row + 1].start_seconds - it.start_seconds
                    max_dur = max(0.6, gap - 0.05) if gap > 0 else it.duration_seconds
                else:
                    max_dur = max(it.duration_seconds, 2.5)

                ok = client.generate_audio(
                    text=it.text,
                    duration_sec=it.duration_seconds,
                    output_path=target_clip,
                    target_lang="km",
                    max_allowed_duration=max_dur,
                    voice=voice_key,
                    ref_audio_path=ref_sample,
                )
                if ok and target_clip.exists() and target_clip.stat().st_size > 500:
                    clip_path = str(target_clip)
                    if not hasattr(self, "_audio_clips") or not self._audio_clips or len(self._audio_clips) != len(self._subtitle_items):
                        self._audio_clips = [""] * len(self._subtitle_items)
                    self._audio_clips[row] = clip_path
                    if hasattr(self, "timeline_widget") and self.timeline_widget:
                        self.timeline_widget.set_audio_clips(self._audio_clips, self._subtitle_items)

            if clip_path and os.path.exists(clip_path):
                if hasattr(self, "preview_audio_player") and self.preview_audio_player:
                    try:
                        self.preview_audio_player.stop()
                        abs_url = QUrl.fromLocalFile(str(Path(clip_path).resolve()))
                        self.preview_audio_player.setSource(abs_url)
                        if hasattr(self, "preview_audio_output") and self.preview_audio_output:
                            self.preview_audio_output.setVolume(1.0)
                            self.preview_audio_output.setMuted(False)

                        # In Full Audio Replace, ensure original video audio remains 100% silent
                        # In Ducking mode, lower original video background sound while speech is playing
                        mode_id = self.mode_group.checkedId() if hasattr(self, "mode_group") and self.mode_group else 0
                        if hasattr(self, "audio_output") and self.audio_output:
                            if mode_id == 1:
                                self.audio_output.setMuted(True)
                                self.audio_output.setVolume(0.0)
                            else:
                                self.audio_output.setVolume(0.12)

                        self.preview_audio_player.play()
                        logger.info(f"Playing Khmer audio preview clip ({row}): {clip_path}")
                    except Exception as e:
                        logger.warning(f"Error playing Khmer audio preview clip: {e}")

    def _on_table_row_double_clicked(self, row: int, col: int) -> None:
        if 0 <= row < len(self._subtitle_items):
            it = self._subtitle_items[row]
            self._seek_to_seconds(it.start_seconds)
            self._play_khmer_audio_preview(row)

    def _get_selected_voice_info(self) -> tuple[str, str, str]:
        """
        Returns:
            (voice_key, ref_audio_sample_path, display_name)
        """
        voices_dir = Path(__file__).parent.parent / "resources" / "voices"
        sdach_sample = str((voices_dir / "sdach_game.mp3").resolve())
        harvard_sample = str((voices_dir / "harvard.mp3").resolve())

        if not hasattr(self, "combo_voice") or not self.combo_voice:
            return ("km-KH-PisethNeural", "", "Piseth (Male)")

        data = self.combo_voice.currentData()
        if data == "sdach_game" or (isinstance(data, int) and data == 2):
            return ("sdach_game", sdach_sample, "Sdach Game")
        elif data == "harvard" or (isinstance(data, int) and data == 3):
            return ("harvard", harvard_sample, "Harvard")
        elif data == "km-KH-SreymomNeural" or (isinstance(data, int) and data == 1):
            return ("km-KH-SreymomNeural", "", "Sreymom (Female)")
        elif data == "custom_clone" or (isinstance(data, int) and data == 4):
            sample_p = getattr(self, "_custom_voice_sample", "")
            s_name = Path(sample_p).name if sample_p else "Sample"
            return ("custom_clone", sample_p, f"Clone ({s_name})")
        else:
            return ("km-KH-PisethNeural", "", "Piseth (Male)")

    def _get_selected_voice_id(self) -> int:
        if hasattr(self, "combo_voice") and self.combo_voice:
            return self.combo_voice.currentIndex()
        return 0

    def _on_voice_combo_changed(self, index: int) -> None:
        voice_key, ref_sample, voice_label = self._get_selected_voice_info()
        if voice_key == "custom_clone" and not getattr(self, "_custom_voice_sample", None):
            self._on_upload_voice_sample_clicked()
        self._sync_voice_profile_table()

    def _stop_sample_playback(self) -> None:
        if hasattr(self, "preview_audio_player") and self.preview_audio_player:
            if self.preview_audio_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.preview_audio_player.stop()

    def _on_play_voice_sample_clicked(self) -> None:
        """Plays a 5-second reference sample preview for the currently selected voice."""
        # Toggle stop if already playing
        if hasattr(self, "preview_audio_player") and self.preview_audio_player:
            if self.preview_audio_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.preview_audio_player.stop()
                return

        voice_key, ref_sample, voice_label = self._get_selected_voice_info()

        if ref_sample and os.path.exists(ref_sample):
            if hasattr(self, "preview_audio_player") and self.preview_audio_player:
                try:
                    self.preview_audio_player.stop()
                    abs_url = QUrl.fromLocalFile(str(Path(ref_sample).resolve()))
                    self.preview_audio_player.setSource(abs_url)
                    if hasattr(self, "preview_audio_output") and self.preview_audio_output:
                        self.preview_audio_output.setVolume(1.0)
                        self.preview_audio_output.setMuted(False)
                    self.preview_audio_player.play()
                    self._show_toast(f"Playing 5s sample preview: {voice_label}", icon_name="mic", is_success=True)
                    # Automatically stop playback after 5 seconds
                    QTimer.singleShot(5000, self._stop_sample_playback)
                    return
                except Exception as e:
                    logger.warning(f"Error playing voice sample: {e}")

        if voice_key == "custom_clone" and not ref_sample:
            self._on_upload_voice_sample_clicked()
            return

        # Generate on-the-fly preview greeting for standard voices
        preview_dir = Path.cwd() / "scratch" / "voice_samples"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_file = preview_dir / f"{voice_key}_sample.wav"

        from downloader_app.core.tts_voxcpm import VoxCPM2Client
        client = VoxCPM2Client()
        greeting = "សួស្តីបងប្អូនទាំងអស់គ្នា! នេះគឺជាសម្លេងគំរូ។"
        ok = client.generate_audio(
            text=greeting,
            duration_sec=2.5,
            output_path=preview_file,
            target_lang="km",
            voice=voice_key,
            ref_audio_path=ref_sample,
        )
        if ok and preview_file.exists():
            if hasattr(self, "preview_audio_player") and self.preview_audio_player:
                self.preview_audio_player.stop()
                abs_url = QUrl.fromLocalFile(str(preview_file.resolve()))
                self.preview_audio_player.setSource(abs_url)
                if hasattr(self, "preview_audio_output") and self.preview_audio_output:
                    self.preview_audio_output.setVolume(1.0)
                    self.preview_audio_output.setMuted(False)
                self.preview_audio_player.play()
                self._show_toast(f"Playing 5s sample preview: {voice_label}", icon_name="mic", is_success=True)
                QTimer.singleShot(5000, self._stop_sample_playback)

    def _on_upload_voice_sample_clicked(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Upload Custom Voice Sample for Voice Cloning",
            get_download_folder(),
            "Audio Files (*.wav *.mp3 *.m4a *.ogg *.flac);;All Files (*.*)",
        )
        if chosen and os.path.exists(chosen):
            self._custom_voice_sample = chosen
            fname = Path(chosen).name
            disp_name = fname if len(fname) <= 20 else fname[:18] + "..."
            if hasattr(self, "btn_upload_sample"):
                self.btn_upload_sample.setText(disp_name)
                self.btn_upload_sample.setIcon(get_icon("mic", size=11))
                self.btn_upload_sample.setToolTip(chosen)
            if hasattr(self, "btn_preview_upload"):
                self.btn_preview_upload.setText(disp_name)
                self.btn_preview_upload.setIcon(get_icon("mic", size=11))
                self.btn_preview_upload.setToolTip(chosen)
            if hasattr(self, "combo_voice"):
                idx = self.combo_voice.findData("custom_clone")
                if idx >= 0:
                    self.combo_voice.setItemText(idx, f"Clone ({disp_name})")
                    self.combo_voice.setCurrentIndex(idx)
                else:
                    self.combo_voice.addItem(get_icon("user", size=15), f"Clone ({disp_name})", "custom_clone")
                    self.combo_voice.setCurrentIndex(self.combo_voice.count() - 1)
            self._sync_voice_profile_table()
            self._show_toast(f"Loaded voice sample: {fname}", icon_name="mic", is_success=True)
            logger.info(f"Loaded custom voice sample for cloning: {chosen}")

    def _sync_voice_profile_table(self) -> None:
        voice_key, ref_sample, voice_code = self._get_selected_voice_info()

        if hasattr(self, "dialogue_table"):
            for r in range(self.dialogue_table.rowCount()):
                v_item = self.dialogue_table.item(r, 4)
                if v_item:
                    v_item.setText(voice_code)
                else:
                    new_item = QTableWidgetItem(voice_code)
                    new_item.setFlags(new_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.dialogue_table.setItem(r, 4, new_item)

                status_item = self.dialogue_table.item(r, 5)
                if status_item:
                    status_item.setText("Pending")
                    status_item.setForeground(QColor("#9CA3AF"))

        # Clear stale audio clips on voice switch so next render executes fresh TTS
        self._audio_clips = None
        if hasattr(self, "timeline_widget") and self.timeline_widget:
            self.timeline_widget.set_audio_clips(None, self._subtitle_items)

    def _on_generate_audio_clicked(self) -> None:
        self._sync_voice_profile_table()
        render_items = []
        for r in range(self.dialogue_table.rowCount()):
            chk_item = self.dialogue_table.item(r, 0)
            txt_item = self.dialogue_table.item(r, 3)
            if txt_item and r < len(self._subtitle_items):
                try:
                    from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
                    cleaned_t = clean_khmer_dialogue_typos(txt_item.text())
                    self._subtitle_items[r].text = cleaned_t
                    if cleaned_t != txt_item.text():
                        txt_item.setText(cleaned_t)
                except Exception:
                    self._subtitle_items[r].text = txt_item.text()
            if chk_item is None or chk_item.checkState() == Qt.CheckState.Checked:
                if r < len(self._subtitle_items):
                    render_items.append(self._subtitle_items[r])

        if not render_items:
            render_items = self._subtitle_items

        self.proc_card.setVisible(True)
        voice_key, ref_sample, voice_label_str = self._get_selected_voice_info()

        current_file = self._get_current_video_path()
        video_path = Path(current_file) if current_file else Path.cwd()
        v_name = video_path.name

        self.lbl_proc_subtitle.setText(f"[{v_name}] Generating Human Khmer voice ({voice_label_str})...")
        self.progress_bar.setValue(10)
        self.lbl_proc_percent.setText("10%")

        clips_dir = video_path.parent / f"{video_path.stem}_voxcpm_clips"

        self.tts_worker = VoxCPM2DubbingWorker(
            subtitle_items=render_items,
            output_dir=str(clips_dir),
            target_lang="km",
            voice=voice_key,
            ref_audio_path=ref_sample,
            parent=self,
        )
        self.tts_worker.progress_changed.connect(
            lambda pct, msg: self._update_progress(10 + (pct * 0.85), f"[{v_name}] {msg}")
        )
        self.tts_worker.finished.connect(self._on_preview_tts_finished)
        self.tts_worker.error.connect(self._on_pipeline_error)
        self.tts_worker.start()

    def _show_toast(self, message: str, icon_name: str = "status_done", is_success: bool = True) -> None:
        """Displays a non-blocking One UI toast notification banner at the top of the view."""
        if not hasattr(self, "toast_banner"):
            return
        is_dark = get_theme() == "dark"
        if is_success:
            bg_color = "rgba(16, 185, 129, 0.12)" if not is_dark else "rgba(16, 185, 129, 0.2)"
            border_color = "rgba(16, 185, 129, 0.35)"
            text_color = "#047857" if not is_dark else "#34D399"
            icon_color = "#10B981"
        else:
            bg_color = "rgba(239, 68, 68, 0.1)" if not is_dark else "rgba(239, 68, 68, 0.2)"
            border_color = "rgba(239, 68, 68, 0.3)"
            text_color = "#B91C1C" if not is_dark else "#F87171"
            icon_color = "#EF4444"

        self.toast_banner.setStyleSheet(
            f"QFrame#toastBanner {{ background-color: {bg_color}; border: 1px solid {border_color}; "
            f"border-radius: 12px; }}"
        )
        self.lbl_toast_icon.setPixmap(get_icon(icon_name, color=icon_color, size=16).pixmap(16, 16))
        self.lbl_toast_msg.setText(message)
        self.lbl_toast_msg.setStyleSheet(f"font-size: 13px; font-weight: 400; color: {text_color};")
        self.toast_banner.setVisible(True)

        if hasattr(self, "lbl_system_status"):
            self.lbl_system_status.setText(message)

        def _safe_hide_toast():
            try:
                if hasattr(self, "toast_banner") and self.toast_banner:
                    self.toast_banner.setVisible(False)
            except (RuntimeError, Exception):
                pass

        QTimer.singleShot(4000, _safe_hide_toast)

    def _on_preview_tts_finished(self, audio_clips: list[str], items: list[SubtitleItem]) -> None:
        self._audio_clips = audio_clips
        self.proc_card.setVisible(False)
        if hasattr(self, "timeline_widget") and self.timeline_widget:
            self.timeline_widget.set_audio_clips(audio_clips, self._subtitle_items)

        # Update table column 5 status to Audio Ready
        for r in range(min(len(audio_clips), self.dialogue_table.rowCount())):
            status_item = self.dialogue_table.item(r, 5)
            if status_item:
                status_item.setText("Audio Ready")
                status_item.setForeground(QColor("#10B981" if get_theme() == "dark" else "#059669"))

        self._show_toast(
            f"Successfully generated {len(audio_clips)} Khmer voice audio clips! Ready for live preview.",
            icon_name="status_done",
            is_success=True,
        )

    def _filter_dialogue_table(self, query: str) -> None:
        q = query.strip().lower()
        visible_count = 0
        for r in range(self.dialogue_table.rowCount()):
            if not q:
                self.dialogue_table.setRowHidden(r, False)
                visible_count += 1
                continue
            txt_item = self.dialogue_table.item(r, 3)
            start_item = self.dialogue_table.item(r, 1)
            txt = txt_item.text().lower() if txt_item else ""
            t_str = start_item.text().lower() if start_item else ""
            match = q in txt or q in t_str
            self.dialogue_table.setRowHidden(r, not match)
            if match:
                visible_count += 1
        if hasattr(self, "lbl_dialogue_count"):
            self.lbl_dialogue_count.setText(f"{visible_count} items")

    def _on_export_srt_clicked(self) -> None:
        if not self._subtitle_items and (not hasattr(self, "dialogue_table") or self.dialogue_table.rowCount() == 0):
            return

        if hasattr(self, "dialogue_table"):
            for r in range(self.dialogue_table.rowCount()):
                txt_item = self.dialogue_table.item(r, 3)
                if txt_item and r < len(self._subtitle_items):
                    try:
                        from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
                        cleaned_t = clean_khmer_dialogue_typos(txt_item.text())
                        self._subtitle_items[r].text = cleaned_t
                        if cleaned_t != txt_item.text():
                            txt_item.setText(cleaned_t)
                    except Exception:
                        self._subtitle_items[r].text = txt_item.text()

        chosen, _ = QFileDialog.getSaveFileName(
            self,
            tr("export_srt"),
            get_download_folder(),
            "Subtitle Files (*.srt);;All Files (*.*)",
        )
        if chosen:
            if not chosen.lower().endswith(".srt"):
                chosen += ".srt"
            from downloader_app.core.subtitle_extractor import format_srt_content
            try:
                with open(chosen, "w", encoding="utf-8") as f:
                    f.write(format_srt_content(self._subtitle_items))
                self._show_toast(
                    f"Successfully exported subtitle to: {Path(chosen).name}",
                    icon_name="download",
                    is_success=True,
                )
            except Exception as e:
                self._show_toast(f"Export failed: {e}", icon_name="alert_circle", is_success=False)

    def _on_preview_back_clicked(self) -> None:
        if self.media_player:
            self.media_player.pause()
            if hasattr(self, "btn_play_pause"):
                self.btn_play_pause.setIcon(get_icon("play", size=16))
        self.stack_widget.setCurrentIndex(0)

    def _on_final_render_clicked(self) -> None:
        if self.media_player:
            self.media_player.pause()
            if hasattr(self, "btn_play_pause"):
                self.btn_play_pause.setIcon(get_icon("play", size=16))

        # Sync edited Khmer text back into subtitle items and filter checked items
        render_items = []
        for r in range(self.dialogue_table.rowCount()):
            chk_item = self.dialogue_table.item(r, 0)
            txt_item = self.dialogue_table.item(r, 3)
            if txt_item and r < len(self._subtitle_items):
                try:
                    from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
                    cleaned_t = clean_khmer_dialogue_typos(txt_item.text())
                    self._subtitle_items[r].text = cleaned_t
                    if cleaned_t != txt_item.text():
                        txt_item.setText(cleaned_t)
                except Exception:
                    self._subtitle_items[r].text = txt_item.text()
            if chk_item is None or chk_item.checkState() == Qt.CheckState.Checked:
                if r < len(self._subtitle_items):
                    render_items.append(self._subtitle_items[r])

        if not render_items:
            render_items = self._subtitle_items

        # Remain in Studio UI and display progress in bottom status bar (matching Transcribe & Generate Selected Audio)
        self.proc_card.setVisible(True)
        if hasattr(self, "lbl_system_status"):
            self.lbl_system_status.setText("Final rendering in progress...")

        # Validate pre-generated clips: ALL clips must exist and be valid non-empty audio files
        all_clips_valid = False
        if hasattr(self, "_audio_clips") and self._audio_clips and len(self._audio_clips) == len(render_items):
            all_clips_valid = all(
                p and Path(p).exists() and Path(p).stat().st_size > 500
                for p in self._audio_clips
            )

        if all_clips_valid:
            logger.info("Using verified pre-generated Khmer audio clips for final video render.")
            self._on_tts_finished(self._audio_clips, render_items)
        else:
            # Clear invalid/incomplete clips and execute fresh TTS generation for ALL dialogue lines
            self._audio_clips = None
            self._execute_tts_and_mux(render_items)

    def _get_current_video_path(self) -> str:
        if self._batch_video_files and 0 <= self._current_batch_index < len(self._batch_video_files):
            return self._batch_video_files[self._current_batch_index]
        return self.file_input.text().strip()

    def _execute_tts_and_mux(self, items: list[SubtitleItem]) -> None:
        voice_key, ref_sample, voice_label_str = self._get_selected_voice_info()

        current_file = self._get_current_video_path()
        video_path = Path(current_file) if current_file else Path.cwd()
        v_name = video_path.name

        self.lbl_proc_subtitle.setText(f"[{v_name}] Step 3/4: Generating Human Khmer voice ({voice_label_str})...")
        if not self._is_batch_mode:
            self.progress_bar.setValue(50)
            self.lbl_proc_percent.setText("50%")

        clips_dir = video_path.parent / f"{video_path.stem}_voxcpm_clips"

        # Step 3: Generate studio-quality neural audio clips
        self.tts_worker = VoxCPM2DubbingWorker(
            subtitle_items=items,
            output_dir=str(clips_dir),
            target_lang="km",
            voice=voice_key,
            ref_audio_path=ref_sample,
            parent=self,
        )
        self.tts_worker.progress_changed.connect(
            lambda pct, msg: self._update_progress(50 + (pct * 0.3), f"[{v_name}] {msg}")
        )
        self.tts_worker.finished.connect(self._on_tts_finished)
        self.tts_worker.error.connect(self._on_pipeline_error)
        self.tts_worker.start()

    def _on_tts_finished(self, audio_clips: list[str], items: list[SubtitleItem]) -> None:
        self._audio_clips = audio_clips
        if hasattr(self, "timeline_widget") and self.timeline_widget:
            self.timeline_widget.set_audio_clips(audio_clips, self._subtitle_items)
        current_file = self._get_current_video_path()
        video_path = Path(current_file)
        v_name = video_path.name

        self.lbl_proc_subtitle.setText(f"[{v_name}] Step 4/4: Muxing dubbed Khmer audio into video track...")
        if not self._is_batch_mode:
            self.progress_bar.setValue(85)
            self.lbl_proc_percent.setText("85%")

        final_dir = video_path.parent / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        out_video = final_dir / f"{video_path.stem}_KhmerDubbed.mp4"
        self._output_video = str(out_video)

        mode_id = self.mode_group.checkedId()
        mix_mode = "replace" if mode_id == 1 else "ducking"
        voice_key, ref_sample, _ = self._get_selected_voice_info()

        burn_subs = self.chk_burn_subtitles.isChecked() if hasattr(self, "chk_burn_subtitles") else False
        blur_subs = self.chk_blur_subtitles.isChecked() if hasattr(self, "chk_blur_subtitles") else False
        sub_size = self._get_current_font_size()
        sub_variant = self._get_current_font_variant()

        # Step 4: Sync & Mix via FFmpeg
        actual_mask_x = self.video_player_view.overlay_item._mask_pos_x_ratio if (hasattr(self, "video_player_view") and self.video_player_view and hasattr(self.video_player_view, "overlay_item")) else getattr(self, "_current_mask_pos_x_ratio", getattr(self, "_current_pos_x_ratio", None))
        actual_mask_y = self.video_player_view.overlay_item._mask_pos_y_ratio if (hasattr(self, "video_player_view") and self.video_player_view and hasattr(self.video_player_view, "overlay_item")) else getattr(self, "_current_mask_pos_y_ratio", getattr(self, "_current_pos_y_ratio", None))
        actual_sub_x = self.video_player_view.overlay_item._sub_pos_x_ratio if (hasattr(self, "video_player_view") and self.video_player_view and hasattr(self.video_player_view, "overlay_item")) else getattr(self, "_current_sub_pos_x_ratio", None)
        actual_sub_y = self.video_player_view.overlay_item._sub_pos_y_ratio if (hasattr(self, "video_player_view") and self.video_player_view and hasattr(self.video_player_view, "overlay_item")) else getattr(self, "_current_sub_pos_y_ratio", None)

        self.mixer_worker = DubbingMixerWorker(
            video_path=str(video_path),
            subtitle_items=items,
            audio_clip_paths=audio_clips,
            output_video_path=str(out_video),
            mix_mode=mix_mode,
            voice=voice_key,
            ref_audio_path=ref_sample,
            burn_subtitles=burn_subs,
            blur_subtitles=blur_subs,
            font_name="Google Sans",
            font_variant=sub_variant,
            font_size=sub_size,
            sub_color=self._get_current_sub_color(),
            bg_box_scale=self._get_current_bg_h_size(),
            bg_box_w_scale=self._get_current_bg_w_size(),
            bg_box_h_scale=self._get_current_bg_h_size(),
            bg_box_color=self._get_current_bg_color(),
            bg_box_opacity=self._get_current_bg_opacity(),
            pos_x_ratio=getattr(self, "_current_pos_x_ratio", None),
            pos_y_ratio=getattr(self, "_current_pos_y_ratio", None),
            mask_pos_x_ratio=actual_mask_x,
            mask_pos_y_ratio=actual_mask_y,
            sub_pos_x_ratio=actual_sub_x,
            sub_pos_y_ratio=actual_sub_y,
            aspect_ratio=self._get_current_aspect_ratio(),
            subtitle_mode=self._get_current_subtitle_mode(),
            parent=self,
        )
        def _handle_mixer_progress(pct: float, msg: str = "") -> None:
            status_text = msg if msg else "Muxing audio & video tracks..."
            if self._is_batch_mode:
                total_batch = max(1, len(self._batch_video_files))
                batch_base = (self._current_batch_index / total_batch) * 100.0
                batch_step = (1.0 / total_batch) * 100.0
                scaled_pct = batch_base + (pct / 100.0) * batch_step
                self._update_progress(scaled_pct, f"[{self._current_batch_index + 1}/{total_batch}] [{v_name}] {status_text}")
            else:
                self._update_progress(pct, f"[{v_name}] {status_text}")

        self.mixer_worker.progress_changed.connect(_handle_mixer_progress)
        self.mixer_worker.finished.connect(self._on_dubbing_finished)
        self.mixer_worker.error.connect(self._on_pipeline_error)
        self.mixer_worker.start()

    def _on_dubbing_finished(self, out_video_path: str) -> None:
        self._output_video = out_video_path
        if self._is_batch_mode:
            self._current_batch_index += 1
            self._process_next_batch_item()
        else:
            self.proc_card.setVisible(False)
            fname = Path(out_video_path).name
            if hasattr(self, "lbl_system_status"):
                self.lbl_system_status.setText(f"Dubbing Complete! Saved to: {fname}")
            if hasattr(self, "lbl_comp_subtitle"):
                self.lbl_comp_subtitle.setText(f"Saved to: {fname}")
            self._show_toast(
                f"Final Render Complete! Video saved to: {fname}",
                icon_name="film",
                is_success=True,
            )
            # Update video player to rendered video for instant preview
            if self.media_player and os.path.exists(out_video_path):
                self.media_player.setSource(QUrl.fromLocalFile(out_video_path))
                if hasattr(self, "lbl_video_title"):
                    self.lbl_video_title.setText(fname)

    def _on_pipeline_error(self, err_msg: str) -> None:
        logger.error(f"Voice dubbing pipeline error: {err_msg}")
        self.proc_card.setVisible(False)
        if self._is_batch_mode:
            logger.warning(f"Batch episode error: {err_msg}. Advancing to next episode...")
            self._current_batch_index += 1
            self._process_next_batch_item()
        else:
            self._show_toast(f"Dubbing failed: {err_msg}", icon_name="alert_circle", is_success=False)

    def _update_progress(self, percent: float, msg: str) -> None:
        val = int(min(100, max(0, percent)))
        if hasattr(self, "progress_bar") and self.progress_bar:
            self.progress_bar.setValue(val)
        if hasattr(self, "lbl_proc_percent") and self.lbl_proc_percent:
            self.lbl_proc_percent.setText(f"{val}%")
        if hasattr(self, "lbl_proc_subtitle") and self.lbl_proc_subtitle:
            self.lbl_proc_subtitle.setText(msg)

        if hasattr(self, "progress_bar_page") and self.progress_bar_page:
            self.progress_bar_page.setValue(val)
        if hasattr(self, "lbl_proc_percent_page") and self.lbl_proc_percent_page:
            self.lbl_proc_percent_page.setText(f"{val}%")

        # Clean msg and extract filename badge for processing page
        clean_msg = msg
        if "[" in msg and "]" in msg:
            parts = msg.split("]", 1)
            fn = parts[0].lstrip("[").strip()
            clean_msg = parts[1].strip() if len(parts) > 1 else msg
            if hasattr(self, "lbl_proc_filename_page") and self.lbl_proc_filename_page:
                self.lbl_proc_filename_page.setText(fn)
                self.lbl_proc_filename_page.setVisible(True)

        if hasattr(self, "lbl_proc_subtitle_page") and self.lbl_proc_subtitle_page:
            self.lbl_proc_subtitle_page.setText(clean_msg)

        # Update video player preview 1-by-1 frame if timestamp is present in OCR scanning message
        if "OCR Scanning frame" in msg and "(" in msg and ")" in msg:
            try:
                ts_str = msg.split("(")[-1].split(")")[0].strip()
                from downloader_app.core.subtitle_extractor import timestamp_to_seconds
                t_sec = timestamp_to_seconds(ts_str)
                if hasattr(self, "media_player") and self.media_player and self.media_player.duration() > 0:
                    self.media_player.setPosition(int(t_sec * 1000))
                if hasattr(self, "lbl_cur_time") and self.lbl_cur_time:
                    self.lbl_cur_time.setText(ts_str[:8])
            except Exception:
                pass

        # Dynamic Stepper Highlighting
        msg_lower = msg.lower()
        if "step 1" in msg_lower or "listening" in msg_lower or "extracting" in msg_lower:
            self._update_stepper_state(1)
        elif "step 2" in msg_lower or "translating" in msg_lower:
            self._update_stepper_state(2)
        elif "step 3" in msg_lower or "generating" in msg_lower or "voice" in msg_lower:
            self._update_stepper_state(3)
        elif "step 4" in msg_lower or "muxing" in msg_lower or "audio track" in msg_lower or val >= 85:
            self._update_stepper_state(4)

    def _on_open_folder_clicked(self) -> None:
        out_path = self._output_video or self.file_input.text().strip()
        if out_path:
            p = Path(out_path).parent
            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))

    def _update_toolbar_button_styles(self) -> None:
        """Updates toolbar buttons and dropdown styles for high contrast in both Dark and Light mode."""
        is_dark = get_theme() == "dark"
        active_bg = "#2563EB" if is_dark else "#1259C3"
        active_border = "#3B82F6" if is_dark else "#1259C3"
        active_color = "#FFFFFF"
        active_hover = "#1D4ED8" if is_dark else "#0E469C"

        inactive_bg = "#242428" if is_dark else "#F1F5F9"
        inactive_border = "#38383E" if is_dark else "#CBD5E1"
        inactive_color = "#F1F5F9" if is_dark else "#1E293B"
        inactive_hover = "#2F2F36" if is_dark else "#E2E8F0"

        icon_active_color = "#FFFFFF"
        icon_inactive_color = "#94A3B8" if is_dark else "#475569"

        def _apply_btn_style(btn: QPushButton, is_checked: bool, icon_name: str | None = None, icon_size: int = 11):
            if is_checked:
                bg = active_bg
                border = active_border
                txt = active_color
                hov = active_hover
                if icon_name:
                    btn.setIcon(get_icon(icon_name, color=icon_active_color, size=icon_size))
            else:
                bg = inactive_bg
                border = inactive_border
                txt = inactive_color
                hov = inactive_hover
                if icon_name:
                    btn.setIcon(get_icon(icon_name, color=icon_inactive_color, size=icon_size))

            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: {txt}; border: 1px solid {border}; "
                f"border-radius: 13px; padding: 0 8px; min-height: 26px; max-height: 26px; font-size: 11px; font-weight: 400; outline: none; }} "
                f"QPushButton:hover {{ background-color: {hov}; }}"
            )

        # Back / Reset Studio button
        if hasattr(self, "btn_back_studio") and self.btn_back_studio:
            self.btn_back_studio.setIcon(get_icon("arrow-left", color=icon_inactive_color, size=11))
            self.btn_back_studio.setStyleSheet(
                f"QPushButton {{ background-color: {inactive_bg}; color: {inactive_color}; border: 1px solid {inactive_border}; "
                f"border-radius: 13px; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0; outline: none; }} "
                f"QPushButton:hover {{ background-color: {inactive_hover}; }}"
            )

        # 0. Open Video button
        if hasattr(self, "btn_open_video") and self.btn_open_video:
            _apply_btn_style(self.btn_open_video, False, "film", 11)

        # 0b. Change Video button
        if hasattr(self, "btn_change_video") and self.btn_change_video:
            _apply_btn_style(self.btn_change_video, False, "folder", 11)

        # 1. SRT Load button
        if hasattr(self, "btn_browse_srt") and self.btn_browse_srt:
            _apply_btn_style(self.btn_browse_srt, False, "folder", 11)

        # 2. Clear SRT button
        if hasattr(self, "btn_clear_srt") and self.btn_clear_srt:
            self.btn_clear_srt.setIcon(get_icon("x", color=icon_inactive_color, size=10))
            self.btn_clear_srt.setStyleSheet(
                f"QPushButton {{ background-color: {inactive_bg}; color: {inactive_color}; border: 1px solid {inactive_border}; "
                f"border-radius: 12px; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; padding: 0; outline: none; }} "
                f"QPushButton:hover {{ background-color: {inactive_hover}; }}"
            )

        # 3. Voice & Language combos
        if hasattr(self, "combo_voice") and self.combo_voice:
            self.combo_voice.setItemIcon(0, get_icon("user", color=icon_inactive_color, size=11))
            self.combo_voice.setItemIcon(1, get_icon("user", color=icon_inactive_color, size=11))
            self.combo_voice.setItemIcon(2, get_icon("mic", color=icon_inactive_color, size=11))
            self.combo_voice.setItemIcon(3, get_icon("mic", color=icon_inactive_color, size=11))
            self.combo_voice.setItemIcon(4, get_icon("user", color=icon_inactive_color, size=11))
            self.combo_voice.setStyleSheet(
                f"QComboBox {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 13px; padding: 0 14px 0 7px; "
                f"min-height: 26px; max-height: 26px; font-size: 11px; outline: none; }} "
                f"QComboBox:hover {{ border: 1px solid {'#484852' if is_dark else '#94A3B8'}; }} "
                f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 13px; border-left: none; }} "
                f"QComboBox::down-arrow {{ width: 0; height: 0; border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 3.5px solid {'#94A3B8' if is_dark else '#64748B'}; margin-right: 3px; }} "
                f"QComboBox QAbstractItemView {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 8px; selection-background-color: {active_bg}; selection-color: #FFFFFF; padding: 4px; }}"
            )

        if hasattr(self, "combo_language") and self.combo_language:
            self.combo_language.setStyleSheet(
                f"QComboBox {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 8px; padding: 4px 8px; "
                f"min-height: 28px; font-size: 11.5px; outline: none; }} "
                f"QComboBox:hover {{ border: 1px solid {'#484852' if is_dark else '#94A3B8'}; }} "
                f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 14px; border-left: none; }} "
                f"QComboBox::down-arrow {{ width: 0; height: 0; border-left: 3.5px solid transparent; border-right: 3.5px solid transparent; border-top: 4px solid {'#94A3B8' if is_dark else '#64748B'}; margin-right: 4px; }} "
                f"QComboBox QAbstractItemView {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 8px; selection-background-color: {active_bg}; selection-color: #FFFFFF; padding: 4px; }}"
            )

        # 4. Listen button
        if hasattr(self, "btn_play_sample") and self.btn_play_sample:
            self.btn_play_sample.setIcon(get_icon("play", color=icon_inactive_color, size=11))
            self.btn_play_sample.setStyleSheet(
                f"QPushButton {{ background-color: {inactive_bg}; color: {inactive_color}; border: 1px solid {inactive_border}; "
                f"border-radius: 13px; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0; outline: none; }} "
                f"QPushButton:hover {{ background-color: {inactive_hover}; }}"
            )

        # 5. Upload button
        if hasattr(self, "btn_upload_sample") and self.btn_upload_sample:
            self.btn_upload_sample.setIcon(get_icon("mic", color=icon_inactive_color, size=11))
            self.btn_upload_sample.setStyleSheet(
                f"QPushButton {{ background-color: {inactive_bg}; color: {inactive_color}; border: 1px solid {inactive_border}; "
                f"border-radius: 13px; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0; outline: none; }} "
                f"QPushButton:hover {{ background-color: {inactive_hover}; }}"
            )

        # 6. Mode buttons: Ducking & Replace
        if hasattr(self, "btn_mode_ducking") and self.btn_mode_ducking:
            _apply_btn_style(self.btn_mode_ducking, self.btn_mode_ducking.isChecked(), None)
        if hasattr(self, "btn_mode_replace") and self.btn_mode_replace:
            _apply_btn_style(self.btn_mode_replace, self.btn_mode_replace.isChecked(), None)

        # 7. Subtitle checkables: Khmer Sub & Black BG
        if hasattr(self, "chk_burn_subtitles") and self.chk_burn_subtitles:
            _apply_btn_style(self.chk_burn_subtitles, self.chk_burn_subtitles.isChecked(), "file-video", 11)
        if hasattr(self, "chk_blur_subtitles") and self.chk_blur_subtitles:
            _apply_btn_style(self.chk_blur_subtitles, self.chk_blur_subtitles.isChecked(), "video", 11)

        # 8. Font Variant combo
        if hasattr(self, "combo_font_variant") and self.combo_font_variant:
            self.combo_font_variant.setStyleSheet(
                f"QComboBox {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 13px; padding: 0 14px 0 7px; "
                f"min-height: 26px; max-height: 26px; font-size: 11px; outline: none; }} "
                f"QComboBox:hover {{ border: 1px solid {'#484852' if is_dark else '#94A3B8'}; }} "
                f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 13px; border-left: none; }} "
                f"QComboBox::down-arrow {{ width: 0; height: 0; border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 3.5px solid {'#94A3B8' if is_dark else '#64748B'}; margin-right: 3px; }} "
                f"QComboBox QAbstractItemView {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 8px; selection-background-color: {active_bg}; selection-color: #FFFFFF; padding: 4px; }}"
            )

        # 9. Font Size combo
        if hasattr(self, "combo_sub_size") and self.combo_sub_size:
            self.combo_sub_size.setStyleSheet(
                f"QComboBox {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 13px; padding: 0 12px 0 5px; "
                f"min-height: 26px; max-height: 26px; font-size: 11px; outline: none; }} "
                f"QComboBox:hover {{ border: 1px solid {'#484852' if is_dark else '#94A3B8'}; }} "
                f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 11px; border-left: none; }} "
                f"QComboBox::down-arrow {{ width: 0; height: 0; border-left: 2.5px solid transparent; border-right: 2.5px solid transparent; border-top: 3px solid {'#94A3B8' if is_dark else '#64748B'}; margin-right: 2px; }} "
                f"QComboBox QLineEdit {{ background: transparent; border: none; color: {inactive_color}; padding: 0; font-size: 11px; }} "
                f"QComboBox QAbstractItemView {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 8px; selection-background-color: {active_bg}; selection-color: #FFFFFF; padding: 4px; }}"
            )

        # 10. Subtitle Text Color Button Swatch
        if hasattr(self, "btn_sub_color") and self.btn_sub_color:
            cur_sub_hex = self._get_current_sub_color()
            swatch_sub = QPixmap(14, 14)
            swatch_sub.fill(Qt.GlobalColor.transparent)
            s_p = QPainter(swatch_sub)
            s_p.setRenderHint(QPainter.RenderHint.Antialiasing)
            s_p.setBrush(QBrush(QColor(cur_sub_hex)))
            s_p.setPen(QPen(QColor(255, 255, 255, 180) if is_dark else QColor(0, 0, 0, 80), 1.0))
            s_p.drawRoundedRect(QRectF(0.5, 0.5, 13, 13), 3.0, 3.0)
            s_p.end()
            self.btn_sub_color.setIcon(QIcon(swatch_sub))
            self.btn_sub_color.setStyleSheet(
                f"QPushButton {{ background-color: {inactive_bg}; color: {inactive_color}; border: 1px solid {inactive_border}; "
                f"border-radius: 13px; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0; outline: none; }} "
                f"QPushButton:hover {{ background-color: {inactive_hover}; }}"
            )

        # 11. Background Color Button Swatch
        if hasattr(self, "btn_bg_color") and self.btn_bg_color:
            cur_hex = self._get_current_bg_color()
            swatch_pix = QPixmap(14, 14)
            swatch_pix.fill(Qt.GlobalColor.transparent)
            sp = QPainter(swatch_pix)
            sp.setRenderHint(QPainter.RenderHint.Antialiasing)
            sp.setBrush(QBrush(QColor(cur_hex)))
            sp.setPen(QPen(QColor(255, 255, 255, 180) if is_dark else QColor(0, 0, 0, 80), 1.0))
            sp.drawRoundedRect(QRectF(0.5, 0.5, 13, 13), 3.0, 3.0)
            sp.end()
            self.btn_bg_color.setIcon(QIcon(swatch_pix))
            self.btn_bg_color.setStyleSheet(
                f"QPushButton {{ background-color: {inactive_bg}; color: {inactive_color}; border: 1px solid {inactive_border}; "
                f"border-radius: 13px; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0; outline: none; }} "
                f"QPushButton:hover {{ background-color: {inactive_hover}; }}"
            )

        # 11. Background Width Scale Combo (W)
        if hasattr(self, "combo_bg_w_size") and self.combo_bg_w_size:
            self.combo_bg_w_size.setStyleSheet(
                f"QComboBox {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 13px; padding: 0 12px 0 5px; "
                f"min-height: 26px; max-height: 26px; font-size: 11px; outline: none; }} "
                f"QComboBox:hover {{ border: 1px solid {'#484852' if is_dark else '#94A3B8'}; }} "
                f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 11px; border-left: none; }} "
                f"QComboBox::down-arrow {{ width: 0; height: 0; border-left: 2.5px solid transparent; border-right: 2.5px solid transparent; border-top: 3px solid {'#94A3B8' if is_dark else '#64748B'}; margin-right: 2px; }} "
                f"QComboBox QLineEdit {{ background: transparent; border: none; color: {inactive_color}; padding: 0; font-size: 11px; }} "
                f"QComboBox QAbstractItemView {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 8px; selection-background-color: {active_bg}; selection-color: #FFFFFF; padding: 4px; }}"
            )

        # 12. Background Height Scale Combo (H)
        if hasattr(self, "combo_bg_h_size") and self.combo_bg_h_size:
            self.combo_bg_h_size.setStyleSheet(
                f"QComboBox {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 13px; padding: 0 12px 0 5px; "
                f"min-height: 26px; max-height: 26px; font-size: 11px; outline: none; }} "
                f"QComboBox:hover {{ border: 1px solid {'#484852' if is_dark else '#94A3B8'}; }} "
                f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 11px; border-left: none; }} "
                f"QComboBox::down-arrow {{ width: 0; height: 0; border-left: 2.5px solid transparent; border-right: 2.5px solid transparent; border-top: 3px solid {'#94A3B8' if is_dark else '#64748B'}; margin-right: 2px; }} "
                f"QComboBox QLineEdit {{ background: transparent; border: none; color: {inactive_color}; padding: 0; font-size: 11px; }} "
                f"QComboBox QAbstractItemView {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 8px; selection-background-color: {active_bg}; selection-color: #FFFFFF; padding: 4px; }}"
            )

        # 13. Background Opacity Combo (Op)
        if hasattr(self, "combo_bg_opacity") and self.combo_bg_opacity:
            self.combo_bg_opacity.setStyleSheet(
                f"QComboBox {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 13px; padding: 0 12px 0 5px; "
                f"min-height: 26px; max-height: 26px; font-size: 11px; outline: none; }} "
                f"QComboBox:hover {{ border: 1px solid {'#484852' if is_dark else '#94A3B8'}; }} "
                f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 11px; border-left: none; }} "
                f"QComboBox::down-arrow {{ width: 0; height: 0; border-left: 2.5px solid transparent; border-right: 2.5px solid transparent; border-top: 3px solid {'#94A3B8' if is_dark else '#64748B'}; margin-right: 2px; }} "
                f"QComboBox QLineEdit {{ background: transparent; border: none; color: {inactive_color}; padding: 0; font-size: 11px; }} "
                f"QComboBox QAbstractItemView {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 8px; selection-background-color: {active_bg}; selection-color: #FFFFFF; padding: 4px; }}"
            )


        # Aspect Ratio combo
        if hasattr(self, "combo_aspect_ratio") and self.combo_aspect_ratio:
            self.combo_aspect_ratio.setStyleSheet(
                f"QComboBox {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 13px; padding: 0 14px 0 7px; "
                f"min-height: 26px; max-height: 26px; font-size: 11px; outline: none; }} "
                f"QComboBox:hover {{ border: 1px solid {'#484852' if is_dark else '#94A3B8'}; }} "
                f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 13px; border-left: none; }} "
                f"QComboBox::down-arrow {{ width: 0; height: 0; border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 3.5px solid {'#94A3B8' if is_dark else '#64748B'}; margin-right: 3px; }} "
                f"QComboBox QAbstractItemView {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 8px; selection-background-color: {active_bg}; selection-color: #FFFFFF; padding: 4px; }}"
            )

        # Subtitle Mode combo
        if hasattr(self, "combo_subtitle_mode") and self.combo_subtitle_mode:
            self.combo_subtitle_mode.setStyleSheet(
                f"QComboBox {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 13px; padding: 0 14px 0 7px; "
                f"min-height: 26px; max-height: 26px; font-size: 11px; outline: none; }} "
                f"QComboBox:hover {{ border: 1px solid {'#484852' if is_dark else '#94A3B8'}; }} "
                f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 13px; border-left: none; }} "
                f"QComboBox::down-arrow {{ width: 0; height: 0; border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 3.5px solid {'#94A3B8' if is_dark else '#64748B'}; margin-right: 3px; }} "
                f"QComboBox QAbstractItemView {{ background-color: {inactive_bg if is_dark else '#FFFFFF'}; color: {inactive_color}; "
                f"border: 1px solid {inactive_border}; border-radius: 8px; selection-background-color: {active_bg}; selection-color: #FFFFFF; padding: 4px; }}"
            )

    def _apply_theme_styles(self) -> None:
        is_dark = get_theme() == "dark"

        # 0. Update top studio toolbar
        self._update_toolbar_button_styles()

        # 1. Dialogue Table styling
        if hasattr(self, "dialogue_table"):
            if is_dark:
                self.dialogue_table.setStyleSheet(
                    "QTableWidget { background-color: #1A1A1C; border: 1px solid #2C2C2E; "
                    "border-radius: 8px; font-weight: 400; font-size: 13px; color: #F2F2F2; gridline-color: transparent; } "
                    "QTableWidget::item { padding: 6px 8px; border-bottom: 1px solid #28282B; color: #F2F2F2; } "
                    "QTableWidget::item:selected { background-color: rgba(79, 160, 255, 0.2); color: #4FA0FF; border: none; } "
                    "QHeaderView::section { background-color: #242426; border: none; "
                    "border-bottom: 1px solid #2C2C2E; padding: 6px; font-size: 11px; font-weight: 400; color: #A0A0A5; }"
                )
            else:
                self.dialogue_table.setStyleSheet(
                    "QTableWidget { background-color: #FFFFFF; border: 1px solid #E5E7EB; "
                    "border-radius: 8px; font-weight: 400; font-size: 13px; color: #1F2937; gridline-color: transparent; } "
                    "QTableWidget::item { padding: 6px 8px; border-bottom: 1px solid #F3F4F6; color: #1F2937; } "
                    "QTableWidget::item:selected { background-color: rgba(18, 89, 195, 0.12); color: #1259C3; border: none; } "
                    "QHeaderView::section { background-color: #F9FAFB; border: none; "
                    "border-bottom: 1px solid #E5E7EB; padding: 6px; font-size: 11px; font-weight: 400; color: #6B7280; }"
                )

        # 2. Timeline Visualizer Frame & Widget
        if hasattr(self, "timeline_widget") and self.timeline_widget:
            self.timeline_widget.set_theme_is_dark(is_dark)
        elif hasattr(self, "timeline_visualizer") and self.timeline_visualizer:
            if is_dark:
                self.timeline_visualizer.setStyleSheet("background-color: #161618; border: 1px solid #2C2C2E; border-radius: 8px;")
            else:
                self.timeline_visualizer.setStyleSheet("background-color: #FAFAFA; border: 1px solid #E5E7EB; border-radius: 8px;")

        # 3. Live Subtitle Banner
        if hasattr(self, "live_sub_label"):
            if is_dark:
                self.live_sub_label.setStyleSheet(
                    "background-color: rgba(79, 160, 255, 0.15); border: 1px solid rgba(79, 160, 255, 0.3); "
                    "border-radius: 8px; padding: 6px 10px; font-size: 13px; font-weight: 400; color: #F2F2F2;"
                )
            else:
                self.live_sub_label.setStyleSheet(
                    "background-color: rgba(18, 89, 195, 0.12); border: 1px solid rgba(18, 89, 195, 0.25); "
                    "border-radius: 8px; padding: 6px 10px; font-size: 13px; font-weight: 400; color: #1C1C1E;"
                )

        # 4. Labels Color Hierarchy
        hdr_color = "#F2F2F2" if is_dark else "#374151"
        sec_color = "#A0A0A5" if is_dark else "#6B7280"
        time_cur = "#4FA0FF" if is_dark else "#4F46E5"
        status_color = "#34D399" if is_dark else "#059669"

        if hasattr(self, "lbl_sub_title"):
            self.lbl_sub_title.setStyleSheet(f"font-size: 14px; font-weight: 400; color: {hdr_color};")
        if hasattr(self, "lbl_tl_title"):
            self.lbl_tl_title.setStyleSheet(f"font-size: 13px; font-weight: 400; color: {hdr_color};")
        if hasattr(self, "lbl_zoom"):
            self.lbl_zoom.setStyleSheet(f"font-size: 12px; font-weight: 400; color: {sec_color};")
        if hasattr(self, "lbl_zoom_val"):
            self.lbl_zoom_val.setStyleSheet(f"font-size: 12px; font-weight: 400; color: {sec_color};")
        if hasattr(self, "lbl_t1"):
            self.lbl_t1.setStyleSheet(f"font-size: 11px; font-weight: 400; color: {sec_color}; min-width: 40px;")
        if hasattr(self, "lbl_a1"):
            self.lbl_a1.setStyleSheet(f"font-size: 11px; font-weight: 400; color: {sec_color}; min-width: 40px;")
        if hasattr(self, "lbl_cur_time"):
            self.lbl_cur_time.setStyleSheet(f"font-size: 12px; font-weight: 400; color: {time_cur};")
        if hasattr(self, "lbl_total_time"):
            self.lbl_total_time.setStyleSheet(f"font-size: 12px; font-weight: 400; color: {sec_color};")
        if hasattr(self, "lbl_system_status"):
            self.lbl_system_status.setStyleSheet(f"font-size: 11px; font-weight: 400; color: {status_color};")
        if hasattr(self, "lbl_project_info"):
            self.lbl_project_info.setStyleSheet(f"font-size: 11px; font-weight: 400; color: {sec_color};")
        if hasattr(self, "lbl_mem_usage"):
            self.lbl_mem_usage.setStyleSheet(f"font-size: 11px; font-weight: 400; color: {sec_color};")

        # 5. Video Viewport & Placeholder Frame
        if hasattr(self, "video_placeholder") and self.video_placeholder:
            if hasattr(self.video_placeholder, "_apply_drag_style"):
                self.video_placeholder._apply_drag_style()
            if is_dark:
                if hasattr(self, "lbl_plus_tile"):
                    self.lbl_plus_tile.setStyleSheet(
                        "background-color: rgba(99, 102, 241, 0.15); border-radius: 32px; border: 1px solid rgba(99, 102, 241, 0.3); outline: none;"
                    )
                    self.lbl_plus_tile.setPixmap(get_icon("film", color="#818CF8", size=32).pixmap(32, 32))
                if hasattr(self, "lbl_import_hint"):
                    self.lbl_import_hint.setStyleSheet("font-size: 15px; font-weight: 400; color: #F8FAFC; border: none; outline: none;")
                if hasattr(self, "lbl_import_subhint"):
                    self.lbl_import_subhint.setStyleSheet("font-size: 12px; font-weight: 400; color: #94A3B8; border: none; outline: none;")
                if hasattr(self, "btn_overlay_video"):
                    self.btn_overlay_video.setStyleSheet(
                        "QPushButton { background-color: #1259C3; color: #FFFFFF; border: none; border-radius: 18px; "
                        "padding: 0 24px; min-height: 36px; max-height: 36px; font-weight: 400; font-size: 13px; outline: none; } "
                        "QPushButton:hover { background-color: #0E469C; } "
                        "QPushButton:pressed { background-color: #0B377B; }"
                    )
                    self.btn_overlay_video.setIcon(get_icon("video", color="#FFFFFF", size=15))
                if hasattr(self, "btn_overlay_folder"):
                    self.btn_overlay_folder.setStyleSheet(
                        "QPushButton { background-color: #2C2C2E; color: #F2F2F2; border: 1px solid #3A3A3C; "
                        "outline: none; border-radius: 18px; padding: 0 20px; min-height: 36px; max-height: 36px; font-weight: 400; font-size: 13px; } "
                        "QPushButton:hover { background-color: #3A3A3C; } "
                        "QPushButton:pressed { background-color: #242426; }"
                    )
                    self.btn_overlay_folder.setIcon(get_icon("folder", color="#F2F2F2", size=15))
            else:
                if hasattr(self, "lbl_plus_tile"):
                    self.lbl_plus_tile.setStyleSheet(
                        "background-color: rgba(18, 89, 195, 0.08); border-radius: 32px; border: 1px solid rgba(18, 89, 195, 0.18); outline: none;"
                    )
                    self.lbl_plus_tile.setPixmap(get_icon("film", color="#1259C3", size=32).pixmap(32, 32))
                if hasattr(self, "lbl_import_hint"):
                    self.lbl_import_hint.setStyleSheet("font-size: 15px; font-weight: 400; color: #1C1C1E; border: none; outline: none;")
                if hasattr(self, "lbl_import_subhint"):
                    self.lbl_import_subhint.setStyleSheet("font-size: 12px; font-weight: 400; color: #64748B; border: none; outline: none;")
                if hasattr(self, "btn_overlay_video"):
                    self.btn_overlay_video.setStyleSheet(
                        "QPushButton { background-color: #1259C3; color: #FFFFFF; border: none; border-radius: 18px; "
                        "padding: 0 24px; min-height: 36px; max-height: 36px; font-weight: 400; font-size: 13px; outline: none; } "
                        "QPushButton:hover { background-color: #0E469C; } "
                        "QPushButton:pressed { background-color: #0B377B; }"
                    )
                    self.btn_overlay_video.setIcon(get_icon("video", color="#FFFFFF", size=15))
                if hasattr(self, "btn_overlay_folder"):
                    self.btn_overlay_folder.setStyleSheet(
                        "QPushButton { background-color: #F2F2F7; color: #1C1C1E; border: 1px solid #E5E5EA; "
                        "outline: none; border-radius: 18px; padding: 0 20px; min-height: 36px; max-height: 36px; font-weight: 400; font-size: 13px; } "
                        "QPushButton:hover { background-color: #E5E5EA; border-color: #D1D1D6; } "
                        "QPushButton:pressed { background-color: #D1D1D6; }"
                    )
                    self.btn_overlay_folder.setIcon(get_icon("folder", color="#1C1C1E", size=15))

        # 6. Secondary Action Buttons (Voice Sample & Export SRT)
        if hasattr(self, "btn_preview_upload"):
            if is_dark:
                self.btn_preview_upload.setStyleSheet(
                    "QPushButton { background-color: rgba(255, 255, 255, 0.08); color: #F8FAFC; border: 1px solid rgba(255, 255, 255, 0.15); "
                    "outline: none; border-radius: 14px; padding: 0 12px; min-height: 28px; max-height: 28px; font-weight: 400; font-size: 11.5px; } "
                    "QPushButton:hover { background-color: rgba(255, 255, 255, 0.14); border-color: rgba(255, 255, 255, 0.25); }"
                )
            else:
                self.btn_preview_upload.setStyleSheet(
                    "QPushButton { background-color: #F1F5F9; color: #1E293B; border: 1px solid #CBD5E1; "
                    "outline: none; border-radius: 14px; padding: 0 12px; min-height: 28px; max-height: 28px; font-weight: 400; font-size: 11.5px; } "
                    "QPushButton:hover { background-color: #E2E8F0; border-color: #94A3B8; }"
                )

        if hasattr(self, "btn_export_srt"):
            if is_dark:
                self.btn_export_srt.setStyleSheet(
                    "QPushButton { background-color: rgba(255, 255, 255, 0.08); color: #F8FAFC; border: 1px solid rgba(255, 255, 255, 0.15); "
                    "outline: none; border-radius: 14px; padding: 0 12px; min-height: 28px; max-height: 28px; font-weight: 400; font-size: 11.5px; } "
                    "QPushButton:hover { background-color: rgba(255, 255, 255, 0.14); border-color: rgba(255, 255, 255, 0.25); }"
                )
            else:
                self.btn_export_srt.setStyleSheet(
                    "QPushButton { background-color: #F1F5F9; color: #1E293B; border: 1px solid #CBD5E1; "
                    "outline: none; border-radius: 14px; padding: 0 12px; min-height: 28px; max-height: 28px; font-weight: 400; font-size: 11.5px; } "
                    "QPushButton:hover { background-color: #E2E8F0; border-color: #94A3B8; }"
                )

        if hasattr(self, "btn_retranscribe"):
            self.btn_retranscribe.setStyleSheet(
                "background-color: #059669; color: #FFFFFF; font-size: 11.5px; font-weight: 400; "
                "border-radius: 14px; padding: 0 12px; min-height: 28px; max-height: 28px;"
            )
        if hasattr(self, "btn_generate_audio") and self.btn_generate_audio:
            self.btn_generate_audio.setStyleSheet(
                "background-color: #7C3AED; color: #FFFFFF; font-size: 11.5px; font-weight: 400; "
                "border-radius: 14px; padding: 0 12px; min-height: 28px; max-height: 28px; outline: none; border: none;"
            )
        if hasattr(self, "btn_final_render"):
            self.btn_final_render.setStyleSheet(
                "background-color: #1259C3; color: #FFFFFF; font-size: 11.5px; font-weight: 400; "
                "border-radius: 14px; padding: 0 14px; min-height: 28px; max-height: 28px;"
            )

        if hasattr(self, "ruler_labels"):
            ruler_color = "#8E8E93" if is_dark else "#9CA3AF"
            for lbl in self.ruler_labels:
                lbl.setStyleSheet(f"font-size: 10px; font-weight: 400; color: {ruler_color};")

    def update_theme_icons(self) -> None:
        self._apply_theme_styles()
        if hasattr(self, "btn_back"):
            self.btn_back.setIcon(get_icon("arrow-left", size=20))
        if hasattr(self, "header_icon"):
            self.header_icon.setPixmap(get_icon("film", size=22).pixmap(22, 22))
        self.btn_browse.setIcon(get_icon("file-video", size=16))
        if hasattr(self, "btn_browse_folder"):
            self.btn_browse_folder.setIcon(get_icon("folder", size=16))
        self.btn_start.setIcon(get_icon("film", color="#FFFFFF", size=18))
        self.btn_open_folder.setIcon(get_icon("folder", size=16))
        if hasattr(self, "btn_dub_another"):
            self.btn_dub_another.setIcon(get_icon("film", color="#FFFFFF", size=16))
        if hasattr(self, "btn_retranscribe"):
            self.btn_retranscribe.setIcon(get_icon("rotate-cw", color="#FFFFFF", size=13))
        if hasattr(self, "btn_generate_audio"):
            self.btn_generate_audio.setIcon(get_icon("user", color="#FFFFFF", size=13))
        if hasattr(self, "btn_final_render"):
            self.btn_final_render.setIcon(get_icon("film", color="#FFFFFF", size=13))
        if hasattr(self, "btn_export_srt"):
            self.btn_export_srt.setIcon(get_icon("download", size=13))
        if hasattr(self, "btn_preview_upload"):
            self.btn_preview_upload.setIcon(get_icon("mic", size=13))
        if hasattr(self, "lbl_sub_icon"):
            self.lbl_sub_icon.setPixmap(get_icon("file-video", size=16).pixmap(16, 16))
        if hasattr(self, "lbl_video_icon"):
            self.lbl_video_icon.setPixmap(get_icon("video", size=16).pixmap(16, 16))
        if hasattr(self, "lbl_vol_icon"):
            self.lbl_vol_icon.setPixmap(get_icon("status_done", size=14).pixmap(14, 14))
        if hasattr(self, "btn_preview_back"):
            self.btn_preview_back.setIcon(get_icon("arrow-left", size=16))
        if hasattr(self, "btn_overlay_video"):
            self.btn_overlay_video.setIcon(get_icon("file-video", color="#FFFFFF", size=15))
        if hasattr(self, "btn_overlay_folder"):
            folder_icon_color = "#1E293B" if get_theme() != "dark" else "#F8FAFC"
            self.btn_overlay_folder.setIcon(get_icon("folder", color=folder_icon_color, size=15))
        if hasattr(self, "btn_play_pause") and self.media_player:
            is_playing = (
                self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            )
            self.btn_play_pause.setIcon(get_icon("pause" if is_playing else "play", size=16))

    def retranslate_ui(self) -> None:
        self.title_label.setText(tr("dubbing_tool_title"))
        if hasattr(self, "file_label"):
            self.file_label.setText(tr("select_video_dubbing"))
        self.btn_browse.setText(tr("browse"))
        if hasattr(self, "btn_browse_folder"):
            self.btn_browse_folder.setText(tr("browse_folder"))
        if hasattr(self, "srt_label"):
            self.srt_label.setText(tr("select_srt_dubbing"))
        if hasattr(self, "srt_input"):
            self.srt_input.setPlaceholderText(tr("choose_srt_file"))
        if hasattr(self, "btn_browse_srt"):
            if hasattr(self, "srt_input") and not self.srt_input.text().strip():
                self.btn_browse_srt.setText("+ SRT")
        if hasattr(self, "btn_clear_srt"):
            self.btn_clear_srt.setText(tr("clear"))
            self.btn_clear_srt.setToolTip(tr("clear_srt_tooltip"))
        if hasattr(self, "combo_voice"):
            self.combo_voice.setItemText(0, tr("voice_male_piseth"))
            self.combo_voice.setItemText(1, tr("voice_female_sreymom"))
        if hasattr(self, "btn_play_sample"):
            self.btn_play_sample.setText(tr("listen_sample"))
        if hasattr(self, "btn_upload_sample"):
            self.btn_upload_sample.setText(tr("upload_sample"))
        if hasattr(self, "mode_label"):
            self.mode_label.setText(tr("voice_mode"))
        self.btn_mode_ducking.setText(tr("mode_ducking"))
        self.btn_mode_replace.setText(tr("mode_replace"))
        if hasattr(self, "chk_burn_subtitles"):
            self.chk_burn_subtitles.setText(tr("burn_khmer_subtitles"))
        if hasattr(self, "chk_blur_subtitles"):
            self.chk_blur_subtitles.setText(tr("black_background"))
        self.btn_start.setText(tr("start_dubbing"))
        if hasattr(self, "btn_dub_another"):
            self.btn_dub_another.setText(tr("dub_another"))
        if hasattr(self, "lbl_preview_title"):
            self.lbl_preview_title.setText(tr("preview_studio_title"))
        if hasattr(self, "btn_generate_audio") and self.btn_generate_audio:
            self.btn_generate_audio.setText(tr("generate_audio"))
        if hasattr(self, "btn_final_render"):
            self.btn_final_render.setText(tr("final_render"))
        if hasattr(self, "dialogue_search") and self.dialogue_search:
            self.dialogue_search.setPlaceholderText(tr("search_dialogue"))
        if hasattr(self, "btn_export_srt"):
            self.btn_export_srt.setText(tr("export_srt"))
        if hasattr(self, "btn_preview_back"):
            self.btn_preview_back.setText(tr("back_to_setup"))
        if hasattr(self, "dialogue_table"):
            self.dialogue_table.setHorizontalHeaderLabels([
                "☑",
                "START",
                "END",
                "KHMER TEXT (EDITABLE)",
                "VOICE PROFILE",
                "AUDIO STATUS",
            ])
        self._update_toolbar_button_styles()

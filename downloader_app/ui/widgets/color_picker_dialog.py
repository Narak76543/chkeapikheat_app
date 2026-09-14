"""
Subtitle Color Picker Dialog Module
Modern One UI 9 styled color picker with curated palette presets,
instant preview, hex code editor, and smooth RGB channel sliders.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from downloader_app.core.config import get_theme
from downloader_app.ui.resources.icon_helper import get_icon


class PresetSwatchButton(QPushButton):
    """Circular/Rounded color preset swatch with hover and active ring."""

    def __init__(self, hex_color: str, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hex_color = hex_color.upper()
        self.name = name
        self.setFixedSize(36, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{name} ({self.hex_color})")
        self._is_selected = False
        self._update_appearance()

    def set_selected(self, selected: bool) -> None:
        self._is_selected = selected
        self._update_appearance()

    def _update_appearance(self) -> None:
        is_dark = get_theme() == "dark"

        border_col = "#3B82F6" if self._is_selected else ("#475569" if is_dark else "#CBD5E1")
        border_width = "2.5px" if self._is_selected else "1px"

        self.setStyleSheet(
            f"QPushButton {{ "
            f"  background-color: {self.hex_color}; "
            f"  border: {border_width} solid {border_col}; "
            f"  border-radius: 18px; "
            f"  outline: none; "
            f"}} "
            f"QPushButton:hover {{ "
            f"  border: 2px solid #60A5FA; "
            f"}}"
        )


class SubtitleColorPickerDialog(QDialog):
    """Modern One UI 9 Subtitle Color Picker with Presets, Hex Input, and RGB Sliders."""

    color_selected = pyqtSignal(str)

    PRESETS = [
        ("#000000", "Solid Black"),
        ("#121214", "Slate Charcoal"),
        ("#0A0F1D", "Midnight Navy"),
        ("#1E293B", "Dark Slate Blue"),
        ("#1C130D", "Warm Espresso"),
        ("#1E0F14", "Deep Burgundy"),
        ("#0A1A12", "Forest Pine"),
        ("#2A2A2E", "Graphite Grey"),
        ("#475569", "Cool Slate"),
        ("#FFFFFF", "Pure White"),
    ]

    def __init__(self, initial_color: str = "#000000", current_color: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        chosen_color = current_color if current_color is not None else initial_color
        self._initial_color = chosen_color.upper() if QColor.isValidColor(chosen_color) else "#000000"
        self._current_color = self._initial_color
        self._preset_buttons: list[PresetSwatchButton] = []

        self._init_ui()
        self.hex_input = self.input_hex
        self._apply_theme()
        self._set_color(self._current_color, update_sliders=True, update_hex=True)

    def _init_ui(self) -> None:
        self.setFixedSize(380, 460)

        main_vbox = QVBoxLayout(self)
        main_vbox.setContentsMargins(12, 12, 12, 12)

        # Container Card
        self.card = QFrame(self)
        self.card.setObjectName("colorPickerCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(14)
        main_vbox.addWidget(self.card)

        # 1. Header: Icon, Title, and Close '✕' Button
        header = QHBoxLayout()
        header.setSpacing(8)

        self.lbl_title_icon = QLabel()
        self.lbl_title_icon.setFixedSize(20, 20)
        header.addWidget(self.lbl_title_icon)

        self.lbl_title = QLabel("Subtitle Background Color")
        self.lbl_title.setStyleSheet("font-size: 14px; font-weight: 500;")
        header.addWidget(self.lbl_title, 1)

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(26, 26)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.reject)
        header.addWidget(self.btn_close)

        card_layout.addLayout(header)

        # 2. Dual Color Comparison Banner
        preview_box = QFrame()
        preview_box.setObjectName("previewBox")
        preview_layout = QHBoxLayout(preview_box)
        preview_layout.setContentsMargins(12, 10, 12, 10)
        preview_layout.setSpacing(16)

        # Previous Color Box
        prev_col_layout = QVBoxLayout()
        prev_col_layout.setSpacing(4)
        prev_col_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_prev_tag = QLabel("PREVIOUS")
        self.lbl_prev_tag.setStyleSheet("font-size: 9.5px; font-weight: 500; letter-spacing: 0.5px;")
        prev_col_layout.addWidget(self.lbl_prev_tag, 0, Qt.AlignmentFlag.AlignCenter)

        self.prev_swatch = QFrame()
        self.prev_swatch.setFixedSize(64, 32)
        self.prev_swatch.setStyleSheet(
            f"background-color: {self._initial_color}; border-radius: 8px; border: 1px solid rgba(255,255,255,0.2);"
        )
        prev_col_layout.addWidget(self.prev_swatch, 0, Qt.AlignmentFlag.AlignCenter)
        preview_layout.addLayout(prev_col_layout)

        # Arrow indicator
        lbl_arrow = QLabel("→")
        lbl_arrow.setStyleSheet("font-size: 16px; font-weight: 400; color: #94A3B8;")
        preview_layout.addWidget(lbl_arrow, 0, Qt.AlignmentFlag.AlignCenter)

        # New Color Box
        new_col_layout = QVBoxLayout()
        new_col_layout.setSpacing(4)
        new_col_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_new_tag = QLabel("NEW COLOR")
        self.lbl_new_tag.setStyleSheet("font-size: 9.5px; font-weight: 500; letter-spacing: 0.5px;")
        new_col_layout.addWidget(self.lbl_new_tag, 0, Qt.AlignmentFlag.AlignCenter)

        self.new_swatch = QFrame()
        self.new_swatch.setFixedSize(64, 32)
        self.new_swatch.setStyleSheet(
            f"background-color: {self._current_color}; border-radius: 8px; border: 1px solid rgba(255,255,255,0.2);"
        )
        new_col_layout.addWidget(self.new_swatch, 0, Qt.AlignmentFlag.AlignCenter)
        preview_layout.addLayout(new_col_layout)

        card_layout.addWidget(preview_box)

        # 3. Quick Preset Palette Grid
        lbl_presets = QLabel("Preset Palette")
        lbl_presets.setStyleSheet("font-size: 11.5px; font-weight: 500;")
        card_layout.addWidget(lbl_presets)

        preset_grid = QGridLayout()
        preset_grid.setSpacing(8)
        preset_grid.setContentsMargins(0, 0, 0, 0)

        for i, (hex_code, name) in enumerate(self.PRESETS):
            btn = PresetSwatchButton(hex_code, name, self)
            btn.clicked.connect(lambda checked, h=hex_code: self._on_swatch_clicked(h))
            self._preset_buttons.append(btn)
            row = i // 5
            col = i % 5
            preset_grid.addWidget(btn, row, col)

        card_layout.addLayout(preset_grid)

        # 4. Hex Input Field
        hex_row = QHBoxLayout()
        hex_row.setSpacing(10)

        lbl_hex = QLabel("Hex Color:")
        lbl_hex.setStyleSheet("font-size: 12px; font-weight: 400;")
        hex_row.addWidget(lbl_hex)

        self.input_hex = QLineEdit()
        self.input_hex.setPlaceholderText("#000000")
        self.input_hex.setMaxLength(7)
        self.input_hex.textChanged.connect(self._on_hex_text_changed)
        hex_row.addWidget(self.input_hex, 1)

        card_layout.addLayout(hex_row)

        # 5. RGB Sliders
        sliders_box = QVBoxLayout()
        sliders_box.setSpacing(6)

        # Red Channel
        r_layout = QHBoxLayout()
        self.lbl_r = QLabel("R")
        self.lbl_r.setFixedWidth(16)
        self.lbl_r.setStyleSheet("font-size: 11px; font-weight: 500; color: #EF4444;")
        r_layout.addWidget(self.lbl_r)

        self.slider_r = QSlider(Qt.Orientation.Horizontal)
        self.slider_r.setRange(0, 255)
        self.slider_r.valueChanged.connect(self._on_rgb_slider_changed)
        r_layout.addWidget(self.slider_r, 1)

        self.lbl_r_val = QLabel("0")
        self.lbl_r_val.setFixedWidth(28)
        self.lbl_r_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_r_val.setStyleSheet("font-size: 11px; font-weight: 400;")
        r_layout.addWidget(self.lbl_r_val)
        sliders_box.addLayout(r_layout)

        # Green Channel
        g_layout = QHBoxLayout()
        self.lbl_g = QLabel("G")
        self.lbl_g.setFixedWidth(16)
        self.lbl_g.setStyleSheet("font-size: 11px; font-weight: 500; color: #10B981;")
        g_layout.addWidget(self.lbl_g)

        self.slider_g = QSlider(Qt.Orientation.Horizontal)
        self.slider_g.setRange(0, 255)
        self.slider_g.valueChanged.connect(self._on_rgb_slider_changed)
        g_layout.addWidget(self.slider_g, 1)

        self.lbl_g_val = QLabel("0")
        self.lbl_g_val.setFixedWidth(28)
        self.lbl_g_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_g_val.setStyleSheet("font-size: 11px; font-weight: 400;")
        g_layout.addWidget(self.lbl_g_val)
        sliders_box.addLayout(g_layout)

        # Blue Channel
        b_layout = QHBoxLayout()
        self.lbl_b = QLabel("B")
        self.lbl_b.setFixedWidth(16)
        self.lbl_b.setStyleSheet("font-size: 11px; font-weight: 500; color: #3B82F6;")
        b_layout.addWidget(self.lbl_b)

        self.slider_b = QSlider(Qt.Orientation.Horizontal)
        self.slider_b.setRange(0, 255)
        self.slider_b.valueChanged.connect(self._on_rgb_slider_changed)
        b_layout.addWidget(self.slider_b, 1)

        self.lbl_b_val = QLabel("0")
        self.lbl_b_val.setFixedWidth(28)
        self.lbl_b_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_b_val.setStyleSheet("font-size: 11px; font-weight: 400;")
        b_layout.addWidget(self.lbl_b_val)
        sliders_box.addLayout(b_layout)

        card_layout.addLayout(sliders_box)

        # 6. Action Button Row: Cancel / Apply
        card_layout.addStretch(1)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel, 1)

        self.btn_apply = QPushButton("Apply Color")
        self.btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply.clicked.connect(self._on_apply_clicked)
        btn_row.addWidget(self.btn_apply, 1)

        card_layout.addLayout(btn_row)

    def _apply_theme(self) -> None:
        is_dark = get_theme() == "dark"

        bg_card = "#1C1C1E" if is_dark else "#FFFFFF"
        border_card = "#2E2E32" if is_dark else "#E2E8F0"
        txt_main = "#F8FAFC" if is_dark else "#0F172A"
        txt_sub = "#94A3B8" if is_dark else "#64748B"
        preview_bg = "#121214" if is_dark else "#F8FAFC"
        preview_border = "#2A2A2E" if is_dark else "#E2E8F0"

        input_bg = "#242428" if is_dark else "#F1F5F9"
        input_border = "#38383E" if is_dark else "#CBD5E1"

        btn_cancel_bg = "#242428" if is_dark else "#F1F5F9"
        btn_cancel_hov = "#2E2E34" if is_dark else "#E2E8F0"
        btn_cancel_txt = "#E2E8F0" if is_dark else "#1E293B"

        self.card.setStyleSheet(
            f"QFrame#colorPickerCard {{ "
            f"  background-color: {bg_card}; "
            f"  border: 1px solid {border_card}; "
            f"  border-radius: 16px; "
            f"}}"
        )

        self.lbl_title.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {txt_main};")
        self.lbl_prev_tag.setStyleSheet(f"font-size: 9.5px; font-weight: 500; color: {txt_sub}; letter-spacing: 0.5px;")
        self.lbl_new_tag.setStyleSheet(f"font-size: 9.5px; font-weight: 500; color: {txt_sub}; letter-spacing: 0.5px;")

        self.btn_close.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {txt_sub}; font-size: 14px; font-weight: 500; border-radius: 13px; }} "
            f"QPushButton:hover {{ background-color: {'rgba(255,255,255,0.08)' if is_dark else 'rgba(0,0,0,0.06)'}; color: {txt_main}; }}"
        )

        preview_box_widget = self.card.findChild(QFrame, "previewBox")
        if preview_box_widget:
            preview_box_widget.setStyleSheet(
                f"QFrame#previewBox {{ background-color: {preview_bg}; border: 1px solid {preview_border}; border-radius: 12px; }}"
            )

        self.input_hex.setStyleSheet(
            f"QLineEdit {{ background-color: {input_bg}; color: {txt_main}; border: 1px solid {input_border}; "
            f"border-radius: 8px; padding: 5px 10px; font-size: 13px; font-weight: 500; }} "
            f"QLineEdit:focus {{ border: 1px solid #3B82F6; }}"
        )

        slider_qss = (
            f"QSlider::groove:horizontal {{ height: 4px; background: {'#334155' if is_dark else '#E2E8F0'}; border-radius: 2px; }} "
            f"QSlider::sub-page:horizontal {{ background: #3B82F6; border-radius: 2px; }} "
            f"QSlider::handle:horizontal {{ background: #FFFFFF; border: 2px solid #3B82F6; width: 14px; margin: -5px 0; border-radius: 7px; }}"
        )
        self.slider_r.setStyleSheet(slider_qss)
        self.slider_g.setStyleSheet(slider_qss)
        self.slider_b.setStyleSheet(slider_qss)

        self.lbl_r_val.setStyleSheet(f"font-size: 11px; font-weight: 400; color: {txt_sub};")
        self.lbl_g_val.setStyleSheet(f"font-size: 11px; font-weight: 400; color: {txt_sub};")
        self.lbl_b_val.setStyleSheet(f"font-size: 11px; font-weight: 400; color: {txt_sub};")

        self.btn_cancel.setStyleSheet(
            f"QPushButton {{ background-color: {btn_cancel_bg}; color: {btn_cancel_txt}; border: 1px solid {input_border}; "
            f"border-radius: 14px; min-height: 30px; font-size: 12px; font-weight: 400; }} "
            f"QPushButton:hover {{ background-color: {btn_cancel_hov}; }}"
        )

        self.btn_apply.setStyleSheet(
            "QPushButton { background-color: #1259C3; color: #FFFFFF; border: none; "
            "border-radius: 14px; min-height: 30px; font-size: 12px; font-weight: 500; } "
            "QPushButton:hover { background-color: #0E469C; } "
            "QPushButton:pressed { background-color: #0B377B; }"
        )

        # Icon
        self.lbl_title_icon.setPixmap(get_icon("settings", color="#3B82F6" if is_dark else "#1259C3", size=16).pixmap(16, 16))

    def _on_swatch_clicked(self, hex_code: str) -> None:
        self._set_color(hex_code, update_sliders=True, update_hex=True)

    def _set_color(self, hex_code: str, update_sliders: bool = False, update_hex: bool = False) -> None:
        if not QColor.isValidColor(hex_code):
            return

        c = QColor(hex_code)
        clean_hex = c.name(QColor.NameFormat.HexRgb).upper()
        self._current_color = clean_hex

        # Update swatch
        self.new_swatch.setStyleSheet(
            f"background-color: {self._current_color}; border-radius: 8px; border: 1.5px solid rgba(255,255,255,0.3);"
        )

        # Update presets selected state
        for btn in self._preset_buttons:
            btn.set_selected(btn.hex_color == clean_hex)

        # Update hex input
        if update_hex:
            self.input_hex.blockSignals(True)
            self.input_hex.setText(clean_hex)
            self.input_hex.blockSignals(False)

        # Update RGB sliders
        if update_sliders:
            self.slider_r.blockSignals(True)
            self.slider_g.blockSignals(True)
            self.slider_b.blockSignals(True)
            self.slider_r.setValue(c.red())
            self.slider_g.setValue(c.green())
            self.slider_b.setValue(c.blue())
            self.lbl_r_val.setText(str(c.red()))
            self.lbl_g_val.setText(str(c.green()))
            self.lbl_b_val.setText(str(c.blue()))
            self.slider_r.blockSignals(False)
            self.slider_g.blockSignals(False)
            self.slider_b.blockSignals(False)

    def _on_hex_text_changed(self, text: str) -> None:
        raw = text.strip()
        if not raw.startswith("#"):
            raw = f"#{raw}"
        if len(raw) == 7 and QColor.isValidColor(raw):
            self._set_color(raw, update_sliders=True, update_hex=False)

    def _on_rgb_slider_changed(self) -> None:
        r = self.slider_r.value()
        g = self.slider_g.value()
        b = self.slider_b.value()

        self.lbl_r_val.setText(str(r))
        self.lbl_g_val.setText(str(g))
        self.lbl_b_val.setText(str(b))

        c = QColor(r, g, b)
        self._set_color(c.name(QColor.NameFormat.HexRgb).upper(), update_sliders=False, update_hex=True)

    def _on_apply_clicked(self) -> None:
        self.color_selected.emit(self._current_color)
        self.accept()

    def get_selected_color(self) -> str:
        return self._current_color

    @property
    def selected_color(self) -> str:
        return self._current_color

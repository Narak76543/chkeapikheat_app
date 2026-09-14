"""
Icon Helper Module
Loads Lucide SVG icons and renders them dynamically with theme-matching colors.
"""

from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from downloader_app.core.config import get_theme
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.icon_helper")
ICONS_DIR = Path(__file__).parent / "icons"


def _render_svg_pixmap(svg_file: Path, color_hex: str, size: int) -> QPixmap:
    with open(svg_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Replace stroke/currentColor/fill with the target color
    content = content.replace('stroke="currentColor"', f'stroke="{color_hex}"')
    content = content.replace('fill="currentColor"', f'fill="{color_hex}"')
    content = content.replace("currentColor", color_hex)

    # Handle icons with hardcoded dark strokes/fills when rendering light/white icons or dark theme
    if get_theme() == "dark" or color_hex.lower() in ("#ffffff", "#f5f5f7", "#f2f2f2", "#fff", "white"):
        content = content.replace('stroke="#1C1C1E"', f'stroke="{color_hex}"')
        content = content.replace('stroke="#1c1c1e"', f'stroke="{color_hex}"')
        content = content.replace('stroke="#000000"', f'stroke="{color_hex}"')
        content = content.replace('stroke="#000"', f'stroke="{color_hex}"')

    renderer = QSvgRenderer(QByteArray(content.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return pixmap


def get_icon(name: str, color: str | None = None, size: int = 24) -> QIcon:
    """
    Loads an SVG icon from the bundled Lucide icon directory.
    Optionally tints 'currentColor' with a specific hex or named color.
    If color is None, automatically adapts to the current theme and button states:
    - Normal (Off): #F5F5F7 in Dark mode, #1C1C1E in Light mode
    - Checked (On): #FFFFFF (pure white on active accent backgrounds)
    """
    svg_file = ICONS_DIR / f"{name}.svg"
    if not svg_file.exists():
        logger.warning(f"Icon not found: {svg_file}")
        return QIcon()

    if color is None:
        normal_color = "#F5F5F7" if get_theme() == "dark" else "#1C1C1E"
        checked_color = "#FFFFFF"
    else:
        normal_color = color
        checked_color = color

    try:
        icon = QIcon()
        pix_off = _render_svg_pixmap(svg_file, normal_color, size)
        icon.addPixmap(pix_off, QIcon.Mode.Normal, QIcon.State.Off)
        icon.addPixmap(pix_off, QIcon.Mode.Active, QIcon.State.Off)

        pix_on = _render_svg_pixmap(svg_file, checked_color, size)
        icon.addPixmap(pix_on, QIcon.Mode.Normal, QIcon.State.On)
        icon.addPixmap(pix_on, QIcon.Mode.Active, QIcon.State.On)
        icon.addPixmap(pix_on, QIcon.Mode.Selected, QIcon.State.On)

        return icon
    except (OSError, RuntimeError, ValueError) as e:
        logger.error(f"Error loading icon {name}: {e}")
        return QIcon()


def get_empty_state_icon(size: int = 48) -> QIcon:
    """Returns a muted inbox icon suited for the empty-state container."""
    muted_color = "#A0A0A5" if get_theme() == "dark" else "#8E8E93"
    return get_icon("inbox", color=muted_color, size=size)

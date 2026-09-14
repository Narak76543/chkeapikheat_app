"""
Image Loader Utility Module
Asynchronously downloads, rounds, and caches movie poster thumbnails and pictures.
"""

import urllib.error
import urllib.request

from PyQt6.QtCore import QByteArray, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPainterPath, QPixmap

from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.image_loader")

_PIXMAP_CACHE: dict[str, QPixmap] = {}


def round_pixmap(pixmap: QPixmap, corner_radius: int = 12) -> QPixmap:
    """Renders a pixmap with rounded corners and antialiasing."""
    if pixmap.isNull() or corner_radius <= 0:
        return pixmap

    rounded = QPixmap(pixmap.size())
    rounded.fill(Qt.GlobalColor.transparent)

    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    path = QPainterPath()
    path.addRoundedRect(
        0.0,
        0.0,
        float(pixmap.width()),
        float(pixmap.height()),
        float(corner_radius),
        float(corner_radius),
    )
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()

    return rounded


def fetch_image_pixmap(
    url: str,
    target_size: QSize | None = None,
    corner_radius: int = 12,
    timeout: int = 8,
) -> QPixmap | None:
    """Synchronously fetches image bytes and returns a rounded QPixmap."""
    cache_key = f"{url}_{target_size}_{corner_radius}"
    if cache_key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[cache_key]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://hongguoduanju.com/",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()

        image = QImage()
        if not image.loadFromData(QByteArray(data)):
            logger.warning(f"Could not parse image data from {url}")
            return None

        pixmap = QPixmap.fromImage(image)
        if target_size:
            pixmap = pixmap.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            # Crop to exact dimensions
            x = max(0, (pixmap.width() - target_size.width()) // 2)
            y = max(0, (pixmap.height() - target_size.height()) // 2)
            pixmap = pixmap.copy(x, y, target_size.width(), target_size.height())

        if corner_radius > 0:
            pixmap = round_pixmap(pixmap, corner_radius)

        _PIXMAP_CACHE[cache_key] = pixmap
        return pixmap

    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.warning(f"Failed to fetch image from {url}: {e}")
        return None


class AsyncImageLoader(QThread):
    """Background worker that fetches and scales an image without blocking UI."""

    image_loaded = pyqtSignal(QPixmap)

    def __init__(
        self,
        url: str,
        target_size: QSize | None = None,
        corner_radius: int = 12,
        parent: QThread | None = None,
    ) -> None:
        super().__init__(parent)
        self.url = url
        self.target_size = target_size
        self.corner_radius = corner_radius

    def run(self) -> None:
        if not self.url:
            return
        pixmap = fetch_image_pixmap(self.url, self.target_size, self.corner_radius)
        if pixmap and not pixmap.isNull():
            self.image_loaded.emit(pixmap)

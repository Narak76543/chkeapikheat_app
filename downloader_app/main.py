"""
PyQt6 Download Manager Entry Point
Initializes application, loads Noto Sans & Noto Sans Khmer fonts with fallback,
applies active theme QSS and active i18n language.
"""

import sys
from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase, QIcon
from PyQt6.QtWidgets import QApplication

from downloader_app.core.config import get_language, get_theme
from downloader_app.ui.main_window import MainWindow
from downloader_app.utils.i18n import set_language
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.main")


def load_application_fonts(app: QApplication) -> None:
    """Loads bundled Noto Sans and Noto Sans Khmer fonts with fallback chain."""
    fonts_dir = Path(__file__).parent / "ui" / "resources" / "fonts"
    if fonts_dir.exists():
        for font_file in fonts_dir.glob("*.ttf"):
            font_id = QFontDatabase.addApplicationFont(str(font_file))
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                logger.debug(
                    f"Loaded font '{font_file.name}' with families: {families}"
                )
            else:
                logger.warning(f"Failed to load font '{font_file.name}'")

    # Ensure CJK glyph support on Windows
    win_fonts = Path(r"C:\Windows\Fonts")
    for win_font in ["msyh.ttc", "simsun.ttc"]:
        p = win_fonts / win_font
        if p.exists():
            QFontDatabase.addApplicationFont(str(p))
            break

    app_font = QFont()
    # Primary font: Google Sans (with Kantumruy Pro & Noto Sans Khmer for Khmer coverage)
    app_font.setFamilies([
        "Google Sans",
        "Kantumruy Pro",
        "Khmer OS Battambang",
        "Leelawadee UI",
        "Noto Sans Khmer",
        "Noto Sans",
        "Microsoft YaHei",
        "Segoe UI",
        "sans-serif",
    ])
    app_font.setPointSize(10)
    app_font.setWeight(QFont.Weight.Normal)
    app.setFont(app_font)


def load_theme(app: QApplication, theme_name: str) -> None:
    """Applies theme_light.qss or theme_dark.qss to the application with proper icon paths."""
    qss_filename = f"theme_{theme_name}.qss"
    qss_path = Path(__file__).parent / "ui" / "resources" / qss_filename
    if not qss_path.exists():
        # Fallback to style.qss if theme file does not exist yet
        qss_path = Path(__file__).parent / "ui" / "resources" / "style.qss"

    if qss_path.exists():
        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                content = f.read()
            icons_dir_posix = (Path(__file__).parent / "ui" / "resources" / "icons").as_posix()
            content = content.replace("{ICON_DIR}", icons_dir_posix)
            app.setStyleSheet(content)
            logger.info(f"Applied theme stylesheet: {qss_path.name}")
        except OSError as e:
            logger.warning(f"Could not load stylesheet: {e}")


def main() -> None:
    logger.info("Starting PyQt6 Download Manager (One UI 9)...")

    # Ensure Windows taskbar displays app-logo icon instead of default Python executable icon
    if sys.platform == "win32":
        try:
            import ctypes
            myappid = "org.antigravity.chkeapikheat.app"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception as e:
            logger.warning(f"Could not set AppUserModelID: {e}")

    app = QApplication(sys.argv)
    app.setApplicationName("PyQt6 Download Manager")

    # 1. Setup typography & font fallback
    load_application_fonts(app)

    # 2. Setup active language
    active_lang = get_language()
    set_language(active_lang)

    # 3. Apply active theme
    active_theme = get_theme()
    load_theme(app, active_theme)

    # 4. Set application icon
    logo_candidates = [
        Path(__file__).parent / "ui" / "resources" / "app-logo.png",
        Path(__file__).parent / "resources" / "app-logo.png",
        Path(__file__).parent.parent / "app-logo.png",
    ]
    for cand in logo_candidates:
        if cand.exists():
            app.setWindowIcon(QIcon(str(cand.resolve())))
            break

    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

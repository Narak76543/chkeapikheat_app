"""
Application Logger Configuration
Sets up console (INFO) and rotating file (DEBUG) logging handlers.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path.home() / ".pyqt6_downloader"
LOG_FILE = LOG_DIR / "downloader.log"


class SafeRotatingFileHandler(RotatingFileHandler):
    """Subclass of RotatingFileHandler that gracefully handles Windows file lock (WinError 32) during rollover."""

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except (PermissionError, OSError):
            pass


def setup_logger(name: str = "downloader") -> logging.Logger:
    """
    Initializes and returns a configured logger with console and rotating file output.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (INFO level)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Rotating file handler (DEBUG level)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = SafeRotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=3,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as e:
        logger.warning(f"Could not initialize rotating file logger: {e}")

    return logger

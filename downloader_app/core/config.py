"""
Application Configuration
Wraps QSettings with typed getters/setters for persistent settings across platforms.
"""

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QSettings

ORG_NAME = "YourOrgName"
APP_NAME = "PyQt6DownloadManager"

import os

DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Downloads")
DEFAULT_MAX_CONCURRENT = 3
DEFAULT_THEME = "light"
DEFAULT_LANGUAGE = "km"
DEFAULT_GEMINI_KEY = ""


def _get_settings() -> QSettings:
    return QSettings(ORG_NAME, APP_NAME)


def get_gemini_api_key() -> str:
    """Returns the persisted Gemini API key from QSettings, os.environ, or .env file."""
    val = str(_get_settings().value("gemini_api_key", "")).strip()
    if val and val != "your-gemini-api-key-here":
        return val

    env_val = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_val and env_val != "your-gemini-api-key-here":
        return env_val

    # Check for .env file in CWD or parent paths
    cwd = Path.cwd()
    env_paths = [
        cwd / ".env",
        cwd.parent / ".env",
        Path(__file__).parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",
    ]
    for ep in env_paths:
        if ep.exists():
            try:
                with open(ep, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("GEMINI_API_KEY="):
                            parts = line.split("=", 1)
                            if len(parts) == 2:
                                v = parts[1].strip().strip('"').strip("'")
                                if v and v != "your-gemini-api-key-here":
                                    return v
            except OSError:
                pass
    return ""


def set_gemini_api_key(key: str) -> None:
    """Persists the Gemini API key to QSettings, os.environ, and updates .env file."""
    clean_key = str(key).strip()
    _get_settings().setValue("gemini_api_key", clean_key)
    os.environ["GEMINI_API_KEY"] = clean_key

    # Also sync into .env if present or create in project root
    cwd = Path.cwd()
    env_paths = [cwd / ".env", cwd.parent / ".env"]
    target_env = None
    for ep in env_paths:
        if ep.exists():
            target_env = ep
            break
    if not target_env:
        target_env = cwd / ".env"

    try:
        lines = []
        replaced = False
        if target_env.exists():
            with open(target_env, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("GEMINI_API_KEY="):
                        lines.append(f'GEMINI_API_KEY="{clean_key}"\n')
                        replaced = True
                    else:
                        lines.append(line)
        if not replaced:
            lines.append(f'GEMINI_API_KEY="{clean_key}"\n')
        with open(target_env, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError:
        pass


def get_theme() -> str:
    """Returns the persisted theme ('light' or 'dark')."""
    return str(_get_settings().value("theme", DEFAULT_THEME))


def set_theme(theme: str) -> None:
    """Persists the user's theme selection."""
    if theme in ["light", "dark"]:
        _get_settings().setValue("theme", theme)


def get_language() -> str:
    """Returns the persisted language ('en' or 'km')."""
    return str(_get_settings().value("language", DEFAULT_LANGUAGE))


def set_language(lang: str) -> None:
    """Persists the user's language selection."""
    if lang in ["en", "km"]:
        _get_settings().setValue("language", lang)


def get_download_folder() -> str:
    """Returns the persisted download directory."""
    return str(_get_settings().value("download_dir", DEFAULT_DOWNLOAD_DIR))


def set_download_folder(folder: str) -> None:
    """Persists the download directory."""
    _get_settings().setValue("download_dir", folder)


def get_max_concurrent() -> int:
    """Returns the persisted max concurrent downloads limit."""
    val = _get_settings().value("max_concurrent", DEFAULT_MAX_CONCURRENT)
    try:
        return int(val)
    except (ValueError, TypeError):
        return DEFAULT_MAX_CONCURRENT


def set_max_concurrent(count: int) -> None:
    """Persists max concurrent downloads limit."""
    _get_settings().setValue("max_concurrent", max(1, count))


@dataclass
class AppConfig:
    """
    Data class representing current runtime configuration.
    Synchronizes with QSettings for cross-platform persistence.
    """

    download_dir: str = DEFAULT_DOWNLOAD_DIR
    max_concurrent_downloads: int = DEFAULT_MAX_CONCURRENT
    theme: str = DEFAULT_THEME
    language: str = DEFAULT_LANGUAGE
    gemini_api_key: str = DEFAULT_GEMINI_KEY
    chunk_size_bytes: int = 512 * 1024
    timeout_seconds: int = 30
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    @classmethod
    def load(cls) -> "AppConfig":
        """Loads configuration from QSettings."""
        return cls(
            download_dir=get_download_folder(),
            max_concurrent_downloads=get_max_concurrent(),
            theme=get_theme(),
            language=get_language(),
            gemini_api_key=get_gemini_api_key(),
        )

    def save(self) -> None:
        """Saves current configuration to QSettings."""
        set_download_folder(self.download_dir)
        set_max_concurrent(self.max_concurrent_downloads)
        set_theme(self.theme)
        set_language(self.language)
        set_gemini_api_key(self.gemini_api_key)

"""
Internationalization (i18n) Module
Provides translation lookup with English fallback and reactive language change signals.
"""

import json
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.i18n")


class I18nManager(QObject):
    """Manages active language, loads translation JSON files, and emits change signals."""

    language_changed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._current_language: str = "en"
        self._translations: dict[str, dict[str, str]] = {}
        self._find_and_load_catalogs()

    def _find_and_load_catalogs(self) -> None:
        """Finds resources/i18n directory and loads en.json and km.json."""
        candidate_dirs = [
            Path(__file__).parent.parent / "resources" / "i18n",
            Path(__file__).parent.parent.parent / "resources" / "i18n",
            Path("resources/i18n"),
        ]
        i18n_dir: Path | None = None
        for cd in candidate_dirs:
            if cd.exists() and (cd / "en.json").exists():
                i18n_dir = cd
                break

        if not i18n_dir:
            logger.warning("Could not find i18n directory!")
            return

        for lang in ["en", "km"]:
            file_path = i18n_dir / f"{lang}.json"
            if file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self._translations[lang] = json.load(f)
                    logger.debug(
                        f"Loaded {len(self._translations[lang])} keys for '{lang}'"
                    )
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"Failed to load {file_path}: {e}")
                    self._translations[lang] = {}

    def get_language(self) -> str:
        return self._current_language

    def set_language(self, lang_code: str) -> None:
        if lang_code not in ["en", "km"]:
            lang_code = "en"
        if self._current_language != lang_code:
            self._current_language = lang_code
            logger.info(f"Language switched to '{lang_code}'")
            self.language_changed.emit(lang_code)

    def translate(self, key: str) -> str:
        """Translates a key, falling back to English, then returning the raw key if missing."""
        current_map = self._translations.get(self._current_language, {})
        if key in current_map:
            return current_map[key]

        # Fallback to English
        en_map = self._translations.get("en", {})
        if key in en_map:
            return en_map[key]

        return key


# Global singleton instance
_instance: I18nManager | None = None


def get_i18n_manager() -> I18nManager:
    """Returns the singleton instance to connect to language_changed signal."""
    global _instance
    if _instance is None:
        _instance = I18nManager()
    else:
        try:
            _ = _instance.objectName()
        except RuntimeError:
            _instance = I18nManager()
    return _instance


def tr(key: str) -> str:
    """Convenient global translation helper."""
    return get_i18n_manager().translate(key)


def set_language(lang_code: str) -> None:
    """Sets active language and notifies listeners."""
    get_i18n_manager().set_language(lang_code)


def get_current_language() -> str:
    """Returns the current active language code."""
    return get_i18n_manager().get_language()

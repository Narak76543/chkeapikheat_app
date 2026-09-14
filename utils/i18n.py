"""
Re-export i18n functions from downloader_app.utils.i18n
"""

from downloader_app.utils.i18n import (
    get_current_language,
    get_i18n_manager,
    set_language,
    tr,
)

__all__ = ["tr", "set_language", "get_current_language", "get_i18n_manager"]

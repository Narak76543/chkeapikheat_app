"""
Pytest configuration for PyQt6 Download Manager tests.
Ensures a GUI-capable offscreen QApplication is available for all tests.
"""

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication supporting both QObjects and QWidgets offscreen."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(["", "-platform", "offscreen"])
    return app

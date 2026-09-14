"""
Unit tests for SidebarPanel and embedded views.
Verifies panel toggling, views switching (Settings, Split, Movie), and theme/language signals.
"""

from unittest.mock import MagicMock, patch

from downloader_app.ui.widgets.sidebar_panel import SidebarPanel


def test_sidebar_panel_views_switching(qapp):
    sidebar = SidebarPanel()

    # 1. Open Settings
    sidebar.open_settings()
    assert sidebar.isVisible()
    assert sidebar.stack.currentIndex() == 0

    # 2. Open Video Splitter
    sidebar.open_video_splitter("test_video.mp4")
    assert sidebar.isVisible()
    assert sidebar.stack.currentIndex() == 1
    assert sidebar.split_view.edit_video_path.text() == "test_video.mp4"

    # 3. Open Movie Details
    sample_movie = {
        "title": "侧边栏电影",
        "total_episodes": 45,
        "estimated_duration_mins": 90,
    }
    with patch("downloader_app.ui.widgets.sidebar_panel.AsyncImageLoader"):
        sidebar.open_movie_details(sample_movie)
        assert sidebar.isVisible()
        assert sidebar.stack.currentIndex() == 2
        assert sidebar.movie_view.lbl_title.text() == "侧边栏电影"

    # 4. Close
    sidebar.close_sidebar()
    assert not sidebar.isVisible()


def test_sidebar_panel_signals(qapp):
    sidebar = SidebarPanel()

    theme_spy = MagicMock()
    lang_spy = MagicMock()
    full_movie_spy = MagicMock()

    sidebar.theme_changed.connect(theme_spy)
    sidebar.language_changed.connect(lang_spy)
    sidebar.download_full_movie_selected.connect(full_movie_spy)

    # Trigger theme change
    sidebar.settings_view.theme_changed.emit("dark")
    theme_spy.assert_called_once_with("dark")

    # Trigger language change
    sidebar.settings_view.language_changed.emit("km")
    lang_spy.assert_called_once_with("km")

    # Trigger movie download from view
    sample = {"title": "Test Movie"}
    sidebar.movie_view.movie_data = sample
    sidebar.movie_view.btn_full_movie.click()
    expected_sample = {"title": "Test Movie", "quality": "1080p"}
    full_movie_spy.assert_called_once_with(expected_sample)

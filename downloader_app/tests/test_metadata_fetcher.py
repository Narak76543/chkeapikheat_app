"""
Unit tests for MovieMetadataFetcherWorker.
Tests metadata extraction (title, poster URL, duration, episodes, synopsis) from queries.
"""

from unittest.mock import patch

from downloader_app.core.metadata_fetcher import MovieMetadataFetcherWorker


def test_metadata_fetcher_with_mocked_search(qapp):
    """Tests successful movie metadata extraction and duration estimation."""
    mock_drama = {
        "series_id": "7680883072278989849",
        "title": "糯糯下山，师兄们都慌了第二季",
        "cover_url": "https://example.com/poster.jpg",
        "total_episodes": 93,
        "intro": "Sample storyline intro.",
        "tags": ["萌宝", "异界"],
    }

    with (
        patch(
            "downloader_app.core.metadata_fetcher.search_dramas_by_title",
            return_value=[mock_drama],
        ),
        patch(
            "downloader_app.core.metadata_fetcher.get_drama_details",
            return_value=mock_drama,
        ),
    ):
        worker = MovieMetadataFetcherWorker("糯糯下山，师兄们都慌了第二季")
        results = []
        errors = []
        worker.metadata_ready.connect(lambda d: results.append(d))
        worker.error.connect(lambda e: errors.append(e))

        worker.start()
        worker.wait(5000)
        qapp.processEvents()

        assert len(errors) == 0
        assert len(results) == 1
        data = results[0]
        assert data["title"] == "糯糯下山，师兄们都慌了第二季"
        assert data["total_episodes"] == 93
        assert data["estimated_duration_mins"] == 186
        assert data["cover_url"] == "https://example.com/poster.jpg"
        assert "萌宝" in data["tags"]
        assert data["raw_url"] == "https://hongguoduanju.com/detail?series_id=7680883072278989849"


def test_metadata_fetcher_empty_query(qapp):
    """Tests error emission on empty query."""
    worker = MovieMetadataFetcherWorker("")
    errors = []
    worker.error.connect(lambda e: errors.append(e))

    worker.start()
    worker.wait(3000)
    qapp.processEvents()

    assert len(errors) == 1
    assert "empty" in errors[0].lower()


def test_rank_entries_anti_loop_filtering():
    """Tests that FullMovieResolverWorker._rank_entries avoids 4h-5h loop videos."""
    from downloader_app.core.metadata_fetcher import FullMovieResolverWorker

    entries = [
        {
            "title": "我的游戏好友全是大佬 全集 4小时循环播放",
            "duration": 280 * 60,  # 4.6 hours fake loop
            "id": "loop123",
        },
        {
            "title": "我的游戏好友全是大佬 完整版全集 5 hours loop",
            "duration": 310 * 60,  # 5.1 hours fake loop
            "id": "loop456",
        },
        {
            "title": "《我的游戏好友全是大佬》全集 完整版",
            "duration": 95 * 60,  # 1.5 hours real movie
            "id": "real789",
        },
    ]

    best = FullMovieResolverWorker._rank_entries(
        entries, query_title="我的游戏好友全是大佬", expected_mins=90
    )
    assert best is not None
    assert best["id"] == "real789"


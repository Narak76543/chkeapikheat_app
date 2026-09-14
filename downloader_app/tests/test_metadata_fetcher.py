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

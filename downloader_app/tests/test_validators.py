"""
Unit tests for validators and filename sanitization.
"""

from downloader_app.utils.validators import (
    extract_filename_from_url,
    is_valid_url,
    sanitize_filename,
)


def test_is_valid_url():
    # Valid HTTP/HTTPS URLs
    assert is_valid_url("https://example.com/file.zip") is True
    assert is_valid_url("http://sub.domain.org/path/to/video.mp4?id=123") is True
    assert is_valid_url("https://127.0.0.1:8080/test") is True

    # Invalid URLs & Schemes
    assert is_valid_url("") is False
    assert is_valid_url("ftp://example.com/file.zip") is False
    assert is_valid_url("javascript:alert(1)") is False
    assert is_valid_url("file:///C:/test.txt") is False
    assert is_valid_url("not_a_url") is False
    assert is_valid_url(None) is False


def test_sanitize_filename():
    # Invalid character replacement
    assert sanitize_filename("my:file*name?.mp4") == "my_file_name_.mp4"
    assert sanitize_filename("test/slash\\backslash.zip") == "test_slash_backslash.zip"
    assert sanitize_filename('hello<world>"quotes"|pipe') == "hello_world__quotes__pipe"

    # Leading/trailing whitespace and dots
    assert sanitize_filename("  ..file.txt..  ") == "file.txt"

    # Empty fallback
    assert sanitize_filename("") == "downloaded_file"
    assert sanitize_filename(None) == "downloaded_file"

    # Windows reserved filenames (CON, PRN, NUL)
    assert sanitize_filename("CON.txt") == "_CON.txt"
    assert sanitize_filename("nul.tar.gz") == "_nul.tar.gz"


def test_extract_filename_from_url():
    # Standard URL path extraction
    assert (
        extract_filename_from_url("https://example.com/downloads/archive.zip")
        == "archive.zip"
    )
    assert (
        extract_filename_from_url("https://example.com/video%20file.mp4")
        == "video file.mp4"
    )

    # With Content-Disposition header
    cd_header = 'attachment; filename="custom_report.pdf"'
    assert (
        extract_filename_from_url("https://example.com/dl?id=1", cd_header)
        == "custom_report.pdf"
    )

    # With RFC 5987 UTF-8 Content-Disposition
    cd_utf8 = "attachment; filename*=UTF-8''%E6%B5%8B%E8%AF%95.mp4"
    assert (
        extract_filename_from_url("https://example.com/dl?id=2", cd_utf8) == "测试.mp4"
    )

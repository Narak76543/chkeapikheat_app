"""
Validators and Sanitization Utilities
Validates URLs and sanitizes filenames across platforms.
"""

import os
import re
import urllib.parse
from pathlib import Path

# Prohibited characters in filenames across Windows, macOS, and Linux
INVALID_FILENAME_CHARS = re.compile(r'[\\/*?:"<>|\x00-\x1f]')
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


def is_valid_url(url: str) -> bool:
    """
    Validates if a URL is a valid, well-formed HTTP/HTTPS URL.
    Rejects malformed schemes, empty inputs, or dangerous pseudo-protocols.
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False
        return bool(parsed.netloc)
    except (ValueError, AttributeError):
        return False


def sanitize_filename(name: str, fallback: str = "downloaded_file") -> str:
    """
    Sanitizes a string to be a safe filename on any OS.
    Handles invalid characters, leading/trailing whitespace/dots, and reserved names.
    """
    if not name or not isinstance(name, str):
        return fallback

    # Remove invalid characters
    clean = INVALID_FILENAME_CHARS.sub("_", name)

    # Strip leading/trailing spaces and dots (important for Windows)
    clean = clean.strip(". ")

    if not clean:
        return fallback

    # Check for Windows reserved names (e.g., CON, PRN, NUL)
    base_stem = clean.split(".")[0].upper()
    if base_stem in RESERVED_WINDOWS_NAMES:
        clean = f"_{clean}"

    # Truncate length if excessively long
    if len(clean) > 200:
        ext = Path(clean).suffix
        clean = clean[: 200 - len(ext)] + ext

    return clean


def extract_filename_from_url(url: str, content_disposition: str | None = None) -> str:
    """
    Extracts or infers a sensible filename from Content-Disposition or the URL path.
    """
    if content_disposition:
        # Check filename* (RFC 5987)
        match_star = re.search(
            r"filename\*\s*=\s*UTF-8''([^;]+)", content_disposition, re.IGNORECASE
        )
        if match_star:
            extracted = urllib.parse.unquote(match_star.group(1).strip("\"' "))
            return sanitize_filename(extracted)

        # Check standard filename=
        match = re.search(
            r'filename\s*=\s*"?([^";]+)"?', content_disposition, re.IGNORECASE
        )
        if match:
            extracted = match.group(1).strip("\"' ")
            return sanitize_filename(extracted)

    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/")
    if path:
        base_name = os.path.basename(path)
        if base_name:
            unquoted = urllib.parse.unquote(base_name)
            return sanitize_filename(unquoted)

    # If domain only or no path found, use netloc
    domain_name = parsed.netloc.replace(":", "_")
    return sanitize_filename(f"download_{domain_name}")

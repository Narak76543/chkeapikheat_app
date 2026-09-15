"""
Movie Metadata Fetcher Module
Extracts rich movie metadata (Poster Picture, Title, Episode Count, Duration, Synopsis, Tags)
from Hongguo short drama searches or video stream extractors.
"""

from urllib.parse import parse_qs, urlparse

from PyQt6.QtCore import QThread, pyqtSignal

from downloader_app.core.hongguo_search import get_drama_details, search_dramas_by_title
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.metadata_fetcher")


def format_duration(mins: int) -> str:
    """Formats duration in minutes to user-friendly string (e.g. 1h 30m or 45m)."""
    if mins <= 0:
        return ""
    hours = mins // 60
    rem = mins % 60
    if hours > 0:
        return f"{hours}h {rem}m" if rem > 0 else f"{hours}h"
    return f"{rem}m"


class MovieMetadataFetcherWorker(QThread):
    """Background worker that retrieves movie data, poster URL, and duration metrics."""

    metadata_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, query: str, parent: QThread | None = None) -> None:
        super().__init__(parent)
        self.query = query.strip()

    def run(self) -> None:
        if not self.query:
            self.error.emit("Query is empty.")
            return

        logger.info(f"Fetching metadata for query: '{self.query}'")

        # 1. Check if query is a direct URL
        if self.query.startswith("http://") or self.query.startswith("https://"):
            data = self._fetch_from_url(self.query)
        else:
            data = self._fetch_from_title(self.query)

        if data:
            self.metadata_ready.emit(data)
        else:
            self.error.emit(f"No movie data found for '{self.query}'")

    def _fetch_from_url(self, url: str) -> dict | None:
        """Extracts metadata from URL (Hongguo detail URL or yt-dlp stream)."""
        parsed = urlparse(url)
        # Check if it is a Hongguo series link
        if "hongguoduanju.com" in parsed.netloc and "series_id=" in url:
            params = parse_qs(parsed.query)
            series_id = params.get("series_id", [""])[0]
            if series_id:
                details = get_drama_details(series_id)
                if details:
                    vid_list = details.get("vid_list", [])
                    total_eps = details.get("total_episodes") or len(vid_list)
                    dur_mins = int(total_eps * 2.0)
                    return {
                        "series_id": series_id,
                        "title": details.get("title", ""),
                        "cover_url": details.get("cover_url", ""),
                        "total_episodes": total_eps,
                        "vid_list": vid_list,
                        "estimated_duration_mins": dur_mins,
                        "duration_str": format_duration(dur_mins),
                        "intro": details.get("intro", ""),
                        "tags": details.get("tags", []),
                        "source": "hongguo",
                        "raw_url": url,
                    }

        # Fallback to yt-dlp for media URLs
        try:
            import yt_dlp

            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    duration_sec = info.get("duration") or 0
                    duration_mins = int(duration_sec // 60) if duration_sec else 0
                    return {
                        "series_id": "",
                        "title": info.get("title", "Video"),
                        "cover_url": info.get("thumbnail", ""),
                        "total_episodes": 1,
                        "estimated_duration_mins": duration_mins,
                        "duration_str": format_duration(duration_mins),
                        "intro": info.get("description", "")[:500],
                        "tags": info.get("tags", [])[:5] if info.get("tags") else [],
                        "source": "yt-dlp",
                        "raw_url": url,
                    }
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning(f"yt-dlp metadata extraction failed: {e}")

        return None

    def _fetch_from_title(self, title: str) -> dict | None:
        """Searches Hongguo for the title and compiles full movie details."""
        dramas = search_dramas_by_title(title)
        if not dramas:
            logger.info(f"No Hongguo results for '{title}', trying yt-dlp fallback...")
            # Fallback to public compilation query via yt-dlp
            return self._fetch_from_ytdlp_search(title)

        top_match = dramas[0]
        series_id = top_match.get("series_id", "")

        # Try to get extended details if available
        details = get_drama_details(series_id) if series_id else None
        if details:
            vid_list = details.get("vid_list") or top_match.get("vid_list", [])
            total_eps = (
                details.get("total_episodes")
                or len(vid_list)
                or top_match.get("total_episodes", 0)
            )
            intro = details.get("intro") or top_match.get("intro", "")
            cover_url = details.get("cover_url") or top_match.get("cover_url", "")
            tags = details.get("tags") or top_match.get("tags", [])
        else:
            vid_list = top_match.get("vid_list", [])
            total_eps = top_match.get("total_episodes") or len(vid_list)
            intro = top_match.get("intro", "")
            cover_url = top_match.get("cover_url", "")
            tags = top_match.get("tags", [])

        duration_mins = int(total_eps * 2.0) if total_eps > 0 else 90
        raw_url = f"https://hongguoduanju.com/detail?series_id={series_id}" if series_id else ""

        return {
            "series_id": series_id,
            "title": top_match.get("title", title),
            "cover_url": cover_url,
            "total_episodes": total_eps,
            "vid_list": vid_list,
            "estimated_duration_mins": duration_mins,
            "duration_str": format_duration(duration_mins),
            "intro": intro,
            "tags": tags,
            "source": "hongguo",
            "raw_url": raw_url,
            "matches": dramas[:5],
        }

    def _fetch_from_ytdlp_search(self, title: str) -> dict | None:
        """Public platform search fallback via yt-dlp."""
        try:
            import yt_dlp

            query = f"ytsearch1:{title} 全集 1080p"
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                entries = info.get("entries", [])
                if entries and entries[0]:
                    item = entries[0]
                    duration_sec = item.get("duration") or 5400
                    raw_url = item.get("url") or (
                        f"https://www.youtube.com/watch?v={item.get('id')}"
                        if item.get("id")
                        else ""
                    )
                    desc = item.get("description") or ""
                    dur_mins = int(duration_sec // 60)
                    return {
                        "series_id": "",
                        "title": item.get("title", title),
                        "cover_url": item.get("thumbnail", ""),
                        "total_episodes": 1,
                        "estimated_duration_mins": dur_mins,
                        "duration_str": format_duration(dur_mins),
                        "intro": desc[:400] or f"Full season compilation for {title}",
                        "tags": ["Full Season", "1080p"],
                        "source": "yt-dlp",
                        "raw_url": raw_url,
                    }

        except (OSError, RuntimeError, ValueError) as e:
            logger.warning(f"yt-dlp search failed: {e}")
        return None


class HongguoEpisodeResolverWorker(QThread):
    """
    Background worker that resolves episode VIDs into direct CDN video stream URLs.
    Emits episodes_resolved signal with list of dicts:
    [{ "url": cdn_stream_url, "filename": ep_filename, "poster_url": cover_url }, ...]
    """

    episodes_resolved = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(
        self,
        series_id: str,
        title: str,
        cover_url: str = "",
        max_episodes: int = 0,
        parent: QThread | None = None,
    ) -> None:
        super().__init__(parent)
        self.series_id = series_id
        self.title = title
        self.cover_url = cover_url
        self.max_episodes = max_episodes

    def run(self) -> None:
        from downloader_app.core.hongguo_search import (
            get_drama_details,
            get_episode_stream_url,
        )

        logger.info(
            f"Resolving episode CDN streams for series '{self.title}' (ID: {self.series_id})"
        )
        details = get_drama_details(self.series_id)
        if not details or not details.get("vid_list"):
            self.error.emit(
                f"No episode video data found for series ID: {self.series_id}"
            )
            return

        vid_list = details["vid_list"]
        if self.max_episodes > 0:
            vid_list = vid_list[: self.max_episodes]

        episodes = []
        for idx, vid in enumerate(vid_list, start=1):
            stream_info = get_episode_stream_url(self.series_id, idx, vid)
            if stream_info and stream_info.get("video_url"):
                cdn_url = stream_info["video_url"]
                ep_filename = f"{self.title}_Ep{idx:02d}.mp4"
                episodes.append(
                    {
                        "url": cdn_url,
                        "filename": ep_filename,
                        "poster_url": self.cover_url,
                    }
                )

        if episodes:
            logger.info(
                f"Successfully resolved {len(episodes)} episode stream URLs for '{self.title}'"
            )
            self.episodes_resolved.emit(episodes)
        else:
            self.error.emit(f"Could not extract video streams for '{self.title}'")


class FullMovieResolverWorker(QThread):
    """
    Background worker that searches for a full movie compilation video URL via yt-dlp.
    Emits movie_resolved signal with dict containing raw_url, title, cover_url.
    """

    movie_resolved = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        title: str,
        cover_url: str = "",
        expected_duration_mins: int = 0,
        parent: QThread | None = None,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.cover_url = cover_url
        self.expected_duration_mins = expected_duration_mins

    def run(self) -> None:
        logger.info(f"Searching yt-dlp for full movie compilation of '{self.title}'")
        try:
            import yt_dlp

            query = f"ytsearch10:{self.title} 全集"
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                entries = info.get("entries", [])
                best_item = self._rank_entries(
                    entries, self.title, self.expected_duration_mins
                )
                if best_item:
                    duration_sec = best_item.get("duration") or 5400
                    raw_url = best_item.get("url") or (
                        f"https://www.youtube.com/watch?v={best_item.get('id')}"
                        if best_item.get("id")
                        else ""
                    )
                    desc = best_item.get("description") or ""
                    dur_mins = int(duration_sec // 60)
                    res = {
                        "series_id": "",
                        "title": best_item.get("title", self.title),
                        "cover_url": best_item.get("thumbnail") or self.cover_url,
                        "total_episodes": 1,
                        "estimated_duration_mins": dur_mins,
                        "duration_str": format_duration(dur_mins),
                        "intro": desc[:400]
                        or f"Full season compilation for {self.title}",
                        "tags": ["Full Season", "1080p"],
                        "source": "yt-dlp",
                        "raw_url": raw_url,
                    }
                    if raw_url:
                        self.movie_resolved.emit(res)
                        return
            self.error.emit(f"No compilation video found for {self.title}")
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning(f"yt-dlp full movie search error: {e}")
            self.error.emit(str(e))

    @staticmethod
    def _rank_entries(
        entries: list[dict], query_title: str, expected_mins: int = 0
    ) -> dict | None:
        import re

        if not entries:
            return None

        clean_q = re.sub(r"[^\w\u4e00-\u9fff]", "", query_title)
        stem = clean_q[:3] if len(clean_q) >= 3 else clean_q

        candidates = []
        for item in entries:
            if not item or not item.get("title"):
                continue
            item_title = item.get("title", "")
            clean_t = re.sub(r"[^\w\u4e00-\u9fff]", "", item_title)
            dur_sec = item.get("duration") or 0
            dur_mins = dur_sec // 60

            score = 0
            if clean_q and clean_q in clean_t:
                score += 100
            elif stem and stem in clean_t:
                score += 50

            # Loop detection & anti-fake penalties:
            # Fake loop videos on YouTube typically say '循环', 'loop', '4小时', '5小时', '4 hours', 'repeat'
            lower_title = item_title.lower()
            if any(term in lower_title or term in clean_t for term in ["循环", "loop", "repeat", "4小时", "5小时", "6小时", "4 hours", "5 hours", "6 hours"]):
                score -= 150

            # Short drama full movies are usually 50 to 140 minutes (1h - 2.3h)
            # Videos longer than 180 minutes (3 hours) for short dramas are almost universally fake loops
            if dur_mins > 180:
                score -= 80
            elif 50 <= dur_mins <= 140:
                score += 30

            if expected_mins > 0 and dur_mins > 0:
                diff = abs(dur_mins - expected_mins)
                if diff <= 30:
                    score += 50
                elif diff <= 60:
                    score += 30
                elif dur_mins < expected_mins * 0.5:
                    score -= 40
                elif dur_mins > expected_mins * 1.8:
                    score -= 60
            elif dur_mins > 30:
                score += 20

            candidates.append((score, dur_mins, item))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        if candidates[0][0] > 0:
            return candidates[0][2]
        return entries[0]

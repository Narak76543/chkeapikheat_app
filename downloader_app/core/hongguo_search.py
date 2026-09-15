"""
Hongguo Short Drama Search & Episode Extractor
Searches dramas by title and extracts episode stream URLs.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.hongguo_search")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://hongguoduanju.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def search_dramas_by_title(title: str) -> list[dict]:
    """
    Searches dramas by title on hongguoduanju.com.
    Returns a list of matching series dictionaries.
    """
    clean_title = title.strip()
    if not clean_title:
        return []

    encoded = urllib.parse.quote(clean_title)
    search_url = f"https://hongguoduanju.com/search/{encoded}"

    try:
        req = urllib.request.Request(search_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")

        idx = html.find("_ROUTER_DATA = ")
        if idx == -1:
            return []

        start_json = idx + len("_ROUTER_DATA = ")
        data, _ = json.JSONDecoder().raw_decode(html[start_json:])
        loader_data = data.get("loaderData", {})

        # Find search page data in loader
        search_page = None
        for k, v in loader_data.items():
            if "search" in k and isinstance(v, dict) and "searchList" in v:
                search_page = v
                break

        if not search_page:
            return []

        search_list = search_page.get("searchList", [])
        results = []
        for item in search_list:
            vdata = item.get("video_data", {})
            series_id = vdata.get("series_id") or item.get("keyword")
            if not series_id:
                continue

            results.append(
                {
                    "series_id": str(series_id),
                    "title": vdata.get("series_title") or item.get("name", clean_title),
                    "cover_url": vdata.get("series_cover", ""),
                    "total_episodes": vdata.get("episode_cnt", 0),
                    "intro": vdata.get("series_intro", ""),
                    "tags": [
                        cat.get("name")
                        for cat in vdata.get("category_list", [])
                        if isinstance(cat, dict)
                    ],
                    "vid_list": vdata.get("vid_list", []),
                }
            )

        logger.info(f"Search for '{title}' returned {len(results)} dramas.")
        return results

    except (urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Error searching drama by title '{title}': {e}")
        return []


def get_drama_details(series_id: str) -> dict | None:
    """Fetches full metadata and complete VID list for a series."""
    detail_url = f"https://hongguoduanju.com/detail?series_id={series_id}"
    try:
        req = urllib.request.Request(detail_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")

        idx = html.find("_ROUTER_DATA = ")
        if idx == -1:
            return None

        start_json = idx + len("_ROUTER_DATA = ")
        data, _ = json.JSONDecoder().raw_decode(html[start_json:])
        detail_page = data.get("loaderData", {}).get("detail_page", {})
        series_detail = detail_page.get("seriesDetail", {})
        if not series_detail:
            return None

        return {
            "series_id": series_id,
            "title": series_detail.get("series_name", f"Series_{series_id}"),
            "total_episodes": series_detail.get("episode_cnt", 0),
            "accessible_episodes": series_detail.get("accessible_episode_cnt", 0),
            "cover_url": series_detail.get("series_cover", ""),
            "intro": series_detail.get("series_intro", ""),
            "tags": series_detail.get("tags", []),
            "vid_list": series_detail.get("vid_list", []),
        }
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Error fetching drama detail for {series_id}: {e}")
        return None


def get_episode_stream_url(series_id: str, ep_index: int, vid: str) -> dict | None:
    """Fetches the direct CDN video URL for an episode."""
    urls_to_try = []
    if vid:
        urls_to_try.append(f"https://hongguoduanju.com/player/{series_id}/{vid}")
        urls_to_try.append(f"https://hongguoduanju.com/player/{series_id}?vid={vid}")
    else:
        urls_to_try.append(f"https://hongguoduanju.com/player/{series_id}")

    for ep_url in urls_to_try:
        try:
            req = urllib.request.Request(ep_url, headers=DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode("utf-8", errors="ignore")

            idx = html.find("_ROUTER_DATA = ")
            if idx == -1:
                continue

            start_json = idx + len("_ROUTER_DATA = ")
            data, _ = json.JSONDecoder().raw_decode(html[start_json:])
            loader_data = data.get("loaderData", {})

            page_data = None
            for key, val in loader_data.items():
                if isinstance(val, dict) and "video_player_info" in val:
                    if vid and vid in key:
                        page_data = val
                        break
                    if not page_data:
                        page_data = val

            if not page_data or not page_data.get("video_player_info"):
                continue

            # Verify that the returned stream actually matches the requested VID.
            # On Hongguo web, paywalled episodes (ep 4+) silently redirect to Episode 1.
            ret_vid = page_data.get("vid")
            if vid and ret_vid and str(ret_vid) != str(vid):
                logger.info(
                    f"Hongguo web episode {ep_index} (vid={vid}) is paywalled/locked (server returned vid={ret_vid})."
                )
                continue

            vinfo = page_data["video_player_info"]
            video_url = vinfo.get("main_url")
            if video_url:
                return {
                    "vid": vid,
                    "episode_num": ep_index,
                    "video_url": video_url,
                    "duration": vinfo.get("duration"),
                    "width": vinfo.get("width"),
                    "height": vinfo.get("height"),
                }
        except (urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError):
            continue

    return None

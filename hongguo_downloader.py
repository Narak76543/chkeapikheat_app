#!/usr/bin/env python3
"""
Hongguo Short Drama (红果短剧) Video Downloader
Supports downloading available episodes directly from https://hongguoduanju.com/
"""

import os
import re
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path

# Ensure UTF-8 output across standard console streams
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://hongguoduanju.com/',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
}


def sanitize_filename(name: str) -> str:
    """Removes or replaces characters not allowed in filenames across OSes."""
    return re.sub(r'[\\/*?:"<>|]', '_', name).strip()


def extract_series_id(url_or_id: str) -> str:
    """Extracts series_id from URL or returns the ID if already clean."""
    url_or_id = url_or_id.strip()
    if url_or_id.isdigit():
        return url_or_id
    
    # Try query param series_id=
    match = re.search(r'series_id=(\d+)', url_or_id)
    if match:
        return match.group(1)
    
    # Try player URL format /player/(\d+)
    match = re.search(r'/player/(\d+)', url_or_id)
    if match:
        return match.group(1)
    
    raise ValueError(f"Could not extract a valid series_id from '{url_or_id}'")


def fetch_url(url: str, headers: dict = None) -> str:
    """Fetches text content from URL with custom headers."""
    req_headers = DEFAULT_HEADERS.copy()
    if headers:
        req_headers.update(headers)
    
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.read().decode('utf-8', errors='ignore')


def extract_router_data(html: str) -> dict:
    """Extracts _ROUTER_DATA JSON object from page HTML."""
    idx = html.find('_ROUTER_DATA = ')
    if idx == -1:
        raise ValueError("Could not find _ROUTER_DATA in page content.")
    
    start_json = idx + len('_ROUTER_DATA = ')
    decoder = json.JSONDecoder()
    data, _ = decoder.raw_decode(html[start_json:])
    return data


def get_series_info(series_id: str) -> dict:
    """Fetches series metadata and episode list from the detail page."""
    detail_url = f"https://hongguoduanju.com/detail?series_id={series_id}"
    html = fetch_url(detail_url)
    router_data = extract_router_data(html)
    
    loader_data = router_data.get('loaderData', {})
    detail_page = loader_data.get('detail_page', {})
    series_detail = detail_page.get('seriesDetail', {})
    
    if not series_detail:
        raise ValueError(f"Series detail not found for ID: {series_id}")
    
    return {
        'series_id': series_id,
        'title': series_detail.get('series_name', f'series_{series_id}'),
        'total_episodes': series_detail.get('episode_cnt', 0),
        'accessible_episodes': series_detail.get('accessible_episode_cnt', 0),
        'cover_url': series_detail.get('series_cover', ''),
        'intro': series_detail.get('series_intro', ''),
        'tags': series_detail.get('tags', []),
        'vid_list': series_detail.get('vid_list', [])
    }


def get_episode_video_info(series_id: str, episode_index: int, vid: str) -> dict:
    """Fetches direct video stream URL and specs for a specific episode."""
    if episode_index == 1:
        ep_url = f"https://hongguoduanju.com/player/{series_id}"
    else:
        ep_url = f"https://hongguoduanju.com/player/{series_id}/{vid}"
    
    try:
        html = fetch_url(ep_url)
        router_data = extract_router_data(html)
        loader_data = router_data.get('loaderData', {})
        
        page_data = None
        for key, val in loader_data.items():
            if 'page' in key and isinstance(val, dict) and 'video_player_info' in val:
                page_data = val
                break
        
        if not page_data or not page_data.get('video_player_info'):
            return None
        
        vinfo = page_data['video_player_info']
        return {
            'vid': vid,
            'episode_num': episode_index,
            'video_url': vinfo.get('main_url'),
            'duration': vinfo.get('duration'),
            'width': vinfo.get('width'),
            'height': vinfo.get('height'),
            'poster_url': vinfo.get('poster_url')
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def download_file(url: str, output_filepath: str, headers: dict = None) -> bool:
    """Downloads a file with streaming progress display."""
    req_headers = DEFAULT_HEADERS.copy()
    if headers:
        req_headers.update(headers)
    
    req = urllib.request.Request(url, headers=req_headers)
    target_path = Path(output_filepath)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    temp_path = target_path.with_suffix(target_path.suffix + '.part')
    
    start_time = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as response, open(temp_path, 'wb') as out_file:
            total_bytes = int(response.info().get('Content-Length', 0))
            downloaded = 0
            chunk_size = 1024 * 64
            
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)
                
                elapsed = time.time() - start_time
                speed_kb = (downloaded / 1024) / max(elapsed, 0.001)
                
                if total_bytes > 0:
                    percent = (downloaded / total_bytes) * 100
                    bar_len = 25
                    filled = int(bar_len * downloaded // total_bytes)
                    bar = '=' * filled + '-' * (bar_len - filled)
                    sys.stdout.write(
                        f"\r  [{bar}] {percent:5.1f}% | {downloaded / (1024*1024):.2f}/{total_bytes / (1024*1024):.2f} MB | {speed_kb:.1f} KB/s"
                    )
                else:
                    sys.stdout.write(f"\r  Downloaded: {downloaded / (1024*1024):.2f} MB | {speed_kb:.1f} KB/s")
                sys.stdout.flush()
        
        print()  # Newline after download complete
        if temp_path.exists():
            temp_path.replace(target_path)
        return True
    except Exception as e:
        print(f"\n  Download failed: {e}")
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return False


def parse_episode_selection(selection: str, max_episodes: int) -> list:
    """Parses episode selection string like 'all', '1', '1-3', '1,2,5' into 1-based index list."""
    if not selection or selection.lower() == 'all':
        return list(range(1, max_episodes + 1))
    
    indices = set()
    parts = selection.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            start_str, end_str = part.split('-', 1)
            start = max(1, int(start_str))
            end = min(max_episodes, int(end_str))
            indices.update(range(start, end + 1))
        elif part.isdigit():
            idx = int(part)
            if 1 <= idx <= max_episodes:
                indices.add(idx)
    return sorted(list(indices))


def download_from_file(file_path: str, output_folder: Path):
    """Downloads video URLs listed line by line in a text file."""
    if not os.path.exists(file_path):
        print(f"[-] File not found: {file_path}")
        return
        
    with open(file_path, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        
    print(f"\n[+] Loaded {len(urls)} URLs from {file_path}")
    output_folder.mkdir(parents=True, exist_ok=True)
    
    successful = 0
    for idx, url in enumerate(urls, 1):
        filename = f"EP{idx:02d}.mp4"
        dest_path = output_folder / filename
        print(f"\n--- Downloading Item {idx:02d}/{len(urls)}: {filename} ---")
        ok = download_file(url, str(dest_path))
        if ok:
            successful += 1
            print(f"  [✓] Successfully downloaded {filename}")
        else:
            print(f"  [✗] Failed downloading {filename}")
            
    print("\n" + "=" * 60)
    print(f"Finished! Downloaded {successful}/{len(urls)} files to: {output_folder.resolve()}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Download videos from Hongguo Short Drama (红果短剧)")
    parser.add_argument('url_or_id', nargs='?', help="Drama URL or Series ID")
    parser.add_argument('-e', '--episodes', default='all', help="Episodes to download: 'all', '1', '1-3', '1,2,3' (default: all available)")
    parser.add_argument('-f', '--file', help="Text file containing direct video/stream URLs (one per line) to download in batch")
    parser.add_argument('-o', '--output-dir', default='./downloads', help="Output directory (default: ./downloads)")
    parser.add_argument('--info-only', action='store_true', help="Only show series info without downloading")
    
    args = parser.parse_args()
    
    if args.file:
        download_from_file(args.file, Path(args.output_dir))
        return
    
    target_input = args.url_or_id
    if not target_input:
        target_input = input("Enter Hongguo Drama URL, Series ID, or path to URL list file: ").strip()
        if not target_input:
            print("No input provided. Exiting.")
            sys.exit(1)
        if os.path.exists(target_input):
            download_from_file(target_input, Path(args.output_dir))
            return
            
    try:
        series_id = extract_series_id(target_input)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
        
    print(f"\n[+] Fetching drama metadata for Series ID: {series_id}...")
    try:
        series_info = get_series_info(series_id)
    except Exception as e:
        print(f"[-] Failed to fetch drama info: {e}")
        sys.exit(1)
        
    print("=" * 60)
    print(f"Title:       {series_info['title']}")
    print(f"Total EPs:   {series_info['total_episodes']}")
    print(f"Free on Web: {series_info['accessible_episodes']}")
    if series_info['tags']:
        print(f"Tags:        {', '.join(series_info['tags'])}")
    if series_info['intro']:
        print(f"Intro:       {series_info['intro'][:150]}...")
    print("=" * 60)
    
    if args.info_only:
        return
    
    vids = series_info['vid_list']
    total_eps = len(vids)
    if total_eps == 0:
        print("[-] No episodes found in drama list.")
        return
    
    selected_ep_numbers = parse_episode_selection(args.episodes, total_eps)
    print(f"\n[+] Processing {len(selected_ep_numbers)} episode(s)...")
    
    safe_title = sanitize_filename(series_info['title'])
    output_folder = Path(args.output_dir) / safe_title
    output_folder.mkdir(parents=True, exist_ok=True)
    
    successful = 0
    for ep_num in selected_ep_numbers:
        vid = vids[ep_num - 1]
        print(f"\n--- Episode {ep_num:02d} / {total_eps} (VID: {vid}) ---")
        
        ep_file_name = f"EP{ep_num:02d}_{vid}.mp4"
        dest_path = output_folder / ep_file_name
        
        if dest_path.exists() and dest_path.stat().st_size > 0:
            print(f"  [i] Episode already downloaded ({dest_path.name}), skipping.")
            successful += 1
            continue
        
        print("  [*] Fetching stream URL...")
        ep_info = get_episode_video_info(series_id, ep_num, vid)
        
        if not ep_info or not ep_info.get('video_url'):
            print(f"  [-] Episode {ep_num} is not accessible on web (app only/VIP).")
            continue
        
        print(f"  [+] Video resolution: {ep_info.get('width')}x{ep_info.get('height')} | Duration: {ep_info.get('duration')}s")
        print(f"  [*] Downloading to: {dest_path}...")
        
        ok = download_file(ep_info['video_url'], str(dest_path))
        if ok:
            successful += 1
            print(f"  [✓] Successfully downloaded EP{ep_num:02d}")
        else:
            print(f"  [✗] Failed downloading EP{ep_num:02d}")
    
    print("\n" + "=" * 60)
    print(f"Finished! Successfully downloaded {successful} episode(s) to:\n{output_folder.resolve()}")
    print("=" * 60)


if __name__ == '__main__':
    main()

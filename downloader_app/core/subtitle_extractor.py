"""
Subtitle Extractor Core Module
Parses SRT/VTT subtitle files, extracts embedded subtitle tracks via FFmpeg,
and manages subtitle item timestamps for localization and TTS alignment.
"""

import base64
import concurrent.futures
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
import subprocess
import time

import requests

from PyQt6.QtCore import QThread, pyqtSignal

from downloader_app.core.downloader import get_ffmpeg_path
from downloader_app.utils.logger import setup_logger
from downloader_app.utils.validators import sanitize_filename

logger = setup_logger("downloader.subtitle_extractor")


@dataclass
class SubtitleItem:
    """Represents a single timed subtitle entry."""
    index: int
    start_time: str
    end_time: str
    start_seconds: float
    end_seconds: float
    text: str

    @property
    def duration_seconds(self) -> float:
        return max(0.1, self.end_seconds - self.start_seconds)


def timestamp_to_seconds(ts: str) -> float:
    """Converts HH:MM:SS,mmm, MM:SS,mmm, or MM:SS to seconds float with tolerance for loose spacing."""
    if not ts:
        return 0.0
    # Clean whitespace and extract only timestamp characters
    ts = ts.strip().replace(" ", "").replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600.0 + float(m) * 60.0 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return float(m) * 60.0 + float(s)
        elif len(parts) == 1:
            return float(parts[0])
    except (ValueError, TypeError):
        # Fallback regex extraction of numbers
        nums = re.findall(r"\d+(?:\.\d+)?", ts)
        if len(nums) >= 3:
            return float(nums[0]) * 3600.0 + float(nums[1]) * 60.0 + float(nums[2])
        elif len(nums) == 2:
            return float(nums[0]) * 60.0 + float(nums[1])
        elif len(nums) == 1:
            return float(nums[0])
    return 0.0


def seconds_to_timestamp(seconds: float) -> str:
    """Converts seconds float to HH:MM:SS,mmm string."""
    seconds = max(0.0, seconds)
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def parse_srt_content(content: str) -> list[SubtitleItem]:
    """
    Parses SRT format text string into a list of SubtitleItem objects.
    Ultra-robust against LLM formatting quirks (same-line index, MM:SS, spaces in timestamps, missing newlines).
    """
    if not content or not content.strip():
        return []
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # Universal timestamp regex matching:
    # Optional index on same line -> start timestamp -> delimiter (--> or -> or ~) -> end timestamp -> optional same-line text
    ts_pattern = re.compile(
        r"(?:^|\n)\s*(?:(\d+)\s+)?"  # Optional index
        r"(\d{1,2}(?::\d{1,2}){1,2}(?:[\.,]\s*\d{1,3})?)"  # Start timestamp (HH:MM:SS or MM:SS)
        r"\s*(?:-->|->|~|-)\s*"  # Delimiter
        r"(\d{1,2}(?::\d{1,2}){1,2}(?:[\.,]\s*\d{1,3})?)"  # End timestamp
        r"(?:[ \t]+([^\n]+))?",  # Optional same-line text
        re.MULTILINE,
    )

    matches = list(ts_pattern.finditer(content))
    raw_items = []

    if matches:
        for i, m in enumerate(matches):
            idx_str, start_raw, end_raw, same_line_text = m.groups()
            content_start = m.end()
            content_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            body_text = content[content_start:content_end].strip()

            full_text_lines = []
            if same_line_text and same_line_text.strip():
                full_text_lines.append(same_line_text.strip())
            for line in body_text.splitlines():
                l = line.strip()
                if l.isdigit() and i + 1 < len(matches):
                    continue
                if l:
                    full_text_lines.append(l)

            text = " ".join(full_text_lines).strip()
            # Remove any leading stray index numbers
            text = re.sub(r"^\d+\s+", "", text).strip()
            if not text:
                continue

            start_s = timestamp_to_seconds(start_raw)
            end_s = timestamp_to_seconds(end_raw)

            if end_s <= start_s:
                end_s = start_s + max(1.5, min(8.0, len(text) * 0.08))

            raw_items.append(
                SubtitleItem(
                    index=i + 1,
                    start_time=seconds_to_timestamp(start_s),
                    end_time=seconds_to_timestamp(end_s),
                    start_seconds=start_s,
                    end_seconds=end_s,
                    text=text,
                )
            )

    if not raw_items:
        # Fallback to classic block splitting
        blocks = re.split(r"\n\n+", content.strip())
        for idx, block in enumerate(blocks, start=1):
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            if not lines:
                continue
            time_line_idx = -1
            for i, line in enumerate(lines):
                if "-->" in line or "->" in line:
                    time_line_idx = i
                    break
            if time_line_idx != -1:
                delim = "-->" if "-->" in lines[time_line_idx] else "->"
                time_parts = lines[time_line_idx].split(delim)
                start_str = time_parts[0].strip()
                # Clean any leading index from start_str
                start_str = re.sub(r"^\d+\s+", "", start_str)
                end_str = time_parts[1].strip() if len(time_parts) > 1 else start_str
                text_lines = lines[time_line_idx + 1 :]
                text = " ".join(text_lines).strip()
                if not text:
                    continue
                start_sec = timestamp_to_seconds(start_str)
                end_sec = timestamp_to_seconds(end_str)
                if end_sec <= start_sec:
                    end_sec = start_sec + max(1.5, min(8.0, len(text) * 0.08))
                raw_items.append(
                    SubtitleItem(
                        index=idx,
                        start_time=seconds_to_timestamp(start_sec),
                        end_time=seconds_to_timestamp(end_sec),
                        start_seconds=start_sec,
                        end_seconds=end_sec,
                        text=text,
                    )
                )

    raw_items.sort(key=lambda x: x.start_seconds)
    for idx, it in enumerate(raw_items, start=1):
        it.index = idx
    return raw_items


def format_srt_content(items: list[SubtitleItem]) -> str:
    """Formats a list of SubtitleItem objects back into an SRT string."""
    blocks = []
    for i, item in enumerate(items, start=1):
        start_ts = seconds_to_timestamp(item.start_seconds)
        end_ts = seconds_to_timestamp(item.end_seconds)
        blocks.append(f"{i}\n{start_ts} --> {end_ts}\n{item.text}\n")
    return "\n".join(blocks)


def get_video_duration_ffmpeg(video_path: Path) -> float:
    """Extracts video duration in seconds using FFmpeg metadata."""
    ffmpeg_bin = get_ffmpeg_path()
    if not ffmpeg_bin or not video_path.exists():
        return 0.0
    cmd = [ffmpeg_bin, "-i", str(video_path.resolve())]
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr)
        if match:
            h, m, s = match.groups()
            return float(h) * 3600 + float(m) * 60 + float(s)
    except Exception as e:
        logger.debug(f"Failed to extract video duration via FFmpeg: {e}")
    return 0.0




# Compiled once: matches junk artifacts from Gemini STT output
_NOISE_ARTIFACT_RE = re.compile(
    r"""
    ^\s*
    (?:
        # Brackets containing ONLY digits / Khmer digits / punctuation / whitespace
        [\[\(【（][\s\d០-៩]+[\]\)】）]
        |
        # Brackets containing music / sound effect annotations
        [\[\(【（♪][^a-zA-Z\u1780-\u17FF\u4e00-\u9fff\u0e00-\u0e7f]*[\]\)】）♪]
        |
        # Standalone Khmer digit(s) only: ០ ១ ២ ៣ ៤ ៥ ៦ ៧ ៨ ៩
        [០-៩]+
        |
        # Standalone Western digit(s) only e.g. "1" "12"
        \d+
        |
        # Common non-speech markers: [music] [applause] [laughs] [♪] ♪ (music) etc.
        [\[\(【（♪][\w\s,\.♪\-]*?(?:music|sound|effect|laugh|applause|noise|ambient|silence|pause|sigh|cry|sob|shout|scream|groan|cough|sneeze)[\w\s,\.♪\-]*?[\]\)】）♪]?
        |
        # Translator alternative note: starts with (ឬ or (ឬ៖
        \(ឬ[៖:]?.*
        |
        # Lone closing parenthesis / bracket
        [\)\]】）]+
        |
        # Ellipsis / dash / dot-only lines
        [\.…\-–—\s]+
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)

# Characters belonging to non-Khmer, non-Latin, non-CJK scripts that should never appear in a Khmer subtitle
_FOREIGN_SCRIPT_RE = re.compile(
    r"[\u0370-\u03FF"   # Greek
    r"\u3040-\u30FF"    # Japanese Hiragana / Katakana
    r"\u4DC0-\u4DFF"    # Yijing hexagrams (junk)
    r"\u1100-\u11FF"    # Korean Jamo
    r"\uAC00-\uD7AF"    # Korean Hangul
    r"\u0400-\u04FF"    # Cyrillic
    r"\u0E00-\u0E7F"    # Thai
    r"\u1200-\u137F"    # Ethiopic
    r"\u0600-\u06FF"    # Arabic
    r"]",
    re.UNICODE,
)

# Excessive foreign consonant clusters: ហ + ្ + consonant repeated many times = phonetic Chinese in Khmer
_PHONETIC_TRANSLITERATION_RE = re.compile(
    r"(?:ហ្[កខគឃងចឆជឈញដឋឌឍណតថទធនបផពភមយរលវឃសហឡអ]){3,}",
    re.UNICODE,
)


def _is_noise_artifact(text: str) -> bool:
    """Returns True if the subtitle line is a non-speech artifact that should be discarded."""
    if not text or not text.strip():
        return True
    t = text.strip()

    # Must have at least one real Khmer letter (or Latin/CJK as fallback during translation)
    has_real_letter = bool(re.search(
        r"[a-zA-Z\u1780-\u17FF\u4e00-\u9fff\u0e00-\u0e7f]", t
    ))
    if not has_real_letter:
        return True

    # Contains non-target scripts (Greek, Japanese, Cyrillic, Korean) — hallucination/leak
    if _FOREIGN_SCRIPT_RE.search(t):
        return True

    # Match known noise patterns (digit-only, music markers, translator notes, lone brackets)
    if _NOISE_ARTIFACT_RE.match(t):
        return True

    # Excessive phonetic Chinese-in-Khmer transliteration (3+ foreign clusters in a row)
    if _PHONETIC_TRANSLITERATION_RE.search(t):
        return True

    return False



def _split_text_into_sentences(text: str) -> list[str]:
    """Splits dialogue text into individual sentences supporting Khmer, Chinese, Thai, and Latin punctuation."""
    if not text:
        return []
    # Primary sentence terminators: Khmer (។, ៕), Chinese/CJK (。！？), Western (.!?\n)
    pattern = r"([។៕。！？!?\n]+)"
    raw_tokens = [t for t in re.split(pattern, text) if t]
    sentences = []
    curr = ""
    for tok in raw_tokens:
        if re.match(r"^[។៕。！？!?\n]+$", tok):
            curr += tok
            if curr.strip():
                sentences.append(curr.strip())
            curr = ""
        else:
            if curr.strip():
                sentences.append(curr.strip())
            curr = tok
    if curr.strip():
        sentences.append(curr.strip())

    # If a sentence is unusually long (> 45 chars) and has comma/clause delimiters, split further
    final_sentences = []
    for s in sentences:
        if len(s) > 45 and any(c in s for c in "，,;；、\t"):
            clause_parts = [p.strip() for p in re.split(r"([，,;；、\t]+)", s) if p.strip()]
            c_curr = ""
            for cp in clause_parts:
                if re.match(r"^[，,;；、\t]+$", cp):
                    c_curr += cp
                    if len(c_curr.strip()) > 12:
                        final_sentences.append(c_curr.strip())
                        c_curr = ""
                else:
                    if c_curr.strip() and len(c_curr.strip()) > 12:
                        final_sentences.append(c_curr.strip())
                        c_curr = cp
                    else:
                        c_curr = (c_curr + " " + cp).strip() if c_curr else cp
            if c_curr.strip():
                final_sentences.append(c_curr.strip())
        else:
            final_sentences.append(s)

    return [s for s in final_sentences if s]


def _split_long_items(items: list[SubtitleItem], max_block_dur: float = 8.0) -> list[SubtitleItem]:
    """Splits multi-sentence subtitle blocks into granular timed dialogue turns without slicing Unicode text."""
    new_items = []
    idx = 1
    for it in items:
        sentences = _split_text_into_sentences(it.text)

        if len(sentences) > 1:
            total_dur = max(1.0, it.duration_seconds)
            total_chars = sum(max(1, len(s)) for s in sentences)
            curr_start = it.start_seconds
            for s_i, sent in enumerate(sentences):
                char_ratio = max(1, len(sent)) / total_chars
                sent_dur = char_ratio * total_dur
                if s_i == len(sentences) - 1:
                    sent_end = it.end_seconds
                else:
                    sent_end = min(it.end_seconds, curr_start + sent_dur)
                new_items.append(
                    SubtitleItem(
                        index=idx,
                        start_time=seconds_to_timestamp(curr_start),
                        end_time=seconds_to_timestamp(sent_end),
                        start_seconds=curr_start,
                        end_seconds=sent_end,
                        text=sent,
                    )
                )
                idx += 1
                curr_start = sent_end
        else:
            it.index = idx
            new_items.append(it)
            idx += 1
    return new_items


_PREFERRED_STT_MODEL: str | None = "gemini-3.6-flash"
ACTIVE_STT_MODELS: list[str] = [
    "gemini-3.6-flash",       # Best accuracy for Chinese STT (user verified)
    "gemini-3.5-flash-lite",  # Fast fallback
    "gemini-3.5-transcribe",  # Transcription-specialized fallback
    "gemini-3.7-flash",       # High capability fallback
    "gemini-3.1-flash-lite",  # Lightweight fallback
    "gemini-flash-latest",    # Latest stable fallback
]


def _transcribe_audio_slice_with_gemini(
    audio_bytes: bytes,
    api_key: str,
    chunk_index: int,
    total_chunks: int,
    start_sec: float,
) -> list[SubtitleItem]:
    """Transcribes a single audio chunk (<= 150s) with Gemini AI using multi-model resilience."""
    global _PREFERRED_STT_MODEL, ACTIVE_STT_MODELS
    if not audio_bytes or not api_key:
        return []

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    prompt = (
        "You are a professional Chinese speech-to-text transcription specialist.\n"
        "The audio track contains Chinese (Mandarin) spoken dialogue.\n"
        "Your ONLY task is to transcribe what is spoken — do NOT translate.\n"
        "\n"
        "Rules:\n"
        "1. Output each spoken sentence or dialogue turn as actual Chinese characters (中文字幕).\n"
        "2. Do NOT translate to Khmer, English, or any other language — only Chinese characters.\n"
        "3. Break dialogue into natural short blocks of 2–6 seconds each.\n"
        "4. Each block must be a complete, natural Chinese sentence or phrase.\n"
        "5. Skip segments that are music, sound effects, or silence — output nothing for those.\n"
        "6. Do NOT output bracket markers like [音乐], [笑声], [1], [♪] or any annotation.\n"
        "7. Do NOT output timestamps beyond the actual length of this audio clip.\n"
        "8. Output STRICTLY standard numbered SRT format:\n"
        "   INDEX\n"
        "   HH:MM:SS,mmm --> HH:MM:SS,mmm\n"
        "   Chinese text\n"
        "\n"
        "Example:\n"
        "1\n"
        "00:00:01,500 --> 00:00:04,200\n"
        "你好，欢迎来到节目。\n"
        "\n"
        "2\n"
        "00:00:05,100 --> 00:00:08,300\n"
        "今天我们要讨论一个重要的话题。\n"
        "\n"
        "Return ONLY the raw SRT text. No markdown, no explanations, no notes."
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "audio/mp3",
                            "data": audio_b64,
                        }
                    },
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "topP": 0.1,
        },
    }

    # Prioritize last successful model
    models_to_try = []
    if _PREFERRED_STT_MODEL and _PREFERRED_STT_MODEL in ACTIVE_STT_MODELS:
        models_to_try.append(_PREFERRED_STT_MODEL)
    for m in ACTIVE_STT_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    for model_name in models_to_try:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        for attempt in range(2):
            try:
                logger.info(
                    f"Sending audio chunk {chunk_index}/{total_chunks} ({len(audio_bytes) // 1024} KB) to Gemini ({model_name}, attempt {attempt+1})..."
                )
                resp = requests.post(endpoint, json=payload, timeout=35)
                logger.info(f"Gemini ({model_name}) chunk {chunk_index} response status: {resp.status_code}")

                if resp.status_code == 200:
                    _PREFERRED_STT_MODEL = model_name
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            srt_text = parts[0].get("text", "").strip()
                            srt_text = re.sub(r"^```[a-z]*\n?", "", srt_text)
                            srt_text = re.sub(r"\n?```$", "", srt_text).strip()
                            chunk_items = parse_srt_content(srt_text)
                            if chunk_items:
                                # Offset by chunk start_sec
                                for it in chunk_items:
                                    it.start_seconds += start_sec
                                    it.end_seconds += start_sec
                                    it.start_time = seconds_to_timestamp(it.start_seconds)
                                    it.end_time = seconds_to_timestamp(it.end_seconds)
                                logger.info(
                                    f"Chunk {chunk_index}/{total_chunks} extracted {len(chunk_items)} lines from ({start_sec:.1f}s)."
                                )
                                return chunk_items
                            else:
                                logger.info(f"Chunk {chunk_index}/{total_chunks} returned no speech dialogue (ambient/music).")
                                return []
                elif resp.status_code in (404, 400):
                    logger.warning(
                        f"Gemini model '{model_name}' unavailable/deprecated (HTTP {resp.status_code}). Removing from active pool."
                    )
                    if model_name in ACTIVE_STT_MODELS:
                        ACTIVE_STT_MODELS.remove(model_name)
                    break
                elif resp.status_code in (429, 503):
                    logger.warning(
                        f"Gemini ({model_name}) busy/quota (HTTP {resp.status_code}). Waiting 1.0s before retry..."
                    )
                    time.sleep(1.0)
                    continue
                else:
                    logger.warning(f"Gemini ({model_name}) error HTTP {resp.status_code}: {resp.text[:200]}")
                    break
            except requests.exceptions.Timeout:
                logger.warning(f"Gemini ({model_name}) timed out on chunk {chunk_index}, trying next model...")
                break
            except Exception as e:
                logger.warning(f"Gemini ({model_name}) chunk {chunk_index} error: {e}")
                break

    return []


def transcribe_video_audio_to_subtitles(
    video_path: Path, target_lang: str = "km", progress_callback=None
) -> list[SubtitleItem]:
    """
    Extracts audio in parallel time slices using FFmpeg, transcribes dialogue concurrently
    with Gemini Multimodal AI, offsets timestamps, and returns a unified timed SubtitleItem list.
    Handles any video length (from short clips to 2+ hour full movies) with high speed and zero timeouts.
    """
    from downloader_app.core.translator import get_api_key
    api_key = get_api_key()
    ffmpeg_bin = get_ffmpeg_path()
    if not api_key or not ffmpeg_bin or not video_path.exists():
        return []

    if progress_callback:
        progress_callback(10.0, "Analyzing video duration...")

    total_dur = get_video_duration_ffmpeg(video_path)
    logger.info(f"Video total duration for speech transcription: {total_dur:.2f}s ({total_dur/60:.1f} mins)")

    CHUNK_DURATION = 150.0  # 2.5 minutes per slice: optimal for Gemini fast STT & zero timeouts
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    if total_dur <= 0.0:
        chunks = [(0.0, None)]
    else:
        chunks = []
        curr = 0.0
        while curr < total_dur:
            length = min(CHUNK_DURATION, total_dur - curr)
            chunks.append((curr, length))
            curr += CHUNK_DURATION

    total_chunks = len(chunks)
    if progress_callback:
        progress_callback(15.0, f"Extracting audio into {total_chunks} segments...")

    # Step 1: Rapidly extract full audio once (or slices directly) via FFmpeg
    chunk_tasks = []
    temp_files = []

    # First attempt single fast full-audio extraction
    full_audio_temp = video_path.parent / f"{video_path.stem}_full_audio_temp.mp3"
    temp_files.append(full_audio_temp)
    full_cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(video_path.resolve()),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "libmp3lame",
        "-b:a", "64k",
        str(full_audio_temp.resolve()),
    ]
    subprocess.run(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creation_flags)

    has_full_audio = full_audio_temp.exists() and full_audio_temp.stat().st_size > 0

    for chunk_idx, (chunk_start, chunk_len) in enumerate(chunks, start=1):
        temp_chunk_mp3 = video_path.parent / f"{video_path.stem}_chunk_{chunk_idx}_{int(chunk_start)}s.mp3"
        temp_files.append(temp_chunk_mp3)

        if has_full_audio and total_chunks > 1:
            # Fast slicing directly from lightweight compressed audio file
            cmd = [
                ffmpeg_bin,
                "-y",
                "-ss", f"{chunk_start:.3f}",
                "-i", str(full_audio_temp.resolve()),
            ]
            if chunk_len is not None:
                cmd.extend(["-t", f"{chunk_len:.3f}"])
            cmd.extend([
                "-c", "copy",
                str(temp_chunk_mp3.resolve()),
            ])
        else:
            # Slicing directly from video
            cmd = [
                ffmpeg_bin,
                "-y",
                "-ss", f"{chunk_start:.3f}",
                "-i", str(video_path.resolve()),
            ]
            if chunk_len is not None:
                cmd.extend(["-t", f"{chunk_len:.3f}"])
            cmd.extend([
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                "-b:a", "64k",
                str(temp_chunk_mp3.resolve()),
            ])

        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creation_flags)

        if temp_chunk_mp3.exists() and temp_chunk_mp3.stat().st_size > 0:
            with open(temp_chunk_mp3, "rb") as f:
                audio_bytes = f.read()
            chunk_tasks.append((chunk_idx, chunk_start, chunk_len, audio_bytes))

    # Clean up temp files immediately
    for tf in temp_files:
        try:
            if tf.exists():
                tf.unlink()
        except OSError:
            pass

    # Step 2: Concurrent multi-threaded transcription with Gemini
    completed_chunks = 0
    total_valid_chunks = len(chunk_tasks)
    results_map: dict[int, list[SubtitleItem]] = {}
    progress_lock = threading.Lock()

    def _worker_task(task_info):
        nonlocal completed_chunks
        idx, start_s, length_s, a_bytes = task_info
        items = _transcribe_audio_slice_with_gemini(
            audio_bytes=a_bytes,
            api_key=api_key,
            chunk_index=idx,
            total_chunks=total_valid_chunks,
            start_sec=start_s,
        )
        with progress_lock:
            completed_chunks += 1
            if progress_callback and total_valid_chunks > 0:
                pct = 20.0 + (completed_chunks / total_valid_chunks) * 65.0
                progress_callback(
                    pct,
                    f"Transcribing audio with AI ({completed_chunks}/{total_valid_chunks} chunks)...",
                )
        return idx, items

    max_workers = min(8, max(1, total_valid_chunks))
    logger.info(f"Launching {total_valid_chunks} transcription tasks across {max_workers} concurrent threads...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_worker_task, t) for t in chunk_tasks]
        for f in concurrent.futures.as_completed(futures):
            try:
                c_idx, items = f.result()
                results_map[c_idx] = items
            except Exception as e:
                logger.warning(f"Error transcribing chunk: {e}")

    # Assemble in exact chronological order
    all_collected_items: list[SubtitleItem] = []
    for c_idx in sorted(results_map.keys()):
        all_collected_items.extend(results_map[c_idx])

    if not all_collected_items:
        logger.warning("No speech dialogue could be transcribed across any chunk.")
        return []

    # Sanitize, sort, re-index
    all_collected_items.sort(key=lambda x: x.start_seconds)
    for idx, it in enumerate(all_collected_items, start=1):
        it.index = idx

    # ── Filter out non-speech artifacts: [1], [០], [♪], (music), standalone digits, etc.
    # Also drop zero/micro duration entries (< 0.3s) which are always spurious
    before_filter = len(all_collected_items)
    all_collected_items = [
        it for it in all_collected_items
        if not _is_noise_artifact(it.text) and it.duration_seconds >= 0.3
    ]
    if len(all_collected_items) < before_filter:
        logger.info(f"Filtered {before_filter - len(all_collected_items)} noise/non-speech artifacts from transcript.")

    # ── Normalize & auto-align dialogue timestamps to fit video duration ──────
    if total_dur > 0 and all_collected_items:
        min_start = all_collected_items[0].start_seconds
        max_end = max((it.end_seconds for it in all_collected_items), default=0.0)

        # If Gemini offset the entire dialogue (e.g. starting at 100s for a 60s clip)
        if min_start >= (total_dur * 0.7) or (min_start > 20.0 and total_dur <= 180.0):
            shift_amount = max(0.0, min_start - 0.8)
            logger.info(
                f"Auto-aligning timestamps: shifting dialogue start from {min_start:.1f}s to 0.8s (video duration {total_dur:.1f}s)"
            )
            for it in all_collected_items:
                dur = it.duration_seconds
                it.start_seconds = max(0.0, it.start_seconds - shift_amount)
                it.end_seconds = it.start_seconds + dur
                it.start_time = seconds_to_timestamp(it.start_seconds)
                it.end_time = seconds_to_timestamp(it.end_seconds)

        # If timestamps still exceed video duration, scale timestamps proportionally to fit video bounds
        if all_collected_items and all_collected_items[-1].end_seconds > (total_dur * 1.05):
            last_end = all_collected_items[-1].end_seconds
            first_start = all_collected_items[0].start_seconds
            current_span = max(1.0, last_end - first_start)
            target_span = max(1.0, total_dur - first_start - 0.5)
            scale_factor = target_span / current_span
            if 0.15 < scale_factor < 1.0:
                logger.info(f"Scaling dialogue timestamps by {scale_factor:.2f}x to fit video duration {total_dur:.1f}s")
                for it in all_collected_items:
                    rel_s = it.start_seconds - first_start
                    rel_e = it.end_seconds - first_start
                    it.start_seconds = first_start + (rel_s * scale_factor)
                    it.end_seconds = first_start + (rel_e * scale_factor)
                    it.start_time = seconds_to_timestamp(it.start_seconds)
                    it.end_time = seconds_to_timestamp(it.end_seconds)

        # Final safety cleanup for any impossible outlier timestamp
        max_allowed_ts = total_dur * 1.25 + 15.0
        ts_before = len(all_collected_items)
        all_collected_items = [it for it in all_collected_items if it.start_seconds <= max_allowed_ts]
        if len(all_collected_items) < ts_before:
            logger.info(f"Trimmed {ts_before - len(all_collected_items)} stray items beyond video bounds.")

    for idx, it in enumerate(all_collected_items, start=1):
        it.index = idx

    # Split overly long blocks (> 8s)
    items = _split_long_items(all_collected_items, max_block_dur=8.0)

    # ── Translation pass: STT outputs Chinese characters → translate to Khmer
    # Since the STT prompt now transcribes Chinese (not translates), we always need this pass.
    all_text = " ".join(it.text for it in items)
    total_letters = len([c for c in all_text if c.isalnum() or "\u1780" <= c <= "\u17ff"])
    khmer_letters = len([c for c in all_text if "\u1780" <= c <= "\u17ff"])
    chinese_letters = len([c for c in all_text if "\u4e00" <= c <= "\u9fff"])
    ratio = (khmer_letters / total_letters) if total_letters > 0 else 0
    has_chinese = chinese_letters > 0
    has_thai_script = bool(re.search(r"[\u0e00-\u0e7f]", all_text))

    # Always translate if less than 85% Khmer OR Chinese/Thai script detected
    needs_translation = ratio < 0.85 or has_chinese or has_thai_script

    if needs_translation:
        logger.info(
            f"Transcribed {len(items)} dialogue items ({ratio*100:.1f}% Khmer, "
            f"chinese_chars={chinese_letters}, has_thai={has_thai_script}). "
            f"Running Chinese→Khmer semantic translation pass..."
        )
        if progress_callback:
            progress_callback(88.0, f"Translating {len(items)} Chinese dialogue lines to Khmer...")
        from downloader_app.core.translator import Translator
        translator = Translator()
        raw_texts = [it.text for it in items]
        translated_texts = translator.translate_subtitle_blocks(raw_texts, target_lang="km")

        if len(translated_texts) > len(items) and len(items) > 0:
            logger.info(
                f"Translation expanded {len(items)} items into {len(translated_texts)} individual sentences. Redistributing timeline..."
            )
            total_start = items[0].start_seconds
            total_end = items[-1].end_seconds
            natural_durations = [max(1.8, min(7.0, len(t) * 0.12)) for t in translated_texts]
            min_needed_span = sum(natural_durations)
            total_span = max(total_end - total_start, min_needed_span)
            total_chars = sum(max(1, len(t)) for t in translated_texts)

            expanded_items = []
            curr_s = total_start
            for idx_t, (t_str, nat_dur) in enumerate(zip(translated_texts, natural_durations), start=1):
                char_ratio = max(1, len(t_str)) / total_chars
                seg_dur = max(nat_dur, char_ratio * total_span)
                seg_end = curr_s + seg_dur
                expanded_items.append(
                    SubtitleItem(
                        index=idx_t,
                        start_time=seconds_to_timestamp(curr_s),
                        end_time=seconds_to_timestamp(seg_end),
                        start_seconds=curr_s,
                        end_seconds=seg_end,
                        text=t_str,
                    )
                )
                curr_s = seg_end
            items = expanded_items
        else:
            for idx, it in enumerate(items):
                if idx < len(translated_texts) and translated_texts[idx]:
                    it.text = translated_texts[idx]

        # Post-translation sentence splitting pass (in case translated text contains multiple Khmer sentences)
        items = _split_long_items(items, max_block_dur=8.0)
        for idx, it in enumerate(items, start=1):
            it.index = idx

        # ── Final Khmer purity sweep ──────────────────────────────────────────────
        # Any item still containing Chinese/Thai after translation gets one more GTX attempt
        from downloader_app.core.translator import has_cjk, has_thai, is_valid_target_text
        dirty_items = [it for it in items if has_cjk(it.text) or has_thai(it.text)]
        if dirty_items:
            logger.warning(f"Final purity sweep: {len(dirty_items)} items still contain Chinese/Thai — applying GTX cleanup...")
            for it in dirty_items:
                gtx = translator._translate_gtx(it.text, target_lang="km")
                if gtx and is_valid_target_text(gtx, "km"):
                    it.text = gtx
                else:
                    # Strip all non-Khmer characters as absolute last resort
                    khmer_only = re.sub(
                        r"[^\u1780-\u17FF\u200B\u200C\u200D\s\.,!?\-:;។៕]",
                        "", it.text
                    ).strip()
                    it.text = khmer_only if khmer_only else ""

        # Drop items whose text ended up empty after cleanup
        items = [it for it in items if it.text.strip()]
        for idx, it in enumerate(items, start=1):
            it.index = idx

        logger.info(f"Successfully converted {len(items)} dialogue lines to 100% Khmer.")

    # Save persistent Khmer SRT cache file
    khmer_srt_file = video_path.parent / f"{video_path.stem}_KhmerDub.srt"
    try:
        with open(khmer_srt_file, "w", encoding="utf-8") as f:
            f.write(format_srt_content(items))
        logger.info(f"Saved persistent Khmer SRT cache file: {khmer_srt_file.name}")
    except Exception as ex_cache:
        logger.warning(f"Failed to save persistent Khmer SRT cache: {ex_cache}")

    if progress_callback:
        progress_callback(100.0, f"Speech transcription complete ({len(items)} dialogue lines).")
    return items


class SubtitleExtractorWorker(QThread):
    """QThread worker to extract embedded subtitle tracks from video files via FFmpeg or custom SRT."""

    finished = pyqtSignal(list)  # List of SubtitleItem
    error = pyqtSignal(str)
    progress_changed = pyqtSignal(float, str)  # percent, status message

    def __init__(
        self,
        video_path: str,
        srt_path: str | None = None,
        ignore_sidecar: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.video_path = Path(video_path)
        self.srt_path = Path(srt_path) if srt_path and str(srt_path).strip() else None
        self.ignore_sidecar = ignore_sidecar

    def run(self) -> None:
        self.progress_changed.emit(5.0, "Reading subtitle file / video track...")
        # Priority 1: Explicitly provided custom SRT path
        if self.srt_path:
            if self.srt_path.exists():
                try:
                    with open(self.srt_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    items = parse_srt_content(content)
                    if items:
                        self.progress_changed.emit(100.0, "Custom subtitle file loaded successfully.")
                        self.finished.emit(items)
                        return
                    else:
                        self.error.emit(f"Subtitle file is empty or invalid format: {self.srt_path.name}")
                        return
                except Exception as e:
                    self.error.emit(f"Failed to read custom SRT file: {e}")
                    return
            else:
                self.error.emit(f"Specified subtitle file not found: {self.srt_path}")
                return

        if not self.video_path.exists():
            self.error.emit(f"Video file not found: {self.video_path}")
            return

        ffmpeg_bin = get_ffmpeg_path()
        if ffmpeg_bin:
            self.progress_changed.emit(15.0, "Checking embedded subtitle track...")
            # Priority 2: Attempt to extract embedded subtitle track 0 to temporary srt file
            out_srt = self.video_path.parent / f"{self.video_path.stem}_temp_sub.srt"
            cmd = [
                ffmpeg_bin,
                "-y",
                "-i",
                str(self.video_path.resolve()),
                "-map",
                "0:s:0",
                str(out_srt),
            ]

            try:
                res = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )

                if out_srt.exists() and out_srt.stat().st_size > 0:
                    with open(out_srt, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    try:
                        out_srt.unlink()
                    except OSError:
                        pass
                    items = parse_srt_content(content)
                    if items:
                        self.progress_changed.emit(100.0, "Embedded subtitle track extracted.")
                        self.finished.emit(items)
                        return
            except Exception as e:
                logger.debug(f"Embedded subtitle extraction exception: {e}")

        # Priority 3: check for sidecar .srt files in same folder (if sidecars are not ignored)
        if not self.ignore_sidecar:
            self.progress_changed.emit(20.0, "Checking sidecar subtitle files...")
            candidates = [
                self.video_path.parent / f"{self.video_path.stem}_KhmerDub.srt",
                self.video_path.with_suffix(".srt"),
                self.video_path.parent / f"{self.video_path.stem}.km.srt",
            ]
            for sidecar_srt in candidates:
                if sidecar_srt.exists():
                    try:
                        with open(sidecar_srt, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                        items = parse_srt_content(content)
                        if items:
                            self.progress_changed.emit(100.0, f"Sidecar subtitle file loaded ({sidecar_srt.name}).")
                            self.finished.emit(items)
                            return
                    except OSError as e:
                        logger.warning(f"Failed to read sidecar SRT {sidecar_srt.name}: {e}")

        # Priority 4: Gemini AI Speech-to-Text — listens to the real spoken dialogue in the video
        # and returns a timed Khmer-translated SRT based on what humans actually say in the video.
        self.progress_changed.emit(25.0, "Listening to spoken dialogue with Gemini AI...")
        logger.info("No subtitle file found. Using Gemini AI to listen to real spoken dialogue...")

        def _on_stt_progress(pct: float, msg: str):
            self.progress_changed.emit(pct, msg)

        ai_transcribed_items = transcribe_video_audio_to_subtitles(
            self.video_path, target_lang="km", progress_callback=_on_stt_progress
        )
        if ai_transcribed_items:
            logger.info(
                f"Gemini AI transcribed {len(ai_transcribed_items)} real spoken dialogue lines from video."
            )
            self.progress_changed.emit(100.0, "Speech transcription complete.")
            self.finished.emit(ai_transcribed_items)
            return

        # No real speech could be extracted — tell the user clearly
        self.error.emit(
            "Could not transcribe real spoken dialogue from this video.\n\n"
            "This may happen if:\n"
            "• The video has no audible speech\n"
            "• The Gemini AI API key is missing or invalid\n"
            "• The audio could not be read by FFmpeg\n\n"
            "Please select a subtitle (.srt) file that matches this video's spoken dialogue, "
            "then try again."
        )

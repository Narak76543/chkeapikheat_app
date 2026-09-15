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
            # Normalize trailing commas and stray punctuation
            text = re.sub(r"[\,\，\;\；\、\s]+$", "", text).strip()
            if not text:
                continue

            try:
                from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
                text = clean_khmer_dialogue_typos(text)
            except Exception:
                pass

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
                try:
                    from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
                    text = clean_khmer_dialogue_typos(text)
                except Exception:
                    pass
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
    try:
        from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
    except ImportError:
        clean_khmer_dialogue_typos = lambda t: t

    blocks = []
    for i, item in enumerate(items, start=1):
        start_ts = seconds_to_timestamp(item.start_seconds)
        end_ts = seconds_to_timestamp(item.end_seconds)
        clean_text = clean_khmer_dialogue_typos(item.text) if item.text else ""
        blocks.append(f"{i}\n{start_ts} --> {end_ts}\n{clean_text}\n")
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

    # If a sentence is long (> 26 chars for CJK or > 45 chars for other scripts) and has comma/clause delimiters, split further
    final_sentences = []
    for s in sentences:
        is_cjk = any("\u4e00" <= c <= "\u9fff" for c in s)
        max_clause_len = 26 if is_cjk else 45
        if len(s) > max_clause_len and any(c in s for c in "，,;；、\t"):
            clause_parts = [p.strip() for p in re.split(r"([，,;；、\t]+)", s) if p.strip()]
            c_curr = ""
            for cp in clause_parts:
                if re.match(r"^[，,;；、\t]+$", cp):
                    c_curr += cp
                    min_chunk = 8 if is_cjk else 14
                    if len(c_curr.strip()) > min_chunk:
                        final_sentences.append(c_curr.strip())
                        c_curr = ""
                else:
                    min_chunk = 8 if is_cjk else 14
                    if c_curr.strip() and len(c_curr.strip()) > min_chunk:
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

        # Only split into separate items if each dialogue sentence has adequate speaking time (>= 1.5s each)
        if len(sentences) > 1 and it.duration_seconds >= (len(sentences) * 1.5):
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


_PREFERRED_STT_MODEL: str | None = "gemini-3.1-flash-lite"
ACTIVE_STT_MODELS: list[str] = [
    "gemini-3.1-flash-lite",       # Fast, high-accuracy multimodal STT with high available free-tier quota
    "gemini-3.1-flash-lite-preview",# Stable fallback with fresh quota
    "gemini-3-flash-preview",     # Alternate multimodal preview with fresh quota
    "gemini-3.5-flash-lite",       # Standard flash-lite
    "gemini-flash-lite-latest",   # Stable latest flash-lite
    "gemini-3.5-flash",           # High capacity multimodal audio model
    "gemini-3.6-flash",           # Next-gen high capacity flash
    "gemini-flash-latest",        # Latest stable flash
    "gemini-3.7-flash",           # Extended context model
    "gemini-3.8-flash",           # Ultra-high capability multimodal
]


def _transcribe_audio_slice_with_gemini(
    audio_bytes: bytes,
    api_key: str,
    chunk_index: int,
    total_chunks: int,
    start_sec: float,
) -> list[SubtitleItem]:
    """Transcribes audio with Gemini AI using multi-model resilience, exponential backoff, and full-duration coverage."""
    global _PREFERRED_STT_MODEL, ACTIVE_STT_MODELS
    if not audio_bytes or not api_key:
        return []

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    prompt = (
        "You are an elite Chinese speech-to-text transcription engine for movie, drama, and video dialogue.\n"
        "The audio contains Chinese (Mandarin) speech.\n"
        "YOUR TASK: Transcribe EVERY SINGLE spoken sentence, dialogue turn, and character conversation with 100% completeness from the very start (00:00.00) to the very end of this audio.\n"
        "\n"
        "CRITICAL RULES:\n"
        "1. Transcribe ALL dialogue spoken by every actor/character across the entire audio duration. Do NOT stop transcribing early.\n"
        "2. Transcribe in Simplified Chinese characters (中文字幕). Do NOT translate into English or Khmer.\n"
        "3. Accurately capture dialogue turns with precise start and end timestamps matching the audio playback.\n"
        "4. Break dialogue naturally into individual spoken lines (typically 1.5–6.0 seconds per line).\n"
        "5. Do NOT skip fast dialogue, quiet speech, emotional shouts, or conversational responses.\n"
        "6. Do NOT output annotations like [音乐], [笑声], [♪], [1], or descriptions of sounds.\n"
        "7. Output STRICT standard numbered SRT format ONLY:\n"
        "   INDEX\n"
        "   HH:MM:SS,mmm --> HH:MM:SS,mmm\n"
        "   Chinese text\n"
        "\n"
        "Example:\n"
        "1\n"
        "00:00:01,200 --> 00:00:03,800\n"
        "你怎么现在才回来？\n"
        "\n"
        "2\n"
        "00:00:04,100 --> 00:00:06,500\n"
        "路上有点事情耽搁了。\n"
        "\n"
        "Output ONLY raw numbered SRT format. No markdown codeblocks, no extra explanations."
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
            "maxOutputTokens": 8192,
        },
    }

    models_to_try = []
    if _PREFERRED_STT_MODEL and _PREFERRED_STT_MODEL in ACTIVE_STT_MODELS:
        models_to_try.append(_PREFERRED_STT_MODEL)
    for m in ACTIVE_STT_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    for model_name in models_to_try:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        for attempt in range(3):
            try:
                logger.info(
                    f"Sending audio segment {chunk_index}/{total_chunks} ({len(audio_bytes) // 1024} KB) to Gemini ({model_name}, attempt {attempt+1})..."
                )
                resp = requests.post(endpoint, json=payload, timeout=60)
                logger.info(f"Gemini ({model_name}) segment {chunk_index} response status: {resp.status_code}")

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
                                # Smart timestamp offset: only offset if timestamps are relative to segment start
                                if start_sec > 0:
                                    min_s = min(it.start_seconds for it in chunk_items)
                                    if min_s < (start_sec * 0.5):
                                        for it in chunk_items:
                                            it.start_seconds += start_sec
                                            it.end_seconds += start_sec
                                            it.start_time = seconds_to_timestamp(it.start_seconds)
                                            it.end_time = seconds_to_timestamp(it.end_seconds)

                                logger.info(
                                    f"Segment {chunk_index}/{total_chunks} extracted {len(chunk_items)} lines (from {start_sec:.1f}s to {chunk_items[-1].end_seconds:.1f}s)."
                                )
                                return chunk_items
                            else:
                                logger.info(f"Segment {chunk_index}/{total_chunks} returned no speech dialogue.")
                                return []
                elif resp.status_code in (404, 400):
                    logger.warning(
                        f"Gemini model '{model_name}' returned HTTP {resp.status_code}. Trying next model..."
                    )
                    break
                elif resp.status_code in (429, 503):
                    sleep_dur = 2.0 * (attempt + 1)
                    logger.warning(
                        f"Gemini ({model_name}) busy/quota (HTTP {resp.status_code}). Waiting {sleep_dur:.1f}s before retry..."
                    )
                    time.sleep(sleep_dur)
                    continue
                else:
                    logger.warning(f"Gemini ({model_name}) error HTTP {resp.status_code}: {resp.text[:200]}")
                    break
            except requests.exceptions.Timeout:
                logger.warning(f"Gemini ({model_name}) timed out on segment {chunk_index}, trying next model...")
                break
            except Exception as e:
                logger.warning(f"Gemini ({model_name}) segment {chunk_index} error: {e}")
                break

    return []


def transcribe_video_audio_to_subtitles(
    video_path: Path, target_lang: str = "km", progress_callback=None
) -> list[SubtitleItem]:
    """
    Extracts audio using FFmpeg and transcribes Chinese speech dialogue with Gemini Multimodal AI.
    For videos up to 8 minutes: transcribes in one seamless continuous audio stream to ensure 100% coverage
    of every actor speak from beginning to the very last second without any chunk cutoffs.
    For full movies (> 8 mins): uses large overlapping segments with rate-limit resilient execution.
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

    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    # Optimal segmentation strategy:
    # 1. Videos <= 8 minutes (480s): 1 single continuous audio stream ensures 100% uninterrupted dialogue capture
    # 2. Videos > 8 minutes: 240s (4 min) segments with 8s overlap to maintain speech continuity
    if total_dur <= 480.0:
        chunks = [(0.0, total_dur if total_dur > 0.0 else None)]
    else:
        CHUNK_DURATION = 240.0
        OVERLAP = 8.0
        chunks = []
        curr = 0.0
        while curr < total_dur:
            length = min(CHUNK_DURATION, total_dur - curr)
            chunks.append((curr, length))
            curr += (CHUNK_DURATION - OVERLAP)

    total_chunks = len(chunks)
    if progress_callback:
        progress_callback(15.0, f"Extracting audio track ({total_chunks} segment{'s' if total_chunks > 1 else ''})...")

    # Step 1: Rapidly extract high-clarity vocal audio via FFmpeg
    chunk_tasks = []
    temp_files = []

    for chunk_idx, (chunk_start, chunk_len) in enumerate(chunks, start=1):
        temp_chunk_mp3 = video_path.parent / f"{video_path.stem}_audio_seg_{chunk_idx}_{int(chunk_start)}s.mp3"
        temp_files.append(temp_chunk_mp3)

        cmd = [
            ffmpeg_bin,
            "-y",
        ]
        if chunk_start > 0:
            cmd.extend(["-ss", f"{chunk_start:.3f}"])
        cmd.extend([
            "-i", str(video_path.resolve()),
        ])
        if chunk_len is not None and total_chunks > 1:
            cmd.extend(["-t", f"{chunk_len:.3f}"])
        cmd.extend([
            "-vn",
            "-af", "highpass=f=80,lowpass=f=8000,volume=1.3",
            "-ac", "1",
            "-ar", "24000",
            "-c:a", "libmp3lame",
            "-b:a", "96k",
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

    # Step 2: Concurrent transcription with Gemini AI
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
                    f"Listening & transcribing dialogue ({completed_chunks}/{total_valid_chunks})...",
                )
        return idx, items

    max_workers = min(3, max(1, total_valid_chunks))
    logger.info(f"Launching {total_valid_chunks} transcription tasks across {max_workers} worker threads...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_worker_task, t) for t in chunk_tasks]
        for f in concurrent.futures.as_completed(futures):
            try:
                c_idx, items = f.result()
                results_map[c_idx] = items
            except Exception as e:
                logger.warning(f"Error transcribing segment: {e}")

    # Assemble in exact chronological order
    all_collected_items: list[SubtitleItem] = []
    for c_idx in sorted(results_map.keys()):
        all_collected_items.extend(results_map[c_idx])

    if not all_collected_items:
        logger.warning("No speech dialogue could be transcribed across any segment.")
        return []

    # Sanitize, sort, re-index
    all_collected_items.sort(key=lambda x: x.start_seconds)
    for idx, it in enumerate(all_collected_items, start=1):
        it.index = idx

    # Filter out non-speech noise artifacts
    before_filter = len(all_collected_items)
    all_collected_items = [
        it for it in all_collected_items
        if not _is_noise_artifact(it.text) and it.duration_seconds >= 0.3
    ]
    if len(all_collected_items) < before_filter:
        logger.info(f"Filtered {before_filter - len(all_collected_items)} noise/non-speech artifacts from transcript.")

    # Clamp dialogue timestamps cleanly to video duration without distorting timeline
    if total_dur > 0 and all_collected_items:
        cleaned_items = []
        for it in all_collected_items:
            if it.start_seconds < total_dur:
                if it.end_seconds > total_dur:
                    it.end_seconds = total_dur
                    it.end_time = seconds_to_timestamp(it.end_seconds)
                cleaned_items.append(it)
        all_collected_items = cleaned_items

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

        if target_lang == "km" and translated_texts:
            if progress_callback:
                progress_callback(93.0, f"Polishing & Correcting Khmer Grammar ({len(translated_texts)} lines)...")
            try:
                from downloader_app.core.grammar_corrector import correct_khmer_dialogue_grammar
                translated_texts = correct_khmer_dialogue_grammar(translated_texts, progress_callback=progress_callback)
            except Exception as e:
                logger.warning(f"Khmer grammar correction step error: {e}")

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

        # Priority 3: check for sidecar subtitle files (.srt, .vtt) in same folder
        if not self.ignore_sidecar:
            self.progress_changed.emit(20.0, "Checking sidecar subtitle files...")
            stem = self.video_path.stem
            parent = self.video_path.parent
            candidates = [
                parent / f"{stem}_KhmerDub.srt",
                self.video_path.with_suffix(".srt"),
                parent / f"{stem}.km.srt",
                parent / f"{stem}.zh-Hans.srt",
                parent / f"{stem}.zh-Hant.srt",
                parent / f"{stem}.zh.srt",
                parent / f"{stem}.en.srt",
                self.video_path.with_suffix(".vtt"),
                parent / f"{stem}.zh-Hans.vtt",
                parent / f"{stem}.zh-Hant.vtt",
                parent / f"{stem}.zh.vtt",
                parent / f"{stem}.en.vtt",
            ]
            # Glob for any srt or vtt matching video stem
            for ext_pattern in (f"{stem}*.srt", f"{stem}*.vtt"):
                for matched in parent.glob(ext_pattern):
                    if matched not in candidates:
                        candidates.append(matched)

            for sidecar_srt in candidates:
                if sidecar_srt.exists():
                    try:
                        with open(sidecar_srt, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                        items = parse_srt_content(content)
                        if items:
                            self.progress_changed.emit(100.0, f"Sidecar subtitle loaded ({sidecar_srt.name}).")
                            self.finished.emit(items)
                            return
                    except OSError as e:
                        logger.warning(f"Failed to read sidecar subtitle {sidecar_srt.name}: {e}")

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


def _parse_gemini_vision_fallback_lines(
    raw_text: str,
    interval_sec: float,
    batch_start_idx: int,
    batch_size: int,
) -> list[SubtitleItem]:
    """
    Fallback parser when Gemini Vision AI outputs list-style, bulleted, or conversational frames
    instead of strict SRT format.
    """
    if not raw_text or not raw_text.strip():
        return []

    from downloader_app.core.translator import has_cjk

    items: list[SubtitleItem] = []
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

    frame_pat = re.compile(r"Frame\s*#?\s*(\d+).*?[:\-]\s*(.*)", re.IGNORECASE)
    ts_pat = re.compile(r"\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[\.,]\d{1,3})?)\]?[\s:\-]+(.*)")

    for line in lines:
        m_frame = frame_pat.search(line)
        if m_frame:
            f_num = int(m_frame.group(1))
            txt = m_frame.group(2).strip()
            txt = re.sub(r"^\*+|\*+$", "", txt).strip()
            if txt and has_cjk(txt) and not txt.lower().startswith("none") and not txt.lower().startswith("no subtitle"):
                t_sec = (f_num - 1) * interval_sec
                items.append(SubtitleItem(
                    index=len(items) + 1,
                    start_time=seconds_to_timestamp(t_sec),
                    end_time=seconds_to_timestamp(t_sec + interval_sec),
                    start_seconds=t_sec,
                    end_seconds=t_sec + interval_sec,
                    text=txt,
                ))
            continue

        m_ts = ts_pat.search(line)
        if m_ts:
            ts_str = m_ts.group(1).strip()
            txt = m_ts.group(2).strip()
            txt = re.sub(r"^\*+|\*+$", "", txt).strip()
            if txt and has_cjk(txt):
                t_sec = timestamp_to_seconds(ts_str)
                items.append(SubtitleItem(
                    index=len(items) + 1,
                    start_time=seconds_to_timestamp(t_sec),
                    end_time=seconds_to_timestamp(t_sec + interval_sec),
                    start_seconds=t_sec,
                    end_seconds=t_sec + interval_sec,
                    text=txt,
                ))
            continue

    if not items:
        valid_cjk_lines = []
        for line in lines:
            cleaned = re.sub(r"^[\*\-\d\.\)\s]+", "", line).strip()
            cleaned = re.sub(r"^\*+|\*+$", "", cleaned).strip()
            if cleaned and has_cjk(cleaned) and len(cleaned) <= 60:
                valid_cjk_lines.append(cleaned)

        if valid_cjk_lines:
            for idx, cjk_txt in enumerate(valid_cjk_lines):
                t_sec = (batch_start_idx + idx) * interval_sec
                items.append(SubtitleItem(
                    index=len(items) + 1,
                    start_time=seconds_to_timestamp(t_sec),
                    end_time=seconds_to_timestamp(t_sec + interval_sec),
                    start_seconds=t_sec,
                    end_seconds=t_sec + interval_sec,
                    text=cjk_txt,
                ))

    return items


def extract_subtitles_via_vision_ocr(
    video_path: Path,
    target_lang: str = "km",
    crop_box_ratio: tuple[float, float, float, float] | None = None,
    progress_callback=None,
) -> list[SubtitleItem]:
    """
    Extracts hardcoded Chinese subtitles directly from video screen frames using FFmpeg crop + Gemini Vision AI.
    Ideal for short dramas (抖音短剧) and 1h-3h movies with burned-in subtitles.
    """
    import tempfile
    import shutil
    from downloader_app.core.translator import get_api_key, Translator, has_cjk

    api_key = get_api_key()
    ffmpeg_bin = get_ffmpeg_path()
    if not api_key or not ffmpeg_bin or not video_path.exists():
        logger.warning("Vision OCR failed: missing API key, FFmpeg, or video path.")
        return []

    if progress_callback:
        progress_callback(5.0, "Analyzing video duration for Vision OCR...")

    total_dur = get_video_duration_ffmpeg(video_path)
    if total_dur <= 0.0:
        total_dur = 600.0

    # Determine frame sampling interval based on video duration
    # Tight 1.0s - 1.25s intervals ensure no fast-spoken Chinese dialogue is skipped and timestamps align accurately
    if total_dur <= 1800.0:
        interval_sec = 1.0
    elif total_dur <= 3600.0:
        interval_sec = 1.25
    else:
        interval_sec = 1.5

    fps_val = 1.0 / interval_sec

    # Default crop box: bottom 40% region [x_ratio, y_ratio, w_ratio, h_ratio]
    # Covers y from 0.58 to 0.98 so subtitles in vertical (Douyin/Reels) and horizontal videos are fully captured
    if not crop_box_ratio:
        crop_box_ratio = (0.01, 0.58, 0.98, 0.40)

    x_ratio, y_ratio, w_ratio, h_ratio = crop_box_ratio
    crop_filter = f"crop=in_w*{w_ratio:.3f}:in_h*{h_ratio:.3f}:in_w*{x_ratio:.3f}:in_h*{y_ratio:.3f},fps={fps_val:.4f}"

    if progress_callback:
        progress_callback(10.0, "Sampling subtitle region frames from video...")

    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    with tempfile.TemporaryDirectory(prefix="sub_ocr_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        out_pattern = str(tmp_dir / "frame_%05d.jpg")

        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss",
            "0",
            "-i",
            str(video_path.resolve()),
            "-vf",
            crop_filter,
            "-q:v",
            "3",
            out_pattern,
        ]

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creation_flags,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(300, int(total_dur * 0.25)),
            )
        except Exception as e:
            logger.error(f"FFmpeg frame extraction error for Vision OCR: {e}")
            return []

        frame_files = sorted(tmp_dir.glob("frame_*.jpg"))
        if not frame_files:
            logger.warning("No frame images extracted for Vision OCR.")
            return []

        total_frames = len(frame_files)
        logger.info(f"Extracted {total_frames} cropped frame snapshots for Vision OCR.")

        if progress_callback:
            progress_callback(30.0, f"Scanning {total_frames} frames with Gemini Vision AI...")

        # Batch frames (15 frames per batch) to Gemini Vision API
        BATCH_SIZE = 15
        all_ocr_items: list[SubtitleItem] = []
        had_quota_error = False

        for batch_start_idx in range(0, total_frames, BATCH_SIZE):
            batch_files = frame_files[batch_start_idx : batch_start_idx + BATCH_SIZE]
            parts = []

            for i, fpath in enumerate(batch_files):
                frame_idx = batch_start_idx + i + 1
                t_sec = (frame_idx - 1) * interval_sec
                t_str = seconds_to_timestamp(t_sec)

                # Smooth 1-by-1 frame progress feedback
                pct = 30.0 + ((frame_idx - 1) / total_frames) * 50.0
                if progress_callback:
                    progress_callback(pct, f"OCR Scanning frame {frame_idx} of {total_frames} ({t_str[:8]})")
                time.sleep(0.015)

                try:
                    with open(fpath, "rb") as img_f:
                        img_b64 = base64.b64encode(img_f.read()).decode("utf-8")

                    parts.append(
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": img_b64,
                            }
                        }
                    )
                    parts.append({"text": f"Frame #{frame_idx} (Timestamp: {t_str})"})
                except OSError as e:
                    logger.warning(f"Failed to read frame image {fpath.name}: {e}")

            if not parts:
                continue

            prompt = (
                "YOUR TASK: Perform high-accuracy OCR on the hardcoded Chinese subtitles shown in these sequential video frame images.\n"
                "CRITICAL REQUIREMENTS FOR 100% TIMING ACCURACY:\n"
                "1. Examine EVERY frame carefully in chronological order. Do NOT skip any frame with Chinese subtitle text.\n"
                "2. For each subtitle line, use the timestamp of the FIRST frame it appears as the start time, and the timestamp of the LAST frame it is visible as the end time.\n"
                "3. If a subtitle is visible in only a single frame at timestamp T, set start time to T and end time to T + 1.5s.\n"
                "4. Output STRICT standard numbered SRT format ONLY:\n"
                "   INDEX\n"
                "   HH:MM:SS,mmm --> HH:MM:SS,mmm\n"
                "   Exact Chinese subtitle text\n\n"
                "Output pure numbered SRT format ONLY. No extra text, explanation, or markdown."
            )
            parts.append({"text": prompt})

            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": 0.0,
                    "topP": 0.1,
                    "maxOutputTokens": 8192,
                },
            }

            cur_last_frame = min(total_frames, batch_start_idx + len(batch_files))
            pct = 30.0 + (cur_last_frame / total_frames) * 50.0
            if progress_callback:
                progress_callback(pct, f"OCR Scanning frame {cur_last_frame} of {total_frames}...")

            batch_succeeded = False
            for retry_attempt in range(4):
                for model_name in ACTIVE_STT_MODELS:
                    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                    try:
                        resp = requests.post(endpoint, json=payload, timeout=60)
                        if resp.status_code == 200:
                            cands = resp.json().get("candidates", [])
                            if cands:
                                res_parts = cands[0].get("content", {}).get("parts", [])
                                if res_parts:
                                    raw_text = res_parts[0].get("text", "").strip()
                                    raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text)
                                    raw_text = re.sub(r"\n?```$", "", raw_text).strip()
                                    batch_items = parse_srt_content(raw_text)
                                    if not batch_items:
                                        batch_items = _parse_gemini_vision_fallback_lines(
                                            raw_text=raw_text,
                                            interval_sec=interval_sec,
                                            batch_start_idx=batch_start_idx,
                                            batch_size=len(batch_files),
                                        )
                                    if batch_items:
                                        all_ocr_items.extend(batch_items)
                                    batch_succeeded = True
                                    break
                        elif resp.status_code == 429:
                            had_quota_error = True
                            logger.warning(f"Vision OCR model '{model_name}' rate limited (HTTP 429 Quota Exceeded), trying next model...")
                            time.sleep(1.5)
                            continue
                        elif resp.status_code in (500, 503):
                            logger.warning(f"Vision OCR model '{model_name}' temporary server error (HTTP {resp.status_code}), retrying...")
                            time.sleep(2.0)
                            continue
                        else:
                            logger.warning(f"Vision OCR model '{model_name}' returned HTTP {resp.status_code}: {resp.text[:100]}")
                    except Exception as e:
                        logger.warning(f"Vision OCR batch error on model {model_name}: {e}")
                        continue

                if batch_succeeded:
                    break
                if had_quota_error and retry_attempt < 3:
                    backoff_sec = 4.0 * (retry_attempt + 1)
                    if progress_callback:
                        progress_callback(pct, f"Rate limit reached, pausing {int(backoff_sec)}s before retrying batch {batch_start_idx//BATCH_SIZE + 1}...")
                    time.sleep(backoff_sec)
                else:
                    break

            # Pacing delay between batches to stay within free-tier API rate limits
            time.sleep(1.0)

        if not all_ocr_items:
            if had_quota_error:
                raise RuntimeError(
                    "Gemini AI API Quota Exceeded (HTTP 429 Rate Limit).\n\n"
                    "Your Gemini API free-tier request quota was temporarily reached. "
                    "Please wait 30-60 seconds, or configure an alternate/paid API key in Settings."
                )
            logger.warning("No subtitle text extracted from frames via Vision OCR.")
            return []

        # Sort items chronologically by start time
        all_ocr_items.sort(key=lambda x: x.start_seconds)

        # Merge duplicate consecutive items with gap and overlap constraints
        merged_items: list[SubtitleItem] = []
        for item in all_ocr_items:
            clean_txt = item.text.strip()
            if not clean_txt:
                continue
            if not merged_items:
                merged_items.append(item)
            else:
                last = merged_items[-1]
                # Merge if identical text AND gap between last end and item start is small (<= 1.5 * interval_sec)
                if last.text.strip() == clean_txt and (item.start_seconds - last.end_seconds) <= (interval_sec * 1.5):
                    last.end_seconds = max(last.end_seconds, item.end_seconds)
                    last.end_time = seconds_to_timestamp(last.end_seconds)
                else:
                    # Prevent overlap: clamp last.end_seconds if it spills into item.start_seconds
                    if item.start_seconds < last.end_seconds:
                        last.end_seconds = max(last.start_seconds + 0.6, item.start_seconds)
                        last.end_time = seconds_to_timestamp(last.end_seconds)
                    item.index = len(merged_items) + 1
                    merged_items.append(item)

        if progress_callback:
            progress_callback(85.0, f"Translating {len(merged_items)} OCR subtitles into Khmer...")

        # Translate extracted Chinese subtitles into Khmer
        translator = Translator()
        raw_texts = [it.text for it in merged_items]
        translated_texts = translator.translate_subtitle_blocks(raw_texts, target_lang=target_lang)

        if target_lang == "km" and translated_texts:
            if progress_callback:
                progress_callback(90.0, f"Polishing & Correcting Khmer Grammar ({len(translated_texts)} lines)...")
            try:
                from downloader_app.core.grammar_corrector import correct_khmer_dialogue_grammar, clean_khmer_dialogue_typos
                translated_texts = correct_khmer_dialogue_grammar(translated_texts, progress_callback=progress_callback)
            except Exception as e:
                logger.warning(f"Khmer grammar correction step error: {e}")

        from downloader_app.core.grammar_corrector import clean_khmer_dialogue_typos
        translated_items = []
        for idx, (it, tr_text) in enumerate(zip(merged_items, translated_texts), start=1):
            it.index = idx
            it.text = clean_khmer_dialogue_typos(tr_text)
            translated_items.append(it)

        # Save sidecar SRT file
        out_srt_path = video_path.parent / f"{video_path.stem}_KhmerDub.srt"
        try:
            srt_lines = []
            for it in translated_items:
                srt_lines.append(f"{it.index}\n{it.start_time} --> {it.end_time}\n{it.text}\n")
            with open(out_srt_path, "w", encoding="utf-8") as sf:
                sf.write("\n".join(srt_lines))
            logger.info(f"Saved Vision OCR Khmer subtitle file to {out_srt_path.name}")
        except OSError as e:
            logger.warning(f"Failed to write Vision OCR sidecar SRT: {e}")

        if progress_callback:
            progress_callback(100.0, f"Vision OCR complete! Extracted {len(translated_items)} dialogue items.")

        return translated_items


class SubtitleOCRWorker(QThread):
    """
    Background worker thread that runs Vision AI OCR frame scanning on videos
    and emits results to the UI.
    """
    finished = pyqtSignal(list)
    progress_changed = pyqtSignal(float, str)
    error = pyqtSignal(str)

    def __init__(
        self,
        video_path: str | Path,
        crop_box_ratio: tuple[float, float, float, float] | None = None,
        target_lang: str = "km",
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = Path(video_path)
        self.crop_box_ratio = crop_box_ratio
        self.target_lang = target_lang

    def run(self) -> None:
        try:
            def _on_progress(pct: float, msg: str):
                self.progress_changed.emit(pct, msg)

            items = extract_subtitles_via_vision_ocr(
                video_path=self.video_path,
                target_lang=self.target_lang,
                crop_box_ratio=self.crop_box_ratio,
                progress_callback=_on_progress,
            )
            if items:
                self.finished.emit(items)
            else:
                self.error.emit(
                    "No hardcoded Chinese subtitles could be extracted from video frames via Vision OCR.\n\n"
                    "Please ensure the subtitle crop box covers the written text on screen, then try again."
                )
        except RuntimeError as e:
            logger.warning(f"SubtitleOCRWorker quota/runtime error: {e}")
            self.error.emit(str(e))
        except Exception as e:
            logger.error(f"SubtitleOCRWorker exception: {e}")
            self.error.emit(f"Vision OCR Subtitle Extraction error: {e}")


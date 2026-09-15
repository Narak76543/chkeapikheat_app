# AGENT.md — PyQt6 Download Manager

## Project Goal
Build a professional desktop download manager using PyQt6. The app lets
a user paste a direct file URL (or a URL supported by yt-dlp for public/
Creative-Commons/permitted content) and manages the download with a
queue, progress bar, pause/resume, and retry logic.

**Out of scope / do not implement:** bypassing authentication, DRM,
token/signature-protected streams, or any site-specific scraping that
circumvents access controls. This tool only handles URLs the user
explicitly provides and that are legally downloadable.

## Tech Stack
- Python 3.11+
- PyQt6 for UI
- `requests` for direct HTTP downloads
- `yt-dlp` for supported public video platforms
- `pytest` for tests
- `PyInstaller` for packaging (final step)

## Project Structure
Create this exact structure:

\```
downloader_app/
├── main.py                      # App entry point, creates QApplication
├── core/
│   ├── __init__.py
│   ├── downloader.py            # QThread-based download worker(s)
│   ├── queue_manager.py         # Manages multiple DownloadTask objects
│   └── config.py                # App settings (save path, max threads, etc.)
├── models/
│   ├── __init__.py
│   └── download_task.py         # Dataclass: url, filename, status, progress, speed
├── ui/
│   ├── __init__.py
│   ├── main_window.py           # QMainWindow, holds toolbar + list + status bar
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── url_input_bar.py     # QLineEdit + "Add Download" button
│   │   ├── download_row.py      # QWidget: filename, progress bar, speed, actions
│   │   └── download_list.py     # QListWidget/QTableView container for rows
│   └── resources/
│       ├── icons/
│       └── style.qss            # Optional dark-mode stylesheet
├── utils/
│   ├── __init__.py
│   ├── logger.py                # Rotating file logger
│   └── validators.py            # URL validation, filename sanitization
├── tests/
│   ├── test_downloader.py
│   ├── test_queue_manager.py
│   └── test_validators.py
├── requirements.txt
├── .gitignore
└── README.md
\```

## Implementation Steps (do in order)

1. **Scaffold structure** exactly as above with empty `__init__.py` files.
2. **models/download_task.py** — dataclass with fields: `id`, `url`,
   `destination_path`, `status` (enum: QUEUED/DOWNLOADING/PAUSED/DONE/ERROR),
   `progress_percent`, `speed_bytes_per_sec`, `error_message`.
3. **core/downloader.py** — a `QThread` (or `QRunnable` + `QThreadPool`)
   subclass that:
   - Streams the file in chunks via `requests` (or delegates to `yt-dlp`
     when the URL matches a supported extractor).
   - Emits Qt signals: `progress_changed(task_id, percent, speed)`,
     `status_changed(task_id, status)`, `finished(task_id)`, `error(task_id, msg)`.
   - Supports pause (stop the loop, keep partial file) and resume
     (HTTP Range header) where the server allows it.
4. **core/queue_manager.py** — owns a list of `DownloadTask`, a
   `QThreadPool`, enforces `max_concurrent_downloads` from config, and
   exposes `add(url)`, `pause(id)`, `resume(id)`, `cancel(id)`, `retry(id)`.
5. **ui/widgets/download_row.py** — one row per task: filename label,
   `QProgressBar`, speed label, pause/resume/cancel buttons wired to
   `queue_manager` signals/slots.
6. **ui/main_window.py** — top URL input bar, central download list,
   status bar showing active/total downloads, menu for settings
   (download folder, max concurrent downloads).
7. **utils/validators.py** — validate the URL is well-formed and reject
   obviously unsupported/protected patterns; sanitize filenames for the
   OS.
8. **utils/logger.py** — standard rotating file handler, INFO level to
   console, DEBUG to file.
9. **Tests** — unit test the queue manager's concurrency limits and the
   validator's edge cases; mock network calls in downloader tests.
10. **requirements.txt**:
    \```
    PyQt6>=6.6
    requests>=2.31
    yt-dlp>=2024.1
    pytest>=8.0
    \```
11. **Packaging** — add a `build.spec` for PyInstaller once the app is
    functional, producing a single-file executable.

## Coding Conventions
- Type hints everywhere.
- All network/IO work happens off the main (UI) thread.
- UI updates only via Qt signals, never direct cross-thread widget calls.
- Follow PEP 8; format with `black`; lint with `ruff`.

## Definition of Done
- Pasting a direct file URL downloads it with a live progress bar.
- Pasting a yt-dlp-supported public video URL downloads it.
- Pause/resume/cancel work per row.
- App survives closing mid-download (asks to confirm, cleans up).
- `pytest` passes; `black --check` and `ruff` pass.

---

## 🔒 PERMANENT ARCHITECTURE RULES: TTS & TRANSCRIPT PIPELINE (DO NOT MODIFY)

> **CRITICAL RULE FOR ALL FUTURE AGENTS:**
> The current Speech-to-Text (STT) transcription and Text-to-Speech (TTS) voice dubbing engine is calibrated and approved as high quality by the user. **DO NOT change, refactor, or mangle the core logic below without explicit user request.**

### 1. Text-to-Speech (TTS) Quality & Fidelity Rules
- **100% Transcript Fidelity**: TTS input text must retain **100% of the original words, numbers, and phrasing**.
- **Non-Destructive Sanitization**: `clean_text_for_tts` must only perform lightweight safety checks:
  - Remove only trailing repeated dots (`...`, `....`) and XML characters (`<`, `>`) that cause Edge-TTS silence/crashes.
  - **NEVER** strip words inside brackets/parentheses (`(word)`, `[number]`).
  - **NEVER** replace all punctuation with flat Khmer periods `។` (this destroys natural speech intonation, questions, and emotion).
- **Natural Human Cadence & Tempo**:
  - Speech rate in Edge-TTS must stay natural (`+6%` to `+14%` base).
  - FFmpeg `atempo` dynamic speed adjustments must NEVER exceed `1.20x` (never use aggressive chipmunk compression like `1.45x+`).
- **Studio Vocal Mastering Chain**:
  - Preserve the 6-band studio mastering filter chain (`highpass`, `lowshelf`, `equalizer`, `highshelf`, `acompressor`, `loudnorm=I=-16:TP=-1.5:LRA=7`).
  - Preserve voice profiles for **Piseth (Male)**, **Sreymom (Female)**, **Sdach Game (+12% formant elevation)**, **Harvard (-30Hz deep documentary)**, and **Custom Voice Clone**.

### 2. Audio Timeline Assembly & Seamless Transitions
- **Acoustic Boundary Smoothing**: Keep `_apply_pcm_boundary_fades(clip_bytes, fade_frames=576)` (12ms smooth micro-fade envelope on 16-bit stereo PCM) to prevent boundary clicks and pops.
- **Conversational Turn-Taking Gap**: Maintain a `100ms` natural breath gap between consecutive dialogue turns when shifting timestamps (`effective_start < last_clip_end_time + 0.10`).
- **Smooth Background Ducking**: Keep `alimiter=limit=0.96:attack=7:release=120` to prevent background audio volume pumping during dialogue pauses.

### 3. Subtitle Extraction & Multi-Model Translation
- **Parallel Chunked Extraction**: 60s FFmpeg audio chunk slicing with `libmp3lame` and 24kHz clarity filter.
- **Gemini Fallback Chain**: Keep the resilient multi-model failover chain (`gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-1.5-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.7-flash`, `gemini-flash-latest`, followed by GTX fallback) for 100% zero-429 completion.

### 4. Git Operations
- **STRICT PROHIBITION**: **DO NOT run `git push`** under any circumstances unless explicitly commanded by the user.
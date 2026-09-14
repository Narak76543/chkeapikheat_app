# PyQt6 Download Manager

A professional desktop download manager built with Python 3.11+ and PyQt6. It handles direct file downloads (via `requests`) and public media streams (via `yt-dlp`) with queuing, real-time speed monitoring, pause/resume, and concurrency control.

---

## 🚀 Key Features

- **Queue Management**: Enforce maximum concurrent downloads with automated dispatch.
- **Direct & Video Streaming Support**: Direct HTTP/HTTPS files and public media links via `yt-dlp`.
- **Pause & Resume**: Chunked downloads with HTTP `Range` header support to resume partial files.
- **Real-time Metrics**: Live progress bar, downloaded size / total size, and transfer speed per row.
- **Graceful Shutdown**: Mid-download confirmation prompt that cleanly pauses workers.
- **Configurable Settings**: Custom download directories and concurrency limits.
- **Dark Mode UI**: Clean, modern dark stylesheet.

---

## 📂 Project Structure

```
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
│   │   └── download_list.py     # QListWidget container for rows
│   └── resources/
│       ├── icons/
│       └── style.qss            # Dark-mode stylesheet
├── utils/
│   ├── __init__.py
│   ├── logger.py                # Rotating file logger
│   └── validators.py            # URL validation, filename sanitization
├── tests/
│   ├── test_downloader.py
│   ├── test_queue_manager.py
│   └── test_validators.py
├── requirements.txt
├── build.spec                   # PyInstaller packaging spec
├── .gitignore
└── README.md
```

---

## 🛠 Installation & Usage

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Gemini API Key (Title Translation)
The title translator uses raw REST calls to the Gemini API (`gemini-3.6-flash`).
You can set your API key in either of two ways:

- **Option A**: Create a `.env` file in the project root:
  ```bash
  cp .env.example .env
  # Edit .env and set: GEMINI_API_KEY=your-actual-api-key
  ```
- **Option B**: Set an environment variable in your terminal:
  ```bash
  export GEMINI_API_KEY="your-actual-api-key"        # Linux/macOS
  $env:GEMINI_API_KEY="your-actual-api-key"         # PowerShell
  ```
> *Note: If no API key is set, the translator gracefully falls back to returning the original title without errors or blocking.*

### 3. Run Application
```bash
python -m downloader_app.main
```

### 4. Run Tests
```bash
pytest downloader_app/tests -v
```

### 4. Build Standalone Executable (PyInstaller)
```bash
pip install pyinstaller
pyinstaller build.spec
```
The executable will be generated in `dist/PyQt6DownloadManager.exe`.

---

## 🔤 Typography & Font Sourcing

The application bundles open-source fonts in `downloader_app/ui/resources/fonts/`:
- **Noto Sans** (`NotoSans-Regular.ttf`): Google Open Font License (OFL 1.1) for Latin scripts.
- **Noto Sans Khmer** (`NotoSansKhmer-Regular.ttf`): Google Open Font License (OFL 1.1) for Khmer glyphs.

### Sourcing & Customizing Fonts
- Both fonts are sourced from [Google Fonts](https://fonts.google.com/).
- To use proprietary fonts such as **Google Sans** or **Google Sans Text** (if locally licensed), drop the `.ttf` files into `downloader_app/ui/resources/fonts/` or configure them in system fonts. The application's `QFontDatabase` fallback chain will automatically prioritize them before falling back to Noto Sans and Noto Sans Khmer.

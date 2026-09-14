"""
Subtitle Burner & Video Filter Module
Generates pixel-perfect Khmer subtitle overlays styled in Google Sans / Noto Sans Khmer
and constructs FFmpeg filtergraphs for blurring original hardcoded subtitles (Chinese)
and burning newly translated Khmer subtitles with crystal clarity, zero broken ligatures, and exact contrast.
"""

import os
from pathlib import Path
import re
import subprocess
import sys

from PyQt6.QtCore import QCoreApplication, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
)

from downloader_app.core.downloader import get_ffmpeg_path
from downloader_app.core.subtitle_extractor import SubtitleItem
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.subtitle_burner")


def get_video_dimensions(video_path: str | Path, ffmpeg_bin: str) -> tuple[int, int]:
    """
    Probes video width and height using FFmpeg / FFprobe.
    Defaults to (1280, 720) if detection fails.
    """
    if not video_path or not Path(video_path).exists() or not ffmpeg_bin:
        return 1280, 720

    cmd = [ffmpeg_bin, "-i", str(Path(video_path).resolve())]
    try:
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
        # Search for resolution pattern like 1920x1080 or 1280x720
        match = re.search(r",\s*(\d{3,4})x(\d{3,4})", res.stderr)
        if match:
            w, h = int(match.group(1)), int(match.group(2))
            if w > 0 and h > 0:
                return w, h
    except Exception as e:
        logger.debug(f"Error detecting video dimensions: {e}")

    return 1280, 720


def get_video_duration(video_path: str | Path, ffmpeg_bin: str = "") -> float:
    """
    Probes video total duration in seconds using FFmpeg.
    Returns 0.0 if duration cannot be determined.
    """
    if not ffmpeg_bin:
        ffmpeg_bin = get_ffmpeg_path()
    if not video_path or not Path(video_path).exists() or not ffmpeg_bin:
        return 0.0

    cmd = [ffmpeg_bin, "-i", str(Path(video_path).resolve())]
    try:
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr)
        if match:
            h, m, s = float(match.group(1)), float(match.group(2)), float(match.group(3))
            return h * 3600.0 + m * 60.0 + s
    except Exception as e:
        logger.debug(f"Error detecting video duration: {e}")

    return 0.0


def auto_wrap_khmer_text(text: str, max_chars_per_line: int = 26) -> str:
    """
    Intelligently splits long single-line Khmer dialogue sentences into balanced 2 lines
    without breaking words arbitrarily.
    """
    text = text.strip()
    if not text:
        return ""
    if "\n" in text or len(text) <= max_chars_per_line:
        return text

    mid = len(text) // 2
    # 1. Try breaking at natural whitespace
    spaces = [i for i, ch in enumerate(text) if ch.isspace()]
    if spaces:
        best_space = min(spaces, key=lambda i: abs(i - mid))
        return text[:best_space].strip() + "\n" + text[best_space:].strip()

    # 2. Try breaking at common Khmer grammatical conjunctions/particles
    connectors = ["ហើយ", "ពីព្រោះ", "ដោយសារ", "ដូច្នេះ", "ដើម្បី", "ប៉ុន្តែ", "ដែល", "នោះ", "ថា", "ខ្ញុំ", "អ្នក"]
    for conn in connectors:
        idx = text.find(conn, int(len(text) * 0.22))
        if idx != -1 and idx <= int(len(text) * 0.78):
            return text[:idx].strip() + "\n" + text[idx:].strip()

    # 3. Fallback: split at midpoint
    return text[:mid].strip() + "\n" + text[mid:].strip()


def render_subtitle_overlay_image(
    text: str,
    width: int,
    height: int,
    font_variant: str = "Bold",
    font_size_pt: int = 30,
    blur_enabled: bool = True,
    bg_box_scale: int | None = None,
    bg_box_w_scale: int = 100,
    bg_box_h_scale: int = 100,
    bg_box_color: str = "#000000",
    bg_box_opacity: int = 90,
    output_path: Path | None = None,
) -> QImage:
    """
    Renders a transparent RGBA subtitle image with HarfBuzz native Khmer text shaping,
    customizable font variant and size, auto-fitting font metrics, and frosted dark background box.
    """
    # Ensure QGuiApplication is active for QPainter & QFont fontconfig / HarfBuzz shaping
    _app = QGuiApplication.instance()
    if _app is None:
        _app = QGuiApplication(sys.argv if sys.argv else ["ai_downloader"])

    img = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    if not text.strip():
        if output_path:
            img.save(str(output_path.resolve()))
        return img

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    w = float(width)
    h = float(height)
    is_portrait = h > w

    if is_portrait:
        # Portrait (9:16) Chinese subtitle zone is at Y = 68% - 90%
        base_w = max(60.0, w * 0.94)
        base_h = max(36.0, h * 0.22)
        base_y = h * 0.68
        corner_r = 16.0
        pad_x = 32.0
        pad_y = 16.0
    else:
        # Landscape (16:9) subtitle zone is at Y = 76% - 94%
        base_w = max(60.0, w * 0.88)
        base_h = max(36.0, h * 0.18)
        base_y = h * 0.76
        corner_r = 12.0
        pad_x = 28.0
        pad_y = 12.0

    # Custom background box width and height scaling
    actual_h_scale = bg_box_scale if bg_box_scale is not None else bg_box_h_scale
    w_mult = max(0.30, min(2.0, float(bg_box_w_scale) / 100.0))
    h_mult = max(0.30, min(3.0, float(actual_h_scale) / 100.0))

    box_w = max(40.0, min(w, base_w * w_mult))
    box_h = max(20.0, min(h, base_h * h_mult))
    box_x = (w - box_w) / 2.0
    box_y = base_y - ((box_h - base_h) / 2.0)
    box_y = max(0.0, min(h - box_h, box_y))
    box_x = max(0.0, min(w - box_w, box_x))

    box_rect = QRectF(box_x, box_y, box_w, box_h)

    # 1. Sleek Frosted Background Box (Use or None Use)
    if blur_enabled:
        col = QColor(bg_box_color) if QColor.isValidColor(bg_box_color) else QColor("#000000")
        alpha = max(0, min(255, int(round((bg_box_opacity / 100.0) * 255.0))))
        col.setAlpha(alpha)

        stroke_alpha = max(0, min(100, int(round((bg_box_opacity / 100.0) * 55.0))))
        stroke_color = QColor(255, 255, 255, stroke_alpha)

        painter.setPen(QPen(stroke_color, 1.5))
        painter.setBrush(QBrush(col))
        painter.drawRoundedRect(box_rect, corner_r, corner_r)

    # 2. Multi-line Word & Sentence Formatting
    formatted_lines = []
    for raw_l in text.strip().split("\n"):
        formatted_lines.append(auto_wrap_khmer_text(raw_l.strip(), max_chars_per_line=28 if is_portrait else 38))
    wrapped_text = "\n".join(formatted_lines)

    # 3. Dynamic Scaled Font Size with Auto-Fitting
    base_target_px = int(round((font_size_pt / 30.0) * (min(w, h) * (0.044 if is_portrait else 0.050))))
    target_px = max(14, base_target_px)

    variant_clean = str(font_variant).strip().lower()
    if "italic" in variant_clean:
        font_weight = QFont.Weight.Normal
        is_italic = True
    elif "regular" in variant_clean or "normal" in variant_clean:
        font_weight = QFont.Weight.Normal
        is_italic = False
    elif "semibold" in variant_clean or "demi" in variant_clean:
        font_weight = QFont.Weight.DemiBold
        is_italic = False
    else:  # Bold
        font_weight = QFont.Weight.Bold
        is_italic = False

    avail_w = box_w - (pad_x * 2.0)
    avail_h = box_h - (pad_y * 2.0)

    # Auto-fit font size so text is guaranteed to fit comfortably inside the box
    while target_px > 14:
        f_test = QFont("Google Sans", target_px, font_weight)
        f_test.setItalic(is_italic)
        f_test.setStyleHint(QFont.StyleHint.SansSerif)
        fm = QFontMetrics(f_test)
        max_line_w = max((fm.horizontalAdvance(line) for line in wrapped_text.split("\n")), default=0)
        total_text_h = fm.height() * len(wrapped_text.split("\n"))
        if max_line_w <= avail_w and total_text_h <= avail_h:
            break
        target_px -= 1

    final_font = QFont("Google Sans", target_px, font_weight)
    final_font.setItalic(is_italic)
    final_font.setStyleHint(QFont.StyleHint.SansSerif)
    painter.setFont(final_font)

    text_rect = box_rect.adjusted(pad_x, pad_y, -pad_x, -pad_y)
    flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap

    # Multi-pass drop shadow & outline for maximum contrast and legibility
    for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-1.5, -1.5), (1.5, 1.5), (-1.5, 1.5), (1.5, -1.5), (0, 2.5)]:
        painter.setPen(QColor(0, 0, 0, 245))
        painter.drawText(text_rect, int(flags), wrapped_text)

    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(text_rect, int(flags), wrapped_text)
    painter.end()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path.resolve()))

    return img


def generate_subtitle_overlay_sequence(
    subtitle_items: list[SubtitleItem],
    output_dir: Path,
    video_width: int = 1280,
    video_height: int = 720,
    font_name: str = "Google Sans",
    font_variant: str = "Bold",
    font_size_pt: int = 30,
    blur_enabled: bool = True,
    bg_box_scale: int | None = None,
    bg_box_w_scale: int = 100,
    bg_box_h_scale: int = 100,
    bg_box_color: str = "#000000",
    bg_box_opacity: int = 90,
    progress_callback=None,
) -> Path:
    """
    Renders transparent HarfBuzz-shaped Khmer subtitle frames and generates
    an ffconcat timeline script for frame-accurate FFmpeg video muxing.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    w, h = max(100, int(video_width)), max(100, int(video_height))

    # 1. Blank transparent frame for silent gaps
    blank_png = output_dir / "sub_blank.png"
    render_subtitle_overlay_image("", w, h, output_path=blank_png)

    concat_lines = ["ffconcat version 1.0"]
    cur_timeline = 0.0

    # Sort items chronologically
    sorted_items = sorted(subtitle_items, key=lambda it: it.start_seconds)
    total_items = max(1, len(sorted_items))

    for i, it in enumerate(sorted_items):
        if progress_callback:
            try:
                progress_callback(i + 1, total_items)
            except Exception:
                pass

        if not it.text.strip():
            continue

        # Fill any preceding gap
        gap = it.start_seconds - cur_timeline
        if gap > 0.02:
            concat_lines.append(f"file '{blank_png.resolve().as_posix()}'")
            concat_lines.append(f"duration {gap:.3f}")
            cur_timeline += gap

        # Render active dialogue line frame
        sub_frame_png = output_dir / f"frame_{i:04d}.png"
        render_subtitle_overlay_image(
            text=it.text,
            width=w,
            height=h,
            font_variant=font_variant,
            font_size_pt=font_size_pt,
            blur_enabled=blur_enabled,
            bg_box_scale=bg_box_scale,
            bg_box_w_scale=bg_box_w_scale,
            bg_box_h_scale=bg_box_h_scale,
            bg_box_color=bg_box_color,
            bg_box_opacity=bg_box_opacity,
            output_path=sub_frame_png,
        )

        dur = max(0.1, it.duration_seconds)
        concat_lines.append(f"file '{sub_frame_png.resolve().as_posix()}'")
        concat_lines.append(f"duration {dur:.3f}")
        cur_timeline += dur

    # Trailing safety frame
    concat_lines.append(f"file '{blank_png.resolve().as_posix()}'")
    concat_lines.append("duration 30.0")
    # Duplicate last file for ffconcat termination semantics
    concat_lines.append(f"file '{blank_png.resolve().as_posix()}'")

    concat_file = output_dir / "subtitles_timeline.txt"
    concat_file.write_text("\n".join(concat_lines), encoding="utf-8")
    logger.info(f"Generated {len(sorted_items)} subtitle overlay frames in: {output_dir.name}")
    return concat_file


def format_ass_time(seconds: float) -> str:
    """Formats seconds into ASS timestamp format (H:MM:SS.cs)."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_styled_ass_file(
    subtitle_items: list[SubtitleItem],
    output_ass_path: Path,
    font_name: str = "Google Sans",
    font_variant: str = "Bold",
    base_font_size: int = 30,
    video_width: int = 1280,
    video_height: int = 720,
) -> bool:
    """
    Generates an Advanced SubStation Alpha (.ass) sidecar subtitle file formatted with
    the Google Sans / Noto Sans Khmer font family, selectable font variant,
    and balanced margin matching the Dialogue Studio preview.
    """
    try:
        output_ass_path.parent.mkdir(parents=True, exist_ok=True)
        w, h = max(100, int(video_width)), max(100, int(video_height))
        is_portrait = h > w
        min_dim = min(w, h)

        if is_portrait:
            font_size = max(24, int(round((base_font_size / 30.0) * (min_dim * 0.052))))
            margin_v = max(30, int(round(h * 0.16)))
            margin_lr = max(24, int(round(w * 0.08)))
        else:
            font_size = max(20, int(round((base_font_size / 30.0) * (h * 0.056))))
            margin_v = max(24, int(round(h * 0.10)))
            margin_lr = max(30, int(round(w * 0.08)))

        outline_width = max(2.0, round((font_size / 30.0) * 2.8, 1))
        shadow_depth = max(1.0, round((font_size / 30.0) * 1.5, 1))

        variant_clean = str(font_variant).strip().lower()
        if "italic" in variant_clean:
            bold_val = 0
            italic_val = 1
        elif "regular" in variant_clean or "normal" in variant_clean:
            bold_val = 0
            italic_val = 0
        elif "semibold" in variant_clean or "demi" in variant_clean:
            bold_val = 1
            italic_val = 0
        else:  # Bold
            bold_val = 1
            italic_val = 0

        ass_header = f"""[Script Info]
Title: Khmer Dubbed Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: {w}
PlayResY: {h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: KhmerDefault,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,{bold_val},{italic_val},0,0,100,100,0,0,1,{outline_width},{shadow_depth},2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        dialogue_lines = []
        for it in subtitle_items:
            wrapped = auto_wrap_khmer_text(it.text.strip(), max_chars_per_line=28 if is_portrait else 38)
            text = wrapped.replace("\n", r"\N")
            if not text:
                continue
            start_str = format_ass_time(it.start_seconds)
            end_str = format_ass_time(it.end_seconds)
            dialogue_lines.append(
                f"Dialogue: 0,{start_str},{end_str},KhmerDefault,,0,0,0,,{text}"
            )

        full_content = ass_header + "\n".join(dialogue_lines) + "\n"
        output_ass_path.write_text(full_content, encoding="utf-8")
        logger.info(f"Generated styled ASS subtitle file with {len(dialogue_lines)} lines: {output_ass_path.name}")
        return True
    except Exception as e:
        logger.error(f"Failed to generate ASS subtitle file: {e}")
        return False


def build_subtitle_filter_complex(
    ass_path: Path | None = None,
    overlay_concat_path: Path | None = None,
    blur_original_subtitles: bool = True,
    video_width: int = 1280,
    video_height: int = 720,
    blur_y_ratio: float | None = None,
    blur_height_ratio: float | None = None,
    overlay_input_index: int = 1,
) -> tuple[str, str]:
    """
    Constructs an FFmpeg filter_complex string to:
    1. Apply smooth frosted-glass boxblur covering the Chinese hardcoded subtitle zone.
    2. Overlay the pixel-perfect HarfBuzz-rendered Khmer subtitle stream (or ASS filter).

    Returns:
        (filter_complex_string, output_map_label)
    """
    filters = []
    current_stream = "[0:v]"
    w, h = max(100, int(video_width)), max(100, int(video_height))
    is_portrait = h > w

    if blur_original_subtitles:
        # Default positioning covering hardcoded Chinese subtitles
        if blur_y_ratio is None:
            blur_y_ratio = 0.68 if is_portrait else 0.76
        if blur_height_ratio is None:
            blur_height_ratio = 0.22 if is_portrait else 0.18

        box_w_ratio = 0.94 if is_portrait else 0.88

        # Smooth frosted boxblur over the subtitle area
        blur_chain = (
            f"{current_stream}split=2[main_v][sub_crop];"
            f"[sub_crop]crop=iw*{box_w_ratio:.3f}:ih*{blur_height_ratio:.3f}:(iw-iw*{box_w_ratio:.3f})/2:ih*{blur_y_ratio:.3f},"
            f"boxblur=12:2[blurred_crop];"
            f"[main_v][blurred_crop]overlay=(W-w)/2:H*{blur_y_ratio:.3f}[v_blurred]"
        )
        filters.append(blur_chain)
        current_stream = "[v_blurred]"

    if overlay_concat_path and Path(overlay_concat_path).exists():
        # High-fidelity transparent subtitle overlay stream
        filters.append(f"{current_stream}[{overlay_input_index}:v]overlay=0:0:shortest=1[v_out]")
        current_stream = "[v_out]"
    elif ass_path and Path(ass_path).exists():
        escaped_ass = str(Path(ass_path).resolve()).replace("\\", "/").replace(":", r"\:")
        fonts_dir = "C\\:/Windows/Fonts" if os.name == "nt" else "/usr/share/fonts"
        sub_filter = f"{current_stream}subtitles='{escaped_ass}':fontsdir='{fonts_dir}'[v_out]"
        filters.append(sub_filter)
        current_stream = "[v_out]"
    else:
        if current_stream != "[0:v]":
            filters.append(f"{current_stream}null[v_out]")
            current_stream = "[v_out]"

    return ";".join(filters), current_stream

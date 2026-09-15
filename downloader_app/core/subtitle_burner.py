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
    QLinearGradient,
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


def smart_tokenize_khmer_words(text: str) -> list[str]:
    """
    Intelligently tokenizes Khmer script sentences into individual words or small compound phrases
    without breaking ligature glyphs or sub-consonant clusters.
    """
    text = text.strip()
    if not text:
        return []

    particles = [
        "សេចក្តី", "ការ", "ភាព", "អ្នក", "របស់", "នៅក្រោម", "នៅ", "ក្នុង", "ខាងលើ", "ខាង",
        "ទើបតែ", "ចេញ", "ដំណឹង", "ថា", "ដែល", "ត្រូវដឹក", "ត្រូវ", "គឺមិន", "មិនអាច",
        "គឺ", "មិន", "អាច", "បានទេ", "បាន", "ទេ", "បច្ចុប្បន្ន", "នេះ", "នោះ", "ហើយ", "និង",
    ]

    parts = re.split(r"(\s+|[។ៗ!?,:;]+)", text)
    tokens = []
    for p in parts:
        p = p.strip()
        if not p or p in "។ៗ!?,:;":
            continue

        cur = p
        sub_tokens = []
        while cur:
            if len(cur) <= 8:
                sub_tokens.append(cur)
                break

            best_idx = -1
            for part in particles:
                idx = cur.find(part, 2)
                if idx != -1:
                    if best_idx == -1 or idx < best_idx:
                        best_idx = idx

            if best_idx != -1 and best_idx <= 12:
                sub_tokens.append(cur[:best_idx])
                cur = cur[best_idx:]
            else:
                syl_pat = re.compile(
                    r"[\u1780-\u17B3](?:\u17D2[\u1780-\u17B3])*(?:[\u17B6-\u17C5])*(?:[\u17C6-\u17D3\u17DD])*|[A-Za-z0-9]+"
                )
                syls = [m.group(0) for m in syl_pat.finditer(cur)]
                if len(syls) > 3:
                    cut_len = sum(len(s) for s in syls[:3])
                    sub_tokens.append(cur[:cut_len])
                    cur = cur[cut_len:]
                else:
                    sub_tokens.append(cur)
                    break
        tokens.extend(sub_tokens)

    return tokens if tokens else [text]


def split_subtitle_into_timed_chunks(
    item: SubtitleItem,
    subtitle_mode: str = "full",
) -> list[SubtitleItem]:
    """
    Subdivides a single SubtitleItem into timed 1-2 word chunks or short phrases for
    dynamic, fast-paced subtitle presentation (e.g. TikTok / Facebook Reels / CapCut captions).
    """
    if subtitle_mode in ("full", "sentence", "none") or not item.text.strip():
        return [item]

    if subtitle_mode == "1_word":
        max_words = 1
    elif subtitle_mode == "short_phrase":
        max_words = 2
    elif subtitle_mode == "compact_line":
        max_words = 4
    else:
        max_words = 2

    tokens = smart_tokenize_khmer_words(item.text)
    if not tokens:
        return [item]

    raw_chunks = []
    i = 0
    while i < len(tokens):
        raw_chunks.append(" ".join(tokens[i : i + max_words]))
        i += max_words

    if len(raw_chunks) <= 1:
        return [item]

    total_dur = max(0.2, item.end_seconds - item.start_seconds)
    total_chars = sum(max(1, len(c)) for c in raw_chunks)

    timed_items = []
    cur_start = item.start_seconds
    for idx, c in enumerate(raw_chunks):
        c_dur = (len(c) / total_chars) * total_dur
        c_end = cur_start + c_dur if idx < len(raw_chunks) - 1 else item.end_seconds

        sh, sm = divmod(int(cur_start), 60)
        ss = cur_start % 60
        eh, em = divmod(int(c_end), 60)
        es = c_end % 60
        s_time = f"{sh:02d}:{sm:02d}:{ss:06.3f}".replace(".", ",")
        e_time = f"{eh:02d}:{em:02d}:{es:06.3f}".replace(".", ",")

        timed_items.append(
            SubtitleItem(
                index=idx + 1,
                start_time=s_time,
                end_time=e_time,
                text=c,
                start_seconds=round(cur_start, 3),
                end_seconds=round(c_end, 3),
            )
        )
        cur_start = c_end

    return timed_items


def hex_to_ass_color(hex_color: str, alpha: int = 0) -> str:
    """
    Converts a standard #RRGGBB or #RGB hex color to ASS &HAABBGGRR color format.
    ASS format expects &H + 2 hex digits alpha (00=opaque) + Blue + Green + Red.
    """
    c = hex_color.strip().lstrip("#")
    if len(c) == 6:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    elif len(c) == 3:
        r, g, b = int(c[0] * 2, 16), int(c[1] * 2, 16), int(c[2] * 2, 16)
    else:
        r, g, b = 255, 255, 255
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def render_subtitle_overlay_image(
    text: str,
    width: int,
    height: int,
    blur_enabled: bool = True,
    font_variant: str = "Bold",
    font_size_pt: int = 30,
    sub_text_color: str = "#FFFFFF",
    bg_box_scale: int | None = None,
    bg_box_w_scale: int = 100,
    bg_box_h_scale: int = 100,
    bg_box_color: str = "#FFFFFF",
    bg_box_opacity: int = 100,
    pos_x_ratio: float | None = None,
    pos_y_ratio: float | None = None,
    mask_pos_x_ratio: float | None = None,
    mask_pos_y_ratio: float | None = None,
    sub_pos_x_ratio: float | None = None,
    sub_pos_y_ratio: float | None = None,
    output_path: Path | None = None,
) -> QImage:
    """
    Renders a transparent PNG overlay containing:
    1. Independent background mask panel at mask_pos_x_ratio / mask_pos_y_ratio to hide Chinese subtitles.
    2. Independent Khmer subtitle text centered at sub_pos_x_ratio / sub_pos_y_ratio with clean styling (no outline) and custom color.
    """
    w = max(100, int(width))
    h = max(100, int(height))
    is_portrait = h > w

    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    actual_w_scale = bg_box_w_scale if bg_box_w_scale is not None else (bg_box_scale or 100)
    actual_h_scale = bg_box_h_scale if bg_box_h_scale is not None else (bg_box_scale or 100)

    w_mult = max(0.20, min(2.5, float(actual_w_scale) / 100.0))
    h_mult = max(0.20, min(3.5, float(actual_h_scale) / 100.0))

    actual_mask_x = mask_pos_x_ratio if mask_pos_x_ratio is not None else pos_x_ratio
    actual_mask_y = mask_pos_y_ratio if mask_pos_y_ratio is not None else pos_y_ratio

    # 1. Background Mask Panel Dimensions
    base_w = w * (0.94 if is_portrait else 0.88)
    base_h = h * (0.22 if is_portrait else 0.18)
    base_y = h * (0.68 if is_portrait else 0.76)

    box_w = min(w, base_w * w_mult)
    box_h = min(h, base_h * h_mult)
    corner_r = min(12.0, max(4.0, box_h * 0.16))

    if actual_mask_x is not None:
        box_x = (w * actual_mask_x) - (box_w / 2.0)
    else:
        box_x = (w - box_w) / 2.0

    if actual_mask_y is not None:
        box_y = (h * actual_mask_y) - (box_h / 2.0)
    else:
        box_y = base_y - ((box_h - base_h) / 2.0)

    box_y = max(0.0, min(h - box_h, box_y))
    box_x = max(0.0, min(w - box_w, box_x))

    mask_rect = QRectF(box_x, box_y, box_w, box_h)

    # Render Mask Box (to cover Chinese subtitles)
    if blur_enabled:
        grad = QLinearGradient(mask_rect.topLeft(), mask_rect.bottomLeft())
        op_factor = max(0.0, min(1.0, bg_box_opacity / 100.0))
        top_a = max(20, min(255, int(round(op_factor * 255.0))))
        bot_a = max(30, min(255, int(round(op_factor * 255.0))))

        col_base = QColor(bg_box_color) if QColor.isValidColor(bg_box_color) else QColor("#FFFFFF")
        col_top = QColor(col_base.red(), col_base.green(), col_base.blue(), top_a)
        col_bot = QColor(col_base.red(), col_base.green(), col_base.blue(), bot_a)
        grad.setColorAt(0.0, col_top)
        grad.setColorAt(1.0, col_bot)

        stroke_alpha = max(20, min(100, int(round(op_factor * 50.0))))
        painter.setPen(QPen(QColor(200, 205, 215, stroke_alpha), 1.2))
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(mask_rect, corner_r, corner_r)

    # 2. Independent Subtitle Text Rendering (Clean typography matching Preview)
    if text.strip():
        formatted_lines = []
        for raw_l in text.strip().split("\n"):
            formatted_lines.append(auto_wrap_khmer_text(raw_l.strip(), max_chars_per_line=28 if is_portrait else 38))
        wrapped_text = "\n".join(formatted_lines)

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

        actual_sub_x = sub_pos_x_ratio if sub_pos_x_ratio is not None else 0.5
        actual_sub_y = sub_pos_y_ratio if sub_pos_y_ratio is not None else (0.82 if is_portrait else 0.88)

        max_sub_w = max(100.0, w * 0.90)
        max_sub_h = max(40.0, h * 0.40)

        # Auto-fit font size
        while target_px > 14:
            f_test = QFont("Google Sans", target_px, font_weight)
            f_test.setItalic(is_italic)
            f_test.setStyleHint(QFont.StyleHint.SansSerif)
            fm = QFontMetrics(f_test)
            max_line_w = max((fm.horizontalAdvance(line) for line in wrapped_text.split("\n")), default=0)
            total_text_h = fm.height() * len(wrapped_text.split("\n"))
            if max_line_w <= max_sub_w and total_text_h <= max_sub_h:
                break
            target_px -= 1

        final_font = QFont("Google Sans", target_px, font_weight)
        final_font.setItalic(is_italic)
        final_font.setStyleHint(QFont.StyleHint.SansSerif)
        painter.setFont(final_font)

        fm = QFontMetrics(final_font)
        rendered_w = min(max_sub_w, max((fm.horizontalAdvance(line) for line in wrapped_text.split("\n")), default=100) + 32.0)
        rendered_h = min(max_sub_h, fm.height() * len(wrapped_text.split("\n")) + 16.0)

        sub_cx = w * actual_sub_x
        sub_cy = h * actual_sub_y
        sub_x = max(0.0, min(w - rendered_w, sub_cx - (rendered_w / 2.0)))
        sub_y = max(0.0, min(h - rendered_h, sub_cy - (rendered_h / 2.0)))
        text_rect = QRectF(sub_x, sub_y, rendered_w, rendered_h)
        flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap

        # Clean text rendering (No outline, crisp text color)
        text_col = QColor(sub_text_color) if QColor.isValidColor(sub_text_color) else QColor("#FFFFFF")
        painter.setPen(text_col)
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
    sub_text_color: str = "#FFFFFF",
    blur_enabled: bool = True,
    bg_box_scale: int | None = None,
    bg_box_w_scale: int = 100,
    bg_box_h_scale: int = 100,
    bg_box_color: str = "#FFFFFF",
    bg_box_opacity: int = 100,
    sub_pos_x_ratio: float | None = None,
    sub_pos_y_ratio: float | None = None,
    mask_pos_x_ratio: float | None = None,
    mask_pos_y_ratio: float | None = None,
    progress_callback=None,
) -> Path:
    """
    Renders transparent HarfBuzz-shaped Khmer subtitle frames and generates
    an ffconcat timeline script for frame-accurate FFmpeg video muxing.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    w, h = max(100, int(video_width)), max(100, int(video_height))

    # 1. Blank frame for silent gaps (preserves mask panel if enabled)
    blank_png = output_dir / "sub_blank.png"
    render_subtitle_overlay_image(
        "",
        w,
        h,
        blur_enabled=blur_enabled,
        bg_box_scale=bg_box_scale,
        bg_box_w_scale=bg_box_w_scale,
        bg_box_h_scale=bg_box_h_scale,
        bg_box_color=bg_box_color,
        bg_box_opacity=bg_box_opacity,
        mask_pos_x_ratio=mask_pos_x_ratio,
        mask_pos_y_ratio=mask_pos_y_ratio,
        output_path=blank_png,
    )

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
            sub_text_color=sub_text_color,
            blur_enabled=blur_enabled,
            bg_box_scale=bg_box_scale,
            bg_box_w_scale=bg_box_w_scale,
            bg_box_h_scale=bg_box_h_scale,
            bg_box_color=bg_box_color,
            bg_box_opacity=bg_box_opacity,
            mask_pos_x_ratio=mask_pos_x_ratio,
            mask_pos_y_ratio=mask_pos_y_ratio,
            sub_pos_x_ratio=sub_pos_x_ratio,
            sub_pos_y_ratio=sub_pos_y_ratio,
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
    aspect_ratio: str = "original",
    subtitle_mode: str = "full",
    sub_pos_x_ratio: float | None = None,
    sub_pos_y_ratio: float | None = None,
    sub_color: str = "#FFFFFF",
    outline_width: float = 0.0,
    shadow_depth: float = 0.0,
) -> bool:
    """
    Generates a production-ready Advanced SubStation Alpha (.ass) subtitle file using
    Google Sans / Noto Sans Khmer with full OpenType complex shaping,
    crisp high-contrast text styling, custom color, and font scaling
    matching the in-app player preview exactly.
    Supports 9:16 Vertical (TikTok/Reels), dynamic 1-2 word / short phrase chunking,
    and free independent positioning via \\pos(X, Y).
    """
    try:
        output_ass_path.parent.mkdir(parents=True, exist_ok=True)
        if subtitle_mode and subtitle_mode != "full":
            expanded = []
            for it in subtitle_items:
                expanded.extend(split_subtitle_into_timed_chunks(it, subtitle_mode=subtitle_mode))
            subtitle_items = expanded
        if aspect_ratio in ("9:16_blur", "9:16_crop", "vertical_blur", "vertical_crop"):
            w, h = 1080, 1920
            is_portrait = True
        else:
            w, h = max(100, int(video_width)), max(100, int(video_height))
            is_portrait = h > w
        min_dim = min(w, h)

        if aspect_ratio in ("9:16_blur", "9:16_crop", "vertical_blur", "vertical_crop"):
            # Tailored for TikTok / Facebook Reels vertical screens (prominent, readable size)
            font_size = max(68, int(round((base_font_size / 30.0) * (h * 0.065))))
            margin_v = max(40, int(round(h * 0.14)))
            margin_lr = max(30, int(round(w * 0.06)))
            wrap_chars = 24
        elif is_portrait:
            # Vertical/portrait videos (e.g. 720x1280, 1080x1920)
            font_size = max(64, int(round((base_font_size / 30.0) * (h * 0.065))))
            margin_v = max(30, int(round(h * 0.14)))
            margin_lr = max(24, int(round(w * 0.06)))
            wrap_chars = 28
        else:
            # Widescreen landscape videos (e.g. 1280x720, 1920x1080)
            font_size = max(48, int(round((base_font_size / 30.0) * (h * 0.075))))
            margin_v = max(24, int(round(h * 0.10)))
            margin_lr = max(30, int(round(w * 0.08)))
            wrap_chars = 38

        outline_val = max(3.0, float(outline_width)) if outline_width > 0 else 3.0
        shadow_val = max(1.5, float(shadow_depth)) if shadow_depth > 0 else 1.5

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

        ass_primary = hex_to_ass_color(sub_color, alpha=0)
        effective_font = font_name if (font_name and font_name.strip()) else "Google Sans"

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
Style: KhmerDefault,{effective_font},{font_size},{ass_primary},&H000000FF,&H00000000,&H80000000,{bold_val},{italic_val},0,0,100,100,0,0,1,{outline_val},{shadow_val},2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        dialogue_lines = []
        actual_sub_x = sub_pos_x_ratio if sub_pos_x_ratio is not None else 0.5
        actual_sub_y = sub_pos_y_ratio if sub_pos_y_ratio is not None else (0.82 if is_portrait else 0.88)
        cx = int(round(w * actual_sub_x))
        cy = int(round(h * actual_sub_y))
        pos_tag = f"{{\\an5\\pos({cx},{cy})}}"

        for it in subtitle_items:
            wrapped = auto_wrap_khmer_text(it.text.strip(), max_chars_per_line=wrap_chars)
            text = wrapped.replace("\n", r"\N")
            if not text:
                continue
            start_str = format_ass_time(it.start_seconds)
            end_str = format_ass_time(it.end_seconds)
            dialogue_lines.append(
                f"Dialogue: 0,{start_str},{end_str},KhmerDefault,,0,0,0,,{pos_tag}{text}"
            )

        full_content = ass_header + "\n".join(dialogue_lines) + "\n"
        output_ass_path.write_text(full_content, encoding="utf-8")
        logger.info(f"Generated styled ASS subtitle file ({w}x{h}, {len(dialogue_lines)} lines): {output_ass_path.name}")
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
    aspect_ratio: str = "original",
    bg_box_w_scale: int = 100,
    bg_box_h_scale: int = 100,
    bg_box_color: str = "#FFFFFF",
    bg_box_opacity: int = 0,
    pos_x_ratio: float | None = None,
    pos_y_ratio: float | None = None,
    mask_pos_x_ratio: float | None = None,
    mask_pos_y_ratio: float | None = None,
    sub_pos_x_ratio: float | None = None,
    sub_pos_y_ratio: float | None = None,
) -> tuple[str, str]:
    """
    Constructs an FFmpeg filter_complex string to:
    1. Reformat aspect ratio (e.g. 9:16 Vertical TikTok/Reels with blurred background).
    2. Apply smooth frosted-glass boxblur and mask panel covering the Chinese hardcoded subtitle zone.
    3. Render either an ASS subtitle stream or high-fidelity transparent PNG overlay frames on top.
    """
    filters = []
    current_stream = "[0:v]"
    w, h = max(100, int(video_width)), max(100, int(video_height))
    is_portrait = h > w

    # ── Aspect Ratio Target Reformatting (9:16 Reels / TikTok) ──
    if aspect_ratio in ("9:16_blur", "vertical_blur") and not is_portrait:
        # Professional Reel/TikTok layout: 1080x1920 canvas, blurred background + centered crisp video
        blur_bg_chain = (
            f"{current_stream}split=2[in_bg][in_fg];"
            f"[in_bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg_layer];"
            f"[in_fg]scale=1080:-2[fg_layer];"
            f"[bg_layer][fg_layer]overlay=(W-w)/2:(H-h)/2[v_base]"
        )
        filters.append(blur_bg_chain)
        current_stream = "[v_base]"
        w, h = 1080, 1920
        is_portrait = True
    elif aspect_ratio in ("9:16_crop", "vertical_crop") and not is_portrait:
        # Direct center-crop fill to 1080x1920
        crop_chain = f"{current_stream}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v_base]"
        filters.append(crop_chain)
        current_stream = "[v_base]"
        w, h = 1080, 1920
        is_portrait = True

    if blur_original_subtitles:
        w_mult = max(0.20, min(2.5, float(bg_box_w_scale) / 100.0))
        h_mult = max(0.20, min(3.5, float(bg_box_h_scale) / 100.0))

        base_w_ratio = 0.94 if is_portrait else 0.88
        base_h_ratio = 0.22 if is_portrait else 0.18
        base_y_ratio = 0.68 if is_portrait else 0.76

        actual_mask_x = mask_pos_x_ratio if mask_pos_x_ratio is not None else pos_x_ratio
        actual_mask_y = mask_pos_y_ratio if mask_pos_y_ratio is not None else pos_y_ratio

        if actual_mask_y is not None:
            base_y_ratio = actual_mask_y
        elif blur_y_ratio is not None:
            base_y_ratio = blur_y_ratio

        if blur_height_ratio is not None:
            base_h_ratio = blur_height_ratio

        box_w_ratio = min(1.0, base_w_ratio * w_mult)
        box_h_ratio = min(1.0, base_h_ratio * h_mult)

        if actual_mask_x is not None:
            box_x_ratio = max(0.0, min(1.0 - box_w_ratio, actual_mask_x - (box_w_ratio / 2.0)))
        else:
            box_x_ratio = (1.0 - box_w_ratio) / 2.0

        if actual_mask_y is not None:
            box_y_ratio = max(0.0, min(1.0 - box_h_ratio, actual_mask_y - (box_h_ratio / 2.0)))
        else:
            box_y_ratio = max(0.0, min(1.0 - box_h_ratio, base_y_ratio - ((box_h_ratio - base_h_ratio) / 2.0)))

        # Color and opacity for mask panel
        clean_color = bg_box_color if (bg_box_color and bg_box_color.startswith("#")) else "#FFFFFF"
        opacity_val = max(0.0, min(1.0, float(bg_box_opacity) / 100.0))

        # Smooth frosted video boxblur to obscure hardcoded Chinese subtitles
        blur_chain = (
            f"{current_stream}split=2[main_v][sub_crop];"
            f"[sub_crop]crop=iw*{box_w_ratio:.4f}:ih*{box_h_ratio:.4f}:iw*{box_x_ratio:.4f}:ih*{box_y_ratio:.4f},"
            f"boxblur=24:6[blurred_crop];"
            f"[main_v][blurred_crop]overlay=W*{box_x_ratio:.4f}:H*{box_y_ratio:.4f}"
        )
        if opacity_val > 0:
            blur_chain += f",drawbox=x=iw*{box_x_ratio:.4f}:y=ih*{box_y_ratio:.4f}:w=iw*{box_w_ratio:.4f}:h=ih*{box_h_ratio:.4f}:color={clean_color}@{opacity_val:.2f}:t=fill"
        blur_chain += "[v_blurred]"
        filters.append(blur_chain)
        current_stream = "[v_blurred]"

    if overlay_concat_path and Path(overlay_concat_path).exists():
        # High-fidelity transparent subtitle overlay stream
        filters.append(f"{current_stream}[{overlay_input_index}:v]overlay=0:0:shortest=1[v_out]")
        current_stream = "[v_out]"
    elif ass_path and Path(ass_path).exists():
        posix_ass = Path(ass_path).resolve().as_posix().replace(":", r"\:")
        app_fonts_dir = Path(__file__).parent.parent / "ui" / "resources" / "fonts"
        if app_fonts_dir.exists():
            fonts_dir = app_fonts_dir.resolve().as_posix().replace(":", r"\:")
        else:
            fonts_dir = "C\\:/Windows/Fonts" if os.name == "nt" else "/usr/share/fonts"

        if Path(ass_path).suffix.lower() == ".ass":
            sub_filter = f"{current_stream}ass='{posix_ass}':fontsdir='{fonts_dir}':shaping=1[v_out]"
        else:
            sub_filter = f"{current_stream}subtitles='{posix_ass}':fontsdir='{fonts_dir}'[v_out]"
        filters.append(sub_filter)
        current_stream = "[v_out]"
    else:
        if current_stream != "[0:v]":
            filters.append(f"{current_stream}null[v_out]")
            current_stream = "[v_out]"

    return ";".join(filters), current_stream

"""
Dubbing Mixer Core Module
Lossless FFmpeg audio-video synchronizer. Combines timed TTS audio clips
and overlays/replaces the original video audio track to produce dubbed Khmer video.
"""

import os
import re
from pathlib import Path
import subprocess
import wave

import time
import threading
from PyQt6.QtCore import QThread, pyqtSignal

from downloader_app.core.downloader import get_ffmpeg_path
from downloader_app.core.subtitle_burner import (
    build_subtitle_filter_complex,
    generate_styled_ass_file,
    generate_subtitle_overlay_sequence,
    get_video_dimensions,
    get_video_duration,
)
from downloader_app.core.subtitle_extractor import SubtitleItem
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.dubbing_mixer")

_DETECTED_ENCODER_FLAGS: list[str] | None = None


def get_fast_video_encoder_flags(ffmpeg_bin: str) -> list[str]:
    """
    Probes and returns optimal hardware or multi-threaded CPU video encoder flags.
    Prioritizes NVIDIA NVENC (up to ~300-500fps), Intel QSV, AMD AMF, then multi-threaded libx264.
    """
    global _DETECTED_ENCODER_FLAGS
    if _DETECTED_ENCODER_FLAGS is not None:
        return list(_DETECTED_ENCODER_FLAGS)

    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    # 1. Test NVIDIA NVENC (ultra fast hardware encoding)
    try:
        res = subprocess.run(
            [ffmpeg_bin, "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1", "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20", "-pix_fmt", "yuv420p", "-f", "null", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
            timeout=5,
        )
        if res.returncode == 0:
            logger.info("Detected NVIDIA NVENC hardware video acceleration.")
            _DETECTED_ENCODER_FLAGS = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20", "-pix_fmt", "yuv420p"]
            return list(_DETECTED_ENCODER_FLAGS)
    except Exception:
        pass

    # 2. Test Intel QuickSync (QSV)
    try:
        res = subprocess.run(
            [ffmpeg_bin, "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1", "-c:v", "h264_qsv", "-global_quality", "20", "-pix_fmt", "nv12", "-f", "null", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
            timeout=5,
        )
        if res.returncode == 0:
            logger.info("Detected Intel QuickSync (QSV) hardware video acceleration.")
            _DETECTED_ENCODER_FLAGS = ["-c:v", "h264_qsv", "-global_quality", "20", "-pix_fmt", "nv12"]
            return list(_DETECTED_ENCODER_FLAGS)
    except Exception:
        pass

    # 3. Test AMD AMF
    try:
        res = subprocess.run(
            [ffmpeg_bin, "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1", "-c:v", "h264_amf", "-quality", "speed", "-pix_fmt", "yuv420p", "-f", "null", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
            timeout=5,
        )
        if res.returncode == 0:
            logger.info("Detected AMD AMF hardware video acceleration.")
            _DETECTED_ENCODER_FLAGS = ["-c:v", "h264_amf", "-quality", "speed", "-pix_fmt", "yuv420p"]
            return list(_DETECTED_ENCODER_FLAGS)
    except Exception:
        pass

    # 4. Fallback: multi-threaded CPU libx264
    logger.info("Using optimized multi-threaded CPU libx264 (preset: veryfast, threads: 0)")
    _DETECTED_ENCODER_FLAGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "0", "-pix_fmt", "yuv420p"]
    return list(_DETECTED_ENCODER_FLAGS)


def _read_clip_pcm_fast(clip_path: Path, sample_rate: int = 48000, ffmpeg_bin: str = "", creation_flags: int = 0) -> bytes:
    """Reads audio clip directly to 16-bit stereo 48000Hz PCM bytes with zero-subprocess fastpath for standard WAVs."""
    if clip_path.suffix.lower() == ".wav" and clip_path.exists():
        try:
            with wave.open(str(clip_path.resolve()), "rb") as wf:
                nchannels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
                if sampwidth == 2 and framerate == sample_rate:
                    raw_frames = wf.readframes(wf.getnframes())
                    if nchannels == 2:
                        return raw_frames
                    elif nchannels == 1:
                        import array
                        mono_arr = array.array("h", raw_frames)
                        stereo_arr = array.array("h", [0] * (len(mono_arr) * 2))
                        stereo_arr[0::2] = mono_arr
                        stereo_arr[1::2] = mono_arr
                        return stereo_arr.tobytes()
        except Exception:
            pass

    # Fallback to FFmpeg process
    if not ffmpeg_bin:
        ffmpeg_bin = get_ffmpeg_path() or "ffmpeg"
    cmd_pcm = [
        ffmpeg_bin,
        "-y",
        "-i", str(clip_path.resolve()),
        "-f", "s16le",
        "-ac", "2",
        "-ar", str(sample_rate),
        "-",
    ]
    res_pcm = subprocess.run(
        cmd_pcm,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creation_flags,
    )
    return res_pcm.stdout or b""


class DubbingMixerWorker(QThread):
    """Worker thread that stitches audio clips into a master track and muxes them into target video via FFmpeg."""

    progress_changed = pyqtSignal([float, str], [float])
    status_changed = pyqtSignal(str)
    finished = pyqtSignal(str)  # output_video_path
    error = pyqtSignal(str)

    def __init__(
        self,
        video_path: str,
        subtitle_items: list[SubtitleItem],
        audio_clip_paths: list[str],
        output_video_path: str,
        mix_mode: str = "ducking",  # "replace" or "ducking"
        voice: str = "km-KH-PisethNeural",
        ref_audio_path: str = "",
        burn_subtitles: bool = True,
        blur_subtitles: bool = True,
        font_name: str = "Google Sans",
        font_variant: str = "Bold",
        font_size: int = 28,
        bg_box_scale: int | None = None,
        bg_box_w_scale: int = 100,
        bg_box_h_scale: int = 100,
        bg_box_color: str = "#000000",
        bg_box_opacity: int = 90,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.video_path = Path(video_path)
        self.subtitle_items = subtitle_items
        self.audio_clip_paths = [Path(p) for p in audio_clip_paths]
        self.output_video_path = Path(output_video_path)
        self.mix_mode = mix_mode
        self.voice = voice
        self.ref_audio_path = ref_audio_path
        self.burn_subtitles = burn_subtitles
        self.blur_subtitles = blur_subtitles
        self.font_name = font_name
        self.font_variant = font_variant
        self.font_size = font_size
        self.bg_box_w_scale = bg_box_w_scale
        self.bg_box_h_scale = bg_box_scale if bg_box_scale is not None else bg_box_h_scale
        self.bg_box_color = bg_box_color
        self.bg_box_opacity = bg_box_opacity
        self._process: subprocess.Popen | None = None

    def stop(self) -> None:
        """Terminates active underlying FFmpeg subprocess if running."""
        if self._process:
            try:
                self._process.kill()
            except Exception:
                pass

    def run(self) -> None:
        if not self.video_path.exists():
            self.error.emit(f"Source video not found: {self.video_path}")
            return

        ffmpeg_bin = get_ffmpeg_path()
        if not ffmpeg_bin:
            self.error.emit("FFmpeg executable not found.")
            return

        self.output_video_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_changed.emit("Building non-overlapping audio timeline...")
        self.progress_changed.emit(2.0, "Building audio timeline...")

        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        # Verify and recover TTS audio clips
        valid_pairs: list[tuple[SubtitleItem, Path]] = []
        from downloader_app.core.tts_voxcpm import VoxCPM2Client
        tts_client = None

        for i, item in enumerate(self.subtitle_items):
            clip_p = None
            if i < len(self.audio_clip_paths):
                clip_str = str(self.audio_clip_paths[i])
                if clip_str:
                    cp = Path(clip_str)
                    if cp.exists() and cp.stat().st_size > 500:
                        clip_p = cp

            if not clip_p and item.text.strip():
                # On-the-fly recovery for missing or empty clip
                if tts_client is None:
                    tts_client = VoxCPM2Client()
                recover_dir = self.output_video_path.parent / f"{self.output_video_path.stem}_voxcpm_clips"
                recover_dir.mkdir(parents=True, exist_ok=True)
                recover_clip = recover_dir / f"clip_{item.index:04d}.wav"
                logger.info(f"Synthesizing missing audio clip for line #{item.index}: '{item.text[:20]}...' (Voice: {self.voice})")
                ok = tts_client.generate_audio(
                    text=item.text,
                    duration_sec=item.duration_seconds,
                    output_path=recover_clip,
                    target_lang="km",
                    voice=self.voice,
                    ref_audio_path=self.ref_audio_path,
                )
                if ok and recover_clip.exists() and recover_clip.stat().st_size > 500:
                    clip_p = recover_clip

            if clip_p:
                valid_pairs.append((item, clip_p))

        if not valid_pairs:
            self.error.emit("No valid TTS audio clips available for mixing.")
            return

        # 1. Assemble all dialogue clips onto a continuous master audio track
        master_wav = self.output_video_path.parent / f"{self.output_video_path.stem}_master_speech.wav"
        sample_rate = 48000
        bytes_per_frame = 4  # 16-bit stereo PCM

        try:
            video_dur = get_video_duration(self.video_path, ffmpeg_bin)

            min_start = min((it.start_seconds for it, _ in valid_pairs), default=0.0)
            shift_offset = 0.0
            if video_dur > 0 and min_start >= (video_dur * 0.8) and len(valid_pairs) > 0 and min_start > 30.0:
                logger.warning(
                    f"Subtitle timestamps start at {min_start:.1f}s but video duration is {video_dur:.1f}s. "
                    "Shifting dialogue timestamps to align with clip start (00:00)."
                )
                shift_offset = min_start

            adjusted_ends = [(it.end_seconds - shift_offset) for it, _ in valid_pairs]
            max_sub_end = max(adjusted_ends, default=0.0)

            total_dur = max(video_dur, max_sub_end) + 2.0
            total_dur = max(total_dur, 10.0)

            total_frames = int(total_dur * sample_rate)
            master_bytes = bytearray(total_frames * bytes_per_frame)

            # Sort pairs chronologically by item.start_seconds
            sorted_pairs = sorted(valid_pairs, key=lambda x: (x[0].start_seconds - shift_offset))
            total_pair_count = max(1, len(sorted_pairs))
            last_clip_end_time: float = 0.0

            for idx, (item, clip_path) in enumerate(sorted_pairs):
                # Stage 1 progress: 2% -> 10%
                pct_a = 2.0 + (float(idx) / total_pair_count) * 8.0
                if idx % 10 == 0 or idx == total_pair_count - 1:
                    msg_a = f"Assembling audio timeline ({idx + 1}/{total_pair_count})..."
                    self.progress_changed.emit(pct_a, msg_a)
                    self.status_changed.emit(msg_a)

                effective_start = max(0.0, item.start_seconds - shift_offset)

                # ── Guaranteed Non-Overlap Pacing ──────────────────────────────────
                # If the previous speech clip has not finished yet, shift this clip to start
                # naturally right after the previous clip finishes (+60ms natural breath pause).
                if effective_start < last_clip_end_time + 0.06:
                    effective_start = last_clip_end_time + 0.06

                target_start_frame = int(effective_start * sample_rate)
                start_byte = target_start_frame * bytes_per_frame

                try:
                    # Ultra-fast clip reading with Python WAV fast-path (bypasses subprocess overhead)
                    clip_bytes = _read_clip_pcm_fast(
                        clip_path=clip_path,
                        sample_rate=sample_rate,
                        ffmpeg_bin=ffmpeg_bin,
                        creation_flags=creation_flags,
                    )

                    if not clip_bytes:
                        continue

                    # Ensure exact 4-byte frame alignment (16-bit stereo PCM)
                    rem = len(clip_bytes) % bytes_per_frame
                    if rem != 0:
                        clip_bytes = clip_bytes[:-rem]

                    if not clip_bytes or len(clip_bytes) < bytes_per_frame:
                        continue

                    clip_dur_sec = len(clip_bytes) / (sample_rate * bytes_per_frame)
                    last_clip_end_time = effective_start + clip_dur_sec

                    end_byte = start_byte + len(clip_bytes)
                    if end_byte > len(master_bytes):
                        needed = end_byte - len(master_bytes)
                        rem_needed = needed % bytes_per_frame
                        if rem_needed != 0:
                            needed += (bytes_per_frame - rem_needed)
                        master_bytes.extend(b"\x00" * needed)

                    existing_slice = master_bytes[start_byte:end_byte]
                    if len(existing_slice) != len(clip_bytes):
                        min_len = min(len(existing_slice), len(clip_bytes))
                        min_len -= min_len % bytes_per_frame
                        if min_len < bytes_per_frame:
                            continue
                        clip_bytes = clip_bytes[:min_len]
                        end_byte = start_byte + min_len
                        existing_slice = master_bytes[start_byte:end_byte]

                    # Fast mixing
                    if existing_slice == b"\x00" * len(clip_bytes):
                        master_bytes[start_byte:end_byte] = clip_bytes
                    else:
                        import array

                        a_exist = array.array("h", existing_slice)
                        a_clip = array.array("h", clip_bytes)
                        limit = min(len(a_exist), len(a_clip))
                        for k in range(limit):
                            val = a_exist[k] + a_clip[k]
                            a_exist[k] = max(-32768, min(32767, val))
                        master_bytes[start_byte:end_byte] = a_exist.tobytes()

                except Exception as e:
                    logger.warning(f"Could not read audio clip {clip_path}: {e}")

            # Write out master WAV
            with wave.open(str(master_wav), "wb") as out_w:
                out_w.setnchannels(2)
                out_w.setsampwidth(2)
                out_w.setframerate(sample_rate)
                out_w.writeframes(master_bytes)

            logger.info(
                f"Assembled absolute multi-track dubbed speech track ({len(master_bytes) / (sample_rate * bytes_per_frame):.1f}s)"
            )
        except Exception as e:
            logger.error(f"Failed to assemble master speech track: {e}")
            self.error.emit(f"Audio timeline assembly failed: {e}")
            return

        # Save Khmer SRT sidecar file next to output video
        try:
            from downloader_app.core.subtitle_extractor import format_srt_content
            out_srt = self.output_video_path.with_suffix(".srt")
            with open(out_srt, "w", encoding="utf-8") as f:
                f.write(format_srt_content(self.subtitle_items))
            logger.info(f"Saved dubbed Khmer SRT file: {out_srt.name}")
        except Exception as e:
            logger.debug(f"Failed to save Khmer SRT sidecar: {e}")

        # Check if source video contains an audio stream
        def video_has_audio(vpath: Path) -> bool:
            cmd = [ffmpeg_bin, "-i", str(vpath.resolve())]
            try:
                res = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creation_flags,
                )
                return "Audio:" in res.stderr
            except Exception:
                return True

        has_src_audio = video_has_audio(self.video_path)

        # 2. Build Subtitle & Blur Video Filter Complex (if enabled)
        ass_path = None
        overlay_concat_file = None
        v_filter_str = ""
        v_out_label = "[0:v]"
        sub_frames_dir = self.output_video_path.parent / f"{self.output_video_path.stem}_sub_frames"

        w, h = get_video_dimensions(self.video_path, ffmpeg_bin)

        if self.burn_subtitles and self.subtitle_items:
            # Generate sidecar .ass file
            ass_path = self.output_video_path.parent / f"{self.output_video_path.stem}_khmer_subtitles.ass"
            generate_styled_ass_file(
                subtitle_items=self.subtitle_items,
                output_ass_path=ass_path,
                font_name=self.font_name,
                font_variant=self.font_variant,
                base_font_size=self.font_size,
                video_width=w,
                video_height=h,
            )

            self.progress_changed.emit(25.0, "Subtitle file ready. Starting video encoding...")
            self.status_changed.emit("Subtitle file ready. Starting video encoding...")

            # NOTE: We skip PNG overlay sequence generation — it causes FFmpeg to hang on large videos.
            # The ASS subtitle file is used directly via the fast FFmpeg subtitles= filter instead.
            overlay_concat_file = None

        if self.blur_subtitles or (self.burn_subtitles and (overlay_concat_file or (ass_path and ass_path.exists()))):
            overlay_idx = 2 if overlay_concat_file else 1
            v_filter_str, v_out_label = build_subtitle_filter_complex(
                ass_path=ass_path if (not overlay_concat_file and self.burn_subtitles and ass_path and ass_path.exists()) else None,
                overlay_concat_path=overlay_concat_file,
                blur_original_subtitles=self.blur_subtitles,
                video_width=w,
                video_height=h,
                overlay_input_index=overlay_idx,
            )

        is_video_filtered = bool(v_filter_str and v_out_label not in ("[0:v]", "0:v:0"))
        effective_video_dur = video_dur if video_dur > 0.0 else max(total_dur, 10.0)

        # Helper to run FFmpeg mux command with real-time progress streaming and duration ETA estimate
        def execute_ffmpeg_mux(mode: str) -> tuple[bool, str]:
            if self.output_video_path.exists():
                try:
                    self.output_video_path.unlink()
                except OSError:
                    pass

            cmd = [
                ffmpeg_bin,
                "-y",
                "-i", str(self.video_path.resolve()),
                "-i", str(master_wav.resolve()),
            ]

            if overlay_concat_file and overlay_concat_file.exists():
                cmd.extend([
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(overlay_concat_file.resolve()),
                ])

            fast_v_flags = get_fast_video_encoder_flags(ffmpeg_bin)

            if mode == "replace" or not has_src_audio:
                if is_video_filtered:
                    cmd.extend([
                        "-filter_complex", v_filter_str,
                        "-map", v_out_label,
                        "-map", "1:a:0",
                        *fast_v_flags,
                        "-c:a", "aac",
                        "-b:a", "320k",
                        "-ar", "48000",
                        "-shortest",
                        "-progress", "pipe:1",
                        "-nostats",
                        str(self.output_video_path.resolve()),
                    ])
                else:
                    cmd.extend([
                        "-map", "0:v:0",
                        "-map", "1:a:0",
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-b:a", "320k",
                        "-ar", "48000",
                        "-shortest",
                        "-progress", "pipe:1",
                        "-nostats",
                        str(self.output_video_path.resolve()),
                    ])
            else:  # ducking mode
                audio_filter = (
                    "[0:a:0]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=0.18[bg_a];"
                    "[1:a:0]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=1.25[dubbed_a];"
                    "[bg_a][dubbed_a]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,alimiter=limit=0.98:attack=5:release=50[outa]"
                )
                if is_video_filtered:
                    combined_filter = f"{v_filter_str};{audio_filter}"
                    cmd.extend([
                        "-filter_complex", combined_filter,
                        "-map", v_out_label,
                        "-map", "[outa]",
                        *fast_v_flags,
                        "-c:a", "aac",
                        "-b:a", "320k",
                        "-ar", "48000",
                        "-shortest",
                        "-progress", "pipe:1",
                        "-nostats",
                        str(self.output_video_path.resolve()),
                    ])
                else:
                    cmd.extend([
                        "-filter_complex", audio_filter,
                        "-map", "0:v:0",
                        "-map", "[outa]",
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-b:a", "320k",
                        "-ar", "48000",
                        "-shortest",
                        "-progress", "pipe:1",
                        "-nostats",
                        str(self.output_video_path.resolve()),
                    ])

            logger.info(
                f"Running dubbing mux (mode={mode}, video_filtered={is_video_filtered}, has_src_audio={has_src_audio}): "
                f"{self.output_video_path.name}"
            )

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creation_flags,
                    bufsize=1,
                )
                self._process = proc

                # Drain stderr continuously in a background thread to prevent Windows pipe buffer deadlock (64KB limit)
                stderr_chunks: list[str] = []

                def _drain_stderr() -> None:
                    try:
                        if proc.stderr:
                            for err_line in proc.stderr:
                                if err_line:
                                    stderr_chunks.append(err_line)
                    except Exception:
                        pass

                stderr_drain_thread = threading.Thread(target=_drain_stderr, daemon=True)
                stderr_drain_thread.start()

                start_mux_walltime = time.time()
                last_emit_walltime = 0.0
                cur_encoded_sec = 0.0
                cur_speed = 1.0

                if proc.stdout:
                    for raw_line in proc.stdout:
                        line = raw_line.strip()
                        if not line:
                            continue
                        if line.startswith("out_time_us="):
                            try:
                                us_val = int(line.split("=", 1)[1])
                                if us_val > 0:
                                    cur_encoded_sec = us_val / 1_000_000.0
                            except ValueError:
                                pass
                        elif line.startswith("out_time="):
                            t_str = line.split("=", 1)[1].strip()
                            m = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", t_str)
                            if m:
                                cur_encoded_sec = float(m.group(1)) * 3600.0 + float(m.group(2)) * 60.0 + float(m.group(3))
                        elif line.startswith("speed="):
                            s_str = line.split("=", 1)[1].strip()
                            m_spd = re.search(r"([\d\.]+)x", s_str)
                            if m_spd:
                                try:
                                    cur_speed = float(m_spd.group(1))
                                except ValueError:
                                    pass
                        elif line == "progress=end":
                            break

                        now_t = time.time()
                        if now_t - last_emit_walltime >= 0.25:
                            last_emit_walltime = now_t

                            if effective_video_dur > 0:
                                enc_pct = min(100.0, max(0.0, (cur_encoded_sec / effective_video_dur) * 100.0))
                            else:
                                enc_pct = 50.0

                            # Stage 3 spans from 25.0% to 99.0%
                            overall_pct = min(99.0, 25.0 + (enc_pct * 0.74))
                            rem_sec = max(0.0, effective_video_dur - cur_encoded_sec)

                            if cur_speed > 0.05:
                                eta_sec = int(rem_sec / cur_speed)
                            else:
                                elapsed = now_t - start_mux_walltime
                                if enc_pct > 2.0:
                                    eta_sec = int((elapsed / (enc_pct / 100.0)) - elapsed)
                                else:
                                    eta_sec = 0

                            eta_sec = max(0, eta_sec)
                            if eta_sec >= 3600:
                                eta_h = eta_sec // 3600
                                eta_m = (eta_sec % 3600) // 60
                                eta_s = eta_sec % 60
                                eta_text = f"ETA ~{eta_h:02d}:{eta_m:02d}:{eta_s:02d}"
                            elif eta_sec > 0:
                                eta_m = eta_sec // 60
                                eta_s = eta_sec % 60
                                eta_text = f"ETA ~{eta_m:02d}:{eta_s:02d}"
                            else:
                                eta_text = "Finishing..."

                            speed_text = f"Speed {cur_speed:.1f}x" if cur_speed > 0.05 else ""
                            status_parts = [f"Muxing Video: {int(enc_pct)}%"]
                            if speed_text:
                                status_parts.append(speed_text)
                            status_parts.append(eta_text)
                            status_msg = " • ".join(status_parts)

                            self.progress_changed.emit(overall_pct, status_msg)
                            self.status_changed.emit(status_msg)

                proc.wait()
                stderr_drain_thread.join(timeout=2.0)
                self._process = None

                stderr_data = "".join(stderr_chunks)
                if proc.returncode == 0 and self.output_video_path.exists() and self.output_video_path.stat().st_size > 1000:
                    return True, ""
                err_msg = stderr_data[-400:] if stderr_data else f"Exit code {proc.returncode}"
                return False, err_msg
            except Exception as ex:
                self._process = None
                return False, str(ex)

        self.status_changed.emit("Muxing Khmer audio track with video...")
        self.progress_changed.emit(25.0, "Starting video encoding and audio mux...")

        # Attempt requested mix mode (ducking or replace)
        target_mode = self.mix_mode if has_src_audio else "replace"
        success, err_details = execute_ffmpeg_mux(target_mode)

        # If ducking mode failed, automatically fall back to replace mode
        if not success and target_mode == "ducking":
            logger.warning(f"Ducking mode mux failed ({err_details}), falling back to direct Audio Replace mode...")
            success, err_details = execute_ffmpeg_mux("replace")

        # Cleanup temporary master speech WAV, subtitle frame directory, and temporary files
        try:
            if master_wav.exists():
                master_wav.unlink()
        except OSError:
            pass
        try:
            if sub_frames_dir.exists():
                import shutil
                shutil.rmtree(sub_frames_dir, ignore_errors=True)
        except Exception:
            pass

        if not success:
            logger.error(f"FFmpeg dubbing mux failed: {err_details}")
            self.error.emit(f"Muxing failed: {err_details}")
            return

        self.progress_changed.emit(100.0, "Dubbing render complete!")
        self.status_changed.emit("Voice dubbing complete!")
        self.finished.emit(str(self.output_video_path))


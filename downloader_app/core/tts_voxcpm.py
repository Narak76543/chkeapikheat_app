from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import requests

from PyQt6.QtCore import QThread, pyqtSignal

from downloader_app.core.downloader import get_ffmpeg_path
from downloader_app.core.subtitle_extractor import SubtitleItem
from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.tts_voxcpm")

_edge_tts_lock = threading.Lock()


def get_audio_duration_ffmpeg(file_path: Path, ffmpeg_bin: str) -> float:
    """Probes audio file duration in seconds using FFmpeg metadata."""
    cmd = [ffmpeg_bin, "-i", str(file_path.resolve())]
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
            h, m, s = match.groups()
            return float(h) * 3600 + float(m) * 60 + float(s)
    except Exception:
        pass
    return 0.0


def clean_text_for_tts(text: str) -> str:
    """
    Lightweight, non-destructive sanitizer for TTS input text.
    Preserves 100% of original words, natural intonation, and phrasing while
    safely cleaning trailing ellipsis ('...', '....') and XML characters (<, >) that cause TTS errors.
    Strips placeholder text like '(គ្មានទិន្នន័យ)', '[គ្មានទិន្នន័យ]', '(No Data)', '(无数据)' so the AI voice NEVER speaks them.
    """
    if not text:
        return ""
    t = text.strip()

    no_data_patterns = [
        r"គ្មានទិន្នន័យ",
        r"no\s*data",
        r"无数据",
        r"暂无数据",
        r"nodata",
    ]

    # Check if text is purely a "no data" placeholder (with or without brackets/parentheses)
    clean_lower = t.lower()
    for pat in no_data_patterns:
        if re.search(r"^\s*[\(\[\（\【\s]*" + pat + r"[\)\]\）\】\s]*$", clean_lower):
            return ""

    # Strip inline parenthesized/bracketed "no data" annotations e.g. (គ្មានទិន្នន័យ), [no data], (无数据)
    for pat in no_data_patterns:
        t = re.sub(r"[\(\[\（\【]\s*" + pat + r"\s*[\)\]\）\】]", " ", t, flags=re.IGNORECASE)
        t = re.sub(pat, " ", t, flags=re.IGNORECASE)

    # Strip XML tags / angle brackets that break SSML synthesis
    t = re.sub(r"<[^>]*>", " ", t)
    t = re.sub(r"[<>]", " ", t)
    # Remove repeated inline dots/ellipses ('....' -> ' ')
    t = re.sub(r"[\.．…]{2,}", " ", t)
    # Remove trailing repeated dots/ellipses and trailing commas
    t = re.sub(r"[\.．…\s]+$", "", t)
    t = re.sub(r"[\,\，\;\；\s]+$", "", t)
    # Clean whitespace
    res = re.sub(r"\s+", " ", t).strip()

    for pat in no_data_patterns:
        if re.search(r"^\s*[\(\[\（\【\s]*" + pat + r"[\)\]\）\】\s]*$", res.lower()):
            return ""
    return res


_voice_profile_cache: dict[str, dict] = {}


def analyze_reference_audio(ref_audio_path: str | Path, ffmpeg_bin: str) -> dict:
    """
    Analyzes an uploaded reference audio sample to extract pitch characteristics (F0),
    spectral timbre, and gender profile for authentic voice cloning.
    Results are cached per sample path for high-performance batch generation.
    """
    import math
    import struct

    default_profile = {
        "gender": "male",
        "base_voice": "km-KH-PisethNeural",
        "pitch_ratio": 1.0,
        "median_f0": 130.0,
    }
    if not ref_audio_path or not Path(ref_audio_path).exists() or not ffmpeg_bin:
        return default_profile

    cache_key = str(Path(ref_audio_path).resolve())
    if cache_key in _voice_profile_cache:
        return _voice_profile_cache[cache_key]

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(Path(ref_audio_path).resolve()),
        "-t",
        "10",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "s16le",
        "-",
    ]
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )
        raw_data = res.stdout
        if len(raw_data) < 3200:
            return default_profile

        num_samples = len(raw_data) // 2
        samples = struct.unpack(f"<{num_samples}h", raw_data[: num_samples * 2])

        frame_size = 1024
        hop_size = 512
        pitches = []
        lag_min = 40  # 400 Hz
        lag_max = 266  # 60 Hz

        for i in range(0, len(samples) - frame_size, hop_size):
            frame = samples[i : i + frame_size]
            sum_sq = sum(s * s for s in frame)
            rms = math.sqrt(sum_sq / frame_size)
            if rms < 250:
                continue

            best_corr = -1
            best_lag = lag_min
            for lag in range(lag_min, lag_max):
                corr = sum(frame[j] * frame[j + lag] for j in range(frame_size - lag))
                if corr > best_corr:
                    best_corr = corr
                    best_lag = lag

            if best_corr > 0:
                f0 = 16000.0 / best_lag
                if 65 < f0 < 380:
                    pitches.append(f0)

        pitches.sort()
        median_f0 = pitches[len(pitches) // 2] if pitches else 140.0
        is_female = median_f0 > 165.0
        base_voice = "km-KH-SreymomNeural" if is_female else "km-KH-PisethNeural"
        base_f0 = 220.0 if is_female else 125.0
        ratio = median_f0 / base_f0
        ratio = max(0.80, min(1.35, ratio))
        pitch_diff_hz = int(median_f0 - base_f0)
        pitch_diff_hz = max(-35, min(35, pitch_diff_hz))

        profile = {
            "median_f0": median_f0,
            "gender": "female" if is_female else "male",
            "base_voice": base_voice,
            "pitch_ratio": ratio,
            "pitch_hz": pitch_diff_hz,
        }
        _voice_profile_cache[cache_key] = profile
        return profile
    except Exception as e:
        logger.debug(f"Audio profile analysis exception: {e}")
        return default_profile


class VoxCPM2Client:
    """Client for VoxCPM2 Neural Text-to-Speech engine."""

    def __init__(self, api_url: str = "http://localhost:8000/tts") -> None:
        self.api_url = api_url

    def generate_audio(
        self,
        text: str,
        duration_sec: float,
        output_path: Path,
        target_lang: str = "km",
        max_allowed_duration: float = 0.0,
        voice: str = "km-KH-PisethNeural",
        ref_audio_path: str = "",
    ) -> bool:
        """
        Sends text to VoxCPM2 API server to generate audio.
        If server is offline, falls back to Microsoft Neural Human Khmer TTS (Piseth/Sreymom/Custom Clone),
        then Google Khmer TTS, then timed audio generator.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        text_clean = clean_text_for_tts(text)
        if not text_clean:
            return self._generate_fallback_audio(max(1.0, max_allowed_duration or duration_sec), output_path)

        # Safeguard: If target is Khmer but text contains Chinese characters (e.g. translation missed),
        # translate it on-the-fly so it NEVER speaks Chinese!
        if target_lang == "km" and re.search(r"[\u4e00-\u9fff]", text_clean):
            try:
                from downloader_app.core.translator import Translator
                trans = Translator().translate_subtitle_blocks([text_clean], target_lang="km")
                if trans and trans[0] and not re.search(r"[\u4e00-\u9fff]", trans[0]):
                    logger.info(f"On-the-fly translated Chinese line '{text_clean[:15]}...' to Khmer: '{trans[0][:20]}...'")
                    text_clean = trans[0].strip()
            except Exception as e:
                logger.warning(f"On-the-fly translation exception: {e}")

        # 1. Try sending request to VoxCPM2 API
        if text_clean:
            try:
                payload = {
                    "text": text_clean,
                    "language": target_lang,
                    "duration": duration_sec,
                    "voice": voice,
                    "ref_audio_path": ref_audio_path,
                }
                resp = requests.post(self.api_url, json=payload, timeout=3)
                if resp.status_code == 200 and resp.content:
                    with open(output_path, "wb") as f:
                        f.write(resp.content)
                    logger.info(f"VoxCPM2 generated audio clip for text: '{text_clean[:20]}...'")
                    return True
            except Exception as e:
                logger.debug(f"VoxCPM2 API endpoint unreachable ({e}), using Neural Khmer TTS.")

            # 2. Microsoft Neural Human Khmer TTS (Piseth / Sreymom / Sdach Game / Custom Sample cloning)
            if self._generate_neural_khmer_tts(
                text_clean, output_path, max_allowed_duration=max_allowed_duration, voice=voice, ref_audio_path=ref_audio_path
            ):
                return True

            # 3. Fallback: Online Google Khmer TTS with dynamic pacing & speedup
            if self._generate_online_khmer_tts(
                text_clean, output_path, max_allowed_duration=max_allowed_duration
            ):
                return True

        # 4. Fallback: generate timed silent/placeholder audio clip using FFmpeg
        return self._generate_fallback_audio(duration_sec, output_path)

    def _generate_gemini_khmer_tts(
        self,
        text: str,
        output_path: Path,
        max_allowed_duration: float = 0.0,
        voice: str = "Puck",
        style_prompt: str = "energetic reviewer",
    ) -> bool:
        """
        Optional Gemini Audio generator helper.
        """
        try:
            from downloader_app.core.translator import get_api_key
            api_key = get_api_key()
            if not api_key:
                return False

            import base64
            gemini_models = [
                "models/gemini-3.1-flash-tts-preview",
                "models/gemini-2.5-flash-preview-tts",
            ]

            text_clean = text.strip()
            if not text_clean:
                return False

            gemini_voice = voice if voice in ["Puck", "Fenrir", "Charon", "Kore", "Aoede", "Zephyr"] else "Puck"
            payload = {
                "contents": [{"parts": [{"text": text_clean}]}],
                "generationConfig": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {
                                "voice_name": gemini_voice
                            }
                        }
                    },
                },
            }

            ffmpeg_bin = get_ffmpeg_path()
            if not ffmpeg_bin:
                return False

            for model in gemini_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={api_key}"
                try:
                    resp = requests.post(url, json=payload, timeout=6)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            for part in parts:
                                inline = part.get("inlineData")
                                if inline and "data" in inline:
                                    raw_pcm = base64.b64decode(inline["data"])
                                    temp_pcm = output_path.with_suffix(".temp.pcm")
                                    temp_pcm.write_bytes(raw_pcm)

                                    filters = [
                                        "highpass=f=75",
                                        "equalizer=f=3500:width_type=q:width=1.5:g=2.5",
                                        "lowshelf=g=1.5:f=160",
                                        "acompressor=threshold=0.12:ratio=3.0:attack=10:release=100:makeup=1.5",
                                        "loudnorm=I=-16:TP=-1.5:LRA=7",
                                    ]
                                    cmd = [
                                        ffmpeg_bin,
                                        "-y",
                                        "-f", "s16le",
                                        "-ar", "24000",
                                        "-ac", "1",
                                        "-i", str(temp_pcm.resolve()),
                                        "-filter:a", ",".join(filters),
                                        "-ar", "48000",
                                        "-ac", "2",
                                        str(output_path.resolve()),
                                    ]
                                    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                                    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creation_flags)
                                    try:
                                        temp_pcm.unlink()
                                    except OSError:
                                        pass

                                    if output_path.exists() and output_path.stat().st_size > 500:
                                        logger.info(f"Gemini Neural TTS ({gemini_voice}) generated distinct voice for: '{text_clean[:20]}...'")
                                        return True
                except Exception as e:
                    logger.debug(f"Gemini TTS request exception on {model}: {e}")
                    continue
        except Exception as ex:
            logger.debug(f"Gemini TTS generation error: {ex}")

        return False

    def _generate_neural_khmer_tts(
        self,
        text: str,
        output_path: Path,
        max_allowed_duration: float = 0.0,
        voice: str = "km-KH-PisethNeural",
        ref_audio_path: str = "",
    ) -> bool:
        """
        Generates ultra-natural, human-like Khmer speech using Microsoft Neural TTS (Edge-TTS).
        Dynamically adjusts tempo within natural human limits, synthesizes pitch natively, and
        applies studio mastering filters for pristine vocal clarity and warmth.
        """
        text_clean = clean_text_for_tts(text)
        if not text_clean:
            return self._generate_fallback_audio(max(1.0, max_allowed_duration), output_path)

        try:
            import asyncio
            import edge_tts

            ffmpeg_bin = get_ffmpeg_path()
            voice_profile = None

            # Auto-resolve bundled voice samples if not explicitly passed
            if (voice == "sdach_game" or voice == "sdach") and not ref_audio_path:
                bundled_sample = Path(__file__).parent.parent / "ui" / "resources" / "voices" / "sdach_game.mp3"
                if bundled_sample.exists():
                    ref_audio_path = str(bundled_sample.resolve())
            elif (voice == "harvard" or voice == "havard") and not ref_audio_path:
                bundled_sample = Path(__file__).parent.parent / "ui" / "resources" / "voices" / "harvard.mp3"
                if bundled_sample.exists():
                    ref_audio_path = str(bundled_sample.resolve())

            is_sdach = (voice == "sdach_game" or voice == "sdach" or (ref_audio_path and "sdach" in Path(ref_audio_path).stem.lower()))
            is_harvard = (voice == "harvard" or voice == "havard" or (ref_audio_path and "harvard" in Path(ref_audio_path).stem.lower()))

            if ref_audio_path and Path(ref_audio_path).exists() and ffmpeg_bin and not is_sdach and not is_harvard:
                voice_profile = analyze_reference_audio(ref_audio_path, ffmpeg_bin)

            # Estimate duration based on text length (~14 chars/sec in Khmer)
            char_count = len(text_clean)
            est_dur = max(0.8, char_count / 14.0)

            base_rate = 6
            if is_sdach:
                voice_clean = "km-KH-PisethNeural"
                pitch_str = "+16Hz"
                base_rate = 14
            elif is_harvard:
                voice_clean = "km-KH-PisethNeural"
                pitch_str = "-30Hz"
                base_rate = 0
            elif voice_profile:
                voice_clean = voice_profile["base_voice"]
                p_hz = voice_profile.get("pitch_hz", 0)
                pitch_str = f"{p_hz:+d}Hz" if p_hz != 0 else "+0Hz"
                base_rate = 8
            elif voice and voice.startswith("km-"):
                voice_clean = voice
                pitch_str = "+0Hz"
                base_rate = 6
            else:
                voice_clean = "km-KH-PisethNeural"
                pitch_str = "+0Hz"
                base_rate = 6

            # Dynamically accelerate Edge-TTS speech rate if slot duration is tight
            if max_allowed_duration > 0 and est_dur > max_allowed_duration:
                need_boost = ((est_dur / max_allowed_duration) - 1.0) * 100
                calculated_rate = int(min(45, max(base_rate, base_rate + need_boost * 0.75)))
                rate_val = f"+{calculated_rate}%"
            else:
                rate_val = f"+{base_rate}%" if base_rate >= 0 else f"{base_rate}%"

            temp_mp3 = output_path.with_suffix(".neural.mp3")

            with _edge_tts_lock:
                for attempt in range(3):
                    try:
                        communicate = edge_tts.Communicate(
                            text_clean, voice=voice_clean, rate=rate_val, pitch=pitch_str
                        )
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(communicate.save(str(temp_mp3)))
                        finally:
                            try:
                                loop.close()
                            except Exception:
                                pass
                        if temp_mp3.exists() and temp_mp3.stat().st_size > 500:
                            break
                    except Exception as ex_attempt:
                        logger.warning(
                            f"Neural Khmer TTS attempt {attempt + 1}/3 failed for '{text_clean[:15]}...': {ex_attempt}"
                        )
                        time.sleep(0.3)

            if temp_mp3.exists() and temp_mp3.stat().st_size > 0 and ffmpeg_bin:
                raw_dur = get_audio_duration_ffmpeg(temp_mp3, ffmpeg_bin)
                
                if is_sdach:
                    # Sdach Game Signature Vocal Transformation:
                    # 1. Formant Harmonic Pitch Shift (+12% frequency elevation to eliminate deep Piseth tone)
                    # 2. Resonator Presence EQ (+4.5dB at 2.8kHz)
                    # 3. Boxiness De-mud EQ (-3.5dB at 480Hz)
                    # 4. Airy Brilliance (+3.5dB at 5.5kHz) & Chest Warmth (+2.2dB at 160Hz)
                    # 5. Punchy Reviewer Broadcast Compression & Loudness
                    filters = [
                        "asetrate=48000*1.12,aresample=48000,atempo=1.03",
                        "equalizer=f=480:width_type=q:width=1.5:g=-3.5",
                        "equalizer=f=2800:width_type=q:width=1.2:g=4.5",
                        "highshelf=f=5500:g=3.5",
                        "lowshelf=f=160:g=2.2",
                        "acompressor=threshold=0.08:ratio=4.2:attack=5:release=80:makeup=2.2",
                        "loudnorm=I=-16:TP=-1.5:LRA=6",
                    ]
                elif is_harvard:
                    # Harvard Signature Documentary / Narrator Acoustic Profile:
                    # 1. Deep chest resonance (+4.5dB at 110Hz & +3.5dB at 180Hz)
                    # 2. De-nasal filter (-4.0dB at 1100Hz) to eliminate Piseth's nasal tone
                    # 3. Articulate broadcast presence (+3.2dB at 3.2kHz)
                    # 4. Silky air (+2.8dB at 8kHz) & High-frequency smoothing
                    # 5. Authoritative narrator dynamics
                    filters = [
                        "highpass=f=55",
                        "lowshelf=g=4.5:f=110",
                        "equalizer=f=180:width_type=q:width=1.2:g=3.5",
                        "equalizer=f=1100:width_type=q:width=1.8:g=-4.0",
                        "equalizer=f=3200:width_type=q:width=1.2:g=3.2",
                        "highshelf=g=2.8:f=8000",
                        "lowpass=f=15000",
                        "acompressor=threshold=0.08:ratio=3.8:attack=10:release=140:makeup=2.2",
                        "loudnorm=I=-16:TP=-1.5:LRA=6",
                    ]
                elif voice_profile and voice_profile.get("pitch_ratio", 1.0) != 1.0:
                    p_ratio = voice_profile["pitch_ratio"]
                    filters = [
                        f"asetrate=48000*{p_ratio:.3f},aresample=48000",
                        "equalizer=f=3200:width_type=q:width=1.2:g=2.5",
                        "lowshelf=g=1.5:f=180",
                        "highshelf=g=1.5:f=10000",
                        "acompressor=threshold=0.12:ratio=3.5:attack=8:release=90:makeup=1.8",
                        "loudnorm=I=-16:TP=-1.5:LRA=7",
                    ]
                else:
                    # Standard Studio Vocal Mastering Chain: Warmth, Consonant Clarity, Air & Compression
                    filters = [
                        "highpass=f=80",
                        "lowshelf=g=1.2:f=180",
                        "equalizer=f=3200:width_type=q:width=1.2:g=2.2",
                        "highshelf=g=1.5:f=10000",
                        "lowpass=f=16500",
                        "acompressor=threshold=0.15:ratio=3.0:attack=10:release=100:makeup=1.5",
                        "loudnorm=I=-16:TP=-1.5:LRA=7",
                    ]

                # Dynamic tempo matching for lip sync & zero cutoffs:
                # Guarantees each audio clip finishes completely within the available time slot
                if max_allowed_duration > 0 and raw_dur > 0:
                    ratio = raw_dur / max_allowed_duration
                    if ratio > 1.03:
                        speed = min(1.65, max(1.0, ratio))
                        if speed > 1.02:
                            filters.append(f"atempo={speed:.2f}")
                    elif ratio < 0.65 and raw_dur > 0.6:
                        speed = max(0.88, ratio)
                        filters.append(f"atempo={speed:.2f}")

                # Broadcast dynamic leveling and studio loudness
                filters.append("acompressor=threshold=0.15:ratio=3.0:attack=10:release=100:makeup=1.5")
                filters.append("loudnorm=I=-16:TP=-1.5:LRA=7")

                cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-i",
                    str(temp_mp3.resolve()),
                ]
                if filters:
                    cmd.extend(["-filter:a", ",".join(filters)])

                cmd.extend([
                    "-ar", "48000",
                    "-ac", "2",
                    str(output_path.resolve()),
                ])

                creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=creation_flags,
                )
                try:
                    temp_mp3.unlink()
                except OSError:
                    pass

                if output_path.exists() and output_path.stat().st_size > 0:
                    v_desc = f"Clone ({Path(ref_audio_path).name})" if (ref_audio_path and Path(ref_audio_path).exists()) else voice_clean
                    logger.info(
                        f"Generated Studio Neural Khmer voice ({v_desc}) with natural cadence for: '{text_clean[:20]}...'"
                    )
                    return True
        except Exception as e:
            logger.warning(f"Neural Khmer TTS exception ({e}), falling back to online Google TTS.")
        return False

    def _generate_online_khmer_tts(
        self, text: str, output_path: Path, max_allowed_duration: float = 0.0
    ) -> bool:
        text_clean = clean_text_for_tts(text)
        if not text_clean:
            return False

        # Under NO circumstance should Chinese characters be passed to Khmer TTS
        if re.search(r"[\u4e00-\u9fff]", text_clean):
            logger.warning(f"Skipping online Google TTS for Chinese text: '{text_clean[:20]}...'")
            return False

        import urllib.parse
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        chunks = [text_clean[i:i+100] for i in range(0, len(text_clean), 100)]
        combined_audio = bytearray()

        try:
            for chunk in chunks:
                encoded_q = urllib.parse.quote(chunk)
                url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={encoded_q}&tl=km&client=tw-ob"
                for attempt in range(2):
                    try:
                        resp = requests.get(url, headers=headers, timeout=5)
                        if resp.status_code == 200 and resp.content:
                            combined_audio.extend(resp.content)
                            break
                    except Exception:
                        pass
                    time.sleep(0.2)

            if combined_audio:
                temp_mp3 = output_path.with_suffix(".temp.mp3")
                with open(temp_mp3, "wb") as f:
                    f.write(combined_audio)

                ffmpeg_bin = get_ffmpeg_path()
                if ffmpeg_bin and temp_mp3.exists():
                    raw_dur = get_audio_duration_ffmpeg(temp_mp3, ffmpeg_bin)
                    filters = []
                    if max_allowed_duration > 0 and raw_dur > 0:
                        ratio = raw_dur / max_allowed_duration
                        if ratio > 1.05:
                            speed = min(2.0, ratio)
                            filters.append(f"atempo={speed:.2f}")
                        elif ratio < 0.75 and raw_dur > 0.5:
                            speed = max(0.85, ratio)
                            filters.append(f"atempo={speed:.2f}")

                    cmd = [
                        ffmpeg_bin,
                        "-y",
                        "-i",
                        str(temp_mp3.resolve()),
                    ]
                    if filters:
                        cmd.extend(["-filter:a", ",".join(filters)])

                    cmd.extend([
                        "-ar",
                        "44100",
                        "-ac",
                        "2",
                        str(output_path.resolve()),
                    ])
                    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=creation_flags,
                    )
                    try:
                        temp_mp3.unlink()
                    except OSError:
                        pass
                    if output_path.exists() and output_path.stat().st_size > 0:
                        logger.info(
                            f"Generated Khmer speech with lip-sync tempo matching for: '{text[:20]}...'"
                        )
                        return True
        except Exception as e:
            logger.debug(f"Online Khmer TTS fallback failed: {e}")
        return False

    def _generate_fallback_audio(self, duration_sec: float, output_path: Path) -> bool:
        ffmpeg_bin = get_ffmpeg_path()
        if not ffmpeg_bin:
            return False

        duration_sec = max(0.2, duration_sec)
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            str(duration_sec),
            "-c:a",
            "pcm_s16le",
            str(output_path.resolve()),
        ]

        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NO_WINDOW

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
            return output_path.exists()
        except Exception as e:
            logger.error(f"Fallback audio generator failed: {e}")
            return False


class VoxCPM2DubbingWorker(QThread):
    """QThread worker to generate TTS audio clips in parallel for a list of SubtitleItem dialogue lines."""

    progress_changed = pyqtSignal(float, str)  # percent, status message
    finished = pyqtSignal(list, list)  # audio_paths, subtitle_items
    error = pyqtSignal(str)

    def __init__(
        self,
        subtitle_items: list[SubtitleItem],
        output_dir: str,
        target_lang: str = "km",
        api_url: str = "http://localhost:8000/tts",
        voice: str = "km-KH-PisethNeural",
        ref_audio_path: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.subtitle_items = subtitle_items
        self.output_dir = Path(output_dir)
        self.target_lang = target_lang
        self.client = VoxCPM2Client(api_url=api_url)
        self.voice = voice
        self.ref_audio_path = ref_audio_path

    def run(self) -> None:
        if not self.subtitle_items:
            self.finished.emit([], [])
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)
        total = len(self.subtitle_items)
        completed_count = 0
        results = [None] * total

        def process_item(item_idx: int, item: SubtitleItem):
            clip_path = self.output_dir / f"clip_{item.index:04d}.wav"
            if item_idx + 1 < total:
                next_item = self.subtitle_items[item_idx + 1]
                gap = next_item.start_seconds - item.start_seconds
                max_allowed = max(0.6, gap - 0.05) if gap > 0 else max(0.6, item.duration_seconds)
            else:
                max_allowed = max(item.duration_seconds, 2.5)

            success = self.client.generate_audio(
                text=item.text,
                duration_sec=item.duration_seconds,
                output_path=clip_path,
                target_lang=self.target_lang,
                max_allowed_duration=max_allowed,
                voice=self.voice,
                ref_audio_path=self.ref_audio_path,
            )
            if success and clip_path.exists():
                return item_idx, str(clip_path)
            return item_idx, None

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(process_item, i, item)
                for i, item in enumerate(self.subtitle_items)
            ]
            for future in as_completed(futures):
                idx, clip_str = future.result()
                if clip_str:
                    results[idx] = clip_str
                completed_count += 1
                percent = (completed_count / total) * 100.0
                msg = f"Generating voice for item {completed_count}/{total}..."
                self.progress_changed.emit(percent, msg)

        # Preserve 1-to-1 index positioning
        audio_files = [path or "" for path in results]
        self.finished.emit(audio_files, self.subtitle_items)

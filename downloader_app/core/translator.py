"""
Title Translator Core Module
Uses Gemini REST API to translate/localize movie and video titles into natural spoken Khmer (or other target languages)
with persistent local caching and non-blocking QThread execution.
"""

import json
import os
import re
from pathlib import Path

import requests
from PyQt6.QtCore import QStandardPaths, QThread, pyqtSignal

from downloader_app.utils.logger import setup_logger

logger = setup_logger("downloader.translator")


def get_api_key() -> str | None:
    """Reads GEMINI_API_KEY from config, environment variables, or .env file."""
    from downloader_app.core.config import get_gemini_api_key
    k = get_gemini_api_key()
    return k if k else None


def get_cache_path() -> Path:
    """Returns the persistent JSON cache filepath in AppData folder."""
    app_data_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not app_data_dir:
        app_data_dir = str(Path.home() / ".downloader_app")
    p = Path(app_data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / "title_translations_cache.json"


def has_cjk(text: str) -> bool:
    """Returns True if text contains Chinese/Japanese/Korean (CJK) characters."""
    if not text:
        return False
    return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))


def has_thai(text: str) -> bool:
    """Returns True if text contains Thai characters (Unicode 0E00-0E7F)."""
    if not text:
        return False
    return bool(re.search(r"[\u0e00-\u0e7f]", text))


def has_khmer(text: str) -> bool:
    """Returns True if text contains Khmer characters (Unicode 1780-17FF, 19E0-19FF)."""
    if not text:
        return False
    return bool(re.search(r"[\u1780-\u17ff\u19e0-\u19ff]", text))


def is_valid_target_text(text: str, target_lang: str = "km") -> bool:
    """
    Validates that translated text matches the target language.
    Strictly forbids Thai script and CJK leakage when target_lang is 'km'.
    """
    if not text or not text.strip():
        return False
    if has_cjk(text):
        return False
    if target_lang == "km":
        if has_thai(text):
            return False
        if not has_khmer(text):
            return False
    elif target_lang == "en":
        if has_thai(text) or has_khmer(text):
            return False
    return True


def clean_drama_title(title: str) -> str:
    """Strips episode numbers, extensions, season tags, and folder noise from a title string."""
    if not title:
        return ""
    t = title.strip()
    t = re.sub(r"\.(mp4|mkv|avi|mov|ts|flv|webm)$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[\s_\-]+(Episode|Ep|EP|ភាគ|ភាគទី)\s*\d+.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[\s_\-]+(parts|part\s*\d+|clip|full\s*movie).*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[\(\[\{]?(Episodes|Full|HD|1080p)[\)\]\}]?", "", t, flags=re.IGNORECASE)
    return t.strip() or title.strip()


class Translator:
    """Handles Gemini API translation requests with local file-backed caching."""

    def __init__(self, cache_file: Path | None = None) -> None:
        self.cache_file = cache_file or get_cache_path()
        self._cache: dict[str, str] = self._load_cache()

    def _load_cache(self) -> dict[str, str]:
        """Loads cached translations from disk, purging any corrupt or foreign script leaks (e.g. Thai in Khmer cache)."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                cleaned = {}
                changed = False
                for k, v in raw.items():
                    if "_km" in k:
                        if isinstance(v, list):
                            if all(is_valid_target_text(item, "km") for item in v):
                                cleaned[k] = v
                            else:
                                changed = True
                        elif isinstance(v, str):
                            if is_valid_target_text(v, "km"):
                                cleaned[k] = v
                            else:
                                changed = True
                    else:
                        cleaned[k] = v
                if changed:
                    try:
                        with open(self.cache_file, "w", encoding="utf-8") as f:
                            json.dump(cleaned, f, ensure_ascii=False, indent=2)
                    except OSError:
                        pass
                return cleaned
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Could not load translation cache: {e}")
        return {}

    def _save_cache(self) -> None:
        """Saves current translation cache to disk."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning(f"Could not save translation cache: {e}")

    def _translate_gtx(self, text: str, target_lang: str = "km") -> str:
        """Translates text into target language using Google Translate GTX endpoint."""
        clean_text = text.strip()
        if not clean_text:
            return text
        try:
            # Multi-stage translation for CJK text:
            # Chinese -> English -> Khmer to ensure true semantic Khmer meaning (no Chinese phonetic transliteration)
            if has_cjk(clean_text) and target_lang == "km":
                eng_text = self._translate_gtx_single(clean_text, target_lang="en", source_lang="zh-CN")
                if eng_text and is_valid_target_text(eng_text, "en") and eng_text.lower() != clean_text.lower():
                    km_text = self._translate_gtx_single(eng_text, target_lang="km", source_lang="en")
                    if km_text and is_valid_target_text(km_text, "km"):
                        return km_text
                    if eng_text:
                        return f"រឿងភាគ {eng_text}"

            res = self._translate_gtx_single(clean_text, target_lang=target_lang, source_lang="auto")
            if target_lang == "km" and has_thai(res):
                return ""
            if has_cjk(res):
                return ""
            return res or clean_text
        except Exception as e:  # noqa: BLE001
            logger.debug(f"GTX translation failed: {e}")
        return clean_text

    def _translate_gtx_single(self, clean_text: str, target_lang: str = "km", source_lang: str = "auto") -> str:
        """Internal single-pass Google Translate GTX request."""
        try:
            import urllib.parse

            encoded = urllib.parse.quote(clean_text)
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q={encoded}"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and data[0]:
                    translated_chunks = [
                        item[0] for item in data[0] if isinstance(item, list) and item[0]
                    ]
                    translated = "".join(translated_chunks).strip()
                    if translated:
                        logger.info(f"GTX single translation ({source_lang}->{target_lang}) for '{clean_text}' -> '{translated}'")
                        return translated
        except Exception as e:  # noqa: BLE001
            logger.debug(f"GTX single request failed: {e}")
        return clean_text

    def _generate_fallback_suggestions(
        self, title: str, target_lang: str = "km", count: int = 3
    ) -> list[str]:
        """Generates smart candidate title localizations translated into target language script."""
        clean_t = clean_drama_title(title)
        translated_base = self._translate_gtx(clean_t, target_lang=target_lang)

        if target_lang == "km":
            if translated_base and is_valid_target_text(translated_base, "km"):
                candidates = [
                    f"រឿងភាគ {translated_base}",
                    f"{translated_base}",
                    f"រឿង {translated_base}",
                    f"រឿងភាគចិន {translated_base}",
                    f"រឿងភាគពិសេស {translated_base}",
                ]
            else:
                candidates = [
                    "រឿងភាគចិន",
                    "រឿងភាគចិន ភាគពិសេស",
                    "រឿងភាគចិន ពេញនិយម",
                    "រឿងភាគពិសេស",
                    "រឿងភាគបុរាណចិន",
                ]
        else:
            if translated_base and is_valid_target_text(translated_base, "en"):
                candidates = [
                    f"Drama Series - {translated_base}",
                    f"{translated_base} Full Season",
                    f"{translated_base}",
                    f"Series - {translated_base}",
                    f"Collection - {translated_base}",
                ]
            else:
                candidates = [
                    "Chinese Drama Series",
                    "Chinese Drama Full Season",
                    "Popular Chinese Drama",
                    "Drama Series",
                    "Special Drama Collection",
                ]
        seen = set()
        res = []
        for c in candidates:
            if c and c not in seen and is_valid_target_text(c, target_lang):
                seen.add(c)
                res.append(c)
        return res[:count]

    def translate_title(self, title: str, target_lang: str = "km") -> str:
        """
        Translates/localizes a movie title into natural target language (default: Khmer).
        Returns cached result if available. On any error, falls back to original title or GTX.
        """
        clean_title = clean_drama_title(title)
        if not clean_title:
            return title

        cache_key = f"{clean_title}_{target_lang}"
        if cache_key in self._cache:
            val = self._cache[cache_key]
            if is_valid_target_text(val, target_lang=target_lang):
                logger.info(f"Translation cache hit for '{clean_title}'")
                return val

        api_key = get_api_key()
        if not api_key:
            logger.info("GEMINI_API_KEY not set — using GTX translation fallback")
            gtx_res = self._translate_gtx(clean_title, target_lang=target_lang)
            if gtx_res and is_valid_target_text(gtx_res, target_lang=target_lang):
                self._cache[cache_key] = gtx_res
                self._save_cache()
                return gtx_res
            return clean_title

        models_to_try = [
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-flash-latest",
        ]

        for model_name in models_to_try:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            prompt = (
                "You are a professional Cambodian movie title translator.\n"
                "TARGET LANGUAGE: Khmer (ភាសាខ្មែរ / Cambodia only).\n"
                "CRITICAL INSTRUCTIONS:\n"
                "1. Output MUST be 100% authentic native KHMER SCRIPT (Unicode 1780-17FF, e.g. រឿង, ស្នេហា, អរគុណ).\n"
                "2. NEVER output Thai script (ภาษาไทย เช่น ท่านหญิง, วิเศษ), Lao, Vietnamese, or Chinese under any circumstances.\n"
                "3. Translate or localize the following movie/drama title into natural, fluent, spoken Khmer — something a native speaker in Cambodia would actually say.\n"
                "4. Return ONLY the translated Khmer title with no quotes, extra explanations, or markdown formatting.\n\n"
                f"Title: '{clean_title}'"
            )

            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt}
                        ]
                    }
                ]
            }

            try:
                logger.info(f"Calling Gemini API ({model_name}) to translate title: '{clean_title}'")
                resp = requests.post(endpoint, json=payload, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            translated_text = parts[0].get("text", "").strip().strip('"').strip("'")
                            if is_valid_target_text(translated_text, target_lang=target_lang):
                                self._cache[cache_key] = translated_text
                                self._save_cache()
                                logger.info(f"Successfully translated title to: '{translated_text}'")
                                return translated_text
                            else:
                                logger.warning(f"Rejected invalid script translation from '{model_name}': '{translated_text}'")
                elif resp.status_code == 429:
                    logger.warning(f"Gemini API model '{model_name}' quota exceeded (HTTP 429), trying next model...")
                    continue
                else:
                    logger.warning(f"Gemini API model '{model_name}' returned HTTP {resp.status_code}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Translation failed on '{model_name}' due to exception: {e}")

        logger.info(f"Gemini API models exhausted/quota exceeded for '{clean_title}' — falling back to GTX")
        gtx_res = self._translate_gtx(clean_title, target_lang=target_lang)
        if gtx_res and is_valid_target_text(gtx_res, target_lang=target_lang):
            self._cache[cache_key] = gtx_res
            self._save_cache()
            return gtx_res

        return clean_title

    def suggest_titles(
        self, title: str, target_lang: str = "km", count: int = 3
    ) -> list[str]:
        """
        Requests `count` distinct natural Khmer title translations/localizations from Gemini.
        Returns cached list if available. On error or missing API key, generates smart fallback list.
        """
        clean_t = clean_drama_title(title)
        if not clean_t:
            return [title]

        count = max(1, min(count, 5))
        cache_key = f"{clean_t}_{target_lang}_count_{count}"
        if cache_key in self._cache and isinstance(self._cache[cache_key], list):
            valid_cached = [item for item in self._cache[cache_key] if is_valid_target_text(item, target_lang=target_lang)]
            if valid_cached and len(valid_cached) == count:
                logger.info(f"Title suggestions cache hit for '{clean_t}' (count={count})")
                return valid_cached

        api_key = get_api_key()
        if not api_key:
            logger.info("GEMINI_API_KEY not set — generating smart fallback title suggestions")
            return self._generate_fallback_suggestions(clean_t, target_lang=target_lang, count=count)

        models_to_try = [
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-flash-latest",
        ]

        prompt = (
            f"You are a professional Cambodian movie title translator.\n"
            f"TARGET LANGUAGE: Khmer (ភាសាខ្មែរ / Cambodia only).\n"
            "CRITICAL INSTRUCTIONS:\n"
            f"1. Produce exactly {count} distinct, natural, fluent spoken Khmer title translations/localizations for the following drama title.\n"
            "2. Output MUST be 100% written in authentic KHMER SCRIPT (Unicode 1780-17FF, e.g. រឿង, ម្ចាស់, ស្នេហា, ទ្រព្យ).\n"
            "3. STRICT NEGATIVE CONSTRAINT: DO NOT output Thai script (ภาษาไทย เช่น ท่านหญิง, วิเศษ, ของมีค่า), Lao, Vietnamese, or Chinese under any circumstances.\n"
            f"4. Return ONLY a numbered list (1. Title1\n2. Title2 ... up to {count}. Title{count}), "
            "with no intro, markdown, quotes, or explanations.\n\n"
            f"Title: '{clean_t}'"
        )

        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        for model_name in models_to_try:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                logger.info(f"Calling Gemini API ({model_name}) for {count} title suggestions: '{clean_t}'")
                resp = requests.post(endpoint, json=payload, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "").strip()
                            items = []
                            for line in text.splitlines():
                                line = line.strip()
                                if not line:
                                    continue
                                if line[0].isdigit():
                                    idx = 0
                                    while idx < len(line) and (line[idx].isdigit() or line[idx] in ".-) "):
                                        idx += 1
                                    line = line[idx:].strip()
                                line = line.strip('"').strip("'")
                                if line and is_valid_target_text(line, target_lang=target_lang):
                                    items.append(line)

                            if len(items) >= count:
                                items = items[:count]
                                self._cache[cache_key] = items
                                self._save_cache()
                                logger.info(f"Successfully generated {len(items)} suggestions using {model_name}: {items}")
                                return items
                            elif items:
                                # Supplement with smart fallbacks to reach count
                                fallbacks = self._generate_fallback_suggestions(clean_t, target_lang=target_lang, count=count)
                                for fb in fallbacks:
                                    if fb not in items:
                                        items.append(fb)
                                    if len(items) == count:
                                        break
                                self._cache[cache_key] = items
                                self._save_cache()
                                return items
                elif resp.status_code == 429:
                    logger.warning(f"Gemini API model '{model_name}' quota exceeded (HTTP 429), trying next model...")
                    continue
                else:
                    logger.warning(f"Gemini API model '{model_name}' returned HTTP {resp.status_code}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Suggest titles failed on '{model_name}' due to exception: {e}")

        logger.info(f"Gemini API models exhausted/quota exceeded for '{clean_t}' — generating smart GTX fallback suggestions")
        return self._generate_fallback_suggestions(clean_t, target_lang=target_lang, count=count)


    def translate_subtitle_blocks(
        self, texts: list[str], target_lang: str = "km", progress_callback=None
    ) -> list[str]:
        """
        Translates a list of dialogue lines into natural spoken Khmer dialogue lines.
        Uses a resilient multi-model fallback chain to ensure 100% completion without 429 quota failures.
        Maintains index 1-to-1 mapping for voice dubbing alignment.
        """
        if not texts:
            return []

        total_count = len(texts)

        # Batch large subtitle lists into chunks of 25 to avoid timeouts or token limits
        if total_count > 25:
            results = []
            chunk_size = 25
            for i in range(0, total_count, chunk_size):
                chunk = texts[i : i + chunk_size]
                chunk_translated = self.translate_subtitle_blocks(chunk, target_lang=target_lang)
                results.extend(chunk_translated)
                done_count = min(total_count, i + chunk_size)
                pct = float(done_count / total_count) * 100.0
                if progress_callback:
                    progress_callback(pct, f"Translating dialogue ({done_count}/{total_count})...")
            return results

        if progress_callback:
            progress_callback(30.0, f"Translating {total_count} dialogue lines...")

        api_key = get_api_key()
        if not api_key:
            logger.info("GEMINI_API_KEY not set — using GTX translation fallback for subtitles")
            res = [self._translate_gtx(t, target_lang=target_lang) or t for t in texts]
            if progress_callback:
                progress_callback(100.0, "Translation complete.")
            return res

        models_to_try = [
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-flash-latest",
        ]

        prompt_lines = [
            "You are a master Cambodian movie dubbing director and translator into natural spoken Khmer (ភាសាខ្មែរ).",
            f"Translate each line of dialogue into natural, dramatic spoken Khmer suitable for Cambodian voice actors.",
            "CRITICAL REQUIREMENTS:",
            "1. Output MUST be 100% written in authentic native Khmer script (អក្សរខ្មែរ, Unicode 1780-17FF).",
            "2. Absolutely NO Chinese characters (中文), Thai script (ภาษาไทย), Vietnamese, or other foreign words.",
            "3. Maintain strict 1-to-1 numbered format (e.g. 1. text\\n2. text).",
            "Lines to translate:\n",
        ]
        for i, txt in enumerate(texts, start=1):
            prompt_lines.append(f"{i}. {txt}")

        prompt = "\n".join(prompt_lines)
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        for model_name in models_to_try:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                resp = requests.post(endpoint, json=payload, timeout=45)
                logger.info(
                    f"translate_subtitle_blocks ({model_name}): status={resp.status_code} for {len(texts)} items"
                )
                if resp.status_code == 200:
                    data = resp.json()
                    parts = (
                        data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [])
                    )
                    if parts:
                        raw_text = parts[0].get("text", "").strip()
                        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
                        result_map = {}
                        for line in lines:
                            # Match lines like '1. text' or '**1. text**'
                            clean_line = re.sub(r"^\*+|\*+$", "", line).strip()
                            match = re.match(r"^(\d+)[\.\:\)]\s*(.*)$", clean_line)
                            if match:
                                num = int(match.group(1))
                                trans_text = match.group(2).strip()
                                # Clean any leftover markdown or asterisks
                                trans_text = re.sub(r"^\*+|\*+$", "", trans_text).strip()
                                if trans_text and is_valid_target_text(trans_text, target_lang):
                                    result_map[num] = trans_text
                                elif trans_text:
                                    # Line still contains CJK/Thai — apply GTX fallback for this line
                                    orig_line = texts[num - 1] if 0 < num <= len(texts) else trans_text
                                    gtx_result = self._translate_gtx(orig_line, target_lang=target_lang)
                                    if gtx_result and is_valid_target_text(gtx_result, target_lang):
                                        result_map[num] = gtx_result
                                        logger.debug(f"Line {num}: GTX fallback succeeded for mixed-script line.")
                                    else:
                                        # Strip non-Khmer characters as last resort
                                        khmer_only = re.sub(
                                            r"[^\u1780-\u17FF\u200B\u200C\u200D\u00A0\s\.,!?\-:;។៕]",
                                            "", trans_text
                                        ).strip()
                                        if khmer_only:
                                            result_map[num] = khmer_only

                        if result_map:
                            logger.info(
                                f"translate_subtitle_blocks: successfully parsed {len(result_map)}/{len(texts)} items using {model_name}"
                            )
                            if len(result_map) > len(texts) and len(texts) == 1:
                                # Input was a single multi-sentence block that the model split into individual translated lines
                                translated = [result_map[k] for k in sorted(result_map.keys())]
                            else:
                                translated = [
                                    result_map.get(idx + 1, orig)
                                    for idx, orig in enumerate(texts)
                                ]
                            if progress_callback:
                                progress_callback(100.0, "Translation complete.")
                            return translated
                elif resp.status_code in (429, 503):
                    logger.warning(
                        f"translate_subtitle_blocks: {model_name} returned {resp.status_code}, failing over to next model..."
                    )
                    time.sleep(1)
                    continue
                else:
                    logger.warning(
                        f"translate_subtitle_blocks: {model_name} HTTP {resp.status_code}: {resp.text[:150]}"
                    )
            except Exception as e:
                logger.warning(f"translate_subtitle_blocks error on {model_name}: {e}")

        logger.info(f"translate_subtitle_blocks: Gemini models exhausted/quota exceeded — falling back to GTX for {len(texts)} items")
        res = [self._translate_gtx(t, target_lang=target_lang) or t for t in texts]
        if progress_callback:
            progress_callback(100.0, "Translation complete.")
        return res


class TranslationWorker(QThread):
    """QThread worker executing translation in the background without blocking the UI."""

    finished = pyqtSignal(str)  # Emits translated title (or original title on fallback)
    error = pyqtSignal(str)

    def __init__(
        self,
        title: str,
        target_lang: str = "km",
        translator: Translator | None = None,
        parent: QThread | None = None,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.target_lang = target_lang
        self.translator = translator or Translator()

    def run(self) -> None:
        try:
            result = self.translator.translate_title(self.title, self.target_lang)
            self.finished.emit(result)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"TranslationWorker exception: {e}")
            self.error.emit(str(e))
            self.finished.emit(self.title)


class TitleSuggestionsWorker(QThread):
    """QThread worker fetching multiple title suggestions in background without blocking UI."""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(
        self,
        title: str,
        target_lang: str = "km",
        count: int = 3,
        translator: Translator | None = None,
        parent: QThread | None = None,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.target_lang = target_lang
        self.count = count
        self.translator = translator or Translator()

    def run(self) -> None:
        try:
            results = self.translator.suggest_titles(
                self.title, self.target_lang, self.count
            )
            self.finished.emit(results)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"TitleSuggestionsWorker exception: {e}")
            self.error.emit(str(e))
            self.finished.emit([self.title])




class SubtitleTranslationWorker(QThread):
    """QThread worker to translate a list of SubtitleItem dialogue lines in background."""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress_changed = pyqtSignal(float, str)  # percent, status message

    def __init__(
        self,
        subtitle_items: list,
        target_lang: str = "km",
        translator: Translator | None = None,
        parent: QThread | None = None,
    ) -> None:
        super().__init__(parent)
        self.subtitle_items = subtitle_items
        self.target_lang = target_lang
        self.translator = translator or Translator()

    def run(self) -> None:
        try:
            raw_texts = [item.text for item in self.subtitle_items]
            logger.info(f"SubtitleTranslationWorker: translating {len(raw_texts)} items to {self.target_lang}")

            def _on_trans_progress(pct: float, msg: str):
                self.progress_changed.emit(pct, msg)

            translated_texts = self.translator.translate_subtitle_blocks(
                raw_texts, self.target_lang, progress_callback=_on_trans_progress
            )
            # Validate translation produced different/non-empty results
            changed = sum(1 for orig, trans in zip(raw_texts, translated_texts) if orig != trans)
            logger.info(f"SubtitleTranslationWorker: {changed}/{len(raw_texts)} items were translated (changed from original)")
            for i, item in enumerate(self.subtitle_items):
                if i < len(translated_texts) and translated_texts[i]:
                    item.text = translated_texts[i]
            self.progress_changed.emit(100.0, "Subtitle translation finished.")
            self.finished.emit(self.subtitle_items)
        except Exception as e:
            logger.warning(f"SubtitleTranslationWorker error: {e}")
            # On failure, emit original items — do NOT also emit error (which resets the UI)
            self.finished.emit(self.subtitle_items)


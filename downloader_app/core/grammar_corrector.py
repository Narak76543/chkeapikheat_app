"""
Khmer Grammar & Phrase Corrector Engine
Uses Gemini Multimodal AI to inspect, correct, and polish Khmer dialogue lines
for authentic Cambodian movie dubbing, fixing typos, incorrect subscripts, and awkward phrasing.
"""

import os
import re
import time
import requests

from downloader_app.core.translator import get_api_key
from downloader_app.utils.logger import setup_logger

ACTIVE_TRANSLATION_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-flash-latest",
]

logger = setup_logger("downloader.grammar_corrector")


def clean_khmer_dialogue_typos(text: str) -> str:
    """
    Applies deterministic Khmer spelling, Unicode combining mark, and typo corrections.
    Fixes common OCR/translation errors in short drama subtitles, and strips any parenthetical commentary/notes.
    """
    if not text:
        return ""
    t = text.strip()

    # Strip any translator/editor parenthetical commentary or notes (e.g. "(រក្សាទុក - ល្អហើយ)", "(កែពី...)", "(បន្ថែម...)")
    t = re.sub(
        r"\s*[\(（\[【][^\)）\]】]*?(?:រក្សាទុក|កែ|បន្ថែម|ដក|ប្ដូរ|ប្តូរ|ល្អ|ស្ដាប់|ស្តាប់|ធម្មជាតិ|បរិបទ|ចំណាំ|សម្គាល់|ពន្យល់|note|keep|edit|change|context|meaning|like|sound)[^\)）\]】]*?[\)）\]】]",
        "",
        t,
        flags=re.IGNORECASE,
    )
    # Strip any trailing parenthetical annotation at the end of the line
    t = re.sub(r"\s*[\(（\[【][^\)）\]】]+[\)）\]】]\s*$", "", t)
    # Strip empty brackets or stray trailing parenthesis
    t = re.sub(r"[\(（\[【]\s*[\)）\]】]", "", t).strip()

    # Remove corrupted currency symbols inserted inside names or words (e.g. យូ៛រ៉ូ -> យូរ៉ូ)
    t = re.sub(r"(?<=\S)៛(?=\S)", "", t)

    # Fix common Khmer word typos and name inconsistencies (Khmer doesn't use standard ASCII \b boundaries)
    replacements = [
        ("ប្រសិនបិយ", "ប្រសិនបើ"),
        ("ិនមិនអាច", "មិនអាច"),
        ("អាកខ្វាក់", "អាខ្វាក់"),
        ("យូ៛រ៉ូ", "យូរ៉ុយ"),
        ("យូ៛រ៉ុយ", "យូរ៉ុយ"),
        ("យូរ៉ូ", "យូរ៉ុយ"),
        ("ធូ ធានសឺ", "ឈូ ធានសឺ"),
        ("ធូ ធានទី", "ឈូ ធានទី"),
        ("ធូ ធានយូ", "ឈូ ធានយូ"),
        ("ធូ ធាន", "ឈូ ធាន"),
    ]

    for pat, rep in replacements:
        t = t.replace(pat, rep)

    return t.strip()


def correct_khmer_dialogue_grammar(
    khmer_lines: list[str], progress_callback=None
) -> list[str]:
    """
    Polishes and corrects Khmer dialogue lines for movie dubbing.
    Fixes Khmer spelling typos, incorrect subscripts (ជើងអក្សរ), awkward phrasing, and removes placeholders like (គ្មានទិន្នន័យ).
    """
    if not khmer_lines:
        return []

    # First pass: clean deterministic typos across all lines
    pre_cleaned = [clean_khmer_dialogue_typos(l) for l in khmer_lines]

    api_key = get_api_key()
    if not api_key:
        logger.info("No Gemini API key available for Khmer grammar correction — returning pre-cleaned lines.")
        return pre_cleaned

    total_count = len(pre_cleaned)

    # Batch in chunks of 25 lines
    if total_count > 25:
        results = []
        chunk_size = 25
        for i in range(0, total_count, chunk_size):
            chunk = pre_cleaned[i : i + chunk_size]
            chunk_corrected = correct_khmer_dialogue_grammar(chunk)
            results.extend(chunk_corrected)
            done_count = min(total_count, i + chunk_size)
            pct = 88.0 + (float(done_count / total_count) * 10.0)
            if progress_callback:
                progress_callback(
                    pct, f"Correcting Khmer Grammar & Phrasing ({done_count}/{total_count})..."
                )
        return [clean_khmer_dialogue_typos(r) for r in results]

    if progress_callback:
        progress_callback(90.0, f"Polishing Khmer grammar & phrasing ({total_count} lines)...")

    prompt_lines = [
        "You are a master Cambodian linguist and senior movie dubbing editor (ភាសាខ្មែរ).",
        "YOUR TASK: Review, polish, and correct the grammar, spelling, and phrasing of these Khmer dialogue lines for Cambodian movie dubbing.",
        "CRITICAL CORRECTION RULES:",
        "1. FIX KHMER SPELLING & TYPOS: Correct any misspelled Khmer words (e.g. 'ប្រសិនបិយ' -> 'ប្រសិនបើ', 'ិនមិនអាច' -> 'មិនអាច', 'អាកខ្វាក់' -> 'អាខ្វាក់'), wrong subscripts (ជើងអក្សរ), or missing vowels.",
        "2. UNIFY CHARACTER NAMES: Maintain strict, consistent spelling of character names throughout the script (e.g. 'ឈូ ធានសឺ', 'ឈូ ធានយូ', 'យូរ៉ុយ'). Never mix different spellings for the same person.",
        "3. NATURAL MOVIE DUBBING PHRASING: Rewrite awkward or literal translations into natural, fluent, spoken conversational Khmer used in Cambodian cinema dubbing.",
        "4. REMOVE PLACEHOLDERS: If any line contains '(គ្មានទិន្នន័យ)' or 'គ្មានទិន្នន័យ' or placeholder text, remove it or replace with appropriate natural dialogue.",
        "5. KEEP TIME ALIGNMENT: Keep dialogue concise so timing fits the original video duration.",
        "6. Maintain strict 1-to-1 numbered format (e.g. 1. corrected Khmer line\n2. corrected Khmer line).",
        "7. STRICT NEGATIVE CONSTRAINT: Output ONLY pure spoken dialogue text! NEVER append any explanations, reasons, or commentary in parentheses like (រក្សាទុក - ល្អហើយ), (កែពី... មក...), or (បន្ថែម...). Absolutely NO parenthetical notes!\n",
        "Khmer dialogue lines to correct:\n",
    ]
    for i, line in enumerate(pre_cleaned, start=1):
        prompt_lines.append(f"{i}. {line}")

    prompt = "\n".join(prompt_lines)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.2,
            "maxOutputTokens": 4096,
        },
    }

    for model_name in ACTIVE_TRANSLATION_MODELS:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            resp = requests.post(endpoint, json=payload, timeout=30)
            if resp.status_code == 200:
                cands = resp.json().get("candidates", [])
                if cands:
                    parts = cands[0].get("content", {}).get("parts", [])
                    if parts:
                        raw_output = parts[0].get("text", "").strip()
                        corrected = _parse_numbered_lines(raw_output, len(pre_cleaned))
                        if len(corrected) == len(pre_cleaned):
                            logger.info(
                                f"Khmer Grammar Corrector ({model_name}) successfully polished {len(corrected)} lines."
                            )
                            return [clean_khmer_dialogue_typos(r) for r in corrected]
            elif resp.status_code in (429, 503):
                time.sleep(2.0)
                continue
        except Exception as e:
            logger.warning(f"Grammar correction error on {model_name}: {e}")
            continue

    return pre_cleaned


def _parse_numbered_lines(text: str, expected_count: int) -> list[str]:
    lines = text.splitlines()
    result = []
    pattern = re.compile(r"^\s*\d+[\.\:\、\)\-]\s*(.*)$")
    for line in lines:
        l = line.strip()
        m = pattern.match(l)
        if m:
            val = m.group(1).strip()
            result.append(val)

    if len(result) == expected_count:
        return result
    return []

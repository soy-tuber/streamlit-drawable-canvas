"""Gemini 2.5 Flash translation for the factory whiteboard.

Translates お知らせ / 安全訓 into the workforce's languages so safety- and
operation-critical text reaches non-Japanese-speaking workers.

Design (plan case C — hybrid):
  - Translations are keyed by a SHA-256 hash of the source text, so identical
    text shares a translation and a changed source naturally re-translates.
  - ``translate_batch`` returns cached results immediately and only calls
    Gemini for cache misses (one call for all misses).
  - Any failure (no API key, network blocked, bad response) falls back to the
    original text, so the app never breaks.
  - Admins can override any cached translation from the sidebar 🌐 翻訳 editor.
"""

import hashlib
import json

import streamlit as st

import db

# code -> display name. Offered as the language menu; admins enable a subset.
LANGUAGES = {
    "en": "English",
    "vi": "Tiếng Việt",
    "zh": "中文",
    "pt": "Português",
    "id": "Bahasa Indonesia",
    "ko": "한국어",
    "tl": "Filipino",
    "ne": "नेपाली",
}

DEFAULT_LANGS = ["en", "vi", "zh", "pt"]

_MODEL = "gemini-2.5-flash"


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _api_key():
    try:
        key = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        key = None
    return str(key).strip() if key else None


def is_available() -> bool:
    """True when translation can actually run (API key present + SDK installed)."""
    if not _api_key():
        return False
    try:
        import google.genai  # noqa: F401
    except ImportError:
        return False
    return True


def enabled_langs() -> list[str]:
    """Admin-configured set of target languages (codes), order preserved."""
    raw = db.get_state("enabled_langs")
    if raw:
        try:
            codes = [c for c in json.loads(raw) if c in LANGUAGES]
            if codes:
                return codes
        except (ValueError, TypeError):
            pass
    return list(DEFAULT_LANGS)


def set_enabled_langs(codes) -> None:
    codes = [c for c in codes if c in LANGUAGES]
    db.set_state("enabled_langs", json.dumps(codes))


def translate_batch(texts, lang: str) -> list[str]:
    """Translate texts into ``lang``; returns a list aligned to the input.

    ``lang == "ja"`` is a no-op. Cache misses are translated in a single
    Gemini call and persisted. Any failure falls back to the original text.
    """
    texts = list(texts)
    if lang == "ja" or not texts:
        return texts

    hashes = [_text_hash(t) for t in texts]
    cached = db.get_cached_translations(set(hashes), lang)
    missing_idx = [i for i, h in enumerate(hashes) if h not in cached]

    if missing_idx and is_available():
        miss_texts = [texts[i] for i in missing_idx]
        try:
            out = _call_gemini(miss_texts, LANGUAGES.get(lang, lang))
        except Exception:
            out = None
        if out and len(out) == len(miss_texts):
            for i, translated in zip(missing_idx, out):
                translated = (translated or "").strip() or texts[i]
                db.save_translation(hashes[i], lang, texts[i], translated)
                cached[hashes[i]] = translated

    return [cached.get(h, texts[i]) for i, h in enumerate(hashes)]


def _call_gemini(texts, lang_name: str) -> list[str]:
    """Translate a list of strings into ``lang_name`` via Gemini 2.5 Flash."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_api_key())
    prompt = (
        "You translate notices for a Japanese factory floor.\n"
        f"Translate each item of the JSON array below into {lang_name}.\n"
        "Use plain, simple wording suited to factory workers. For safety "
        "instructions, keep the meaning exact — do not soften or omit.\n"
        "Return ONLY a JSON array of strings, same length and order as the "
        "input.\n\n"
        f"{json.dumps(texts, ensure_ascii=False)}"
    )
    resp = client.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[str],
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    parsed = json.loads(resp.text)
    if not isinstance(parsed, list):
        raise ValueError("unexpected translation response")
    return [str(x) for x in parsed]

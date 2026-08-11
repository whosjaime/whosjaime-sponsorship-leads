from __future__ import annotations

import unicodedata

from sponsor_models import VideoRecord


def _primary_language(code: str) -> str:
    value = (code or "").strip().lower().replace("_", "-")
    return value.split("-", 1)[0] if value else ""


def _non_latin_ratio(text: str) -> tuple[int, int, float]:
    letters = [char for char in (text or "") if char.isalpha()]
    if not letters:
        return 0, 0, 0.0
    non_latin = 0
    for char in letters:
        name = unicodedata.name(char, "")
        if "LATIN" not in name:
            non_latin += 1
    return non_latin, len(letters), non_latin / len(letters)


def is_english_video(video: VideoRecord) -> bool:
    """Require English YouTube content before sponsor detection.

    YouTube's search `relevanceLanguage=en` is only a ranking preference. Prefer the
    explicit default audio language because it represents the spoken content. If YouTube
    does not expose language metadata, use a conservative Unicode-script fallback on the
    creator/title/description metadata to reject obvious non-English-language videos.
    """
    audio_language = _primary_language(video.default_audio_language)
    metadata_language = _primary_language(video.default_language)

    if audio_language:
        return audio_language == "en"
    if metadata_language:
        return metadata_language == "en"

    # Many uploads omit both language fields. The fallback is deliberately aimed at
    # obvious misses (Hindi, Cyrillic, Arabic, CJK, etc.), not at guessing accents or
    # geography. Sponsor URLs and emoji/numbers do not count as letters here.
    title_sample = f"{video.channel_title or ''} {video.title or ''}"
    non_latin, total, ratio = _non_latin_ratio(title_sample)
    if total >= 6 and non_latin >= 3 and ratio >= 0.20:
        return False

    description_sample = (video.description or "")[:1500]
    non_latin, total, ratio = _non_latin_ratio(description_sample)
    if total >= 20 and non_latin >= 8 and ratio >= 0.30:
        return False

    return True

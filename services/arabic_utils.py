from __future__ import annotations

import re
import unicodedata


ARABIC_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
TASHKEEL_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")


def normalize_digits(value: str) -> str:
    """Convert Arabic-Indic and Persian digits to Western digits."""
    return str(value or "").translate(ARABIC_INDIC_DIGITS).translate(PERSIAN_DIGITS)


def normalize_arabic_for_search(value: str) -> str:
    """Normalize Arabic text for matching only. Do not use for saved display data."""
    text = normalize_digits(value)
    text = unicodedata.normalize("NFKC", text)
    text = TASHKEEL_RE.sub("", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ة", "ه").replace("ى", "ي")
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def compact_identifier(value: str) -> str:
    """Normalize identifiers for matching while preserving separators in storage."""
    return re.sub(r"[\s\-–—_]", "", normalize_digits(value or "")).casefold()


def normalize_identifier_text(value: str) -> str:
    """Normalize digits and common punctuation before identifier/date extraction."""
    text = normalize_digits(value)
    return text.replace("﹣", "-").replace("ـ", "")

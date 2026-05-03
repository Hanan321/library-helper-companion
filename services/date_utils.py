from __future__ import annotations

from services.arabic_utils import normalize_digits


def hijri_to_gregorian_placeholder(hijri_year: str) -> tuple[str, str]:
    """Approximate Hijri to Gregorian year conversion.

    This is intentionally marked as calculated/uncertain. A later version should
    use a dedicated calendar library when exact date conversion is needed.
    """
    digits = "".join(ch for ch in normalize_digits(str(hijri_year)) if ch.isdigit())
    if not digits:
        return "", "No Hijri year digits found for conversion."
    gregorian_year = int(int(digits) * 0.970224 + 621.5774)
    return str(gregorian_year), "Gregorian year calculated from Hijri year; TODO: verify with a proper Hijri calendar library."

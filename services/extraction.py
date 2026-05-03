from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

from models.schema import IdentifierResult
from services.arabic_utils import normalize_digits, normalize_identifier_text


ISBN_LABELS = r"(?:ISBN|ردمك|الرقم\s+الدولي\s+المعياري\s+للكتاب)"
ISSN_LABELS = r"(?:ISSN|ردمد|الرقم\s+الدولي\s+المعياري\s+للدوريات)"
DEPOSIT_LABELS = r"(?:رقم\s+الإيداع|رقم\s+الايداع|deposit\s+number|legal\s+deposit)"


def detect_identifiers(text: str) -> IdentifierResult:
    """Extract ISBN, ISSN, and deposit number without mixing their meanings."""
    text = normalize_identifier_text(text or "")
    result = IdentifierResult()

    isbn_matches = re.findall(
        rf"{ISBN_LABELS}\s*[:：\-]?\s*([0-9Xx\-\s]{{10,20}})",
        text,
        flags=re.IGNORECASE,
    )
    if not isbn_matches:
        isbn_matches = re.findall(r"\b(?:97[89][-\s]?)?[0-9][0-9\-\s]{8,16}[0-9Xx]\b", text)
    result.isbn = _clean_isbn(isbn_matches[0]) if isbn_matches else ""

    issn_matches = re.findall(
        rf"{ISSN_LABELS}\s*[:：\-]?\s*([0-9]{{4}}[-\s]?[0-9Xx]{{4}})",
        text,
        flags=re.IGNORECASE,
    )
    if not issn_matches:
        issn_matches = re.findall(r"\b[0-9]{4}[-\s]?[0-9Xx]{4}\b", text)
    result.issn = _clean_issn(issn_matches[0]) if issn_matches else ""

    deposit_matches = re.findall(
        rf"{DEPOSIT_LABELS}[ \t]*[:：\-]?[ \t]*([0-9A-Za-z\u0600-\u06FF/\- ]{{3,40}})",
        text,
        flags=re.IGNORECASE,
    )
    result.deposit_number = _clean_text(deposit_matches[0]) if deposit_matches else ""

    if result.isbn and result.issn and result.isbn.replace("-", "") == result.issn.replace("-", ""):
        result.notes.append("Identifier conflict: ISBN and ISSN looked identical; verify before saving.")
    if result.deposit_number and result.deposit_number in {result.isbn, result.issn}:
        result.notes.append("Deposit number matched another identifier; verify labels on source image/text.")
    return result


def extract_basic_fields_from_text(text: str) -> dict[str, Any]:
    identifiers = detect_identifiers(text)
    lines = [_clean_text(line) for line in (text or "").splitlines() if _clean_text(line)]
    title = lines[0] if lines else ""
    author = ""
    publisher = ""
    year = ""
    hijri_year = ""

    for line in lines[1:8]:
        normalized_line = normalize_digits(line)
        lowered = normalized_line.lower()
        if any(token in lowered for token in ["author", "by ", "المؤلف", "تأليف"]):
            author = _strip_label(line)
        if any(token in lowered for token in ["publisher", "الناشر", "دار"]):
            publisher = _strip_label(line)
        gregorian = re.search(r"\b(1[5-9][0-9]{2}|20[0-9]{2})\b", normalized_line)
        if gregorian and not year:
            year = gregorian.group(1)
        hijri = re.search(r"\b(1[2345][0-9]{2})\s*(?:هـ|ه|AH)?\b", normalized_line)
        if hijri and not hijri_year:
            hijri_year = hijri.group(1)

    return {
        "title": title,
        "author": author,
        "publisher": publisher,
        "publication_year_gregorian": year,
        "publication_year_hijri": hijri_year,
        "isbn": identifiers.isbn,
        "issn": identifiers.issn,
        "deposit_number": identifiers.deposit_number,
        "notes": "\n".join(identifiers.notes),
    }


def extract_from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    """Use OpenAI Vision when configured; otherwise return an actionable note."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {
            "raw_text": "",
            "fields": {},
            "notes": "OPENAI_API_KEY is not set, so image extraction was skipped.",
        }

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract visible bibliographic data from a book cover or copyright page. "
                        "Preserve Arabic titles exactly. Never guess. Return compact JSON with keys: "
                        "raw_text, title, author, publisher, edition, publication_year_gregorian, "
                        "publication_year_hijri, isbn, issn, deposit_number, language, notes."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract catalog details from this image."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        raw_text = parsed.get("raw_text", "")
        identifiers = detect_identifiers("\n".join([raw_text, json.dumps(parsed, ensure_ascii=False)]))
        fields = {key: parsed.get(key, "") for key in parsed if key != "raw_text"}
        fields["isbn"] = fields.get("isbn") or identifiers.isbn
        fields["issn"] = fields.get("issn") or identifiers.issn
        fields["deposit_number"] = fields.get("deposit_number") or identifiers.deposit_number
        return {"raw_text": raw_text, "fields": fields, "notes": parsed.get("notes", "")}
    except Exception as exc:  # pragma: no cover - depends on external API
        return {"raw_text": "", "fields": {}, "notes": f"Image extraction failed: {exc}"}


def _clean_isbn(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", normalize_digits(value or "")).upper()


def _clean_issn(value: str) -> str:
    compact = re.sub(r"[^0-9Xx]", "", normalize_digits(value or "")).upper()
    return f"{compact[:4]}-{compact[4:8]}" if len(compact) >= 8 else compact


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" :：-\t")


def _strip_label(value: str) -> str:
    return _clean_text(re.sub(r"^[^:：\-]+[:：\-]", "", value or ""))

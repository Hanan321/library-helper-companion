from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


BOOK_FIELDS = [
    "title",
    "author",
    "publisher",
    "edition",
    "publication_year_gregorian",
    "publication_year_hijri",
    "isbn",
    "issn",
    "deposit_number",
    "language",
    "category",
    "description",
    "room",
    "cabinet",
    "shelf",
    "row_position",
    "status",
    "notes",
    "source_links",
]

LOCATION_FIELDS = ["room", "cabinet", "shelf", "row_position"]
STATUS_OPTIONS = ["available", "borrowed", "missing", "unknown"]


@dataclass
class IdentifierResult:
    isbn: str = ""
    issn: str = ""
    deposit_number: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class CatalogDraft:
    title: str = ""
    author: str = ""
    publisher: str = ""
    edition: str = ""
    publication_year_gregorian: str = ""
    publication_year_hijri: str = ""
    isbn: str = ""
    issn: str = ""
    deposit_number: str = ""
    language: str = ""
    category: str = ""
    description: str = ""
    room: str = ""
    cabinet: str = ""
    shelf: str = ""
    row_position: str = ""
    status: str = "unknown"
    notes: str = ""
    source_links: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {field_name: getattr(self, field_name, "") for field_name in BOOK_FIELDS}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CatalogDraft":
        clean = {field_name: data.get(field_name) or "" for field_name in BOOK_FIELDS}
        clean["status"] = clean["status"] or "unknown"
        return cls(**clean)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

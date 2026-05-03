from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

from models.schema import BOOK_FIELDS, utc_now_iso
from services.arabic_utils import compact_identifier, normalize_arabic_for_search


DB_PATH = Path("library.db")


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                author TEXT,
                publisher TEXT,
                edition TEXT,
                publication_year_gregorian TEXT,
                publication_year_hijri TEXT,
                isbn TEXT,
                issn TEXT,
                deposit_number TEXT,
                language TEXT,
                category TEXT,
                description TEXT,
                room TEXT,
                cabinet TEXT,
                shelf TEXT,
                row_position TEXT,
                status TEXT DEFAULT 'unknown',
                notes TEXT,
                source_links TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_title ON books(title)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_author ON books(author)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_isbn ON books(isbn)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_issn ON books(issn)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_deposit ON books(deposit_number)")


def add_book(data: dict[str, Any], db_path: Path | str = DB_PATH) -> int:
    now = utc_now_iso()
    values = {field: data.get(field, "") for field in BOOK_FIELDS}
    values["status"] = values.get("status") or "unknown"
    values["created_at"] = now
    values["updated_at"] = now
    columns = BOOK_FIELDS + ["created_at", "updated_at"]
    placeholders = ", ".join(["?"] * len(columns))
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            f"INSERT INTO books ({', '.join(columns)}) VALUES ({placeholders})",
            [values[column] for column in columns],
        )
        return int(cursor.lastrowid)


def update_book(book_id: int, data: dict[str, Any], db_path: Path | str = DB_PATH) -> None:
    values = {field: data.get(field, "") for field in BOOK_FIELDS}
    values["updated_at"] = utc_now_iso()
    assignments = ", ".join([f"{field} = ?" for field in BOOK_FIELDS] + ["updated_at = ?"])
    with get_connection(db_path) as conn:
        conn.execute(
            f"UPDATE books SET {assignments} WHERE id = ?",
            [values[field] for field in BOOK_FIELDS] + [values["updated_at"], book_id],
        )


def search_books(query: str, db_path: Path | str = DB_PATH, limit: int = 25) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    like = f"%{query}%"
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM books
            WHERE title LIKE ?
               OR author LIKE ?
               OR isbn LIKE ?
               OR issn LIKE ?
               OR deposit_number LIKE ?
               OR notes LIKE ?
               OR description LIKE ?
            ORDER BY updated_at DESC, title ASC
            LIMIT ?
            """,
            [like, like, like, like, like, like, like, limit],
        ).fetchall()
    direct_matches = [dict(row) for row in rows]
    normalized_matches = _normalized_search_books(query, db_path=db_path, limit=limit)
    return _dedupe_books(direct_matches + normalized_matches)[:limit]


def search_by_identifiers(
    isbn: str = "",
    issn: str = "",
    deposit_number: str = "",
    db_path: Path | str = DB_PATH,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[str] = []
    if isbn:
        clauses.append("isbn LIKE ?")
        params.append(f"%{isbn}%")
    if issn:
        clauses.append("issn LIKE ?")
        params.append(f"%{issn}%")
    if deposit_number:
        clauses.append("deposit_number LIKE ?")
        params.append(f"%{deposit_number}%")
    if not clauses:
        return []
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM books WHERE {' OR '.join(clauses)} ORDER BY updated_at DESC LIMIT 10",
            params,
        ).fetchall()
    direct_matches = [dict(row) for row in rows]
    normalized_matches = _normalized_identifier_search(isbn, issn, deposit_number, db_path=db_path)
    return _dedupe_books(direct_matches + normalized_matches)[:10]


def list_books(db_path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM books ORDER BY updated_at DESC, id DESC").fetchall()
    return [dict(row) for row in rows]


def export_books_csv(path: Path | str, db_path: Path | str = DB_PATH) -> Path:
    rows = list_books(db_path)
    output_path = Path(path)
    columns = ["id"] + BOOK_FIELDS + ["created_at", "updated_at"]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


ARABIC_COLUMN_MAP = {
    "العنوان": "title",
    "عنوان": "title",
    "اسم الكتاب": "title",
    "المؤلف": "author",
    "الكاتب": "author",
    "اسم المؤلف": "author",
    "الناشر": "publisher",
    "دار النشر": "publisher",
    "الطبعة": "edition",
    "سنة النشر ميلادي": "publication_year_gregorian",
    "سنة النشر الهجري": "publication_year_hijri",
    "سنة النشر هجري": "publication_year_hijri",
    "ردمك": "isbn",
    "الرقم الدولي المعياري للكتاب": "isbn",
    "ردمد": "issn",
    "الرقم الدولي المعياري للدوريات": "issn",
    "رقم الإيداع": "deposit_number",
    "رقم الايداع": "deposit_number",
    "اللغة": "language",
    "التصنيف": "category",
    "الوصف": "description",
    "الغرفة": "room",
    "الدولاب": "cabinet",
    "الخزانة": "cabinet",
    "الرف": "shelf",
    "الموضع": "row_position",
    "الموقع": "row_position",
    "الحالة": "status",
    "ملاحظات": "notes",
    "الروابط": "source_links",
    "روابط المصادر": "source_links",
}


def import_books_csv(file_obj, db_path: Path | str = DB_PATH) -> int:
    """Import UTF-8/UTF-8-SIG CSV rows, accepting English or Arabic headers."""
    init_db(db_path)
    raw = file_obj.read()
    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig")
    else:
        text = str(raw)
    reader = csv.DictReader(text.splitlines())
    count = 0
    for row in reader:
        mapped = {}
        for key, value in row.items():
            field = _map_csv_column(key or "")
            if field in BOOK_FIELDS:
                mapped[field] = value or ""
        if any(mapped.get(field) for field in BOOK_FIELDS):
            add_book(mapped, db_path=db_path)
            count += 1
    return count


def _map_csv_column(column: str) -> str:
    clean = (column or "").strip()
    if clean in BOOK_FIELDS:
        return clean
    if clean in ARABIC_COLUMN_MAP:
        return ARABIC_COLUMN_MAP[clean]
    normalized = normalize_arabic_for_search(clean)
    for arabic_name, field_name in ARABIC_COLUMN_MAP.items():
        if normalize_arabic_for_search(arabic_name) == normalized:
            return field_name
    return clean


def _normalized_search_books(query: str, db_path: Path | str = DB_PATH, limit: int = 25) -> list[dict[str, Any]]:
    normalized_query = normalize_arabic_for_search(query)
    compact_query = compact_identifier(query)
    if not normalized_query and not compact_query:
        return []
    candidates = list_books(db_path)
    matches = []
    text_fields = ["title", "author", "publisher", "notes", "description", "category"]
    identifier_fields = ["isbn", "issn", "deposit_number", "publication_year_gregorian", "publication_year_hijri"]
    for book in candidates:
        text_match = any(normalized_query in normalize_arabic_for_search(book.get(field, "")) for field in text_fields)
        identifier_match = bool(compact_query) and any(
            compact_query in compact_identifier(book.get(field, "")) for field in identifier_fields
        )
        if text_match or identifier_match:
            matches.append(book)
        if len(matches) >= limit:
            break
    return matches


def _normalized_identifier_search(
    isbn: str = "",
    issn: str = "",
    deposit_number: str = "",
    db_path: Path | str = DB_PATH,
) -> list[dict[str, Any]]:
    normalized_targets = {
        "isbn": compact_identifier(isbn),
        "issn": compact_identifier(issn),
        "deposit_number": compact_identifier(deposit_number),
    }
    if not any(normalized_targets.values()):
        return []
    matches = []
    for book in list_books(db_path):
        for field, target in normalized_targets.items():
            if target and target in compact_identifier(book.get(field, "")):
                matches.append(book)
                break
    return matches


def _dedupe_books(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for row in rows:
        row_id = row.get("id")
        if row_id in seen:
            continue
        seen.add(row_id)
        deduped.append(row)
    return deduped

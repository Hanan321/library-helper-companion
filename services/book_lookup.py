from __future__ import annotations

import urllib.parse
from typing import Any

import requests


GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
OPEN_LIBRARY_ISBN_URL = "https://openlibrary.org/isbn/{isbn}.json"
OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"


def lookup_book_apis(query: str = "", isbn: str = "", issn: str = "") -> dict[str, Any]:
    """Look up book metadata through public APIs. Returns data plus source notes."""
    results: list[dict[str, Any]] = []
    conflicts: list[str] = []

    google = lookup_google_books(query=query, isbn=isbn, issn=issn)
    if google:
        results.append(google)

    open_library = lookup_open_library(query=query, isbn=isbn)
    if open_library:
        results.append(open_library)

    merged = _merge_results(results, conflicts)
    merged["api_results"] = results
    merged["conflicts"] = conflicts
    return merged


def lookup_google_books(query: str = "", isbn: str = "", issn: str = "") -> dict[str, Any]:
    terms = isbn or issn or query
    if not terms:
        return {}
    api_query = f"isbn:{isbn}" if isbn else terms
    try:
        response = requests.get(GOOGLE_BOOKS_URL, params={"q": api_query, "maxResults": 5}, timeout=10)
        response.raise_for_status()
        items = response.json().get("items", [])
    except requests.RequestException as exc:
        return {"source": "Google Books", "notes": f"Google Books lookup failed: {exc}"}
    if not items:
        return {}
    volume = items[0].get("volumeInfo", {})
    identifiers = volume.get("industryIdentifiers", [])
    return {
        "source": "Google Books",
        "title": volume.get("title", ""),
        "author": ", ".join(volume.get("authors", [])),
        "publisher": volume.get("publisher", ""),
        "publication_year_gregorian": (volume.get("publishedDate", "") or "")[:4],
        "isbn": _first_identifier(identifiers, "ISBN_13") or _first_identifier(identifiers, "ISBN_10"),
        "language": volume.get("language", ""),
        "category": ", ".join(volume.get("categories", [])),
        "description": volume.get("description", ""),
        "source_links": volume.get("infoLink", ""),
        "notes": "Verified via Google Books API.",
    }


def lookup_open_library(query: str = "", isbn: str = "") -> dict[str, Any]:
    try:
        if isbn:
            response = requests.get(OPEN_LIBRARY_ISBN_URL.format(isbn=isbn), timeout=10)
            if response.status_code == 404:
                return {}
            response.raise_for_status()
            data = response.json()
            return {
                "source": "Open Library",
                "title": data.get("title", ""),
                "publisher": ", ".join(data.get("publishers", [])),
                "publication_year_gregorian": _first_year(data.get("publish_date", "")),
                "isbn": isbn,
                "source_links": f"https://openlibrary.org/isbn/{urllib.parse.quote(isbn)}",
                "notes": "Verified via Open Library ISBN API.",
            }

        if query:
            response = requests.get(OPEN_LIBRARY_SEARCH_URL, params={"q": query, "limit": 5}, timeout=10)
            response.raise_for_status()
            docs = response.json().get("docs", [])
            if not docs:
                return {}
            doc = docs[0]
            return {
                "source": "Open Library",
                "title": doc.get("title", ""),
                "author": ", ".join(doc.get("author_name", [])[:3]),
                "publisher": ", ".join(doc.get("publisher", [])[:2]),
                "publication_year_gregorian": str(doc.get("first_publish_year", "") or ""),
                "isbn": (doc.get("isbn") or [""])[0],
                "language": ", ".join(doc.get("language", [])[:3]),
                "source_links": f"https://openlibrary.org{doc.get('key', '')}",
                "notes": "Verified via Open Library Search API.",
            }
    except requests.RequestException as exc:
        return {"source": "Open Library", "notes": f"Open Library lookup failed: {exc}"}
    return {}


def build_search_links(title: str = "", author: str = "", isbn: str = "") -> str:
    terms = " ".join(part for part in [title, author, isbn] if part).strip()
    encoded = urllib.parse.quote_plus(terms)
    if not encoded:
        return ""
    links = {
        "Google Books search suggestion": f"https://www.google.com/search?q={encoded}+Google+Books",
        "Publisher search suggestion": f"https://www.google.com/search?q={encoded}+publisher",
        "Amazon search suggestion": f"https://www.amazon.com/s?k={encoded}",
        "AbeBooks search suggestion": f"https://www.abebooks.com/servlet/SearchResults?kn={encoded}",
        "eBay search suggestion": f"https://www.ebay.com/sch/i.html?_nkw={encoded}",
    }
    return "\n".join(f"{label}: {url}" for label, url in links.items())


def _first_identifier(identifiers: list[dict[str, str]], id_type: str) -> str:
    for identifier in identifiers:
        if identifier.get("type") == id_type:
            return identifier.get("identifier", "")
    return ""


def _first_year(value: str) -> str:
    for token in str(value).replace(",", " ").split():
        if token.isdigit() and len(token) == 4:
            return token
    return ""


def _merge_results(results: list[dict[str, Any]], conflicts: list[str]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for result in results:
        for key, value in result.items():
            if key in {"source", "notes"} or not value:
                continue
            if key in merged and merged[key] and merged[key] != value:
                conflicts.append(f"{key}: '{merged[key]}' vs '{value}'")
                continue
            merged[key] = value
    notes = [result.get("notes", "") for result in results if result.get("notes")]
    merged["notes"] = "\n".join(notes)
    return merged

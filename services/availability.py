from __future__ import annotations

import urllib.parse
from typing import Any

import requests


def research_availability(title: str = "", author: str = "", isbn: str = "") -> list[dict[str, str]]:
    """Return legal verified links and clearly labeled search suggestions."""
    terms = " ".join(part for part in [title, author, isbn] if part).strip()
    links: list[dict[str, str]] = []

    if isbn:
        open_library = f"https://openlibrary.org/isbn/{urllib.parse.quote(isbn)}"
        links.append({"label": "Open Library ISBN page", "url": open_library, "kind": "verified"})

    ia_link = _internet_archive_link(terms)
    if ia_link:
        links.append({"label": "Internet Archive result", "url": ia_link, "kind": "verified"})

    if terms:
        encoded = urllib.parse.quote_plus(terms)
        links.extend(
            [
                {"label": "Google Books", "url": f"https://books.google.com/books?q={encoded}", "kind": "search suggestion"},
                {"label": "Publisher page", "url": f"https://www.google.com/search?q={encoded}+publisher", "kind": "search suggestion"},
                {"label": "Amazon", "url": f"https://www.amazon.com/s?k={encoded}", "kind": "search suggestion"},
                {"label": "AbeBooks", "url": f"https://www.abebooks.com/servlet/SearchResults?kn={encoded}", "kind": "search suggestion"},
                {"label": "eBay", "url": f"https://www.ebay.com/sch/i.html?_nkw={encoded}", "kind": "search suggestion"},
            ]
        )
    return links


def format_availability_links(links: list[dict[str, str]]) -> str:
    return "\n".join(f"{item['kind']} - {item['label']}: {item['url']}" for item in links)


def _internet_archive_link(terms: str) -> str:
    if not terms:
        return ""
    try:
        response = requests.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f'title:("{terms}") AND mediatype:texts',
                "fl[]": "identifier",
                "rows": 1,
                "output": "json",
            },
            timeout=10,
        )
        response.raise_for_status()
        docs = response.json().get("response", {}).get("docs", [])
        if docs:
            return f"https://archive.org/details/{docs[0]['identifier']}"
    except requests.RequestException:
        return ""
    return ""

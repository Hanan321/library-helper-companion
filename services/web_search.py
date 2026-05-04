from __future__ import annotations

import os
import urllib.parse
from typing import Any

import requests


TAVILY_SEARCH_URL = "https://api.tavily.com/search"

TRUSTED_SOURCE_HINTS = {
    "books.google": "Google Books",
    "openlibrary.org": "Open Library",
    "worldcat.org": "WorldCat",
    "archive.org": "Internet Archive",
    "loc.gov": "Library of Congress",
    "catalog.hathitrust.org": "HathiTrust",
    "jstor.org": "JSTOR",
    "bnf.fr": "National Library",
    "bl.uk": "British Library",
    "d-nb.info": "German National Library",
    "worldcat": "WorldCat",
    "library": "Library catalog",
    "catalog": "Library catalog",
    "university": "University catalog",
    "edu": "University catalog",
    "amazon.": "Bookstore",
    "abebooks.": "Used/rare bookstore",
    "ebay.": "Marketplace",
}

PIRACY_HINTS = [
    "libgen",
    "z-library",
    "zlibrary",
    "sci-hub",
    "pdfdrive",
    "annas-archive",
    "oceanofpdf",
    "vk.com",
    "4shared",
    "scribd-downloader",
    "free download pdf",
    "تحميل مجاني pdf",
]


def search_web(queries: list[str], max_results_per_query: int = 5) -> dict[str, Any]:
    provider = (os.getenv("WEB_SEARCH_PROVIDER") or "tavily").strip().lower()
    api_key = os.getenv("TAVILY_API_KEY") or os.getenv("WEB_SEARCH_API_KEY")
    debug: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    meta = {
        "provider": provider or "tavily",
        "api_key_found": bool(api_key),
        "tavily_called": False,
        "result_count": 0,
        "errors": [],
    }

    if provider not in {"tavily", ""}:
        meta["errors"].append(f"Unsupported provider: {provider}")
        debug.append(
            {
                "step": "search_web",
                "query": provider,
                "returned_result": False,
                "api_key_found": bool(api_key),
                "tavily_called": False,
                "result_count": 0,
                "note": f"Unsupported WEB_SEARCH_PROVIDER '{provider}'. Tavily is currently implemented.",
            }
        )
        return {"results": [], "debug_steps": debug, "errors": meta["errors"], "meta": meta}

    if not api_key:
        meta["errors"].append("TAVILY_API_KEY is missing. Web search is disabled.")
        debug.append(
            {
                "step": "search_web",
                "query": "Tavily",
                "returned_result": False,
                "api_key_found": False,
                "tavily_called": False,
                "result_count": 0,
                "note": "TAVILY_API_KEY is missing. Web search is disabled.",
            }
        )
        return {"results": [], "debug_steps": debug, "errors": meta["errors"], "meta": meta}

    seen_urls = set()
    for query in queries[:10]:
        try:
            meta["tavily_called"] = True
            response = requests.post(
                TAVILY_SEARCH_URL,
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": max_results_per_query,
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            raw_results = payload.get("results", [])
            safe_results = [_normalize_tavily_result(item, query) for item in raw_results]
            safe_results = [item for item in safe_results if item and _is_legal_safe_result(item)]
            for item in safe_results:
                if item["url"] in seen_urls:
                    continue
                seen_urls.add(item["url"])
                results.append(item)
            debug.append(
                {
                    "step": "search_web",
                    "query": query,
                    "returned_result": bool(safe_results),
                    "api_key_found": True,
                    "tavily_called": True,
                    "result_count": len(safe_results),
                    "note": f"Tavily returned {len(raw_results)} result(s), {len(safe_results)} legal-safe result(s) kept.",
                    "urls": [item["url"] for item in safe_results],
                }
            )
        except requests.RequestException as exc:
            error = f"Tavily search failed: {exc}"
            meta["errors"].append(error)
            debug.append(
                {
                    "step": "search_web",
                    "query": query,
                    "returned_result": False,
                    "api_key_found": True,
                    "tavily_called": True,
                    "result_count": 0,
                    "note": error,
                }
            )
    meta["result_count"] = len(results)
    return {"results": results, "debug_steps": debug, "errors": meta["errors"], "meta": meta}


def summarize_sources(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for result in results[:20]:
        source_type = classify_source(result.get("url", ""), result.get("title", ""), result.get("snippet", ""))
        summaries.append(
            {
                "source": result.get("source") or source_type,
                "source_type": source_type,
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "snippet": result.get("snippet", ""),
                "query": result.get("query", ""),
                "is_trusted": source_type not in {"General web result", "Unknown"},
                "is_legal": True,
            }
        )
    return summaries


def classify_source(url: str, title: str = "", snippet: str = "") -> str:
    haystack = " ".join([url, title, snippet]).lower()
    for hint, label in TRUSTED_SOURCE_HINTS.items():
        if hint in haystack:
            return label
    return "General web result"


def build_legal_search_links(query: str) -> list[dict[str, str]]:
    encoded = urllib.parse.quote_plus(query)
    if not encoded:
        return []
    return [
        {"label": "Google Search", "url": f"https://www.google.com/search?q={encoded}", "kind": "search suggestion"},
        {"label": "Google Books", "url": f"https://books.google.com/books?q={encoded}", "kind": "search suggestion"},
        {"label": "WorldCat", "url": f"https://search.worldcat.org/search?q={encoded}", "kind": "search suggestion"},
        {"label": "Internet Archive", "url": f"https://archive.org/search?query={encoded}", "kind": "search suggestion"},
        {"label": "Publisher search", "url": f"https://www.google.com/search?q={encoded}+publisher", "kind": "search suggestion"},
    ]


def _normalize_tavily_result(item: dict[str, Any], query: str) -> dict[str, Any]:
    url = item.get("url", "")
    title = item.get("title", "")
    snippet = item.get("content", "") or item.get("snippet", "")
    if not url:
        return {}
    return {
        "source": classify_source(url, title, snippet),
        "title": title,
        "url": url,
        "snippet": snippet,
        "score": item.get("score", 0),
        "query": query,
    }


def _is_legal_safe_result(result: dict[str, Any]) -> bool:
    haystack = " ".join([result.get("url", ""), result.get("title", ""), result.get("snippet", "")]).lower()
    return not any(hint in haystack for hint in PIRACY_HINTS)

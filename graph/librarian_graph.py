from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from models.schema import CatalogDraft
from services import database
from services.availability import format_availability_links, research_availability
from services.book_lookup import build_search_links, lookup_book_apis
from services.date_utils import hijri_to_gregorian_placeholder
from services.extraction import detect_identifiers, extract_basic_fields_from_text, extract_from_image
from services.arabic_utils import normalize_arabic_for_search
from services.web_search import build_legal_search_links, search_web, summarize_sources


class LibrarianState(TypedDict, total=False):
    query: str
    image_bytes: bytes
    image_mime_type: str
    extracted_text: str
    extracted_fields: dict[str, Any]
    identifiers: dict[str, str]
    private_matches: list[dict[str, Any]]
    search_queries: list[str]
    api_result: dict[str, Any]
    web_results: list[dict[str, Any]]
    web_search_meta: dict[str, Any]
    source_summaries: list[dict[str, Any]]
    source_evidence: list[dict[str, Any]]
    confidence_level: str
    availability_links: list[dict[str, str]]
    online_search_status: str
    online_search_summary: str
    item_type: str
    lookup_debug: list[dict[str, Any]]
    catalog_draft: dict[str, Any]
    conflicts: list[str]
    uncertainty_notes: list[str]
    approved_for_save: bool
    saved_book_id: int


def build_librarian_graph():
    graph = StateGraph(LibrarianState)
    graph.add_node("parse_user_input", parse_user_input)
    graph.add_node("extract_from_image", extract_image_node)
    graph.add_node("detect_identifiers", detect_identifiers_node)
    graph.add_node("search_private_database", search_private_database)
    graph.add_node("generate_search_queries", generate_search_queries)
    graph.add_node("search_book_apis", search_book_apis_node)
    graph.add_node("search_web", search_web_node)
    graph.add_node("visit_and_summarize_sources", visit_and_summarize_sources)
    graph.add_node("compare_sources", compare_sources)
    graph.add_node("merge_and_validate_results", merge_and_validate_results)
    graph.add_node("research_availability", research_availability_node)
    graph.add_node("generate_catalog_draft", generate_catalog_draft)
    graph.add_node("human_review_before_save", human_review_before_save)
    graph.add_node("save_to_database", save_to_database)

    graph.set_entry_point("parse_user_input")
    graph.add_edge("parse_user_input", "extract_from_image")
    graph.add_edge("extract_from_image", "detect_identifiers")
    graph.add_edge("detect_identifiers", "search_private_database")
    graph.add_edge("search_private_database", "generate_search_queries")
    graph.add_edge("generate_search_queries", "search_book_apis")
    graph.add_edge("search_book_apis", "search_web")
    graph.add_edge("search_web", "visit_and_summarize_sources")
    graph.add_edge("visit_and_summarize_sources", "compare_sources")
    graph.add_edge("compare_sources", "merge_and_validate_results")
    graph.add_edge("merge_and_validate_results", "research_availability")
    graph.add_edge("research_availability", "generate_catalog_draft")
    graph.add_edge("generate_catalog_draft", "human_review_before_save")
    graph.add_edge("human_review_before_save", "save_to_database")
    graph.add_edge("save_to_database", END)
    return graph.compile()


def parse_user_input(state: LibrarianState) -> LibrarianState:
    query = (state.get("query") or "").strip()
    fields = dict(state.get("catalog_draft", {}))
    if query:
        parsed_fields = extract_basic_fields_from_text(query)
        fields.update({key: value for key, value in parsed_fields.items() if value and not fields.get(key)})
    uncertainty = list(state.get("uncertainty_notes", []))
    debug = list(state.get("lookup_debug", []))
    debug.append(
        {
            "step": "parse_user_input",
            "query": query,
            "returned_result": bool(query),
            "note": "Parsed text input." if query else "No typed text input.",
        }
    )
    if not query and not state.get("image_bytes"):
        uncertainty.append("No text or image input was provided.")
    return {"query": query, "extracted_fields": fields, "uncertainty_notes": uncertainty, "lookup_debug": debug}


def extract_image_node(state: LibrarianState) -> LibrarianState:
    image_bytes = state.get("image_bytes")
    if not image_bytes:
        return {}
    result = extract_from_image(image_bytes, state.get("image_mime_type") or "image/jpeg")
    extracted_fields = dict(state.get("extracted_fields", {}))
    raw_text = result.get("raw_text", "")
    extraction_notes = str(result.get("notes", ""))
    parse_text = "\n".join(part for part in [raw_text, extraction_notes] if part)
    ocr_fields = extract_basic_fields_from_text(parse_text) if parse_text else {}
    extracted_fields.update({key: value for key, value in ocr_fields.items() if value and not extracted_fields.get(key)})
    extracted_fields.update({key: value for key, value in result.get("fields", {}).items() if value})
    notes = list(state.get("uncertainty_notes", []))
    if result.get("notes"):
        notes.append(str(result["notes"]))
    debug = list(state.get("lookup_debug", []))
    debug.append(
        {
            "step": "extract_from_image",
            "query": "uploaded image",
            "returned_result": bool(parse_text or result.get("fields")),
            "note": "OCR/image extraction returned text or fields." if parse_text or result.get("fields") else "No image text extracted.",
        }
    )
    return {
        "extracted_text": raw_text or (extraction_notes if ocr_fields else ""),
        "extracted_fields": extracted_fields,
        "uncertainty_notes": notes,
        "lookup_debug": debug,
    }


def detect_identifiers_node(state: LibrarianState) -> LibrarianState:
    text = "\n".join(
        [
            state.get("query", ""),
            state.get("extracted_text", ""),
            " ".join(str(value) for value in state.get("extracted_fields", {}).values()),
        ]
    )
    detected = detect_identifiers(text)
    fields = dict(state.get("extracted_fields", {}))
    fields["isbn"] = fields.get("isbn") or detected.isbn
    fields["issn"] = fields.get("issn") or detected.issn
    fields["deposit_number"] = fields.get("deposit_number") or detected.deposit_number
    notes = list(state.get("uncertainty_notes", [])) + detected.notes
    item_type = detect_item_type(text, fields)
    debug = list(state.get("lookup_debug", []))
    debug.append(
        {
            "step": "detect_identifiers",
            "query": "OCR/text identifiers",
            "returned_result": bool(fields.get("isbn") or fields.get("issn") or fields.get("deposit_number")),
            "note": f"Detected item type: {item_type}.",
        }
    )
    return {
        "identifiers": {
            "isbn": fields.get("isbn", ""),
            "issn": fields.get("issn", ""),
            "deposit_number": fields.get("deposit_number", ""),
        },
        "extracted_fields": fields,
        "item_type": item_type,
        "uncertainty_notes": notes,
        "lookup_debug": debug,
    }


def search_private_database(state: LibrarianState) -> LibrarianState:
    database.init_db()
    fields = state.get("extracted_fields", {})
    identifiers = state.get("identifiers", {})
    matches = []
    if identifiers.get("isbn") or identifiers.get("issn"):
        matches = database.search_by_identifiers(
            identifiers.get("isbn", ""),
            identifiers.get("issn", ""),
            identifiers.get("deposit_number", ""),
        )
    if not matches:
        search_text = " ".join(
            part
            for part in [
                state.get("query", ""),
                fields.get("title", ""),
                fields.get("author", ""),
                identifiers.get("deposit_number", ""),
            ]
            if part
        )
        matches = database.search_books(search_text)
    debug = list(state.get("lookup_debug", []))
    debug.append(
        {
            "step": "search_private_database",
            "query": identifiers.get("isbn") or identifiers.get("issn") or fields.get("title") or state.get("query", ""),
            "returned_result": bool(matches),
            "note": f"Found {len(matches)} local match(es)." if matches else "No local match found.",
        }
    )
    return {"private_matches": matches, "lookup_debug": debug}


def generate_search_queries(state: LibrarianState) -> LibrarianState:
    fields = state.get("extracted_fields", {})
    identifiers = state.get("identifiers", {})
    queries = build_research_queries(fields, identifiers, state.get("query", ""), state.get("extracted_text", ""))
    debug = list(state.get("lookup_debug", []))
    debug.append(
        {
            "step": "generate_search_queries",
            "query": "; ".join(queries[:8]),
            "returned_result": bool(queries),
            "note": f"Generated {len(queries)} research query/queries.",
        }
    )
    return {"search_queries": queries, "lookup_debug": debug}


def search_book_apis_node(state: LibrarianState) -> LibrarianState:
    fields = state.get("extracted_fields", {})
    identifiers = state.get("identifiers", {})
    query = " ".join(part for part in [fields.get("title", ""), fields.get("author", "")] if part) or state.get("query", "")
    search_terms = state.get("search_queries") or build_lookup_terms(fields, identifiers, state.get("query", ""), state.get("extracted_text", ""))
    result = lookup_book_apis(
        query=query,
        isbn=identifiers.get("isbn", ""),
        issn=identifiers.get("issn", ""),
        search_terms=search_terms,
        item_type=state.get("item_type", "unknown"),
    )
    debug = list(state.get("lookup_debug", [])) + result.get("debug_steps", [])
    return {"api_result": result, "conflicts": result.get("conflicts", []), "lookup_debug": debug}


def search_web_node(state: LibrarianState) -> LibrarianState:
    result = search_web(state.get("search_queries", []))
    debug = list(state.get("lookup_debug", [])) + result.get("debug_steps", [])
    return {"web_results": result.get("results", []), "web_search_meta": result.get("meta", {}), "lookup_debug": debug}


def visit_and_summarize_sources(state: LibrarianState) -> LibrarianState:
    summaries = summarize_sources(state.get("web_results", []))
    debug = list(state.get("lookup_debug", []))
    debug.append(
        {
            "step": "visit_and_summarize_sources",
            "query": "Tavily result snippets",
            "returned_result": bool(summaries),
            "note": f"Summarized {len(summaries)} legal-safe source result(s).",
            "urls": [item.get("url", "") for item in summaries],
        }
    )
    return {"source_summaries": summaries, "lookup_debug": debug}


def compare_sources(state: LibrarianState) -> LibrarianState:
    fields = _best_fields(state)
    api_sources = _api_sources_for_evidence(state.get("api_result", {}).get("api_results", []))
    web_sources = state.get("source_summaries", [])
    all_sources = api_sources + web_sources
    evidence, conflicts, confidence = build_source_evidence(fields, all_sources)
    debug = list(state.get("lookup_debug", []))
    debug.append(
        {
            "step": "compare_sources",
            "query": "source evidence",
            "returned_result": bool(evidence),
            "note": f"Built evidence table with confidence: {confidence}.",
        }
    )
    return {
        "source_evidence": evidence,
        "conflicts": list(state.get("conflicts", [])) + conflicts,
        "confidence_level": confidence,
        "lookup_debug": debug,
    }


def research_availability_node(state: LibrarianState) -> LibrarianState:
    fields = _best_fields(state)
    query = " ".join(state.get("search_queries", [])[:1]) or fields.get("title", "") or fields.get("isbn", "") or fields.get("issn", "")
    web_links = build_legal_search_links(query)
    links = research_availability(
        title=fields.get("title", ""),
        author=fields.get("author", ""),
        isbn=fields.get("isbn", ""),
        issn=fields.get("issn", ""),
        publisher=fields.get("publisher", ""),
        year=fields.get("publication_year_gregorian", "") or fields.get("publication_year_hijri", ""),
    )
    existing_urls = {link.get("url") for link in links}
    links.extend([link for link in web_links if link.get("url") not in existing_urls])
    debug = list(state.get("lookup_debug", []))
    debug.append(
        {
            "step": "research_availability",
            "query": fields.get("title", "") or fields.get("isbn", "") or fields.get("issn", ""),
            "returned_result": bool(links),
            "note": f"Generated {len(links)} legal availability/search link(s)." if links else "No availability/search links generated.",
        }
    )
    draft = dict(state.get("catalog_draft", {}))
    if draft:
        draft["source_links"] = "\n".join(
            part
            for part in [
                draft.get("source_links", ""),
                format_availability_links(links),
            ]
            if part
        )
    return {"availability_links": links, "catalog_draft": draft or state.get("catalog_draft", {}), "lookup_debug": debug}


def merge_and_validate_results(state: LibrarianState) -> LibrarianState:
    fields = _best_fields(state)
    notes = list(state.get("uncertainty_notes", []))
    conflicts = list(state.get("conflicts", []))

    if fields.get("publication_year_hijri") and not fields.get("publication_year_gregorian"):
        calculated, note = hijri_to_gregorian_placeholder(fields["publication_year_hijri"])
        fields["publication_year_gregorian"] = calculated
        notes.append(note)

    for important in ["title", "author", "publisher", "publication_year_gregorian"]:
        if not fields.get(important):
            notes.append(f"{important} is missing or uncertain.")

    if state.get("availability_links"):
        fields["source_links"] = "\n".join(
            part
            for part in [
                fields.get("source_links", ""),
                format_availability_links(state["availability_links"]),
            ]
            if part
        )
    elif fields.get("title") or fields.get("author") or fields.get("isbn"):
        fields["source_links"] = build_search_links(
            fields.get("title", ""),
            fields.get("author", ""),
            fields.get("isbn", ""),
            fields.get("issn", ""),
            fields.get("publisher", ""),
            fields.get("publication_year_gregorian", "") or fields.get("publication_year_hijri", ""),
        )

    if conflicts:
        notes.append("Source conflicts:\n" + "\n".join(conflicts))
    if state.get("confidence_level"):
        notes.append(f"Online source confidence: {state['confidence_level']}.")

    api_results = [result for result in state.get("api_result", {}).get("api_results", []) if _is_verified_result(result)]
    trusted_web = [source for source in state.get("source_summaries", []) if source.get("is_trusted")]
    verified_links = [link for link in state.get("availability_links", []) if link.get("kind") == "verified"]
    has_search_links = bool(state.get("search_queries"))
    has_ocr_text = bool(state.get("extracted_text"))
    if api_results or trusted_web or verified_links:
        online_status = "verified_result"
        online_summary = "Found verified online result."
    elif has_ocr_text:
        online_status = "image_only"
        online_summary = "No verified online source was found. This draft is based only on the uploaded image."
    elif has_search_links:
        online_status = "search_links_only"
        online_summary = "No verified online result found. Showing legal search links only."
    else:
        online_status = "no_verified_result"
        online_summary = "No verified online result found."

    if has_ocr_text and not api_results:
        notes.append("No verified online source was found. This draft is based only on the uploaded image.")

    fields["category"] = fields.get("category") or state.get("item_type", "unknown")
    fields["notes"] = "\n".join(part for part in [fields.get("notes", ""), *notes] if part)
    return {
        "catalog_draft": CatalogDraft.from_dict(fields).as_dict(),
        "uncertainty_notes": notes,
        "conflicts": conflicts,
        "online_search_status": online_status,
        "online_search_summary": online_summary,
    }


def generate_catalog_draft(state: LibrarianState) -> LibrarianState:
    draft = dict(state.get("catalog_draft", {}))
    draft.setdefault("status", "unknown")
    return {"catalog_draft": CatalogDraft.from_dict(draft).as_dict()}


def human_review_before_save(state: LibrarianState) -> LibrarianState:
    # The Streamlit UI owns actual human review. This node records the checkpoint.
    return {}


def save_to_database(state: LibrarianState) -> LibrarianState:
    if not state.get("approved_for_save"):
        return {}
    draft = state.get("catalog_draft", {})
    if not draft:
        return {}
    database.init_db()
    book_id = database.add_book(draft)
    return {"saved_book_id": book_id}


def _best_fields(state: LibrarianState) -> dict[str, Any]:
    fields = dict(state.get("extracted_fields", {}))
    api_result = state.get("api_result", {})
    for key, value in api_result.items():
        if key in {"api_results", "conflicts", "debug_steps"}:
            continue
        if value and not fields.get(key):
            fields[key] = value
    identifiers = state.get("identifiers", {})
    for key in ["isbn", "issn", "deposit_number"]:
        if identifiers.get(key) and not fields.get(key):
            fields[key] = identifiers[key]
    return fields


def build_research_queries(fields: dict[str, Any], identifiers: dict[str, str], query: str, extracted_text: str) -> list[str]:
    title = fields.get("title", "")
    author = fields.get("author", "")
    publisher = fields.get("publisher", "")
    isbn = identifiers.get("isbn", "") or fields.get("isbn", "")
    issn = identifiers.get("issn", "") or fields.get("issn", "")
    deposit = identifiers.get("deposit_number", "") or fields.get("deposit_number", "")
    hijri = fields.get("publication_year_hijri", "")
    gregorian = fields.get("publication_year_gregorian", "")
    base = title or query
    queries = [
        title,
        " ".join(part for part in [title, author] if part),
        " ".join(part for part in [title, publisher] if part),
        " ".join(part for part in [title, isbn] if part),
        " ".join(part for part in [title, issn] if part),
        " ".join(part for part in [title, deposit] if part),
        " ".join(part for part in [title, hijri] if part),
        " ".join(part for part in [title, gregorian] if part),
        " ".join(part for part in [base, "PDF"] if part),
        " ".join(part for part in [base, "Internet Archive"] if part),
        " ".join(part for part in [base, "WorldCat"] if part),
        " ".join(part for part in [base, "شراء"] if part),
        " ".join(part for part in [base, "تحميل قانوني"] if part),
        query,
    ]
    if extracted_text:
        lines = [line.strip() for line in extracted_text.splitlines() if line.strip()]
        queries.extend(lines[:5])
    return _unique_terms([item for item in queries if item])


def _api_sources_for_evidence(api_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources = []
    for result in api_results:
        source = result.get("source", "Book API")
        text = " ".join(str(result.get(field, "")) for field in ["title", "author", "publisher", "publication_year_gregorian", "isbn", "issn"])
        sources.append(
            {
                "source": source,
                "source_type": source,
                "title": result.get("title", ""),
                "url": result.get("source_links", ""),
                "snippet": text,
                "is_trusted": _is_verified_result(result),
                "is_legal": True,
            }
        )
    return sources


def build_source_evidence(fields: dict[str, Any], sources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], str]:
    evidence = []
    conflicts = []
    checked_fields = {
        "title": fields.get("title", ""),
        "author": fields.get("author", ""),
        "publisher": fields.get("publisher", ""),
        "year": fields.get("publication_year_gregorian", "") or fields.get("publication_year_hijri", ""),
        "isbn": fields.get("isbn", ""),
        "issn": fields.get("issn", ""),
    }
    trusted_confirmations = 0
    for field, value in checked_fields.items():
        if not value:
            evidence.append({"field": field, "value": "", "confirmed_by": "", "confidence": "missing"})
            continue
        confirmed = []
        normalized_value = normalize_arabic_for_search(value)
        for source in sources:
            haystack = normalize_arabic_for_search(" ".join([source.get("title", ""), source.get("snippet", ""), source.get("url", "")]))
            if normalized_value and normalized_value in haystack:
                confirmed.append(source.get("source") or source.get("source_type") or source.get("url", "Source"))
                if source.get("is_trusted"):
                    trusted_confirmations += 1
        confidence = "high" if len(set(confirmed)) >= 2 else "medium" if confirmed else "low"
        evidence.append({"field": field, "value": value, "confirmed_by": ", ".join(sorted(set(confirmed))), "confidence": confidence})
    confidence_level = "high" if trusted_confirmations >= 4 else "medium" if trusted_confirmations >= 2 else "low"
    return evidence, conflicts, confidence_level


def detect_item_type(text: str, fields: dict[str, Any]) -> str:
    normalized = normalize_arabic_for_search(" ".join([text or "", " ".join(str(value) for value in fields.values())]))
    if any(word in normalized for word in ["مجله", "عدد", "فصليه", "دوريه", "ردمد", "issn"]):
        return "journal/serial issue"
    if any(word in normalized for word in ["تقرير", "report"]):
        return "report"
    if any(word in normalized for word in ["مجلد", "magazine"]):
        return "magazine"
    if fields.get("isbn") or any(word in normalized for word in ["كتاب", "ردمك", "isbn"]):
        return "book"
    return "unknown"


def build_lookup_terms(fields: dict[str, Any], identifiers: dict[str, str], query: str, extracted_text: str) -> list[str]:
    title = fields.get("title", "")
    author = fields.get("author", "")
    publisher = fields.get("publisher", "")
    year = fields.get("publication_year_gregorian", "") or fields.get("publication_year_hijri", "")
    terms = [
        title,
        " ".join(part for part in [title, author] if part),
        " ".join(part for part in [title, publisher] if part),
        " ".join(part for part in [title, year] if part),
        identifiers.get("issn", ""),
        identifiers.get("isbn", ""),
        query,
    ]
    if extracted_text:
        lines = [line.strip() for line in extracted_text.splitlines() if line.strip()]
        terms.extend(lines[:4])
    return _unique_terms(terms)


def _unique_terms(terms: list[str]) -> list[str]:
    seen = set()
    unique = []
    for term in terms:
        clean = " ".join(str(term or "").split())
        if not clean or clean in seen:
            continue
        seen.add(clean)
        unique.append(clean)
    return unique


def _is_verified_result(result: dict[str, Any]) -> bool:
    if not result:
        return False
    if "failed" in str(result.get("notes", "")).lower():
        return False
    return bool(result.get("title") or result.get("source_links") or result.get("isbn"))

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


class LibrarianState(TypedDict, total=False):
    query: str
    image_bytes: bytes
    image_mime_type: str
    extracted_text: str
    extracted_fields: dict[str, Any]
    identifiers: dict[str, str]
    private_matches: list[dict[str, Any]]
    api_result: dict[str, Any]
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
    graph.add_node("lookup_book_apis", lookup_book_apis_node)
    graph.add_node("research_availability", research_availability_node)
    graph.add_node("merge_and_validate_results", merge_and_validate_results)
    graph.add_node("generate_catalog_draft", generate_catalog_draft)
    graph.add_node("human_review_before_save", human_review_before_save)
    graph.add_node("save_to_database", save_to_database)

    graph.set_entry_point("parse_user_input")
    graph.add_edge("parse_user_input", "extract_from_image")
    graph.add_edge("extract_from_image", "detect_identifiers")
    graph.add_edge("detect_identifiers", "search_private_database")
    graph.add_edge("search_private_database", "lookup_book_apis")
    graph.add_edge("lookup_book_apis", "research_availability")
    graph.add_edge("research_availability", "merge_and_validate_results")
    graph.add_edge("merge_and_validate_results", "generate_catalog_draft")
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
    ocr_fields = extract_basic_fields_from_text(raw_text) if raw_text else {}
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
            "returned_result": bool(raw_text or result.get("fields")),
            "note": "OCR/image extraction returned text or fields." if raw_text or result.get("fields") else "No image text extracted.",
        }
    )
    return {
        "extracted_text": raw_text,
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


def lookup_book_apis_node(state: LibrarianState) -> LibrarianState:
    fields = state.get("extracted_fields", {})
    identifiers = state.get("identifiers", {})
    query = " ".join(part for part in [fields.get("title", ""), fields.get("author", "")] if part) or state.get("query", "")
    search_terms = build_lookup_terms(fields, identifiers, state.get("query", ""), state.get("extracted_text", ""))
    result = lookup_book_apis(
        query=query,
        isbn=identifiers.get("isbn", ""),
        issn=identifiers.get("issn", ""),
        search_terms=search_terms,
        item_type=state.get("item_type", "unknown"),
    )
    debug = list(state.get("lookup_debug", [])) + result.get("debug_steps", [])
    return {"api_result": result, "conflicts": result.get("conflicts", []), "lookup_debug": debug}


def research_availability_node(state: LibrarianState) -> LibrarianState:
    fields = _best_fields(state)
    links = research_availability(
        title=fields.get("title", ""),
        author=fields.get("author", ""),
        isbn=fields.get("isbn", ""),
        issn=fields.get("issn", ""),
        publisher=fields.get("publisher", ""),
        year=fields.get("publication_year_gregorian", "") or fields.get("publication_year_hijri", ""),
    )
    debug = list(state.get("lookup_debug", []))
    debug.append(
        {
            "step": "research_availability",
            "query": fields.get("title", "") or fields.get("isbn", "") or fields.get("issn", ""),
            "returned_result": bool(links),
            "note": f"Generated {len(links)} legal availability/search link(s)." if links else "No availability/search links generated.",
        }
    )
    return {"availability_links": links, "lookup_debug": debug}


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

    api_results = [result for result in state.get("api_result", {}).get("api_results", []) if _is_verified_result(result)]
    verified_links = [link for link in state.get("availability_links", []) if link.get("kind") == "verified"]
    has_search_links = any(link.get("kind") == "search suggestion" for link in state.get("availability_links", []))
    has_ocr_text = bool(state.get("extracted_text"))
    if api_results or verified_links:
        online_status = "verified_result"
        online_summary = "Found verified online result."
    elif has_ocr_text:
        online_status = "image_only"
        online_summary = "Draft generated from uploaded image only. No verified online result found; showing legal search links if available."
    elif has_search_links:
        online_status = "search_links_only"
        online_summary = "No verified online result found. Showing legal search links only."
    else:
        online_status = "no_verified_result"
        online_summary = "No verified online result found."

    if has_ocr_text and not api_results:
        notes.append("Draft generated from uploaded image only.")

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

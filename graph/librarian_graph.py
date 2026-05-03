from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from models.schema import CatalogDraft
from services import database
from services.availability import format_availability_links, research_availability
from services.book_lookup import build_search_links, lookup_book_apis
from services.date_utils import hijri_to_gregorian_placeholder
from services.extraction import detect_identifiers, extract_basic_fields_from_text, extract_from_image


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
    if not query and not state.get("image_bytes"):
        uncertainty.append("No text or image input was provided.")
    return {"query": query, "extracted_fields": fields, "uncertainty_notes": uncertainty}


def extract_image_node(state: LibrarianState) -> LibrarianState:
    image_bytes = state.get("image_bytes")
    if not image_bytes:
        return {}
    result = extract_from_image(image_bytes, state.get("image_mime_type") or "image/jpeg")
    extracted_fields = dict(state.get("extracted_fields", {}))
    extracted_fields.update({key: value for key, value in result.get("fields", {}).items() if value})
    notes = list(state.get("uncertainty_notes", []))
    if result.get("notes"):
        notes.append(str(result["notes"]))
    return {
        "extracted_text": result.get("raw_text", ""),
        "extracted_fields": extracted_fields,
        "uncertainty_notes": notes,
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
    return {
        "identifiers": {
            "isbn": fields.get("isbn", ""),
            "issn": fields.get("issn", ""),
            "deposit_number": fields.get("deposit_number", ""),
        },
        "extracted_fields": fields,
        "uncertainty_notes": notes,
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
    return {"private_matches": matches}


def lookup_book_apis_node(state: LibrarianState) -> LibrarianState:
    fields = state.get("extracted_fields", {})
    identifiers = state.get("identifiers", {})
    query = " ".join(part for part in [fields.get("title", ""), fields.get("author", ""), state.get("query", "")] if part)
    result = lookup_book_apis(query=query, isbn=identifiers.get("isbn", ""), issn=identifiers.get("issn", ""))
    return {"api_result": result, "conflicts": result.get("conflicts", [])}


def research_availability_node(state: LibrarianState) -> LibrarianState:
    fields = _best_fields(state)
    links = research_availability(
        title=fields.get("title", ""),
        author=fields.get("author", ""),
        isbn=fields.get("isbn", ""),
    )
    return {"availability_links": links}


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
        fields["source_links"] = build_search_links(fields.get("title", ""), fields.get("author", ""), fields.get("isbn", ""))

    if conflicts:
        notes.append("Source conflicts:\n" + "\n".join(conflicts))

    fields["notes"] = "\n".join(part for part in [fields.get("notes", ""), *notes] if part)
    return {"catalog_draft": CatalogDraft.from_dict(fields).as_dict(), "uncertainty_notes": notes, "conflicts": conflicts}


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
        if key in {"api_results", "conflicts"}:
            continue
        if value and not fields.get(key):
            fields[key] = value
    identifiers = state.get("identifiers", {})
    for key in ["isbn", "issn", "deposit_number"]:
        if identifiers.get(key) and not fields.get(key):
            fields[key] = identifiers[key]
    return fields

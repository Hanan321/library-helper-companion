from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from graph.librarian_graph import build_librarian_graph
from models.schema import BOOK_FIELDS, STATUS_OPTIONS
from services import database
from services.extraction import extract_basic_fields_from_text


st.set_page_config(page_title="AI Librarian Agent", page_icon="📚", layout="wide")


def load_runtime_config() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#") or "=" not in clean:
                continue
            key, value = clean.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    for key in ["OPENAI_API_KEY", "OPENAI_MODEL", "WEB_SEARCH_PROVIDER", "WEB_SEARCH_API_KEY", "TAVILY_API_KEY"]:
        try:
            value = st.secrets.get(key)
        except Exception:
            value = None
        if value:
            os.environ[key] = str(value)


@st.cache_resource
def get_graph():
    return build_librarian_graph()


def main() -> None:
    load_runtime_config()
    database.init_db()

    st.title("AI Librarian Agent")
    st.caption("Private library MVP: search, research, draft, review, save.")

    tabs = st.tabs(["Search My Library", "Research New Book", "Catalog Draft", "Where to Get the Book", "Database"])

    with tabs[0]:
        search_my_library()

    with tabs[1]:
        research_new_book()

    with tabs[2]:
        catalog_draft_section()

    with tabs[3]:
        availability_section()

    with tabs[4]:
        database_section()


def search_my_library() -> None:
    st.subheader("Search My Library")
    query = st.text_input("Search by title, author, ISBN, ISSN, deposit number, or Arabic text", key="library_search")
    if st.button("Search", type="primary", use_container_width=False) or query:
        matches = database.search_books(query)
        if not matches:
            st.info("No local matches found.")
            return
        for book in matches:
            render_book_result(book)


def research_new_book() -> None:
    st.subheader("Research New Book")
    if not (os.getenv("TAVILY_API_KEY") or os.getenv("WEB_SEARCH_API_KEY")):
        st.warning("TAVILY_API_KEY is missing. Web search is disabled.")
    text_query = st.text_area("Title, author, ISBN/ISSN, Arabic text, or notes", height=120)
    uploaded = st.file_uploader("Upload cover or copyright page image", type=["png", "jpg", "jpeg", "webp"])

    if st.button("Research", type="primary"):
        load_runtime_config()
        image_bytes = uploaded.getvalue() if uploaded else None
        image_mime = uploaded.type if uploaded else ""
        with st.spinner("Searching private database first, then legal metadata sources..."):
            state = get_graph().invoke(
                {
                    "query": text_query,
                    "image_bytes": image_bytes,
                    "image_mime_type": image_mime,
                    "approved_for_save": False,
                }
            )
        st.session_state["last_research_state"] = state
        st.session_state["catalog_draft"] = state.get("catalog_draft", {})
        st.session_state["availability_links"] = state.get("availability_links", [])

    state = st.session_state.get("last_research_state")
    if not state:
        return

    st.caption(f"Detected item type: {state.get('item_type', 'unknown')}")
    st.subheader("Private Library Match")
    private_matches = state.get("private_matches", [])
    if private_matches:
        st.success("Found possible match in the private library before online recommendations.")
        for book in private_matches[:5]:
            render_book_result(book)
    else:
        st.info("No private database match found.")

    render_catalog_summary(state)
    render_source_summary(state)
    with st.expander("Raw OCR text", expanded=False):
        render_extracted_text(state)
    with st.expander("Source details", expanded=False):
        render_online_search_results(state)
        render_source_evidence(state)
        render_conflicts_uncertainty(state)
    render_research_debug(state)


def render_catalog_summary(state: dict) -> None:
    st.subheader("Catalog Summary")
    draft = state.get("catalog_draft", {})
    identifiers = state.get("identifiers", {})
    article_title = draft.get("description") or extract_basic_fields_from_text(state.get("extracted_text", "")).get("description", "")
    rows = [
        {"Field": "Title", "Value": draft.get("title", "")},
        {"Field": "Article title", "Value": article_title},
        {"Field": "Author / Editor", "Value": draft.get("author", "")},
        {"Field": "Publisher", "Value": draft.get("publisher", "")},
        {"Field": "Hijri date", "Value": draft.get("publication_year_hijri", "")},
        {"Field": "Gregorian date", "Value": draft.get("publication_year_gregorian", "")},
        {"Field": "ISBN", "Value": draft.get("isbn") or identifiers.get("isbn", "")},
        {"Field": "ISSN", "Value": draft.get("issn") or identifiers.get("issn", "")},
        {"Field": "Deposit number", "Value": draft.get("deposit_number") or identifiers.get("deposit_number", "")},
        {"Field": "Category", "Value": draft.get("category") or state.get("item_type", "")},
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    if st.button("Save to Library", key="save_research_summary"):
        save_draft = dict(draft)
        if article_title and not save_draft.get("description"):
            save_draft["description"] = article_title
        book_id = database.add_book(save_draft)
        st.success(f"Saved book #{book_id} to library.db.")


def render_source_summary(state: dict) -> None:
    status = state.get("online_search_status", "no_verified_result")
    if status == "verified_result":
        st.success("Online source found. Review the catalog summary, then save if correct.")
    elif status == "image_only":
        st.warning("No verified online source was found. This draft is based only on the uploaded image.")
    else:
        st.info("No exact verified online source was found. Search suggestions are available in Source details.")


def render_extracted_text(state: dict) -> None:
    text = state.get("extracted_text", "")
    if text:
        st.text_area("OCR text", value=text, height=180, disabled=True)
    else:
        st.info("No uploaded image text was extracted.")


def render_extracted_details_table(state: dict) -> None:
    st.subheader("Organized Extracted Details")
    draft = state.get("catalog_draft", {})
    identifiers = state.get("identifiers", {})
    row = {
        "Title": draft.get("title", ""),
        "Author / Editor": draft.get("author", ""),
        "Publisher": draft.get("publisher", ""),
        "Hijri Date": draft.get("publication_year_hijri", ""),
        "Gregorian Date": draft.get("publication_year_gregorian", ""),
        "ISBN": draft.get("isbn") or identifiers.get("isbn", ""),
        "ISSN": draft.get("issn") or identifiers.get("issn", ""),
        "Deposit Number": draft.get("deposit_number") or identifiers.get("deposit_number", ""),
        "Item Type": state.get("item_type", "unknown"),
        "Confidence": state.get("confidence_level", "low"),
    }
    st.dataframe([row], use_container_width=True, hide_index=True)


def render_online_search_results(state: dict) -> None:
    st.subheader("Online Search Results")
    status = state.get("online_search_status", "no_verified_result")
    summary = state.get("online_search_summary", "No verified online result found.")
    api_results = state.get("api_result", {}).get("api_results", [])
    web_results = state.get("web_results", [])
    web_meta = state.get("web_search_meta", {})
    links = state.get("availability_links", [])
    source_summaries = state.get("source_summaries", [])

    if not web_meta.get("api_key_found"):
        st.warning("TAVILY_API_KEY is missing. Web search is disabled.")

    if status == "verified_result":
        st.success(summary)
    elif status == "image_only":
        st.warning(summary)
    elif status == "search_links_only":
        st.info(summary)
    else:
        st.info(summary)

    verified_results = [result for result in api_results if result.get("title") or result.get("source_links") or result.get("isbn")]
    verified_links = [item for item in links if item.get("kind") == "verified"]
    if verified_results:
        for result in verified_results:
            source = result.get("source", "Online source")
            title = result.get("title", "Untitled result")
            url = result.get("source_links", "")
            if url:
                st.markdown(f"- **Verified result from {source}:** [{title}]({url})")
            else:
                st.markdown(f"- **Verified result from {source}:** {title}")
    if verified_links:
        for item in verified_links:
            st.markdown(f"- **Verified legal link:** [{item.get('label', 'Verified link')}]({item.get('url', '#')})")
    trusted_sources = [source for source in source_summaries if source.get("is_trusted")]
    if trusted_sources:
        for source in trusted_sources[:10]:
            st.markdown(
                f"- **Research source ({source.get('source_type', 'source')}):** "
                f"[{source.get('title') or source.get('url')}]({source.get('url', '#')})"
            )
            if source.get("snippet"):
                st.caption(source["snippet"])

    if web_results:
        st.markdown("Tavily web results:")
        for result in web_results[:12]:
            st.markdown(f"**{result.get('title') or 'Untitled result'}**")
            st.markdown(f"[{result.get('url')}]({result.get('url')})")
            st.caption(f"Provider/source: Tavily / {result.get('source', 'web')}")
            if result.get("snippet"):
                st.write(result["snippet"])

    if not verified_results and not verified_links and not trusted_sources and not web_results:
        st.write("No verified result was found in Google Books, Open Library, trusted web sources, or legal availability lookup.")

    search_links = [item for item in links if item.get("kind") == "search suggestion"]
    if search_links:
        st.markdown("Search links only:")
        for item in search_links:
            st.markdown(f"- [{item.get('label', 'Search suggestion')}]({item.get('url', '#')})")


def render_source_evidence(state: dict) -> None:
    st.subheader("Source Evidence Table")
    evidence = state.get("source_evidence", [])
    if evidence:
        st.dataframe(evidence, use_container_width=True, hide_index=True)
        confidence = state.get("confidence_level")
        if confidence:
            st.caption(f"Overall confidence: {confidence}")
    else:
        st.info("No source evidence was collected.")


def render_conflicts_uncertainty(state: dict) -> None:
    st.subheader("Conflicts / Uncertainty")
    conflicts = state.get("conflicts", [])
    notes = state.get("uncertainty_notes", [])
    if conflicts:
        st.warning("Source conflicts found. Review before saving.")
        for conflict in conflicts:
            st.write(f"- {conflict}")
    if notes:
        for note in notes:
            st.write(f"- {note}")
    if not conflicts and not notes:
        st.info("No conflicts or uncertainty notes were recorded.")


def render_where_to_get(state: dict) -> None:
    st.subheader("Where to Get the Book")
    links = state.get("availability_links", [])
    if not links:
        st.info("No legal availability links were generated.")
        return
    for item in links:
        st.markdown(f"- **{item.get('kind', 'link')}**: [{item.get('label', 'Link')}]({item.get('url', '#')})")


def render_research_catalog_draft(state: dict) -> None:
    st.subheader("Catalog Draft")
    draft = state.get("catalog_draft", {})
    if not draft:
        st.info("No catalog draft generated.")
        return
    preview_fields = ["title", "author", "publisher", "publication_year_gregorian", "publication_year_hijri", "isbn", "issn", "deposit_number", "category"]
    st.json({field: draft.get(field, "") for field in preview_fields})
    st.caption("Use the Catalog Draft tab to review and edit all fields before saving, or save this draft as-is.")
    if st.button("Save to Library", key="save_research_draft"):
        book_id = database.add_book(draft)
        st.success(f"Saved book #{book_id} to library.db.")


def render_research_debug(state: dict) -> None:
    debug_steps = state.get("lookup_debug", [])
    web_meta = state.get("web_search_meta", {})
    with st.expander("Research Debug", expanded=False):
        st.markdown("Extracted text:")
        st.text(state.get("extracted_text", "") or "(none)")
        st.write(f"TAVILY_API_KEY found: {bool(web_meta.get('api_key_found'))}")
        st.write(f"Tavily called: {bool(web_meta.get('tavily_called'))}")
        st.write(f"Tavily result count: {web_meta.get('result_count', 0)}")
        errors = web_meta.get("errors", [])
        if errors:
            st.markdown("Errors:")
            for error in errors:
                st.caption(f"- {error}")
        queries = state.get("search_queries", [])
        if queries:
            st.markdown("Generated search queries:")
            for query in queries:
                st.caption(f"- {query}")
        if not debug_steps:
            return
        for step in debug_steps:
            result = "returned results" if step.get("returned_result") else "no result"
            st.write(f"**{step.get('step', 'lookup')}** - {result}")
            if step.get("query"):
                st.caption(f"Query: {step['query']}")
            if step.get("note"):
                st.caption(str(step["note"]))
            if step.get("urls"):
                for url in step["urls"]:
                    st.caption(f"URL: {url}")


def catalog_draft_section() -> None:
    st.subheader("Catalog Draft")
    draft = st.session_state.get("catalog_draft")
    if not draft:
        st.info("Research a new book first, or enter a manual sample below.")
        manual_sample_form()
        return

    edited = editable_book_form(draft, form_key="catalog_draft_form")
    if edited:
        st.session_state["catalog_draft"] = edited
        state = get_graph().invoke({"catalog_draft": edited, "approved_for_save": True})
        st.success(f"Saved book #{state.get('saved_book_id')} to the SQLite database.")

    st.divider()
    manual_sample_form()


def availability_section() -> None:
    st.subheader("Where to Get the Book")
    links = st.session_state.get("availability_links", [])
    draft = st.session_state.get("catalog_draft", {})

    st.caption("Only legal free, paid, or safe search options are shown. Illegal download sites are not used.")
    if not links and not draft:
        st.info("Research a book first to generate links.")
        return

    if links:
        for item in links:
            label = f"{item.get('label', 'Link')} ({item.get('kind', 'search suggestion')})"
            st.markdown(f"- [{label}]({item.get('url', '#')})")
    elif draft.get("source_links"):
        st.text(draft["source_links"])
    else:
        st.info("No verified purchase or free download link was found.")


def database_section() -> None:
    st.subheader("Database")
    st.caption(f"Persistent database: `{database.DB_PATH}`")
    st.info("Imported and saved catalog records stay in library.db after closing and reopening the app.")

    uploaded_file = st.file_uploader(
        "Import a new Excel/CSV file into library.db",
        type=["csv", "xlsx", "xls"],
        key="database_csv_import",
    )
    if uploaded_file and st.button("Import into persistent database"):
        try:
            count = database.import_books_file(uploaded_file, uploaded_file.name)
            st.success(f"Imported {count} books into library.db. You do not need to upload this file again.")
        except UnicodeDecodeError:
            st.error("CSV import failed. Please upload a UTF-8 encoded CSV file.")
        except Exception as exc:
            st.error(f"Import failed: {exc}")

    rows = database.list_books()
    st.write(f"{len(rows)} books saved.")

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.download_button(
            "Backup/export current database as CSV",
            data=database.export_books_csv_text(),
            file_name="library_books.csv",
            mime="text/csv",
        )
    else:
        st.info("No books saved yet.")


def manual_sample_form() -> None:
    with st.expander("Add manual sample book with location"):
        sample = {
            "title": "Manual sample book",
            "author": "",
            "publisher": "",
            "edition": "",
            "publication_year_gregorian": "",
            "publication_year_hijri": "",
            "isbn": "",
            "issn": "",
            "deposit_number": "",
            "language": "",
            "category": "",
            "description": "",
            "room": "Main room",
            "cabinet": "Cabinet A",
            "shelf": "Shelf 1",
            "row_position": "Row 1",
            "status": "available",
            "notes": "Manual entry.",
            "source_links": "",
        }
        edited = editable_book_form(sample, form_key="manual_sample_form")
        if edited:
            book_id = database.add_book(edited)
            st.success(f"Saved manual sample book #{book_id}.")


def editable_book_form(draft: dict, form_key: str) -> dict | None:
    with st.form(form_key):
        col1, col2 = st.columns(2)
        values = {}
        for index, field in enumerate(BOOK_FIELDS):
            target = col1 if index % 2 == 0 else col2
            label = field.replace("_", " ").title()
            current = draft.get(field, "")
            if field == "status":
                selected_index = STATUS_OPTIONS.index(current) if current in STATUS_OPTIONS else STATUS_OPTIONS.index("unknown")
                values[field] = target.selectbox(label, STATUS_OPTIONS, index=selected_index)
            elif field in {"description", "notes", "source_links"}:
                values[field] = st.text_area(label, value=current or "", height=120)
            else:
                values[field] = target.text_input(label, value=current or "")

        submitted = st.form_submit_button("Save approved catalog draft", type="primary")
        if submitted:
            return values
    return None


def render_book_result(book: dict) -> None:
    title = book.get("title") or "Untitled"
    author = book.get("author") or "Unknown author"
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.write(author)
        loc_cols = st.columns(5)
        loc_cols[0].metric("Room", book.get("room") or "Unknown")
        loc_cols[1].metric("Cabinet", book.get("cabinet") or "Unknown")
        loc_cols[2].metric("Shelf", book.get("shelf") or "Unknown")
        loc_cols[3].metric("Row/Position", book.get("row_position") or "Unknown")
        loc_cols[4].metric("Status", book.get("status") or "unknown")
        with st.expander("Catalog details"):
            st.json({key: book.get(key, "") for key in ["isbn", "issn", "deposit_number", "publisher", "edition", "notes", "source_links"]})


if __name__ == "__main__":
    main()

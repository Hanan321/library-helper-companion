from __future__ import annotations

import streamlit as st

from graph.librarian_graph import build_librarian_graph
from models.schema import BOOK_FIELDS, STATUS_OPTIONS
from services import database


st.set_page_config(page_title="AI Librarian Agent", page_icon="📚", layout="wide")


@st.cache_resource
def get_graph():
    return build_librarian_graph()


def main() -> None:
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
    text_query = st.text_area("Title, author, ISBN/ISSN, Arabic text, or notes", height=120)
    uploaded = st.file_uploader("Upload cover or copyright page image", type=["png", "jpg", "jpeg", "webp"])

    if st.button("Research", type="primary"):
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

    private_matches = state.get("private_matches", [])
    if private_matches:
        st.success("Found possible match in the private library before online recommendations.")
        for book in private_matches[:5]:
            render_book_result(book)
    else:
        st.info("No private database match found. A catalog draft was generated from available sources.")

    if state.get("conflicts"):
        st.warning("Source conflicts found. Review notes before saving.")
        st.write(state["conflicts"])

    if state.get("uncertainty_notes"):
        with st.expander("Confidence and uncertainty notes", expanded=True):
            for note in state["uncertainty_notes"]:
                st.write(f"- {note}")


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

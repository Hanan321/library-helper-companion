# AI Librarian Agent MVP

Simple Streamlit app for a private library. It can search a local SQLite catalog, research a new book from text or an uploaded image, draft catalog fields, show legal access/purchase options, and save only after librarian review.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add `OPENAI_API_KEY` to `.env` or export it in your shell if you want cover/copyright-page image extraction.

## Run

```bash
streamlit run app.py
```

The first run creates `library.db` with the requested `books` table.

## MVP Workflow

- Search My Library searches SQLite first and shows room, cabinet, shelf, row/position, and status.
- Research New Book accepts text, Arabic text, ISBN/ISSN, or an image upload.
- The LangGraph workflow runs these nodes: `parse_user_input`, `extract_from_image`, `detect_identifiers`, `search_private_database`, `lookup_book_apis`, `research_availability`, `merge_and_validate_results`, `generate_catalog_draft`, `human_review_before_save`, and `save_to_database`.
- Catalog Draft lets the librarian edit all fields before saving.
- Where to Get the Book shows legal free links when verified and paid/search suggestions when not verified.
- Database exports saved books as CSV.

## Identifier Rules

The extractor keeps these fields separate:

- ISBN: `ISBN`, `ردمك`, `الرقم الدولي المعياري للكتاب`
- ISSN: `ISSN`, `ردمد`, `الرقم الدولي المعياري للدوريات`
- Deposit number: `رقم الإيداع`

Missing data is left blank and uncertainty is written into notes. Conflicting API values are also surfaced in notes instead of being silently invented.

## Arabic Data Support

- SQLite stores Arabic text in `TEXT` fields and the app preserves original Arabic display values.
- Search normalizes Arabic only for matching: `أ إ آ` to `ا`, `ة` to `ه`, `ى` to `ي`, and tashkeel is removed.
- Arabic-Indic digits `٠١٢٣٤٥٦٧٨٩` and Persian digits `۰۱۲۳۴۵۶۷۸۹` are converted to Western digits for search, identifier detection, date parsing, and database matching.
- CSV import accepts UTF-8 or UTF-8-SIG files with English or Arabic headers such as `العنوان`, `المؤلف`, `ردمك`, `ردمد`, and `رقم الإيداع`.
- CSV export includes a UTF-8 BOM so Arabic opens more reliably in Excel.

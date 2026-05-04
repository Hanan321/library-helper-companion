# AI Librarian Agent MVP

Simple Streamlit app for a private library. It can search a local SQLite catalog, research a new book from text or an uploaded image, draft catalog fields, show legal access/purchase options, and save only after librarian review.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add `OPENAI_API_KEY` to `.env` or export it in your shell if you want cover/copyright-page image extraction. Add `TAVILY_API_KEY` for deeper web research.

## Run

```bash
streamlit run app.py
```

The first run creates a persistent SQLite file named `library.db` in the project folder with the requested `books` table. If `library.db` already exists, the app automatically connects to it on startup.

## MVP Workflow

- Search My Library searches SQLite first and shows room, cabinet, shelf, row/position, and status.
- Research New Book accepts text, Arabic text, ISBN/ISSN, or an image upload.
- The LangGraph workflow runs these nodes: `parse_user_input`, `extract_from_image`, `detect_identifiers`, `search_private_database`, `generate_search_queries`, `search_book_apis`, `search_web`, `visit_and_summarize_sources`, `compare_sources`, `merge_and_validate_results`, `research_availability`, `generate_catalog_draft`, `human_review_before_save`, and `save_to_database`.
- Catalog Draft lets the librarian edit all fields before saving.
- Where to Get the Book shows legal free links when verified and paid/search suggestions when not verified.
- Database imports Excel/CSV files into persistent `library.db` and exports the current database as a CSV backup.

## Persistent Library Database

- Imported Excel/CSV records are inserted into `library.db`.
- Manually saved catalog drafts are inserted into the same `library.db`.
- Existing records remain available after closing and reopening Streamlit.
- The librarian only needs to upload a file again when importing a new or updated spreadsheet.
- Use the Database tab's backup/export button to download the current database as CSV.

## Web Research

- Tavily is the first supported web search provider.
- Set `WEB_SEARCH_PROVIDER=tavily` and `TAVILY_API_KEY=...` in `.env`, exported environment variables, or Streamlit secrets.
- If no Tavily key is configured, the app still runs and shows: `TAVILY_API_KEY is missing. Web search is disabled.`
- Web results are filtered to avoid obvious piracy/download sites and are treated as evidence, not automatically as truth.
- The Research page shows online research results, source evidence, conflicts/uncertainty, legal availability links, and a debug panel with generated queries and lookup outcomes.

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
- Excel/CSV import accepts English or Arabic headers such as `العنوان`, `المؤلف`, `ردمك`, `ردمد`, and `رقم الإيداع`. CSV files should be UTF-8 or UTF-8-SIG.
- CSV export includes a UTF-8 BOM so Arabic opens more reliably in Excel.

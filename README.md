# Master Data Utility (MDU) — UX-first demo (Windows, no Docker)

This repo is a local-first Django 5 app that lets business users manage authored reference data in a way that feels like a spreadsheet:

- **Catalog** (search + filters)
- **Proposed changes** (draft → submit → approve/reject)
- **Sample data** tab shows the **latest approved** change (Option A)
- **Propose change** starts from the latest approved data (Option B)
- **Generate load files** (values + meta + optional cert) and download as zip

The UI avoids internal jargon. Technical IDs are tucked into **Details**.

## Quick start (Windows)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_demo
python manage.py runserver
```

Open: http://127.0.0.1:8000/

## Demo users
Password: `password123`

- maker1 (group: maker)
- maker2 (group: maker)
- steward1 (group: steward)
- approver1 (group: approver)

## Output folder for load files
Defaults to `./artifacts/`.

To change it, create a `.env` file and set:

```
MDU_ARTIFACTS_DIR=artifacts
```

## Current scope
- **Edit rows only** (column editing planned later)

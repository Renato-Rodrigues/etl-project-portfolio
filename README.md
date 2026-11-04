# ETL project portfolio dashboard

Reads the ETL project-overview documents and the people table (`ETL people.xlsx`) of the overview folder, normalizes them into one JSON
"database", flags missing or unclear information and (later phases) publishes an encrypted, password-protected
single-file dashboard on GitHub Pages.

Setup: [docs/setup-google.md](docs/setup-google.md) · Operations and local testing: [docs/operations.md](docs/operations.md)

**This repository is public. Real project data never goes in it.** Sources are passed as paths to the CLI;
outputs go to a directory outside the repo or to the ignored `out/`.

## Usage

```sh
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"     # Windows; use .venv/bin on Linux/macOS
python -m etl_dash parse --docs <overview folder: docs + ETL people.xlsx> --out <dir>
```

This writes `<dir>/data.json` (normalized data) and `<dir>/issues.md` (data-quality report for review).

## Tests

```sh
pytest                      # synthetic fixtures only (what CI runs)
ETL_REAL_DOCS=../local_real_data/overviews pytest -m real   # local only
```

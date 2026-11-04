"""Runs against the real sources on a developer machine only (pytest -m real). Never in CI.

Set ETL_REAL_DOCS (an overview folder: docs + 'ETL people.xlsx').
Asserts structure only; prints nothing from the data.
"""
import os

import pytest

from etl_dash.normalize import build
from etl_dash.sources.people_table import find, read_people_table
from etl_dash.sources.overview_docs import list_docs, read_doc
from etl_dash.validate import validate

pytestmark = pytest.mark.real
DOCS = os.environ.get("ETL_REAL_DOCS")


@pytest.fixture(scope="module")
def real():
    if not DOCS:
        pytest.skip("ETL_REAL_DOCS not set")
    docs = [read_doc(p) for p in list_docs(DOCS)]
    table = find(DOCS)
    return docs, validate(build(docs, read_people_table(table) if table else []))


def test_every_doc_parsed(real):
    docs, data = real
    assert docs and all(len(d["overview"]) >= 8 for d in docs)
    assert all(not d["extra"] for d in docs), "unrecognized overview labels"


def test_projects_people_tasks(real):
    _, data = real
    active_docs = [p for p in data["projects"] if p["has_overview_doc"] and not p["excluded"]]
    assert active_docs and all(p["status"] in ("active", "proposal", "finished", "rejected")
                               for p in data["projects"] if not p["excluded"])
    assert data["tasks"]
    assert all(t["loc"]["file"] and t["loc"]["row_key"] for t in data["tasks"])


def test_subprojects_have_parents(real):
    _, data = real
    for p in data["projects"]:
        if p["has_overview_doc"] and not p["excluded"] and "-" in p["id"]:
            prefix = p["id"].split("-")[0]
            if any(q["id"] == prefix for q in data["projects"]):
                assert p["parent_id"] == prefix


def test_repo_contains_no_real_values(real):
    """The public repo must not contain values from the real sources (names, titles, amounts, task texts)."""
    from pathlib import Path
    _, data = real
    values = set()
    for p in data["projects"]:
        values |= {p.get("name"), p.get("title"), (p.get("funding") or {}).get("raw"), p.get("funder"), p.get("partners")}
    values |= {q["name"] for q in data["people"]}
    values |= {t["description"] for t in data["tasks"]}
    values = {v.strip() for v in values if v and len(v.strip()) >= 5}
    for p in data["projects"]:  # any longer free text from the docs (durations, remarks, strategy, contacts, …)
        if p.get("excluded") != "template":  # a blank template holds only format hints
            values |= {f["raw"].strip() for f in (p.get("fields") or {}).values() if len(f["raw"].strip()) >= 8}
    values = {v for v in values if v.lower() not in ("active", "proposal", "finished", "rejected")}
    root = Path(__file__).resolve().parents[1]
    skip = {".venv", ".git", "out", "dist", "__pycache__", ".pytest_cache"}  # git-ignored (case-insensitive on Windows)
    files = [f for f in root.rglob("*") if f.is_file() and not skip & {x.lower() for x in f.relative_to(root).parts}]
    hits = sorted({(f.relative_to(root).as_posix(), len(v)) for f in files for v in values
                   if v in f.read_text(encoding="utf-8", errors="ignore")})
    assert not hits, f"real values found in repo files (file, value length): {hits}"

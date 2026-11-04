"""Create a new project-overview doc, add rows, and store proposal files (local folder / dev server).

The Google side (apps_script/Code.gs) implements the same 'save_project' action for native Google Docs.
Folder layout (same as the Drive TEST / PROD folder):
    <root>/overviews/<ID> - Project overview.docx
    <root>/project_descriptions/<ID>/<proposal files>
"""
import base64
import copy
import re
from pathlib import Path

import docx
from docx.oxml.ns import qn

from .sources.overview_docs import read_doc
from .testdata import FOCUS_TOPICS, SECTORS, write_doc
from .writeback import EditError, _grid_cells, _set_text, clean_value

# The overview rows of template v2, in order: (key, label). The dashboard form uses the same keys.
V2_FIELDS = [
    ("name", "Name"), ("status", "Status (Proposal / Active / Finished / Rejected)"), ("duration", "Duration"),
    ("funding_pik", "Funding – total for PIK"), ("funding_etl", "Funding – of which ETL"), ("currency", "Currency"),
    ("funding_secured", "Funding secured (Yes / Partly / No)"), ("project_lead", "Overall project lead"),
    ("partners", "Other key non-PIK partners"), ("responsible_team", "Mainly responsible PIK team (REMIND runs / overall)?"),
    ("etl_main", "Main ETL researcher (operational / coordination)"), ("etl_pi", "ETL PI (guidance / supervision)"),
    ("etl_other", "Other ETL involvement"), ("pik_other", "Other involved PIK teams and colleagues"),
    ("funder", "Funding agency, main contact person (with email address)"),
    ("folder_internal", "Link to internal project folder (with proposal / description of work etc)"),
    ("folder_consortium", "Link to project folder shared with entire consortium"),
    ("proposal", "Proposal / description of work (file or link)"),
    ("full_title", "Full title"), ("website", "Project website"),
    ("mattermost", "Mattermost channel"), ("strategy", "Strategic considerations / our role"),
    ("synergies", "Synergies with (other projects)"), ("remarks", "Other remarks"),
    ("last_reviewed", "Last reviewed (MM/YYYY, name)"), ("template_version", "Template version"),
]
LABEL = dict(V2_FIELDS)
TASK_COLS = ["id", "description", "effort", "start", "deadline", "lead", "others", "status"]
DEMAND_COLS = ["description", "task_refs", "effort", "flexibility", "deadline", "sector_lead", "project_contact", "status"]
UPLOAD_TYPES = {".pdf", ".docx", ".doc", ".odt", ".pptx", ".xlsx", ".txt", ".md"}
MAX_UPLOAD = 15 * 1024 * 1024
ID_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$")


def reviewed_stamp(editor):
    """'MM/YYYY, Editor' for the 'Last reviewed' row, written whenever the project form is saved from the website."""
    import datetime as dt
    return f"{dt.date.today():%m/%Y}, {clean_value(editor)[:80]}"


def doc_name(pid):
    return f"{pid} - Project overview.docx"


def _project_id(value):
    pid = clean_value(value)
    if not ID_RX.match(pid):
        raise EditError("Name: use the project acronym (letters, digits, spaces, - _ . ; max 40 characters)")
    return pid


def create_project(root, overview, tasks=(), demands=None, focus=None):
    """overview: {key: value}; tasks: [{kind: led|contribution, id, description, …}]; demands: {sector: {col: value}}."""
    root = Path(root)
    pid = _project_id(overview.get("name"))
    path = root / "overviews" / doc_name(pid)
    if path.exists() or any(p.name.lower() == path.name.lower() for p in (root / "overviews").glob("*.docx")):
        raise EditError(f"a project overview for {pid} already exists")
    values = {k: clean_value(overview.get(k, "")) for k, _ in V2_FIELDS}
    values["template_version"] = "v2"
    rows = lambda kind: [tuple(clean_value(t.get(c, "")) for c in TASK_COLS) for t in tasks if t.get("kind") == kind]
    dem = {s: [clean_value((demands or {}).get(s, {}).get(c, "")) for c in DEMAND_COLS] for s in SECTORS}
    write_doc(path, [(label, values[k]) for k, label in V2_FIELDS],
              sections=[("Short summary of tasks and responsibilities", rows("led"), rows("contribution"), None)],
              v2=True, demands=dem, snippets=[], focus={t: clean_value((focus or {}).get(t, "")) for t in FOCUS_TOPICS})
    (root / "project_descriptions" / pid).mkdir(parents=True, exist_ok=True)
    return pid, path.name


def add_task_rows(path, tasks):
    """Append rows to the first ETL-led / ETL-contribution table (copying the last row's formatting)."""
    if not tasks:
        return 0
    parsed = read_doc(path)
    d = docx.Document(str(path))
    tables = d.element.body.findall(qn("w:tbl"))
    added = 0
    for kind in ("led", "contribution"):
        rows = [t for t in tasks if t.get("kind") == kind]
        target = next((t for t in parsed["tables"] if t["kind"] == kind), None)
        if not rows:
            continue
        if target is None:
            raise EditError(f"the document has no ETL-{kind} task table")
        tbl = tables[target["index"]]
        template_tr = tbl.findall(qn("w:tr"))[-1]
        for task in rows:
            tr = copy.deepcopy(template_tr)
            cells = _grid_cells(tr)
            for col, name in enumerate(target["columns"]):
                if col < len(cells) and (col == 0 or cells[col] is not cells[col - 1]):
                    _set_text(cells[col], clean_value(task.get(name or ("id" if col == 0 else ""), "")))
            tbl.append(tr)
            added += 1
    d.save(str(path))
    return added


def set_overview_row(path, key, value):
    """Set an overview field; appends the row (template-v2 label) if the doc does not have it yet."""
    parsed = read_doc(path)
    d = docx.Document(str(path))
    tables = d.element.body.findall(qn("w:tbl"))
    field = parsed["overview"].get(key)
    if field and field.get("loc"):
        tr = tables[field["loc"]["table_index"]].findall(qn("w:tr"))[field["loc"]["row"]]
        _set_text(_grid_cells(tr)[1], clean_value(value))
    else:
        loc = next((v["loc"] for v in parsed["overview"].values() if v.get("loc")), None)
        if loc is None:
            raise EditError("the document has no overview table")
        tbl = tables[loc["table_index"]]
        tr = copy.deepcopy(tbl.findall(qn("w:tr"))[-1])
        label_cell, value_cell = _grid_cells(tr)[0], _grid_cells(tr)[1]
        _set_text(label_cell, LABEL[key])
        _set_text(value_cell, clean_value(value))
        tbl.append(tr)
    d.save(str(path))


def save_proposal(root, pid, name, data_b64=None, url=None):
    """Store an uploaded proposal file (or a link) under project_descriptions/<ID>/. -> text for the overview row."""
    folder = Path(root) / "project_descriptions" / _project_id(pid)
    folder.mkdir(parents=True, exist_ok=True)
    if url:
        url = clean_value(url)
        if not re.match(r"^https://\S+$", url):
            raise EditError("proposal link must start with https://")
        (folder / "proposal-link.txt").write_text(url + "\n", encoding="utf-8")
        return url
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", Path(str(name or "")).name).strip()
    if Path(name).suffix.lower() not in UPLOAD_TYPES:
        raise EditError(f"file type not allowed (allowed: {', '.join(sorted(UPLOAD_TYPES))})")
    try:
        raw = base64.b64decode(data_b64 or "", validate=True)
    except ValueError:
        raise EditError("upload is not valid base64") from None
    if not raw or len(raw) > MAX_UPLOAD:
        raise EditError(f"file must be between 1 byte and {MAX_UPLOAD // 1024 // 1024} MB")
    target, n = folder / name, 2
    while target.exists():  # never overwrite an earlier upload
        target = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    target.write_bytes(raw)
    return f"project_descriptions/{folder.name}/{target.name}"

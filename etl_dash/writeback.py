"""Write a correction back into an overview .docx (local folder / dev server). Same rules as apps_script/Code.gs.

An edit = {file, table_index, row, col, old, new}. It is applied only if
  - the file is a project-overview doc directly in the folder (no paths),
  - the cell is on the allow-list: an overview-table value, or a task / sector-demand column in EDITABLE,
  - the cell still contains `old` (otherwise: conflict, nothing written),
  - `new` passes the input checks (plain text, <= MAX_LEN characters).
The cell keeps its paragraph and character formatting; rows are never added or removed.
"""
import copy
import csv
import datetime as dt
import re
from pathlib import Path

import docx
from docx.oxml.ns import qn

from .sources.overview_docs import read_doc

# the name must keep matching the file name; 'Last reviewed' is stamped by the server when the form is saved
NOT_EDITABLE_FIELDS = {"name", "template_version", "last_reviewed"}
EDITABLE = {"description", "effort", "start", "deadline", "lead", "others", "status", "task_refs", "flexibility",
            "priority", "sector_lead", "project_contact", "snippet", "source", "focus_text"}
MAX_LEN = 2000
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class EditError(Exception):
    def __init__(self, message, current=None):
        super().__init__(message)
        self.current = current


def clean_value(text):
    text = CONTROL.sub("", str(text or "")).replace("\r\n", "\n").strip()
    if len(text) > MAX_LEN:
        raise EditError(f"too long (max {MAX_LEN} characters)")
    return text


def _grid_cells(tr):
    """tc elements of a row expanded to grid columns (a merged cell appears once per column it spans)."""
    out = []
    for tc in tr.iterchildren(qn("w:tc")):
        span = tc.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
        out += [tc] * (int(span.get(qn("w:val"))) if span is not None else 1)
    return out


def _text(tc):
    """Cell text with line breaks and tabs, matching what _set_text writes (and python-docx reads)."""
    parts = []
    for p in tc.iter(qn("w:p")):
        line = []
        for el in p.iter(qn("w:t"), qn("w:br"), qn("w:cr"), qn("w:tab")):
            line.append(el.text or "" if el.tag == qn("w:t") else "\t" if el.tag == qn("w:tab") else "\n")
        parts.append("".join(line))
    return "\n".join(parts).strip()


def _set_text(tc, text):
    """Replace the cell text, keeping the first paragraph's and first run's formatting."""
    paras = tc.findall(qn("w:p"))
    first = paras[0]
    for p in paras[1:]:
        tc.remove(p)
    runs = first.findall(qn("w:r"))
    rpr = runs[0].find(qn("w:rPr")) if runs else None
    for child in list(first):
        if child.tag != qn("w:pPr"):
            first.remove(child)
    r = first.makeelement(qn("w:r"), {})
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    for i, line in enumerate(text.split("\n")):
        if i:
            r.append(r.makeelement(qn("w:br"), {}))
        t = r.makeelement(qn("w:t"), {qn("xml:space"): "preserve"})
        t.text = line
        r.append(t)
    first.append(r)


def allowed(parsed, table_index, row, col):
    """-> description of the cell if editing it is allowed, else None."""
    for f, v in parsed["overview"].items():
        loc = v.get("loc")
        if loc and (loc["table_index"], loc["row"], loc["col"]) == (table_index, row, col):
            return None if f in NOT_EDITABLE_FIELDS else f"overview field '{v['label']}'"
    for t in parsed["tables"]:
        if t["index"] == table_index and t["kind"] != "tasks_unknown" and 1 <= row and col < len(t["columns"]):
            name = t["columns"][col]
            if name in EDITABLE:
                return f"{t['kind']} table column '{t['header'][col]}'"
    return None


def apply_edit(folder, edit, dry_run=False):
    """-> (description, old) on success; raises EditError (with the current value on a conflict).
    dry_run: all checks, nothing written (used to validate a whole batch before writing any of it)."""
    name = str(edit.get("file", ""))
    if not name or Path(name).name != name or not name.lower().endswith(".docx"):
        raise EditError("invalid file")
    path = Path(folder) / name
    if not path.is_file():
        raise EditError("file not found")
    try:
        table_index, row, col = int(edit["table_index"]), int(edit["row"]), int(edit["col"])
    except (KeyError, TypeError, ValueError):
        raise EditError("invalid location") from None
    what = allowed(read_doc(path), table_index, row, col)
    if not what:
        raise EditError("this cell cannot be edited")
    new, old = clean_value(edit.get("new")), str(edit.get("old") or "").strip()
    d = docx.Document(str(path))
    tables = d.element.body.findall(qn("w:tbl"))
    rows = tables[table_index].findall(qn("w:tr"))
    cells = _grid_cells(rows[row]) if row < len(rows) else []
    if col >= len(cells):
        raise EditError("cell not found")
    tc = cells[col]
    current = _text(tc)
    if current != old:
        raise EditError("the value was changed in the document in the meantime", current=current)
    if new == current or dry_run:
        return what, old
    _set_text(tc, new)
    d.save(str(path))
    return what, old


def log_edit(folder, editor, edit, result):
    """Append to edit-log.csv next to the overview docs (who, when, where, old -> new, result)."""
    log = Path(folder).parent / "edit-log.csv"
    new_file = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["time (UTC)", "editor", "file", "table", "row", "col", "old", "new", "result"])
        w.writerow([safe_cell(v) for v in (dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), editor,
                    edit.get("file"), edit.get("table_index"), edit.get("row"), edit.get("col"), edit.get("old"),
                    edit.get("new"), result)])


def read_log(path, limit=1000):
    """edit-log.csv (dev server) or the exported edit-log Google Sheet -> [{time, editor, file, where, old, new, result}],
    newest first. Columns are matched by header, so both layouts work."""
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]
    known = any(h.startswith(("time", "editor")) for h in head)
    if not known:  # the Google Sheet log has no header row: time, editor, file, where, old, new, result
        head, body = ["time", "editor", "file", "where", "old", "new", "result"], rows
    else:
        body = rows[1:]
    col = lambda *names: next((head.index(h) for h in head if any(h.startswith(n) for n in names)), None)
    idx = {k: col(*n) for k, n in dict(time=("time",), editor=("editor",), file=("file",), where=("where",), old=("old",),
                                         new=("new",), result=("result",), table=("table",), row=("row",), c=("col",)).items()}
    get = lambda r, k: (r[idx[k]] if idx[k] is not None and idx[k] < len(r) else "").lstrip("'")
    out = []
    for r in body:
        if not any(r):
            continue
        where = get(r, "where") or "/".join(x for x in (get(r, "table"), get(r, "row"), get(r, "c")) if x)
        out.append(dict(time=get(r, "time"), editor=get(r, "editor"), file=get(r, "file"), where=where,
                        old=get(r, "old"), new=get(r, "new"), result=get(r, "result")))
    return out[::-1][:limit]


def safe_cell(v):
    """Spreadsheet-safe text: a leading = + - @ would be run as a formula when the log is opened."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v

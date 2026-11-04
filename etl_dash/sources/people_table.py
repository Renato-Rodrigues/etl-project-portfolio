"""The group's own people table, 'ETL people.xlsx' (or a Google Sheet of that name) in the root of the data folder,
next to overviews/, template/ and project_descriptions/.

It is the single source of names, initials, emails and groups. Columns (row 1 = header, one person per row, the Person ID must be unique):
    Person ID | First name | Last name | Email | PIK team(s) | Sector group(s) | Topics | Active | Aliases
Multiple values are comma-separated. 'Active' = Yes / No (people who left stay, so old docs still resolve).
"""
import re
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.datavalidation import DataValidation

FILE_NAME = "ETL people.xlsx"
SHEET = "People"
COLUMNS = [("id", "Person ID"), ("first", "First name"), ("last", "Last name"), ("email", "Email"),
           ("teams", "PIK team(s)"), ("sectors", "Sector group(s)"), ("topics", "Topics"), ("active", "Active"),
           ("aliases", "Aliases")]
LISTS = ("teams", "sectors", "aliases")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ID_RX = re.compile(r"^[A-Za-z][A-Za-z.-]{1,7}$")
FORMULA = re.compile(r"^[=+\-@]")


def find(folder):
    """The people table for an overview folder: in its parent (the data-folder root), else in the folder itself."""
    folder = Path(folder)
    for place in (folder.parent, folder):
        if place.is_dir():
            hit = next((p for p in sorted(place.glob("*.xlsx")) if p.name.lower() == FILE_NAME.lower()), None)
            if hit:
                return hit
    return None


def path_for(root):
    """Where a new people table is created: the root of the data folder."""
    return find(Path(root) / "overviews") or Path(root) / FILE_NAME


def _split(v):
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def read_people_table(path):
    """-> list of people dicts (first, last, teams, topics, id/initials, email, sectors, active, aliases)."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[SHEET] if SHEET in wb.sheetnames else wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    labels = {label.lower(): key for key, label in COLUMNS}
    col = {labels[str(h).strip().lower()]: i for i, h in enumerate(rows[0] or []) if h and str(h).strip().lower() in labels}
    out = []
    for n, r in enumerate(rows[1:], start=2):
        get = lambda k: str(r[col[k]]).strip() if k in col and col[k] < len(r) and r[col[k]] is not None else ""
        if not get("first") or not get("last"):
            continue
        p = {k: (_split(get(k)) if k in LISTS else get(k)) for k, _ in COLUMNS}
        p["initials"] = p["id"]
        p["active"] = (p["active"] or "Yes").lower() not in ("no", "n", "false", "0")
        p["projects"] = []
        p["source"] = dict(tab=SHEET, row=n)
        out.append(p)
    return out


def cell_value(v):
    """Plain text for a sheet cell; a leading = + - @ would make it a formula, so it is quoted."""
    v = str(v or "").strip()
    return "'" + v if FORMULA.match(v) else v


def write_people_table(path, people):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append([label for _, label in COLUMNS])
    for c in ws[1]:
        c.font = Font(name="Arial", size=10, bold=True)
    for p in people:
        ws.append([cell_value(", ".join(p.get(k) or []) if k in LISTS else ("Yes" if p.get(k, True) else "No") if k == "active" else p.get(k, ""))
                   for k, _ in COLUMNS])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font, c.alignment = Font(name="Arial", size=10), Alignment(vertical="top", wrap_text=True)
    for letter, width in zip("ABCDEFGHI", (10, 14, 18, 30, 18, 22, 40, 8, 20)):
        ws.column_dimensions[letter].width = width
    dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("H2:H1000")
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def clean_person(raw):
    """Dashboard form -> person record (strings stripped, list columns split)."""
    p = {}
    for k, _ in COLUMNS:
        v = raw.get(k, "")
        if k in LISTS:
            p[k] = [x.strip() for x in (v if isinstance(v, list) else str(v).split(",")) if str(x).strip()]
        elif k == "active":
            p[k] = v if isinstance(v, bool) else str(v).strip().lower() not in ("no", "false", "0")
        else:
            p[k] = str(v or "").strip()
    return p


def comparable(p):
    return {k: (", ".join(p.get(k) or []) if k in LISTS else bool(p.get(k, True)) if k == "active" else str(p.get(k) or ""))
            for k, _ in COLUMNS}


def save_person(folder, person, old_id=None, old=None, seed=None):
    """Add (old_id None) or update one person in '<folder>/ETL people.xlsx'.
    old = the record as the dashboard showed it: refused if the table row changed since (concurrent edit).
    seed = people to start the table with if it does not exist yet. -> (status, message)."""
    path = path_for(folder)
    people = read_people_table(path) if path.exists() else [dict(p) for p in (seed or [])]
    person = clean_person(person)
    ids = [p["id"] for p in people]
    errs = validate_person(person, ids, current_id=old_id)
    if errs:
        return "invalid", "; ".join(errs)
    if old_id is None:
        people.append(person)
    else:
        i = next((n for n, p in enumerate(people) if p["id"].lower() == str(old_id).lower()), None)
        if i is None:
            return "conflict", f"{old_id} is no longer in the people table"
        if old is not None and comparable(people[i]) != comparable(clean_person(old)):
            return "conflict", "this person was changed in the people table in the meantime – reload the page"
        people[i] = person
    write_people_table(path, people)
    return "ok", "saved"


def validate_person(p, existing_ids, current_id=None):
    """-> list of error messages for a person record coming from the dashboard."""
    errs = []
    if not ID_RX.match(p.get("id", "")):
        errs.append("Person ID: 2–8 letters (initials), e.g. FS or ReRo")
    elif p["id"].lower() in {i.lower() for i in existing_ids} - ({current_id.lower()} if current_id else set()):
        errs.append(f"Person ID {p['id']} is already used")
    if not p.get("first") or not p.get("last"):
        errs.append("first and last name are required")
    if p.get("email") and not EMAIL.match(p["email"]):
        errs.append("email address looks invalid")
    for k, v in p.items():
        if len(str(v)) > 500:
            errs.append(f"{k}: too long")
    return errs

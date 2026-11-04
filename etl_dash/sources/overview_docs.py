"""Read project-overview .docx files (Google Docs exports), template v1 variants and v2.

Values are located by *label* (overview table) and by *caption/header* (task and demand tables), never by
position, so older and newer template versions parse with the same code. Every value keeps a locator
(table anchor, row key, column) so it can be written back later.
"""
import re
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def norm(s):
    """Lower-case, letters/digits only: 'Dead- / line' -> 'deadline'."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


# Overview-table labels -> canonical field. Ordered: first match wins (more specific patterns first).
OVERVIEW_FIELDS = [
    ("name", r"^name"),
    ("status", r"^status"),
    ("duration", r"^duration"),
    ("funding_pik", r"^funding.*total"),
    ("funding_etl", r"^funding.*whichetl"),
    ("currency", r"^currency"),
    ("funding_secured", r"^fundingsecured"),
    ("funder", r"^fundingagency"),
    ("funding", r"^funding$"),
    ("project_lead", r"^overallprojectlead"),
    ("partners", r"nonpikpartners"),
    ("responsible_team", r"responsiblepikteam"),
    ("etl_main", r"^mainetlresearcher"),
    ("etl_pi", r"^etlpi"),
    ("etl_other", r"^otheretlinvolvement"),
    ("pik_other", r"^otherinvolvedpik"),
    ("folder_consortium", r"sharedwithentireconsortium"),
    ("folder_internal", r"^linkto.*projectfolder"),
    ("mattermost", r"^mattermost"),
    ("full_title", r"^fulltitle"),
    ("website", r"^(project)?website"),
    ("proposal", r"^proposal"),
    ("strategy", r"^strategic"),
    ("synergies", r"^synerg"),
    ("remarks", r"remarks$"),
    ("last_reviewed", r"^lastreviewed"),
    ("template_version", r"^templateversion"),
]

# Task/demand table headers -> canonical column. The unlabeled first column of task tables is the task ID.
COLUMNS = [
    ("sector", r"^sector$"),
    ("sector_lead", r"^sectorlead"),
    ("task_refs", r"^(tasknr|projecttasks|taskids?)"),
    ("description", r"^description"),
    ("effort", r"^effort"),
    ("flexibility", r"^flexib"),
    ("start", r"^start"),
    ("deadline", r"^deadline"),
    ("priority", r"^priority"),
    ("project_contact", r"^projectcontact"),
    ("status", r"^status"),
    ("lead", r"lead$"),
    ("others", r"^(others|etlcontr|pikcontr)"),
    ("snippet", r"^snippet"),
    ("topic", r"^topic$"),
    ("focus_text", r"^whattheprojectdoes"),
    ("source", r"^source$"),
]

CAPTION = re.compile(r"^((etl|pik)(led|contribution)tasks|remindrequirements|sectorrequirements|projectdescriptionsnippets|focustopics)")
PLACEHOLDER = re.compile(r"^\s*([…\.]+|x+|xxx)?\s*$", re.I)


def _match(table, label):
    n = norm(label)
    return next((key for key, rx in table if re.search(rx, n)), None)


def iter_blocks(doc):
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def cell_text(tc_el, doc):
    paras = [Paragraph(p, doc) for p in tc_el.iter(qn("w:p"))]
    return "\n".join(p.text for p in paras).strip(), [h.address for p in paras for h in p.hyperlinks if h.address]


def grid_row(tr, doc):
    """Cells of a table row expanded to grid columns: a cell spanning 2 columns yields its text twice."""
    cells = []
    for tc in tr.iterchildren(qn("w:tc")):
        span_el = tc.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
        span = int(span_el.get(qn("w:val"))) if span_el is not None else 1
        text, links = cell_text(tc, doc)
        cells.extend([(text, links)] * span)
    return cells


def classify(anchor, header_norm):
    a = norm(anchor)
    if (header_norm and header_norm[0] == "topic") or a.startswith("focustopics"):
        return "focus"
    if any(h.startswith("snippet") for h in header_norm) or "snippet" in a:
        return "snippets"
    if header_norm and header_norm[0] == "sector":
        return "demands"
    if re.search(r"(etl|pik)led", a):
        return "led"
    if re.search(r"(etl|pik)contribution", a):
        return "contribution"
    if "description" in header_norm:
        return "tasks_unknown"
    return None


def read_doc(path):
    """-> dict(file, overview{field: {label, raw, links}}, extra{label: raw}, tables[...], headings[])."""
    path = Path(path)
    d = docx.Document(str(path))
    out = dict(file=path.name, overview={}, extra={}, tables=[], headings=[], checklist=[])
    anchor, section, in_overview_done, in_checklist, tbl_index = "", "", False, False, -1
    for block in iter_blocks(d):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            style = block.style.name if block.style is not None else ""
            if norm(text).startswith("stepswhensettingupanewproject"):
                in_checklist = True
                continue
            if in_checklist and text and not style.startswith("Heading"):
                if not PLACEHOLDER.match(text):  # the group's setup checklist, shown on the Information tab
                    out["checklist"].append(dict(text=text, level=_list_level(block)))
                continue
            if text and style.startswith("Heading"):
                in_checklist = False
                # 'Overview of tasks and responsibilities (Sub)' -> section 'Sub'
                out["headings"].append(text)
                m = re.search(r"\(([^)]+)\)\s*$", text)
                section = m.group(1).strip() if m and "task" in text.lower() else ""
                anchor = ""
            if CAPTION.search(norm(text)):  # only real captions; hint lines between caption and table are ignored
                anchor = text
            continue
        in_checklist = False
        tbl_index += 1  # position among the body's tables: part of the write-back locator
        rows = [grid_row(tr, d) for tr in block._tbl.iterchildren(qn("w:tr"))]
        if not any(rows):
            continue
        if not in_overview_done and max(len(r) for r in rows) <= 3 and _is_overview([r for r in rows if r]):
            _read_overview(rows, out, tbl_index)
            in_overview_done = True
            continue
        header = [t for t, _ in rows[0]]
        header_norm = [norm(h) for h in header]
        kind = classify(anchor, header_norm)
        if kind is None:
            continue
        cols = [_match(COLUMNS, h) or ("id" if i == 0 and not h.strip() else None) for i, h in enumerate(header)]
        colpos = {}
        for i, c in enumerate(cols):
            if c:
                colpos.setdefault(c, i)
        table = dict(kind=kind, section=section, anchor=anchor, header=header, columns=cols, rows=[],
                     index=tbl_index, colpos=colpos)
        for i, r in enumerate(rows[1:], start=1):
            if not r:
                continue
            values = {}
            for col, (text, links) in zip(cols, r):
                if col and col not in values:  # first column wins if two headers map to the same field
                    values[col] = text
            if all(PLACEHOLDER.match(v or "") for k, v in values.items() if k != "sector"):
                if kind != "demands":
                    continue
            table["rows"].append(dict(row_index=i, cells=values))
        out["tables"].append(table)
    return out


def _list_level(p):
    ilvl = p._p.find(qn("w:pPr") + "/" + qn("w:numPr") + "/" + qn("w:ilvl"))
    return int(ilvl.get(qn("w:val"))) if ilvl is not None else 0


def list_docs(folder):
    """Overview documents in a folder; skips Office lock files ('~$…')."""
    return sorted(p for p in Path(folder).glob("*.docx") if not p.name.startswith("~$"))


def _is_overview(rows):
    hits = sum(1 for r in rows if _match(OVERVIEW_FIELDS, r[0][0]))
    return hits >= 2


def _read_overview(rows, out, tbl_index):
    for i, r in enumerate(rows):
        if not r:
            continue
        label = r[0][0]
        if not label:
            continue
        value, links = (r[1] if len(r) > 1 else ("", []))
        field = _match(OVERVIEW_FIELDS, label)
        if field and field not in out["overview"]:
            out["overview"][field] = dict(label=label, raw=value, links=links,
                                          loc=dict(table_index=tbl_index, row=i, col=1) if len(r) > 1 else None)
        else:
            out["extra"][label] = value

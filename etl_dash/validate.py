"""Data-quality rules -> issues (feeds the dashboard's Information tab and the review report).

Severity: 'warning' = missing/wrong information someone should fix; 'info' = worth a look.
"""
from .normalize import FLEX, TEMPLATE_HINT, issue, unclear

REQUIRED = {  # field -> (template label, how-to-fill guidance)
    "duration": ("Duration", "Duration as MM/YYYY-MM/YYYY; add (tbc) if not final."),
    "project_lead": ("Overall project lead", "Overall project lead: full name (Organisation)."),
    "etl_main": ("Main ETL researcher", "Main ETL researcher(s): full names."),
    "etl_pi": ("ETL PI", "ETL PI: full name."),
    "funder": ("Funding agency, main contact person", "Funding agency, plus contact person and email."),
}
RECOMMENDED = {
    "partners": ("Other key non-PIK partners", "Key non-PIK partners: organisations (and contact names)."),
    "responsible_team": ("Mainly responsible PIK team", "Mainly responsible PIK team, e.g. ETL."),
    "folder_internal": ("Link to internal project folder", "Link to the internal project folder (Drive)."),
    "strategy": ("Strategic considerations / our role",
                 "Our role (Lead / Co-lead / Partner / Subcontractor) and strategic considerations."),
}
FUNDING_HINT = "Funding amount for PIK and the part for ETL, with currency (e.g. 500k EUR)."


def validate(data):
    issues = data["issues"]
    for p in data["projects"]:
        if p.get("excluded") == "template":
            _template(p, issues)
        if p.get("excluded"):
            continue  # outdated docs are reported in normalize (with tasks found only there)
        if p["has_overview_doc"]:
            _doc_project(p, data, issues)
    return data


def _template(p, issues):
    name = p["fields"].get("name", {}).get("raw", "").strip()
    if name and not TEMPLATE_HINT.match(name) and len(name.split()) <= 4:
        issue(issues, p["id"], "document", "warning", "template_has_data",
              f"The template document contains data of project '{name}'.",
              "Keep the template blank; the project's own overview doc is used.")


def _doc_project(p, data, issues):
    pid, fields = p["id"], p["fields"]
    for rules, severity in ((REQUIRED, "warning"), (RECOMMENDED, "info")):
        for f, (label, hint) in rules.items():
            if not fields.get(f, {}).get("raw", "").strip():
                issue(issues, pid, fields.get(f, {}).get("label", label), severity, "missing", "Missing.", hint)
    no_amount = not (p["funding"]["pik"] or p["funding"]["etl"] or p["funding"]["counted_in"])
    if no_amount:
        issue(issues, pid, "Funding", "warning", "missing" if not p["funding"]["raw"] else "unclear",
              "No funding amount found." if not p["funding"]["raw"] else f"No amount readable in '{p['funding']['raw']}'.",
              FUNDING_HINT)
    for f, v in fields.items():
        raw = v["raw"]
        if no_amount and f.startswith("funding"):
            continue  # already reported above
        if no_amount is False and f.startswith("funding") and p["funding"]["counted_in"]:
            continue  # sub-project repeating its parent's funding: reported in normalize
        if raw and unclear(raw) and not v["label"].rstrip().endswith("?"):
            issue(issues, pid, v["label"], "warning", "unclear", f"Marked as unclear: '{_short(raw)}'.",
                  "Replace tbc / ? / xxx with the confirmed value.")
    for f in ("folder_internal", "folder_consortium"):
        v = fields.get(f)
        if v and v["raw"].strip() and not p["links"]["internal" if f == "folder_internal" else "consortium"]:
            issue(issues, pid, v["label"], "info", "link_without_url", f"'{_short(v['raw'], 40)}' has no link.",
                  "Paste the folder URL (or make the text a hyperlink).")
    if p["duration"]["raw"] and not p["duration"]["end"]:
        issue(issues, pid, "Duration", "warning", "invalid", f"Cannot read start and end from '{p['duration']['raw']}'.",
              REQUIRED["duration"][1])

    tasks = [t for t in data["tasks"] if t["project_id"] == pid]
    demands = [d for d in data["demands"] if d["project_id"] == pid]
    if not p["has_demand_table"]:
        issue(issues, pid, "REMIND / sector requirements", "warning", "no_demand_table",
              "The document has no 'REMIND requirements / sector requirements' table.",
              "Copy the table from the current template and fill in what the project needs from each sector.")
    elif not demands:
        issue(issues, pid, "REMIND / sector requirements", "warning", "no_demands",
              "The sector requirements table is empty.",
              "For each sector group, describe what the project needs, with effort and deadline (or leave empty if nothing).")
    if not tasks:
        issue(issues, pid, "Tasks", "warning", "no_tasks", "No tasks listed.",
              "List ETL-led and ETL-contribution tasks with effort, deadline and lead.")
    gaps = {"effort": [], "deadline": [], "lead": []}
    for t in tasks:
        label = t["code"] or t["description"][:40]
        if t["effort"]["pm"] is None and not t["effort"]["flexible"]:
            gaps["effort"].append(label)
        if not t["deadline"] and not FLEX.match(t["deadline_raw"]):
            gaps["deadline"].append(label)
        if not t["lead"]:
            gaps["lead"].append(label)
        if t["deadline_raw"].strip() and not t["deadline"] and not FLEX.match(t["deadline_raw"]):
            issue(issues, pid, f"task {label}", "warning", "invalid", f"Deadline '{t['deadline_raw']}' is not MM/YYYY.",
                  "Write deadlines as MM/YYYY.")
        if t["deadline"] and p["start"] and p["end"] and not (p["start"] <= t["deadline"] <= p["end"]):
            issue(issues, pid, f"task {label}", "warning", "inconsistent",
                  f"Deadline {t['deadline']} is outside the project duration {p['start']}–{p['end']}.",
                  "Check the task deadline or the project duration.")
    hints = {"effort": "Effort in person-months (or 'flex').", "deadline": "Deadline as MM/YYYY.",
             "lead": "Lead: full name of the responsible person."}
    for what, labels in gaps.items():
        if labels:
            issue(issues, pid, "Tasks", "info", f"task_missing_{what}",
                  f"{len(labels)} of {len(tasks)} tasks without {what}: {'; '.join(labels)}.", hints[what])


def _short(s, n=80):
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"

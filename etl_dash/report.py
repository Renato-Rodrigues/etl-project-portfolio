"""Issues -> Markdown review report (local review only; contains project data, never committed)."""
from collections import defaultdict


def issues_markdown(data):
    projects = {p["id"]: p for p in data["projects"]}
    doc_projects = [p for p in data["projects"] if p.get("has_overview_doc") and not p.get("excluded")]
    by_project = defaultdict(list)
    for i in data["issues"]:
        by_project[i["project"]].append(i)
    warn = sum(i["severity"] == "warning" for i in data["issues"])
    lines = [
        "# Data-quality report",
        "",
        f"*Generated {data['generated_at']} · reference date {data['today']}*",
        "",
        f"- **{len(doc_projects)}** projects with an overview doc, **{len(data['projects']) - len(doc_projects)}** "
        f"excluded (template / outdated)",
        f"- **{len(data['tasks'])}** tasks, **{len(data['demands'])}** sector demands, **{len(data['people'])}** people in the people table",
        f"- **{warn}** warnings, **{len(data['issues']) - warn}** info",
        "",
    ]
    order = sorted(by_project, key=lambda k: (k is None, not projects.get(k, {}).get("has_overview_doc"), str(k)))
    for pid in order:
        p = projects.get(pid, {})
        title = "General (not project-specific)" if pid is None else pid
        tag = ""
        tag += f" · {p['status']}" if p.get("status") else ""
        tag += f" · excluded ({p['excluded']})" if p.get("excluded") else ""
        lines += [f"## {title}{tag}", "", "| | Where | Issue | How to fix |", "|---|---|---|---|"]
        for i in sorted(by_project[pid], key=lambda i: (i["severity"] != "warning", i["field"] or "")):
            icon = "⚠️" if i["severity"] == "warning" else "ℹ️"
            cells = [icon, i["field"] or "", i["message"], i.get("hint") or ""]
            lines.append("| " + " | ".join(c.replace("|", "/").replace("\n", " ") for c in cells) + " |")
        lines.append("")
    return "\n".join(lines)

import subprocess
from pathlib import Path


def codes(data, project):
    return {(i["code"], i["field"]) for i in data["issues"] if i["project"] == project}


def has(data, project, code):
    return any(c == code for c, _ in codes(data, project))


def test_missing_and_unclear(data):
    assert has(data, "BETA", "unclear")                      # '?? k€'
    assert has(data, "ALPHA-Sub", "unclear")                 # '(tbc)'
    assert not any(c == "unclear" and "folder" in f.lower() for c, f in codes(data, "ALPHA"))  # URL is not unclear
    assert ("missing", "Other key non-PIK partners") in codes(data, "BETA")


def test_people_issues(data):
    assert any("'AL'" in i["message"] and i["code"] == "person_ambiguous" for i in data["issues"] if i["project"] == "BETA") \
        or [m["name"] for m in next(p for p in data["projects"] if p["id"] == "BETA")["etl_pi"]] == ["Ada Lovelace"]
    alpha = [i for i in data["issues"] if i["project"] == "ALPHA"]
    assert any("'Kurt Unknown'" in i["message"] and i["severity"] == "info" for i in alpha)   # other PIK team
    assert not any("Someone External" in i["message"] for i in data["issues"])  # external lead not flagged
    assert not any(i["code"] == "person_ambiguous" for i in alpha)             # resolved via names in the doc


def test_demand_table_checks(data):
    assert has(data, "BETA", "no_demand_table")
    assert has(data, "ALPHA-Sub", "no_demands")
    assert not has(data, "GAMMA", "no_demands")


def test_task_checks(data):
    assert has(data, "BETA", "inconsistent")                 # deadline 01/2030 after end 12/2028
    assert not any(c == "invalid" and f.startswith("task") for c, f in codes(data, "ALPHA"))  # 'flexible' is fine


def test_no_workbook_checks(data):
    assert not any(i.get("scope") == "sheet" or "sheet" in i["code"] for i in data["issues"])

def test_template_outdated_subproject_status(data):
    assert has(data, "DELTA", "template_holds_project")
    out = [i for i in data["issues"] if i["code"] == "doc_outdated"]
    assert len(out) == 1 and "Task 4.1" in out[0]["message"] and out[0]["severity"] == "warning"
    assert has(data, "ALPHA-Sub", "subproject_repeats_parent")
    assert not has(data, "ALPHA-Sub", "unclear") or all(f != "Funding" for c, f in codes(data, "ALPHA-Sub") if c == "unclear")
    assert has(data, "ALPHA", "section_copy_differs")
    assert has(data, "DELTA", "status_unknown")


def test_every_issue_has_hint_or_is_info(data):
    for i in data["issues"]:
        assert i["severity"] in ("warning", "info")
        assert i["severity"] == "info" or i["hint"], i


def test_no_data_files_in_repo():
    """Guard for the public repo: no documents, workbooks or data dumps outside ignored folders."""
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(["git", "ls-files", "--others", "--cached", "--exclude-standard"], cwd=root,
                             capture_output=True, text=True, check=True).stdout.split()
    bad = [f for f in tracked if f.lower().endswith((".docx", ".xlsx", ".pdf", ".json", ".md")) and
           not f.startswith(("docs/", "tests/", ".claude/")) and f not in ("README.md", "apps_script/appsscript.json")]
    assert not bad, bad

import pytest

from etl_dash.normalize import (DocContext, PeopleLog, Roster, classify_doc, parse_amount, parse_duration,
                                parse_effort, parse_month, resolve_people, split_acronym, split_people, task_code,
                                unclear)


@pytest.mark.parametrize("raw, expected", [("06/28", "2028-06"), ("9/2028", "2028-09"), ("2/28", "2028-02"),
                                           ("12/2024", "2024-12"), ("flexible", None), ("13/2028", None), ("", None)])
def test_parse_month(raw, expected):
    assert parse_month(raw) == expected


def test_parse_duration_flags_unclear():
    d = parse_duration("03/2024-11/2025 (maybe?)")
    assert (d["start"], d["end"], d["tbc"]) == ("2024-03", "2025-11", True)
    assert parse_duration("11/2024-10/2028")["tbc"] is False


@pytest.mark.parametrize("raw, expected", [("1.234.567,00 € for ETL", 1234567.0), ("2,345,678 USD", 2345678.0),
                                           ("450k€ for PIK", 450000.0), ("300 k€", 300000.0), ("?? k€", None),
                                           ("decision 2026, then 40k EUR", 40000.0), ("1200 EUR", 1200.0)])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_unclear_ignores_urls():
    assert unclear("01/2027 (tbc)") and unclear("?? k€")
    assert not unclear("https://drive.example/folder?usp=sharing")


def test_parse_effort():
    assert parse_effort("10")["pm"] == 10.0
    assert parse_effort("flexible")["flexible"] is True
    assert parse_effort("")["pm"] is None


def test_split_acronym():
    assert split_acronym("ABC (Alpha Beta Collaboration)") == ("ABC", "Alpha Beta Collaboration")
    assert split_acronym("Raw stuff (RAWX)") == ("RAWX", "Raw stuff")


def test_task_codes():
    assert task_code("", "WP2, Task 2.1: Do it") == ("WP2, Task 2.1", "Do it")
    assert task_code("", "WP1: First") == ("WP1", "First")
    assert task_code("", "WP3 Case studies, Task 3.2: Apply X") == ("WP3, Task 3.2", "Case studies: Apply X")
    assert task_code("T9", "Keep") == ("T9", "Keep")


def test_split_people_tags_and_teams():
    toks = split_people("[Sub]\nIAM/CarMa (Robert X, Jess Y)\nLUT: Al Z")
    assert toks == [("Robert X", "Sub", "IAM/CarMa"), ("Jess Y", "Sub", "IAM/CarMa"), ("Al Z", "Sub", "LUT")]


@pytest.fixture
def roster():
    return Roster([dict(first="Ada", last="Lovelace", teams=[], topics=""), dict(first="Alan", last="Turing", teams=[], topics=""),
                   dict(first="Alan", last="Lee", teams=[], topics=""), dict(first="Robert", last="Salz", teams=[], topics="")])


@pytest.mark.parametrize("text, context, name, how, candidates", [
    ("Ada Lovelace", [], "Ada Lovelace", "full", []),
    ("Lovelace", [], "Ada Lovelace", "last", []),
    ("RoSa", [], "Robert Salz", "init", []),
    ("Ada", [], "Ada", None, ["Ada Lovelace"]),                 # bare first name: candidate only, never resolved
    ("Alan", [], "Alan", None, ["Alan Lee", "Alan Turing"]),
    ("AL", [], "AL", None, ["Ada Lovelace", "Alan Lee"]),       # ambiguous initials
    ("AL", ["Alan Lee"], "Alan Lee", "doc context", []),        # … unless the doc names the person in full
    ("Alex", ["Alex Outsider"], "Alex Outsider", "doc context", []),   # not in roster, but written in full in the doc
    ("Alex", ["Alexander Outsider"], "Alex", None, ["Alexander Outsider"]),       # short form: candidate only
    ("Kurt Unknown", [], "Kurt Unknown", None, []),
])
def test_resolve_people(roster, text, context, name, how, candidates):
    out = resolve_people(text, roster, DocContext(context), PeopleLog(), "P", "field")
    assert [(m["name"], m["how"], m["candidates"]) for m in out] == [(name, how, candidates)]


def test_competing_readings_stay_open():
    r = Roster([dict(first="Alex", last="Gale", teams=[], topics=""), dict(first="Gale", last="Tock", teams=[], topics="")])
    resolve = lambda t, ctx=(): resolve_people(t, r, DocContext(list(ctx)), PeopleLog(), "P", "f")[0]
    assert resolve("Gale")["candidates"] == ["Alex Gale", "Gale Tock"]               # last name vs first name
    alex = resolve("Alex", ["Alexander Brook"])                                          # roster 'Alex' vs doc 'Alexander'
    assert alex["person_id"] is None and alex["candidates"] == ["Alex Gale", "Alexander Brook"]
    assert resolve("Alex", ["Alex Gale"])["person_id"] == "alexgale"                   # doc confirms the roster


def test_group_mentions_are_teams(roster):
    assert resolve_people("Someone's group, sector teams tbd, MAgPIE team", roster, DocContext([]), PeopleLog(), "P", "f") == []


def test_people_log_reports_once_per_name(roster):
    log, issues = PeopleLog(), []
    for where in ("task A", "task B", "task A"):
        resolve_people("Kurt Unknown", roster, DocContext([]), log, "P", where)
    log.flush(issues)
    assert len(issues) == 1 and issues[0]["field"] == "task A; task B"


def test_classify_template():
    doc = lambda name: dict(file="TEMPLATE - Project overview .docx", overview={"name": {"raw": name}})
    assert classify_doc(doc("Project acronym as used in the registry (e.g. X)"), set()) == ("TEMPLATE", "template", None)
    assert classify_doc(doc("GAMMA"), {"gamma"}) == ("TEMPLATE", "template", "template_has_data")
    assert classify_doc(doc("DELTA"), set()) == ("DELTA", None, "template_holds_project")


def test_people_fields_resolved(data):
    alpha = next(p for p in data["projects"] if p["id"] == "ALPHA")
    assert [(m["name"], m["section"]) for m in alpha["etl_main"]] == [("Ada Lovelace", ""), ("Alan Turing", "Sub")]
    assert [(m["name"], m["team"], m["person_id"] is None) for m in alpha["pik_other"]] == [
        ("Grace Hopper", "IAM/CarMa", False), ("Kurt Unknown", "IAM/CarMa", True)]
    assert alpha["etl_other"] == []                       # 'sector teams tbd' is a placeholder


def test_tasks_codes_dates_and_people(data):
    t = {t["code"]: t for t in data["tasks"] if t["project_id"] == "ALPHA"}
    assert set(t) == {"T1.1", "WP2", "WP9", "T3"}
    assert t["T1.1"]["deadline"] == "2028-06"
    assert t["T1.1"]["lead"][0]["name"] == "Ada Lovelace" and t["T1.1"]["lead"][0]["uncertain"]   # 'AL?' via doc
    assert t["T1.1"]["others"][0]["name"] == "Grace Hopper"                                       # 'Grace' via doc
    assert t["WP2"]["description"] == "Second task" and t["WP2"]["deadline"] == "2028-09"
    assert t["WP9"]["effort"]["flexible"] and t["T3"]["kind"] == "etl_contribution"
    assert t["T1.1"]["loc"]["table"] == "ETL-led tasks:" and t["T1.1"]["loc"]["row_key"] == "T1.1"


def test_sub_project_parent_section_copy_and_funding(data):
    p = {p["id"]: p for p in data["projects"]}
    assert p["ALPHA-Sub"]["parent_id"] == "ALPHA" and p["ALPHA-Sub"]["name"] == "ALPHA-Sub"
    assert [(t["project_id"], t["description"]) for t in data["tasks"] if t["code"] == "S1"] == [("ALPHA-Sub", "Real sub task")]
    assert p["ALPHA-Sub"]["funding"]["etl"] is None and p["ALPHA-Sub"]["funding"]["counted_in"] == "ALPHA"
    assert p["ALPHA"]["funding"]["etl"] == 1234567.0


def test_projects_come_from_docs_only(data):
    p = {p["id"]: p for p in data["projects"]}
    assert all(q["has_overview_doc"] for q in p.values())
    assert p["ALPHA"]["end"] == "2030-11" and p["BETA"]["title"] == "Beta Long Title"
    assert p["BETA"]["status"] == "active" and p["BETA"]["status_source"] == "doc dates"
    assert p["GAMMA"]["status"] == "proposal" and p["GAMMA"]["status_source"] == "doc"
    assert p["DELTA"]["status_source"] == "default"       # future start, no Status row

def test_template_and_outdated_docs(data):
    p = {p["id"]: p for p in data["projects"]}
    assert p["DELTA"]["excluded"] is None and p["DELTA"]["source"]["file"].startswith("TEMPLATE")
    assert p["DELTA (outdated)"]["excluded"] == "outdated"
    assert [t["code"] for t in data["tasks"] if t["project_id"] == "DELTA"] == ["T2.3"]


def test_demands_and_snippets(data):
    assert [(d["project_id"], d["sector"], d["sector_lead"][0]["name"]) for d in data["demands"]] == [
        ("GAMMA", "Industry", "Grace Hopper")]
    assert data["snippets"][0]["text"] == "We model steel."

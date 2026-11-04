import pytest

from etl_dash.__main__ import load
from etl_dash.sources.people_table import find, read_people_table, save_person, write_people_table
from etl_dash.testdata import make_testdata


@pytest.fixture
def sim(tmp_path):
    return make_testdata(tmp_path / "sim")


def test_people_come_from_the_table(sim):
    data = load(sim / "overviews")
    assert data["people_source"] == "table"
    names = {p["name"] for p in data["people"]}
    assert "Mara Keller" in names and "Nadia Roth" in names
    mara = next(p for p in data["people"] if p["name"] == "Mara Keller")
    assert mara["initials"] == "MK" and mara["email"].endswith("@example.org") and "AURORA" in mara["doc_projects"]


def test_table_resolves_initials_and_aliases(sim):
    data = load(sim / "overviews")
    boreas = next(p for p in data["projects"] if p["id"] == "BOREAS")
    assert [m["name"] for m in boreas["etl_pi"]] == ["Mara Keller"]        # 'MK' is now unique (Person ID)


def test_missing_people_table_is_reported(sim):
    find(sim / "overviews").unlink()
    data = load(sim / "overviews")
    assert data["people_source"] == "none" and any(i["code"] == "no_people_table" for i in data["issues"])

def test_save_person_add_update_conflict(sim):
    folder = sim
    assert save_person(folder, dict(id="QX", first="Quinn", last="Xu", email="q@x.org"))[0] == "ok"
    assert save_person(folder, dict(id="QX", first="Q", last="Dup"))[0] == "invalid"            # ID taken
    old = next(p for p in read_people_table(find(folder / "overviews")) if p["id"] == "QX")
    assert save_person(folder, dict(old, email="new@x.org"), "QX", old)[0] == "ok"
    assert save_person(folder, dict(old, email="other@x.org"), "QX", old)[0] == "conflict"     # stale
    assert save_person(folder, dict(id="ZZ", first="A", last="B", email="not-an-email"))[0] == "invalid"


def test_formula_values_are_stored_as_text(sim, tmp_path):
    path = tmp_path / "ETL people.xlsx"
    write_people_table(path, [dict(id="EV", first="=HYPERLINK(1)", last="X", teams=[], sectors=[], aliases=[])])
    assert read_people_table(path)[0]["first"].startswith("'=")

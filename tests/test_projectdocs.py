import base64

import pytest

from etl_dash.normalize import build
from etl_dash.projectdocs import add_task_rows, create_project, save_proposal, set_overview_row
from etl_dash.sources.people_table import find, read_people_table
from etl_dash.sources.overview_docs import list_docs, read_doc
from etl_dash.testdata import make_testdata
from etl_dash.validate import validate
from etl_dash.writeback import EditError


@pytest.fixture
def sim(tmp_path):
    return make_testdata(tmp_path / "sim")


def test_create_project_is_parsed_like_any_overview(sim):
    pid, name = create_project(sim, {"name": "ZEPHYR", "status": "Proposal", "duration": "01/2027-12/2030",
                                     "funding_pik": "500k", "currency": "EUR", "etl_main": "Mara Keller"},
                               tasks=[{"kind": "led", "id": "T1", "description": "Wind scenarios", "effort": "6", "deadline": "06/2028",
                                       "lead": "Mara Keller"}],
                               demands={"Energy supply": {"description": "Offshore wind costs", "effort": "2"}})
    data = validate(build([read_doc(p) for p in list_docs(sim / "overviews")], read_people_table(find(sim / "overviews"))))
    z = next(p for p in data["projects"] if p["id"] == "ZEPHYR")
    assert z["status"] == "proposal" and z["start"] == "2027-01" and z["funding"]["pik"] == 500000
    assert [t["code"] for t in data["tasks"] if t["project_id"] == "ZEPHYR"] == ["T1"]
    assert [d["sector"] for d in data["demands"] if d["project_id"] == "ZEPHYR"] == ["Energy supply"]
    assert (sim / "project_descriptions" / "ZEPHYR").is_dir()
    with pytest.raises(EditError, match="already exists"):
        create_project(sim, {"name": "zephyr"})


@pytest.mark.parametrize("name", ["", "../evil", "a/b", "x" * 41])
def test_create_rejects_bad_ids(sim, name):
    with pytest.raises(EditError):
        create_project(sim, {"name": name})


def test_add_rows_and_proposal_on_existing_v1_doc(sim):
    doc = sim / "overviews" / "CIRRUS - Project overview.docx"
    before = len([t for t in read_doc(doc)["tables"] if t["kind"] == "led"][0]["rows"])
    add_task_rows(doc, [{"kind": "led", "id": "T9", "description": "New task", "deadline": "01/2029"}])
    led = [t for t in read_doc(doc)["tables"] if t["kind"] == "led"][0]
    assert len(led["rows"]) == before + 1 and led["rows"][-1]["cells"]["description"] == "New task"
    text = save_proposal(sim, "CIRRUS", "proposal.pdf", base64.b64encode(b"%PDF-1.4 test").decode())
    set_overview_row(doc, "proposal", text)                 # v1 doc: row is appended
    assert read_doc(doc)["overview"]["proposal"]["raw"] == "project_descriptions/CIRRUS/proposal.pdf"
    assert (sim / "project_descriptions" / "CIRRUS" / "proposal.pdf").read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("kw, msg", [(dict(name="x.exe", data_b64="QQ=="), "not allowed"),
                                     (dict(name="p.pdf", data_b64="***"), "base64"),
                                     (dict(url="http://insecure"), "https")])
def test_proposal_checks(sim, kw, msg):
    with pytest.raises(EditError, match=msg):
        save_proposal(sim, "CIRRUS", kw.get("name"), kw.get("data_b64"), kw.get("url"))

import pytest

from etl_dash.sources.overview_docs import read_doc
from etl_dash.testdata import make_testdata
from etl_dash.writeback import EditError, apply_edit, log_edit

DOC = "AURORA - Project overview.docx"


@pytest.fixture
def sim(tmp_path):
    return make_testdata(tmp_path / "sim")


def field(sim, name, f):
    return read_doc(sim / "overviews" / name)["overview"][f]


def edit_of(loc, old, new, name=DOC):
    return dict(file=name, table_index=loc["table_index"], row=loc["row"], col=loc["col"], old=old, new=new)


def test_overview_field_edit_keeps_other_cells(sim):
    before = read_doc(sim / "overviews" / DOC)
    f = before["overview"]["mattermost"]
    apply_edit(sim / "overviews", edit_of(f["loc"], f["raw"], "~new\nsecond line"))
    after = read_doc(sim / "overviews" / DOC)
    assert after["overview"]["mattermost"]["raw"] == "~new\nsecond line"
    assert {k: v["raw"] for k, v in after["overview"].items() if k != "mattermost"} == \
        {k: v["raw"] for k, v in before["overview"].items() if k != "mattermost"}
    assert after["tables"] == before["tables"]


def test_task_and_empty_demand_cells(sim):
    d = read_doc(sim / "overviews" / DOC)
    led = next(t for t in d["tables"] if t["kind"] == "led")
    apply_edit(sim / "overviews", dict(file=DOC, table_index=led["index"], row=1, col=led["colpos"]["effort"], old="12", new="14"))
    dem = next(t for t in d["tables"] if t["kind"] == "demands")
    row = next(r["row_index"] for r in dem["rows"] if r["cells"]["sector"] == "Industry")
    apply_edit(sim / "overviews", dict(file=DOC, table_index=dem["index"], row=row, col=dem["colpos"]["description"], old="", new="Steel data"))
    d2 = read_doc(sim / "overviews" / DOC)
    assert next(t for t in d2["tables"] if t["kind"] == "led")["rows"][0]["cells"]["effort"] == "14"
    assert any(r["cells"]["description"] == "Steel data" for t in d2["tables"] if t["kind"] == "demands" for r in t["rows"])


def test_conflict_returns_current_value(sim):
    f = field(sim, DOC, "mattermost")
    with pytest.raises(EditError) as e:
        apply_edit(sim / "overviews", edit_of(f["loc"], "stale", "x"))
    assert e.value.current == f["raw"]


@pytest.mark.parametrize("change, message", [
    (dict(col=0), "cannot be edited"),                      # the label column
    (dict(file="../ETL people.xlsx"), "invalid file"),
    (dict(file="nope.docx"), "not found"),
    (dict(table_index="x"), "invalid location"),
    (dict(new="x" * 2001), "too long"),
])
def test_refusals(sim, change, message):
    f = field(sim, DOC, "mattermost")
    with pytest.raises(EditError, match=message):
        apply_edit(sim / "overviews", {**edit_of(f["loc"], f["raw"], "ok"), **change})


def test_id_column_is_not_editable(sim):
    led = next(t for t in read_doc(sim / "overviews" / DOC)["tables"] if t["kind"] == "led")
    with pytest.raises(EditError, match="cannot be edited"):
        apply_edit(sim / "overviews", dict(file=DOC, table_index=led["index"], row=1, col=0, old="T1.1", new="X"))


def test_log(sim):
    log_edit(sim / "overviews", "Ed", dict(file=DOC, table_index=0, row=1, col=1, old="a", new="b"), "ok")
    assert "Ed" in (sim / "edit-log.csv").read_text(encoding="utf-8")


def test_line_breaks_round_trip(sim):
    f = field(sim, DOC, "mattermost")
    apply_edit(sim / "overviews", edit_of(f["loc"], f["raw"], "line one\nline two"))
    apply_edit(sim / "overviews", edit_of(f["loc"], "line one\nline two", "line three"))   # no false conflict
    assert field(sim, DOC, "mattermost")["raw"] == "line three"


def test_dry_run_writes_nothing(sim):
    f = field(sim, DOC, "mattermost")
    apply_edit(sim / "overviews", edit_of(f["loc"], f["raw"], "changed"), dry_run=True)
    assert field(sim, DOC, "mattermost")["raw"] == f["raw"]


@pytest.mark.parametrize("key", ["name", "template_version"])
def test_protected_fields_are_not_editable(sim, key):
    f = field(sim, DOC, key)
    with pytest.raises(EditError, match="cannot be edited"):
        apply_edit(sim / "overviews", edit_of(f["loc"], f["raw"], "OTHER"))


def test_last_reviewed_is_not_editable(sim):
    from etl_dash.projectdocs import create_project
    create_project(sim, {"name": "REV", "last_reviewed": "01/2020, Someone"})
    f = field(sim, "REV - Project overview.docx", "last_reviewed")
    with pytest.raises(EditError, match="cannot be edited"):
        apply_edit(sim / "overviews", edit_of(f["loc"], f["raw"], "12/2099, Me", name="REV - Project overview.docx"))


def test_log_escapes_formulas(sim):
    log_edit(sim / "overviews", "=cmd", dict(file=DOC, old="@x", new="+1"), "ok")
    text = (sim / "edit-log.csv").read_text(encoding="utf-8")
    assert "'=cmd" in text and "'@x" in text and "'+1" in text

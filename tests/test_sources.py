from etl_dash.sources.overview_docs import list_docs, read_doc


def doc(sources, name):
    return read_doc(sources["docs"] / name)


def test_lock_files_skipped(sources):
    assert not any(p.name.startswith("~$") for p in list_docs(sources["docs"]))
    assert len(list_docs(sources["docs"])) == 6


def test_overview_labels_all_template_versions(sources):
    old = doc(sources, "BETA - Project overview .docx")["overview"]
    assert old["funder"]["raw"] == "Funder Y"           # 'Funding agency:'
    assert old["remarks"]["raw"] == "Old template"        # 'Remarks'
    assert old["etl_main"]["raw"] == "Grace Hopper"       # typo 'coordinatoin'
    v2 = doc(sources, "GAMMA - Project overview (v2).docx")
    assert {"status", "funding_pik", "funding_etl", "currency", "template_version"} <= set(v2["overview"])
    assert not v2["extra"]


def test_tables_by_caption_with_hint_line_and_sections(sources):
    d = doc(sources, "ALPHA - Project overview.docx")
    kinds = [(t["kind"], t["section"]) for t in d["tables"]]
    assert kinds == [("led", ""), ("contribution", ""), ("led", "Sub")]
    led = d["tables"][0]
    assert led["columns"][:3] == ["id", "description", "effort"]
    assert len(led["rows"]) == 3                           # placeholder row '…' dropped


def test_merged_cell_expands_to_both_columns(sources):
    led = doc(sources, "ALPHA - Project overview.docx")["tables"][0]
    merged = next(r["cells"] for r in led["rows"] if r["cells"].get("id") == "WP9")
    assert merged["effort"] == merged["deadline"] == "flexible"
    assert merged["lead"] == "Ada Lovelace"


def test_demand_and_snippet_tables(sources):
    d = doc(sources, "GAMMA - Project overview (v2).docx")
    assert [t["kind"] for t in d["tables"]][-2:] == ["demands", "snippets"]

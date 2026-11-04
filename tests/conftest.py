"""Synthetic fixtures that reproduce every quirk seen in the real sources (no real data in this repo).

Quirks covered: v1-old labels ('Remarks', 'Funding agency:'), v1 and v2 templates, German/English money
formats, merged 'flexible' cells, placeholder rows ('…'), '[Section]' tags, 'Team (A, B)' notation, a
sub-project doc plus a stale copy of its section in the parent, a filled TEMPLATE, an '(outdated)' doc,
Word lock files, hint lines between caption and table; a people table with initials collisions (AL).
"""
import datetime as dt

import docx
import pytest

from etl_dash.sources.people_table import write_people_table

TODAY = dt.date(2026, 11, 4)


def make_doc(path, overview, sections=(), demands=None, snippets=None, hint_after_caption=False):
    d = docx.Document()
    d.add_paragraph("Project overview", style="Title")
    d.add_paragraph("Overview", style="Heading 2")
    t = d.add_table(rows=0, cols=2)
    for label, value in overview:
        c = t.add_row().cells
        c[0].text, c[1].text = label, value
    for title, led, contrib in sections:
        d.add_paragraph(title, style="Heading 3")
        for caption, header, rows in (("ETL-led tasks:", ["", "Description", "Effort [PM]", "Dead- / line", "ETL lead", "others"], led),
                                      ("ETL-contribution tasks:", ["", "Description", "Effort [PM]", "Dead- / line", "PIK lead", "ETL contr."], contrib)):
            if rows is None:
                continue
            d.add_paragraph(caption)
            if hint_after_caption:
                d.add_paragraph("First column: task ID. Effort: person-months.")
            tt = d.add_table(rows=1, cols=len(header))
            for c, h in zip(tt.rows[0].cells, header):
                c.text = h
            for r in rows:
                cells = tt.add_row().cells
                if r == "MERGED":  # 'flexible' spanning Effort + Dead-line
                    cells[0].text, cells[1].text = "WP9", "Merged-cell task"
                    m = cells[2].merge(cells[3]); m.text = "flexible"
                    cells[4].text = "Ada Lovelace"
                    continue
                for c, v in zip(cells, r):
                    c.text = v
    if demands is not None:
        d.add_paragraph("REMIND requirements / sector requirements:")
        header = ["Sector", "Description: what is needed from the sector", "Task Nr", "Effort", "Flexibility",
                  "Dead- / line", "Sector lead", "Project contact"]
        tt = d.add_table(rows=1, cols=len(header))
        for c, h in zip(tt.rows[0].cells, header):
            c.text = h
        for sector in ("Transport", "Buildings", "Industry"):
            cells = tt.add_row().cells
            for c, v in zip(cells, demands.get(sector, (sector,))):
                c.text = v
    if snippets is not None:
        d.add_paragraph("Project description snippets (optional)", style="Heading 3")
        tt = d.add_table(rows=1, cols=3)
        for c, h in zip(tt.rows[0].cells, ["Sector", "Snippet (quote from proposal)", "Source"]):
            c.text = h
        for row in snippets:
            for c, v in zip(tt.add_row().cells, row):
                c.text = v
    d.add_paragraph("Steps when setting up a new project")
    d.save(path)


@pytest.fixture(scope="session")
def sources(tmp_path_factory):
    root = tmp_path_factory.mktemp("sources")
    docs = root / "docs"
    docs.mkdir()
    # v1 (current template), German money format, merged cell, section tags, stale copy of the 'Sub' section
    make_doc(docs / "ALPHA - Project overview.docx", [
        ("Name", "ALPHA"), ("Duration", "02/2026-11/2030"), ("Funding", "1.234.567,00 € for ETL"),
        ("Overall project lead", "Ada Lovelace"), ("Other key non-PIK partners", "Uni X"),
        ("Mainly responsible PIK team (REMIND runs / overall)?", "ETL"),
        ("Main ETL researcher (operational/ / coordination)", "Ada Lovelace,\n\n[Sub] Alan Turing"),
        ("ETL PI (guidance/ supervision)", "Ada Lovelace"), ("Other ETL involvement", "sector teams tbd"),
        ("Other involved PIK teams and colleagues", "[Sub]\nIAM/CarMa (Grace Hopper, Kurt Unknown)"),
        ("Funding agency, main contact person (with email address)", "Funder Z"),
        ("Link to project folder (with proposal / description of work etc)", "https://example.org/folder"),
        ("Strategic considerations/ our role", "Lead"), ("Other remarks", "Synergies with BETA"),
    ], sections=[
        ("Short summary of tasks and responsibilities",
         [("T1.1", "First task", "10", "06/28", "AL?", "Grace"), ("", "WP2: Second task", "5", "9/2028", "Ada", ""),
          ("…", "", "", "", "", ""), "MERGED"],
         [("T3", "Contribution task", "2", "2/31", "Grace Hopper", "Ada Lovelace")]),
        ("Overview of tasks and responsibilities (Sub)", [("S1", "Stale copy", "", "", "", "")], None),
    ], hint_after_caption=True)
    # sub-project doc: repeats the parent's Name and funding
    make_doc(docs / "ALPHA-Sub - Project overview.docx", [
        ("Name", "ALPHA"), ("Duration", "02/2026-11/2030 (tbc)"), ("Funding", "1.234.567,00 € for ETL"),
        ("Main ETL researcher (operational/ / coordination)", "[Sub] Alan Turing"), ("ETL PI (guidance/ supervision)", "Ada Lovelace"),
    ], sections=[("Overview of tasks and responsibilities (Sub)", [("S1", "Real sub task", "3", "03/2027", "Alan Turing", "")], None)],
        demands={})
    # v1-old template labels, '??' funding, no demand table
    make_doc(docs / "BETA - Project overview .docx", [
        ("Name", "BETA (Beta Long Title)"), ("Duration", "11/2024-10/2028"), ("Funding", "?? k€ for PIK"),
        ("Overall project lead", "Someone External, Org"),
        ("Main ETL researcher (operational/ / coordinatoin)", "Grace Hopper"), ("ETL PI (guidance/ / supervision)", "AL"),
        ("Funding agency:", "Funder Y"), ("Remarks", "Old template"),
    ], sections=[("Short summary of tasks and responsibilities", [("T9", "Late task", "1", "01/2030", "Grace Hopper", "")], [])])
    # v2: status row, funding split, filled demand + snippet
    make_doc(docs / "GAMMA - Project overview (v2).docx", [
        ("Name", "GAMMA"), ("Status (Proposal / Active / Finished / Rejected)", "Proposal"),
        ("Duration", "02/2027-11/2029 (tbc)"), ("Funding – total for PIK", "300k"), ("Funding – of which ETL", "120k"),
        ("Currency", "EUR"), ("Overall project lead", "Grace Hopper"), ("Main ETL researcher (operational / coordination)", "Alan Turing"),
        ("ETL PI (guidance / supervision)", "Ada Lovelace"), ("Funding agency, main contact person (with email address)", "Agency X – a@b.de"),
        ("Template version", "v2"),
    ], sections=[("Short summary of tasks and responsibilities", [], [])],
        demands={"Industry": ("Industry", "Steel demand scenarios", "T2.3", "4", "Low", "06/2028", "Grace Hopper", "Alan Turing")},
        snippets=[("Industry", "We model steel.", "Proposal p. 3")])
    # the filled TEMPLATE holds the only current data of DELTA; an older '(outdated)' DELTA doc has an extra task
    make_doc(docs / "TEMPLATE - Project overview .docx", [
        ("Name", "DELTA"), ("Duration", "02/2027-11/2029 (tbc)"), ("Funding", "250 k€ for PIK, xxx of that for ETL"),
        ("Main ETL researcher (operational/ / coordination)", "Alan Turing"), ("ETL PI (guidance/ supervision)", "Ada Lovelace"),
    ], sections=[("Short summary of tasks and responsibilities", [("T2.3", "Current task", "10", "06/28", "Alan Turing", "")], [])])
    make_doc(docs / "Project overview - DELTA (outdated).docx", [("Name", "DELTA"), ("Duration", "01/2027-12/2029")],
             sections=[("Short summary of tasks and responsibilities",
                        [("T2.3", "Current task", "10", "06/28", "AT", ""), ("Task 4.1", "Dropped?", "", "9/2028", "", "")], [])])
    (docs / "~$PHA - Project overview.docx").write_bytes(b"lock")

    write_people_table(docs / "ETL people.xlsx", [
        dict(id=i, first=f, last=l, email="", teams=t, sectors=[], topics=top, active=True, aliases=al)
        for i, f, l, t, top, al in (("AL", "Ada", "Lovelace", ["ETL"], "energy system", []),
                                    ("AT", "Alan", "Turing", ["ETL"], "industry", []),
                                    ("GH", "Grace", "Hopper", ["IAM", "CarMa"], "CDR", []),
                                    ("AlLe", "Alan", "Lee", ["RSE"], "", []),
                                    ("BB", "Bob", "Builder", [], "", []))])
    return dict(docs=docs)


@pytest.fixture(scope="session")
def data(sources):
    from etl_dash.normalize import build
    from etl_dash.sources.overview_docs import list_docs, read_doc
    from etl_dash.sources.people_table import find, read_people_table
    from etl_dash.validate import validate
    people = read_people_table(find(sources["docs"]))
    return validate(build([read_doc(p) for p in list_docs(sources["docs"])], people, today=TODAY))

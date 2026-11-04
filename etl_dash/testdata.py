"""Made-up test data: a local folder that simulates the Google Drive TEST setup and exercises every feature.

    python -m etl_dash make-testdata --out ../local_drive_sim
writes  <out>/overviews/*.docx   (template v1 old/current, v2, sub-project, filled template, outdated doc)
        <out>/overviews/ETL people.xlsx   (the people table)
All names, projects, amounts and texts are invented.
"""
from pathlib import Path

import docx

V1_LED = ["", "Description", "Effort [PM]", "Dead- / line", "ETL lead", "others"]
V1_CON = ["", "Description", "Effort [PM]", "Dead- / line", "PIK lead", "ETL contr."]
V2_LED = ["", "Description", "Effort [PM]", "Start", "Dead- line", "ETL lead", "others", "Status"]
V2_CON = ["", "Description", "Effort [PM]", "Start", "Dead- line", "PIK lead", "ETL contr.", "Status"]
DEMAND = ["Sector", "Description: what is needed from the sector", "Task Nr", "Effort [PM]", "Flexibility",
          "Dead- line", "Sector lead", "Project contact", "Status"]
SECTORS = ["Transport", "Buildings", "Industry", "Energy supply", "SET", "IAM", "CDR / CarMa", "Model core", "RSE", "Other"]
CHECKLIST = ["Create a project sub-folder for proposal, budget and meeting notes",
             "Start a chat channel, with links to", ("the project folder", 1), ("this overview doc, including minutes", 1),
             "Ask IT for a project folder on the cluster before the first model runs",
             ("Keep all runs of the project in that folder", 1),
             "Never delete old run folders during the first 12-24 months"]


def _table(d, header, rows, merged=None):
    t = d.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for c, h in zip(t.rows[0].cells, header):
        c.text = h
    for r in rows:
        cells = t.add_row().cells
        for c, v in zip(cells, r):
            c.text = v
    if merged:  # (row, first col, last col, text): a cell spanning columns, e.g. 'flexible'
        r, a, b, text = merged
        m = t.rows[r].cells[a].merge(t.rows[r].cells[b])
        m.text = text
    return t


FOCUS_TOPICS = ["Macro", "Power", "Transport", "Buildings", "Industry", "CDR", "Region focus", "EU", "Sector coupling", "H2", "Finance", "Policies", "Investment/Cost"]


def write_doc(path, overview, sections=(), v2=False, demands=None, snippets=None, checklist=False, title="Project overview",
              focus=None):
    """sections: [(heading, led_rows, contrib_rows, merged)], demands: {sector: [values after the sector]}."""
    d = docx.Document()
    d.add_paragraph(title, style="Title")
    d.add_paragraph("Overview", style="Heading 2")
    t = d.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for label, value in overview:
        c = t.add_row().cells
        c[0].text, c[1].text = label, value
    for heading, led, con, merged in sections:
        d.add_paragraph(heading, style="Heading 3")
        d.add_paragraph("ETL-led tasks:")
        _table(d, V2_LED if v2 else V1_LED, led or [("",) * 6], merged)
        d.add_paragraph("ETL-contribution tasks:")
        _table(d, V2_CON if v2 else V1_CON, con or [("",) * 6])
    if demands is not None:
        d.add_paragraph("REMIND requirements / sector requirements:")
        _table(d, DEMAND, [[s, *demands.get(s, [""] * 8)] for s in SECTORS])
    if focus is not None:  # template v2: what the project does on each topic
        d.add_paragraph("Focus topics:")
        _table(d, ["Topic", "What the project does on it"], [[t, focus.get(t, "")] for t in FOCUS_TOPICS])
    if snippets is not None:
        d.add_paragraph("Project description snippets (optional)", style="Heading 3")
        _table(d, ["Sector", "Snippet (quote from proposal)", "Source"], snippets or [("", "", "")])
    if checklist:
        d.add_paragraph("Steps when setting up a new project")
        for item in CHECKLIST:
            text, level = item if isinstance(item, tuple) else (item, 0)
            d.add_paragraph(text, style="List Bullet 2" if level else "List Bullet")
    d.save(path)


def v2_overview(name, status, duration, pik, etl, lead, partners, main, pi, other, pik_other, funder, extra=()):
    return [("Name", name), ("Status (Proposal / Active / Finished / Rejected)", status), ("Duration", duration),
            ("Funding – total for PIK", pik), ("Funding – of which ETL", etl), ("Currency", "EUR"),
            ("Funding secured (Yes / Partly / No)", "Yes" if status == "Active" else "No"),
            ("Overall project lead", lead), ("Other key non-PIK partners", partners),
            ("Mainly responsible PIK team (REMIND runs / overall)?", "ETL"),
            ("Main ETL researcher (operational / coordination)", main), ("ETL PI (guidance / supervision)", pi),
            ("Other ETL involvement", other), ("Other involved PIK teams and colleagues", pik_other),
            ("Funding agency, main contact person (with email address)", funder),
            ("Link to internal project folder (with proposal / description of work etc)", "https://example.org/drive/" + name.lower()),
            ("Full title", name + " – test project"), ("Project website", "https://example.org/" + name.lower()),
            ("Mattermost channel", "~" + name.lower()), ("Strategic considerations / our role", "Lead – flagship for the group"),
            *extra, ("Template version", "v2")]


def make_testdata(out):
    out = Path(out)
    docs = out / "overviews"
    docs.mkdir(parents=True, exist_ok=True)

    # AURORA: v2, fully filled, demands in four sectors, snippets, tasks with start/status
    write_doc(docs / "AURORA - Project overview.docx", v2_overview(
        "AURORA", "Active", "01/2025-12/2028", "1.2M", "800k", "Mara Keller", "Uni Nordstadt; Grid Institute",
        "Mara Keller, Jonas Weber; [Grid] Lina Ortiz", "Mara Keller", "Tobias Brandt", "IAM: Petra Lind",
        "Science Fund – Dr. Ruth Gale, ruth.gale@example.org", [("Synergies with (other projects)", "CIRRUS")]),
        sections=[("Short summary of tasks and responsibilities",
                   [("T1.1", "Scenario design for a net-zero power system", "12", "01/2025", "06/2026", "Mara Keller", "Jonas Weber", "Done"),
                    ("T1.2", "Coupling with a detailed power-system model", "18", "03/2025", "03/2027", "Jonas Weber", "Lina Ortiz", "Ongoing"),
                    ("T2.1", "Electrified heating pathways", "8", "01/2026", "12/2027", "Tobias Brandt", "", "Planned")],
                   [("T3.4", "Contribution to the synthesis report", "3", "", "10/2028", "Petra Lind", "Mara Keller", "Planned")], None)],
        v2=True, focus={"Power": "100% renewable power systems", "Buildings": "heat electrification", "Sector coupling": "power-to-heat"},
        demands={"Energy supply": ["Hourly renewable supply curves for Europe", "T1.2", "6", "Low", "09/2026", "Jonas Weber", "Mara Keller", "Ongoing"],
                 "Buildings": ["Heat-pump uptake by building type", "T2.1", "4", "Medium", "06/2027", "Tobias Brandt", "Mara Keller", "Planned"],
                 "Transport": ["Charging-demand profiles", "T1.2", "2", "High", "12/2026", "Nina Roth", "Jonas Weber", "Planned"],
                 "IAM": ["Updated macro baseline", "T1.1", "1", "Low", "03/2026", "Petra Lind", "Mara Keller", "Done"],
                 "Model core": ["Storage equations for the coupled power model", "T1.2", "3", "Low", "12/2026", "Jonas Weber", "Mara Keller", "Planned"],
                 "RSE": ["Automated coupling workflow and tests", "T1.2", "2", "Medium", "09/2026", "Alex Moreau", "Jonas Weber", "Ongoing"]},
        snippets=[("Energy supply", "AURORA quantifies the flexibility needs of a fully renewable power system.", "Proposal p. 4"),
                  ("Buildings", "Heat electrification is analysed for twelve building archetypes.", "Proposal p. 9")])
    # AURORA-Grid: sub-project doc repeating the parent's funding (counted once)
    write_doc(docs / "AURORA-Grid - Project overview.docx", v2_overview(
        "AURORA", "Active", "06/2025-12/2027", "1.2M", "800k", "Mara Keller", "Grid Institute", "[Grid] Lina Ortiz", "Mara Keller",
        "", "", "Science Fund"),
        sections=[("Overview of tasks and responsibilities (Grid)",
                   [("G1", "Grid expansion scenarios", "6", "06/2025", "09/2026", "Lina Ortiz", "Jonas Weber", "Ongoing")], [], None)],
        v2=True, demands={"Energy supply": ["Transmission cost data", "G1", "2", "Medium", "03/2026", "Jonas Weber", "Lina Ortiz", "Planned"]})
    # BOREAS: old v1 template labels, German amount, merged 'flexible' cell, first names, no demand table
    write_doc(docs / "BOREAS - Project overview .docx", [
        ("Name", "BOREAS (Baltic Offshore Renewable Energy Assessment Study)"), ("Duration", "10/2024-09/2028"),
        ("Funding", "1.234.567,00 € for ETL"), ("Overall project lead", "Prof. Ingrid Hal, Baltic University"),
        ("Main ETL researcher (operational/ / coordinatoin)", "Jonas, Weber, Sven Okafor"),
        ("ETL PI (guidance/ / supervision)", "MK"), ("Other ETL involvement", "sector teams tbd"),
        ("Other involved PIK teams and colleagues", "Jo Pratt's group"), ("Funding agency:", "Research Programme X"),
        ("Link to project folder / (with proposal / description of work etc)", "BOREAS folder"), ("Remarks", "Offshore wind focus")],
        sections=[("Short summary of tasks and responsibilities",
                   [("", "WP1: Offshore wind potentials", "", "", "Sven", ""), ("", "WP2: Port and hydrogen hubs", "", "", "Jonas Weber", "Alex")],
                   [("T5.1", "Stakeholder workshops", "2", "2/27", "Ingrid Hal", "Sven Okafor")], (1, 2, 3, "flexible"))])
    # CIRRUS: v1 current template, sections, unclear markers, partially filled demands
    write_doc(docs / "CIRRUS - Project overview.docx", [
        ("Name", "CIRRUS"), ("Duration", "03/2026-02/2030 (tbc)"), ("Funding", "650k€ for PIK, ?? of that for ETL"),
        ("Overall project lead", "Mara Keller"), ("Other key non-PIK partners", "Clean Air Lab"),
        ("Mainly responsible PIK team (REMIND runs / overall)?", "ETL"),
        ("Main ETL researcher (operational/ / coordination)", "Nina Roth,\n\n[Hydrogen] Sven Okafor"),
        ("ETL PI (guidance/ supervision)", "Mara Keller"), ("Other ETL involvement", "Tobias Brandt"),
        ("Other involved PIK teams and colleagues", "[Hydrogen]\nCarMa (Petra Lind, Omar Haddad)"),
        ("Funding agency, main contact person (with email address)", "National Research Agency – tbc"),
        ("Link to project folder (with proposal / description of work etc)", "https://example.org/drive/cirrus?usp=sharing"),
        ("Strategic considerations/ our role", "Co-lead"), ("Other remarks", "Synergies with AURORA")],
        sections=[("Overview of tasks and responsibilities (Main)",
                   [("T1", "Air-quality co-benefits of mitigation", "9", "06/28", "Nina Roth", "Tobias Brandt"),
                    ("T2", "Industry decarbonisation pathways", "14", "9/2029", "NR?", "Lena Fischer")], [], None),
                  ("Overview of tasks and responsibilities (Hydrogen)",
                   [("H1", "Hydrogen import scenarios", "6", "12/27", "Sven Okafor", "Omar Haddad")],
                   [("H2", "Electrolyser cost review", "1", "03/31", "Omar Haddad", "Sven Okafor")], None)],
        demands={"Industry": ["Steel and cement demand projections", "T2", "5", "Medium", "03/2029", "Lena Fischer", "Nina Roth", ""],
                 "CDR / CarMa": ["DACCS cost assumptions", "H1", "", "High", "", "Petra Lind", "Sven Okafor", ""]})
    # DELTA: v2 proposal, demands
    write_doc(docs / "DELTA - Project overview.docx", v2_overview(
        "DELTA", "Proposal", "02/2027-11/2029 (tbc)", "400k", "250k", "Dr. Ana Ruiz (Delta Consortium)", "Delta Consortium",
        "Tobias Brandt", "Mara Keller", "sector teams tbd", "", "Ministry of Energy – call 2026"),
        sections=[("Short summary of tasks and responsibilities",
                   [("T1", "Building renovation scenarios", "10", "01/2027", "12/2028", "Tobias Brandt", "", "Planned")], [], None)],
        v2=True, demands={"Buildings": ["Renovation-rate scenarios", "T1", "3", "Low", "06/2027", "Tobias Brandt", "Tobias Brandt", "Planned"],
                          "Transport": ["Commuting demand by region", "T1", "1", "High", "09/2027", "Nina Roth", "Tobias Brandt", "Planned"]},
        snippets=[])
    # EMBER: finished (v1)
    write_doc(docs / "EMBER - Project overview.docx", [
        ("Name", "EMBER"), ("Duration", "01/2021-12/2024"), ("Funding", "320 k€ for PIK"), ("Overall project lead", "Mara Keller"),
        ("Main ETL researcher (operational/ / coordination)", "Jonas Weber"), ("ETL PI (guidance/ supervision)", "Mara Keller"),
        ("Funding agency, main contact person (with email address)", "Old Fund")],
        sections=[("Short summary of tasks and responsibilities", [("T1", "Coal phase-out pathways", "20", "12/24", "Jonas Weber", "")], [], None)],
        demands={})
    # filled TEMPLATE holding the only current data of FJORD, plus an outdated FJORD doc with an extra task
    write_doc(docs / "TEMPLATE - Project overview .docx", [
        ("Name", "FJORD"), ("Duration", "01/2027-06/2030 (tbc)"), ("Funding", "200 k€ for PIK, xxx of that for ETL"),
        ("Main ETL researcher (operational/ / coordination)", "Lina Ortiz"), ("ETL PI (guidance/ supervision)", "Mara Keller")],
        sections=[("Short summary of tasks and responsibilities", [("T1", "Hydropower flexibility", "6", "06/28", "Lina Ortiz", "")], [], None)],
        demands={}, checklist=True)
    write_doc(docs / "Project overview - FJORD (outdated).docx", [("Name", "FJORD"), ("Duration", "01/2027-06/2030")],
              sections=[("Short summary of tasks and responsibilities",
                         [("T1", "Hydropower flexibility", "6", "06/28", "LO", ""), ("T9", "Dropped idea", "", "", "", "")], [], None)],
              title="Project overview - template proposal")

    # the group's own people table (root of the overview folder); 'Nadia Roth' makes 'Roth' ambiguous on purpose
    from .sources.people_table import write_people_table
    table = [dict(id=i, first=f, last=l, email=f"{f.lower()}.{l.lower()}@example.org", teams=[t for t in teams.split(", ") if t],
                  sectors=sec, topics=top, active=act, aliases=al)
             for i, f, l, teams, sec, top, act, al in [
                 ("MK", "Mara", "Keller", "ETL", ["IAM"], "energy system, policy", True, []),
                 ("JW", "Jonas", "Weber", "ETL", ["Energy supply", "Model core"], "power sector, PyPSA coupling", True, []),
                 ("LO", "Lina", "Ortiz", "ETL", ["Energy supply"], "grids, hydropower", True, []),
                 ("TB", "Tobias", "Brandt", "ETL", ["Buildings"], "buildings, heat pumps", True, []),
                 ("NR", "Nina", "Roth", "ETL", ["Transport"], "transport, air quality", True, []),
                 ("SO", "Sven", "Okafor", "ETL", ["Energy supply"], "hydrogen, offshore wind", True, []),
                 ("LF", "Lena", "Fischer", "ETL", ["Industry"], "industry, steel, cement", True, []),
                 ("PL", "Petra", "Lind", "IAM", ["IAM", "CDR / CarMa"], "macro, CDR", True, []),
                 ("OH", "Omar", "Haddad", "CarMa", ["CDR / CarMa"], "CDR, DACCS", True, []),
                 ("AM", "Alex", "Moreau", "RSE", ["RSE"], "software", True, []),
                 ("NaRo", "Nadia", "Roth", "ETL", ["Transport"], "transport", True, []),
                 ("MaKe", "Max", "Kessler", "ETL", [], "", False, ["Maxi"])]]
    write_people_table(docs / "ETL people.xlsx", table)
    return out

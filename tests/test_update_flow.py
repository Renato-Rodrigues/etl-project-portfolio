"""End-to-end: local dev server (same API as the Apps Script companion) + update button + reload offer."""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from etl_dash.testdata import make_testdata

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    sim = make_testdata(tmp_path_factory.mktemp("sim"))
    test_sim = make_testdata(tmp_path_factory.mktemp("test-sim"))
    SIM["dir"], SIM["test"] = sim, test_sim
    port, out = free_port(), ROOT / "out" / f"e2e-serve-{os.getpid()}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ETL_", "GOOGLE_", "DRIVE_"))}
    env.update(PYTHONIOENCODING="utf-8", ETL_VIEWER_PASSWORD="vvvv", ETL_ADMIN_PASSWORD="aaaa", ETL_TEST_PASSWORD="tttt")
    proc = subprocess.Popen([sys.executable, "-m", "etl_dash", "serve", "--sim", str(sim), "--test-sim", str(test_sim),
                             "--out", str(out), "--port", str(port),
                             "--min-interval", "1", "--allow-short-passwords"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = f"http://127.0.0.1:{port}/"
    for _ in range(120):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.5)
    yield url
    proc.terminate()
    proc.wait(timeout=10)
    shutil.rmtree(out, ignore_errors=True)  # this test's own generated site (made-up data)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as pw:
        for kw in ({"channel": "msedge"}, {}):
            try:
                b = pw.chromium.launch(**kw)
                break
            except Exception:
                b = None
        if b is None:
            pytest.skip("no Chromium-based browser available")
        yield b
        b.close()


def test_update_button_rebuilds_and_offers_reload(server, browser):
    page = browser.new_page()
    problems = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.goto(server)
    page.evaluate("document.addEventListener('securitypolicyviolation', e => console.error('CSP ' + e.violatedDirective))")
    page.fill("#password", "vvvv")
    page.click("#login-form button")
    page.wait_for_selector("#update:not([hidden])", timeout=30000)
    page.click("#update")
    page.wait_for_selector("#toast:has-text('Update requested')", timeout=15000)
    page.wait_for_selector("#toast:has-text('New data is available')", timeout=60000)   # polled every 10 s
    assert not problems, problems


def test_update_api_rejects_wrong_key(server):
    import json
    import urllib.request
    req = urllib.request.Request(server + "api", data=json.dumps({"action": "update", "key": "nope"}).encode(), method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 403


@pytest.fixture(scope="module")
def sim_dir(server):
    return SIM["dir"]


SIM = {}


def submit(page):
    """Click Save; -> '' when the dialog closed (saved), else the dialog's error message."""
    page.click(".modal button[type=submit]")
    page.wait_for_function("""() => !document.querySelector('.modal') ||
        [...document.querySelectorAll('.modal [role=alert]')].some(e => e.textContent && e.textContent !== 'Saving…')""", timeout=20000)
    return page.evaluate("() => document.querySelector('.modal') ? [...document.querySelectorAll('.modal [role=alert], .field-error')].map(e => e.textContent).join(' | ') : ''")


def login(browser, server, password):
    page = browser.new_page()
    page.goto(server)
    page.fill("#password", password)
    page.click("#login-form button")
    page.wait_for_selector("#app:not([hidden])", timeout=30000)
    return page


def test_viewer_cannot_edit(server, browser):
    page = login(browser, server, "vvvv")
    page.evaluate("location.hash = '#/projects?p=AURORA'")
    page.wait_for_selector(".drawer", timeout=10000)
    assert page.locator("#edit-project").count() == 0 and page.locator("button[data-edit]").count() == 0
    assert page.is_hidden("#log-tab")
    page.close()


def test_admin_edit_writes_doc_log_and_change_log_tab(server, browser, sim_dir):
    import docx
    page = login(browser, server, "aaaa")
    assert page.is_visible("#log-tab")
    page.evaluate("location.hash = '#/projects?p=AURORA'")
    page.wait_for_selector("#edit-project", timeout=10000)
    page.click("#edit-project")
    page.fill(".modal tr:has(th:has-text('Mattermost channel')) input", "~aurora-team")
    page.fill(".modal input[name=editor]", "Test Editor")
    assert submit(page) == ""
    doc = docx.Document(str(sim_dir / "overviews" / "AURORA - Project overview.docx"))
    assert [r.cells[1].text for r in doc.tables[0].rows if r.cells[0].text == "Mattermost channel"] == ["~aurora-team"]
    log = (sim_dir / "edit-log.csv").read_text(encoding="utf-8")
    assert "Test Editor" in log and "~aurora-team" in log and ",ok" in log
    page.wait_for_selector("#toast:has-text('New data is available')", timeout=60000)
    page.click("#reload")
    page.fill("#password", "aaaa")
    page.click("#login-form button")
    page.wait_for_selector("#app:not([hidden])", timeout=30000)
    page.evaluate("location.hash = '#/log'")
    page.wait_for_selector("#view:has-text('~aurora-team')", timeout=10000)
    assert "Test Editor" in page.inner_text("#view")
    page.close()

def test_create_project_with_proposal_then_edit(server, browser, sim_dir, tmp_path):
    from etl_dash.sources.overview_docs import read_doc
    pdf = tmp_path / "zephyr proposal.pdf"
    pdf.write_bytes(b"%PDF-1.4 made-up proposal")
    page = login(browser, server, "aaaa")
    page.evaluate("location.hash = '#/projects'")
    page.click("#new-project")
    page.fill(".modal input[name=o_name]", "ZEPHYR")
    page.select_option(".modal select[name=o_status]", "Proposal")
    page.fill(".modal input[name=o_duration]", "01/2027-12/2030")
    page.fill(".modal [name=o_etl_main]", "Mara Keller")
    page.click("[data-add-task=led]")
    page.fill(".modal input[name=n0_id]", "T1")
    page.fill(".modal [name=n0_description]", "Wind scenarios")
    page.fill(".modal input[name=n0_deadline]", "06/2028")
    page.fill(".modal [aria-label^='Model core Description']", "New offshore wind module")
    page.set_input_files(".modal input[name=proposal_file]", str(pdf))
    page.fill(".modal input[name=editor]", "Test Editor")
    page.click(".modal button[type=submit]")
    page.wait_for_selector("#toast:has-text('Project created')", timeout=15000)
    doc = read_doc(sim_dir / "overviews" / "ZEPHYR - Project overview.docx")
    assert doc["overview"]["duration"]["raw"] == "01/2027-12/2030"
    import datetime as dt
    assert doc["overview"]["last_reviewed"]["raw"] == f"{dt.date.today():%m/%Y}, Test Editor"     # stamped on create
    assert doc["overview"]["proposal"]["raw"] == "project_descriptions/ZEPHYR/zephyr proposal.pdf"
    assert (sim_dir / "project_descriptions" / "ZEPHYR" / "zephyr proposal.pdf").read_bytes().startswith(b"%PDF")
    assert any(r["cells"].get("description") == "New offshore wind module" for t in doc["tables"] if t["kind"] == "demands" for r in t["rows"])

    page.wait_for_selector("#toast:has-text('New data is available')", timeout=60000)   # rebuilt with ZEPHYR
    page.goto(server + "#/projects?p=ZEPHYR&scope=all")
    page.reload()
    page.fill("#password", "aaaa")
    page.click("#login-form button")
    page.wait_for_selector("#edit-project", timeout=30000)
    page.click("#edit-project")
    page.fill(".modal tr:has(th:has-text('Mattermost channel')) input", "~zephyr")
    page.fill(".modal input[name=editor]", "Test Editor")
    assert submit(page) == ""
    assert read_doc(sim_dir / "overviews" / "ZEPHYR - Project overview.docx")["overview"]["mattermost"]["raw"] == "~zephyr"
    assert page.locator(".modal").count() == 0
    assert read_doc(sim_dir / "overviews" / "ZEPHYR - Project overview.docx")["overview"]["last_reviewed"]["raw"].endswith(", Test Editor")
    page.close()


def test_test_password_edits_only_the_test_folder(server, browser, sim_dir):
    from etl_dash.sources.overview_docs import read_doc
    page = login(browser, server, "tttt")
    assert page.is_visible("#mode-banner")
    page.evaluate("location.hash = '#/projects?p=AURORA'")
    page.wait_for_selector("#edit-project", timeout=10000)
    page.click("#edit-project")
    page.fill(".modal tr:has(th:has-text('Mattermost channel')) input", "edited in test mode")
    page.fill(".modal input[name=editor]", "Tester")
    assert submit(page) == ""
    mm = lambda d: read_doc(d / "overviews" / "AURORA - Project overview.docx")["overview"]["mattermost"]["raw"]
    assert mm(SIM["test"]) == "edited in test mode" and mm(sim_dir) != "edited in test mode"
    page.close()

def test_people_tab_add_and_edit(server, browser, sim_dir):
    from etl_dash.sources.people_table import find, read_people_table
    page = login(browser, server, "aaaa")
    page.evaluate("location.hash = '#/people'")
    page.wait_for_selector("#add-person", timeout=10000)
    assert "Mara Keller" in page.inner_text("#view")
    page.click("#add-person")
    for k, v in (("id", "QX"), ("first", "Quinn"), ("last", "Xu"), ("email", "quinn.xu@example.org"), ("teams", "ETL")):
        page.fill(f".modal input[name={k}]", v)
    page.check(".modal input[name=sector][value='Model core']")
    page.check(".modal input[name=sector][value='RSE']")
    page.fill(".modal input[name=editor]", "Test Editor")
    assert submit(page) == ""
    quinn = next(p for p in read_people_table(find(sim_dir / "overviews")) if p["id"] == "QX")
    assert find(sim_dir / "overviews").parent == sim_dir                     # the table lives in the root
    assert quinn["sectors"] == ["Model core", "RSE"] and quinn["email"] == "quinn.xu@example.org"
    page.click("button[data-person][aria-label='Edit Mara Keller']")
    page.fill(".modal input[name=email]", "mara@example.org")
    page.fill(".modal input[name=editor]", "Test Editor")
    assert submit(page) == ""
    assert next(p for p in read_people_table(find(sim_dir / "overviews")) if p["id"] == "MK")["email"] == "mara@example.org"
    page.close()


def test_viewer_sees_people_without_edit(server, browser):
    page = login(browser, server, "vvvv")
    page.evaluate("location.hash = '#/people'")
    page.wait_for_selector("text=Mara Keller", timeout=10000)
    assert page.locator("#add-person").count() == 0 and page.locator("button[data-person]").count() == 0
    page.close()

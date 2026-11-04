"""Browser smoke test: the built page runs under its own CSP, all logins work, every view renders cleanly.

Uses Playwright with Edge (Windows dev machines) or Chromium (CI: `playwright install chromium`); skipped if neither.
"""
import pytest

from etl_dash.build import build_site
from etl_dash.crypto import TEST_MIN_PASSWORD_LENGTH

playwright = pytest.importorskip("playwright.sync_api")
VIEWS = ["#/overview", "#/demands", "#/demands?layer=focus&scope=all", "#/timeline?scope=all",
         "#/timeline?group=Industry", "#/projects?scope=all", "#/projects?p=ALPHA", "#/info?sev=all"]


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


@pytest.fixture(scope="module")
def page_url(data, tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    test_data = dict(data, mode_label="TEST DATA – made-up", mode_badge="test data",
                     projects=[p for p in data["projects"] if p["id"] != "BETA"])
    build_site(data, {"viewer": "vvvv", "admin": "aaaa", "test": "tttt"}, out, test=(test_data, {}),
               min_length=TEST_MIN_PASSWORD_LENGTH)
    return (out / "index.html").as_uri()


def login(browser, url, password, scheme="light"):
    page = browser.new_page(color_scheme=scheme, viewport={"width": 1280, "height": 900})
    problems = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(url)
    page.evaluate("document.addEventListener('securitypolicyviolation', e => console.error('CSP ' + e.violatedDirective))")
    page.fill("#password", password)
    page.click("#login-form button")
    return page, problems


def test_wrong_password(browser, page_url):
    page, problems = login(browser, page_url, "nope")
    page.wait_for_selector("#login-error:has-text('Wrong password')", timeout=20000)
    assert page.get_attribute("#password", "aria-invalid") == "true" and page.is_hidden("#app")
    assert not problems


@pytest.mark.parametrize("password, badge, banner", [("vvvv", "viewer", False), ("aaaa", "admin", False), ("tttt", "test data", True)])
def test_roles_and_all_views(browser, page_url, password, badge, banner):
    for scheme in ("light", "dark"):
        page, problems = login(browser, page_url, password, scheme)
        page.wait_for_selector("#app:not([hidden])", timeout=20000)
        assert page.text_content("#role") == badge
        assert page.is_visible("#mode-banner") is banner
        for view in VIEWS:
            page.evaluate(f"location.hash = {view!r}")
            page.wait_for_timeout(150)
            assert page.inner_text("#view").strip(), view

        assert not problems, problems
        page.close()


def test_test_mode_shows_its_own_data(browser, page_url):
    page, _ = login(browser, page_url, "tttt")
    page.wait_for_selector("#app:not([hidden])", timeout=20000)
    page.evaluate("location.hash = '#/projects?scope=all'")
    page.wait_for_timeout(200)
    assert "BETA" not in page.inner_text("#list")
    page.close()


def test_deep_link_survives_login(browser, page_url):
    page = browser.new_page()
    page.goto(page_url + "#/projects?p=ALPHA")
    page.fill("#password", "vvvv")
    page.click("#login-form button")
    page.wait_for_selector(".drawer", timeout=20000)
    assert "ALPHA" in page.inner_text("#drawer-title")
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    assert page.is_hidden("#drawer")
    page.close()

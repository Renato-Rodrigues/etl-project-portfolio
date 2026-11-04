import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from etl_dash.build import assemble, build_site, csp_hash, font_css, leak_scan, sensitive_strings, static_sources
from etl_dash.crypto import TEST_MIN_PASSWORD_LENGTH, decrypt, encrypt

VIEWER, ADMIN, TEST = "viewer-correct-horse-1", "admin-battery-staple-2", "tst1"
ROOT = Path(__file__).resolve().parents[1]
FAST = dict(iterations=1000, min_length=TEST_MIN_PASSWORD_LENGTH)


@pytest.fixture(scope="module")
def payload():
    return encrypt({"projects": [{"name": "Secret Project"}]}, {"edit_key": "k"}, VIEWER, ADMIN,
                   test=({"projects": [{"name": "Demo"}]}, {"edit_key": "t"}, TEST), **FAST)


def test_roles_admin_block_and_test_mode(payload):
    assert decrypt(payload, VIEWER) == ("viewer", {"projects": [{"name": "Secret Project"}]}, None)
    assert decrypt(payload, ADMIN)[0::2] == ("admin", {"edit_key": "k"})
    assert decrypt(payload, TEST) == ("test", {"projects": [{"name": "Demo"}]}, {"edit_key": "t"})


def test_wraps_are_unlabeled_and_shape_hides_test_mode():
    with_test = encrypt({}, {}, VIEWER, ADMIN, test=({}, {}, TEST), **FAST)
    without = encrypt({}, {}, VIEWER, ADMIN, **FAST)
    assert len(with_test["keys"]) == len(without["keys"]) == 3
    assert all(set(w) == {"iv", "ct"} for w in with_test["keys"] + without["keys"])   # no role label to swap
    assert set(with_test["extra"]) == set(without["extra"]) == {"data", "admin"}


def test_role_is_bound_to_the_wrap(payload):
    swapped = json.loads(json.dumps(payload))
    swapped["data"], swapped["extra"]["data"] = swapped["extra"]["data"], swapped["data"]
    with pytest.raises(InvalidTag):  # test keys cannot open the real data box (different AAD)
        decrypt(swapped, TEST)


def test_wrong_password_and_tampering(payload):
    with pytest.raises(ValueError):
        decrypt(payload, "not-the-password")
    bad = json.loads(json.dumps(payload))
    ct = bytearray(base64.b64decode(bad["data"]["ct"]))
    ct[0] ^= 1
    bad["data"]["ct"] = base64.b64encode(bytes(ct)).decode()
    with pytest.raises(InvalidTag):
        decrypt(bad, VIEWER)


@pytest.mark.parametrize("viewer, admin, kw", [("short-but-not-20", ADMIN, {}), (VIEWER, VIEWER, {}),
                                               ("abc", "abcd", {"min_length": TEST_MIN_PASSWORD_LENGTH})])
def test_password_policy(viewer, admin, kw):
    with pytest.raises(ValueError):
        encrypt({}, {}, viewer, admin, iterations=1000, **kw)


def test_short_passwords_only_by_explicit_opt_in():
    assert decrypt(encrypt({}, {}, "vvvv", "aaaa", **FAST), "aaaa")[0] == "admin"


def test_unicode_passwords_are_normalized():
    composed, decomposed = "pässwört-ünïcode-2026", "pässwört-ünïcode-2026"
    assert decrypt(encrypt({}, {}, composed, ADMIN, iterations=1000), decomposed)[0] == "viewer"


def test_default_kdf_strength():
    assert encrypt({}, {}, VIEWER, ADMIN)["kdf"]["iterations"] >= 600_000


def test_single_file_with_csp(payload):
    html = assemble(payload)
    src = static_sources()
    js = src["crypto.js"] + "\n" + src["app.js"]
    assert csp_hash(js) in html and csp_hash(font_css() + src["app.css"]) in html
    assert "default-src 'none'" in html and 'name="robots" content="noindex' in html
    assert not re.search(r"""(src|href)=["']?https?:""", html)        # nothing loaded from outside
    assert "Secret Project" not in html and "Demo" not in html


@pytest.fixture(scope="module")
def site(data, tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    build_site(data, {"viewer": VIEWER, "admin": ADMIN, "test": TEST}, out,
               test=(dict(data, mode_label="TEST DATA", mode_badge="test data"), {}), min_length=TEST_MIN_PASSWORD_LENGTH)
    return out


def test_build_outputs_and_leak_scan(data, site):
    assert {p.name for p in site.iterdir()} == {"index.html", "version.txt", "robots.txt"}
    assert sensitive_strings(data)                                   # the scan has something to look for
    assert leak_scan(data, list(site.iterdir())) == []


@pytest.mark.parametrize("snippet", ["<p>Steel demand scenarios</p>", "<td>ALPHA</td>", "x=1234567", "Steel &amp; more",
                                     "Alan Turing", "Funder Y"])
def test_leak_scan_detects_plaintext(data, tmp_path, snippet):
    leaky = tmp_path / "leaky.html"
    leaky.write_text(snippet, encoding="utf-8")
    assert leak_scan(dict(data, extra={"amount": 1234567, "t": "Steel & more"}), [leaky])


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("password, expected", [(VIEWER, "viewer"), (ADMIN, "admin"), (TEST, "test"), ("wrong-password-123", None)])
def test_browser_code_decrypts_python_output(site, data, password, expected):
    out = subprocess.run(["node", str(ROOT / "tests" / "decrypt_check.mjs"), str(site / "index.html"), password],
                         capture_output=True, text=True, check=True, timeout=60).stdout
    result = json.loads(out)
    if expected is None:
        assert result == {"error": "wrong password"}
    else:
        assert result == {"role": expected, "projects": len(data["projects"]), "admin": expected != "viewer"}


def run_cli(args, env_extra, tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ETL_")}
    env.update(env_extra, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "etl_dash", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)


def test_cli_build_with_test_mode_prints_no_data(sources, data, tmp_path):
    testdata = tmp_path / "sim"
    assert run_cli(["make-testdata", "--out", str(testdata)], {}, tmp_path).returncode == 0
    run = run_cli(["build", "--docs", str(sources["docs"]), "--out", str(tmp_path / "dist"),
                   "--test-docs", str(testdata / "overviews"),
                   "--allow-short-passwords"], {"ETL_VIEWER_PASSWORD": "vvvv", "ETL_ADMIN_PASSWORD": "aaaa", "ETL_TEST_PASSWORD": "tttt"}, tmp_path)
    assert run.returncode == 0, run.stderr
    assert "leak-scan=clean" in run.stdout and "test-mode=on" in run.stdout
    log = run.stdout + run.stderr
    assert not [s for s in sensitive_strings(data) if len(s) >= 6 and s in log]


@pytest.mark.parametrize("env, extra", [({}, []),                                                       # no passwords
                                        ({"ETL_VIEWER_PASSWORD": "vvvv", "ETL_ADMIN_PASSWORD": "aaaa"}, []),   # too short
                                        ({"ETL_VIEWER_PASSWORD": VIEWER, "ETL_ADMIN_PASSWORD": ADMIN, "ETL_TEST_PASSWORD": "tttt"}, [])])  # test pw without test data
def test_cli_build_refusals(sources, tmp_path, env, extra):
    run = run_cli(["build", "--docs", str(sources["docs"]), "--out", str(tmp_path / "dist"), *extra],
                  env, tmp_path)
    assert run.returncode != 0 and not (tmp_path / "dist" / "index.html").exists()

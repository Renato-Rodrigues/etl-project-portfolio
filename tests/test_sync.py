import os
import subprocess
import sys
from pathlib import Path

import pytest

from etl_dash.sources import drive
from etl_dash.testdata import make_testdata

ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, body=None, content=b""):
        self.body, self.content = body, content

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeDrive:
    """Minimal Drive v3 API: a folder with two pages of files: a Google Doc, a .docx, a PDF and the 'ETL people' sheet."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        if url == drive.API:
            if not params.get("pageToken"):
                return FakeResponse({"files": [dict(id="d1", name="ALPHA - Project overview", mimeType=drive.GDOC, modifiedTime="t1"),
                                               dict(id="p1", name="notes.pdf", mimeType="application/pdf", modifiedTime="t1"),
                                               dict(id="s1", name="ETL people", mimeType=drive.GSHEET, modifiedTime="t3")],
                                     "nextPageToken": "page2"})
            return FakeResponse({"files": [dict(id="d2", name="BETA/old - Project overview.docx", mimeType=drive.DOCX, modifiedTime="t2")]})
        if url.endswith("/export"):
            return FakeResponse(content=b"exported:" + params["mimeType"].encode())
        return FakeResponse(content=b"media")


def test_fetch_drive_exports_native_and_downloads_office_files(tmp_path):
    http = FakeDrive()
    m = drive.fetch(tmp_path, env={"ETL_SOURCE": "oauth", "DRIVE_FOLDER_ID": "F"}, http=http)
    assert [d["file"] for d in m["docs"]] == ["ALPHA - Project overview.docx", "BETA_old - Project overview.docx"]
    assert (tmp_path / "overviews" / "ALPHA - Project overview.docx").read_bytes() == b"exported:" + drive.DOCX.encode()
    assert (tmp_path / "overviews" / "BETA_old - Project overview.docx").read_bytes() == b"media"
    assert (tmp_path / "ETL people.xlsx").read_bytes() == b"exported:" + drive.XLSX.encode()
    assert m["docs"][0]["url"] == "https://docs.google.com/document/d/d1/edit" and m["docs"][0]["native"]
    assert not m["docs"][1]["native"] and m["people"]["native"]
    listing = [p for u, p in http.calls if u == drive.API]
    assert len(listing) == 2 and "trashed=false" in listing[0]["q"] and listing[0]["supportsAllDrives"] == "true"


def test_changed_detects_edits():
    a = {"docs": [{"file": "x", "id": "1", "modified": "t1"}], "people": {"file": "p", "id": "p", "modified": "t"}}
    b = {"docs": [{"file": "x", "id": "1", "modified": "t2"}], "people": {"file": "p", "id": "p", "modified": "t"}}
    assert drive.changed(a, None) and drive.changed(b, a) and not drive.changed(a, a)


def test_unknown_source_mode(tmp_path):
    with pytest.raises(ValueError):
        drive.fetch(tmp_path, env={"ETL_SOURCE": "ftp"})


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    return make_testdata(tmp_path_factory.mktemp("sim"))


def test_fetch_local_copies_the_simulated_drive(sim, tmp_path):
    m = drive.fetch(tmp_path, env={"ETL_SOURCE": "local", "ETL_LOCAL_DIR": str(sim)})
    assert m["source"] == "local" and len(m["docs"]) == 8 and (tmp_path / "ETL people.xlsx").exists()


def test_sync_cli_local(sim, tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ETL_", "GOOGLE_", "DRIVE_"))}
    env.update(PYTHONIOENCODING="utf-8", ETL_SOURCE="local", ETL_LOCAL_DIR=str(sim),
               ETL_VIEWER_PASSWORD="vvvv", ETL_ADMIN_PASSWORD="aaaa", ETL_TEST_PASSWORD="tttt")
    run = subprocess.run([sys.executable, "-m", "etl_dash", "sync", "--out", str(tmp_path / "dist"), "--allow-short-passwords"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert run.returncode == 0, run.stderr
    assert "fetched 8 docs" in run.stdout and "test-mode=on" in run.stdout and "leak-scan=clean" in run.stdout
    assert (tmp_path / "dist" / "index.html").exists()


class FakeNestedDrive(FakeDrive):
    """Data-folder root with 'ETL people' and an 'overviews' subfolder (plus template/, which is ignored)."""

    def get(self, url, params=None):
        if url == drive.API and "'R' in parents" in params["q"]:
            return FakeResponse({"files": [dict(id="s1", name="ETL people", mimeType=drive.GSHEET, modifiedTime="t3"),
                                           dict(id="O", name="overviews", mimeType=drive.FOLDER, modifiedTime="t0"),
                                           dict(id="T", name="template", mimeType=drive.FOLDER, modifiedTime="t0"),
                                           dict(id="x", name="stray doc", mimeType=drive.GDOC, modifiedTime="t0")]})
        if url == drive.API and "'O' in parents" in params["q"]:
            return FakeResponse({"files": [dict(id="d1", name="ALPHA - Project overview", mimeType=drive.GDOC, modifiedTime="t1")]})
        return super().get(url, params)


def test_fetch_drive_root_layout(tmp_path):
    m = drive.fetch(tmp_path, env={"ETL_SOURCE": "oauth", "DRIVE_FOLDER_ID": "R"}, http=FakeNestedDrive())
    assert [d["file"] for d in m["docs"]] == ["ALPHA - Project overview.docx"]        # only docs from overviews/
    assert (tmp_path / "ETL people.xlsx").exists() and m["people"]["id"] == "s1"

"""Fetch the overview folder (docs + people table) into a temporary folder, from one of three sources:

  local            ETL_LOCAL_DIR = folder with overviews/ (docs + 'ETL people.xlsx'), e.g. the simulation folder
  oauth            runs as a Google user: GOOGLE_OAUTH_CLIENT_JSON + GOOGLE_OAUTH_REFRESH_TOKEN
  service_account  GOOGLE_SA_KEY (service-account JSON key)

Drive settings: DRIVE_FOLDER_ID (the overview folder: overview docs + the 'ETL people' table),
DRIVE_EDIT_LOG_ID (optional: the companion's edit-log sheet). Google Docs/Sheets are exported as .docx/.xlsx/.csv;
uploaded Office files are downloaded as they are. Read-only scope.
Returns a manifest (file ids, names, modified times, links) used for change detection and links in the dashboard.
"""
import json
import os
import re
import shutil
from pathlib import Path

API = "https://www.googleapis.com/drive/v3/files"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GDOC, GSHEET = "application/vnd.google-apps.document", "application/vnd.google-apps.spreadsheet"
EXPORT = {GDOC: DOCX, GSHEET: XLSX}


def safe_name(name, ext):
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "unnamed"
    return name if name.lower().endswith(ext) else name + ext


def doc_url(file_id, mime):
    if mime in (GDOC, DOCX):
        return f"https://docs.google.com/document/d/{file_id}/edit"
    if mime in (GSHEET, XLSX):
        return f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
    return f"https://drive.google.com/file/d/{file_id}/view"


def session(env=os.environ):
    """Authorized requests session for the configured Google mode."""
    from google.auth.transport.requests import AuthorizedSession  # optional dependency: pip install .[drive]

    mode = env.get("ETL_SOURCE", "local")
    if mode == "service_account":
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(json.loads(env["GOOGLE_SA_KEY"]), scopes=SCOPES)
    elif mode == "oauth":
        from google.oauth2.credentials import Credentials
        client = json.loads(env["GOOGLE_OAUTH_CLIENT_JSON"])
        client = client.get("installed") or client.get("web") or client
        creds = Credentials(None, refresh_token=env["GOOGLE_OAUTH_REFRESH_TOKEN"], token_uri=client["token_uri"],
                            client_id=client["client_id"], client_secret=client["client_secret"], scopes=SCOPES)
    else:
        raise ValueError(f"no Google session for ETL_SOURCE={mode!r}")
    return AuthorizedSession(creds)


def list_folder(http, folder_id):
    files, token = [], None
    while True:
        params = {"q": f"'{folder_id}' in parents and trashed=false", "pageSize": 200, "pageToken": token,
                  "fields": "nextPageToken,files(id,name,mimeType,modifiedTime)",
                  "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
        r = http.get(API, params={k: v for k, v in params.items() if v})
        r.raise_for_status()
        body = r.json()
        files += body.get("files", [])
        token = body.get("nextPageToken")
        if not token:
            return files


def download(http, meta, dest):
    """Google-native files are exported, Office files downloaded as they are."""
    if meta["mimeType"] in EXPORT:
        r = http.get(f"{API}/{meta['id']}/export", params={"mimeType": EXPORT[meta["mimeType"]]})
    else:
        r = http.get(f"{API}/{meta['id']}", params={"alt": "media", "supportsAllDrives": "true"})
    r.raise_for_status()
    dest.write_bytes(r.content)


def fetch_log(http, log_id, out):
    """The companion's edit-log Google Sheet, exported as CSV (optional)."""
    if log_id:
        r = http.get(f"{API}/{log_id}/export", params={"mimeType": "text/csv"})
        r.raise_for_status()
        (out / "edit-log.csv").write_bytes(r.content)


def fetch_drive(http, folder_id, out):
    docs = out / "overviews"
    docs.mkdir(parents=True, exist_ok=True)
    manifest = {"source": "drive", "docs": [], "people": None}
    for f in list_folder(http, folder_id):
        stem = re.sub(r"\.xlsx$", "", f["name"], flags=re.I).strip().lower()
        if f["mimeType"] in (GSHEET, XLSX) and stem == "etl people":
            download(http, f, docs / "ETL people.xlsx")   # the people table, in the root of the overview folder
            manifest["people"] = dict(file="ETL people.xlsx", id=f["id"], modified=f["modifiedTime"],
                                      native=f["mimeType"] == GSHEET, url=doc_url(f["id"], f["mimeType"]))
            continue
        if f["mimeType"] not in (GDOC, DOCX):
            continue  # subfolders (e.g. _archive), PDFs, … are ignored
        name = safe_name(f["name"], ".docx")
        download(http, f, docs / name)
        manifest["docs"].append(dict(file=name, id=f["id"], modified=f["modifiedTime"], native=f["mimeType"] == GDOC,
                                     url=doc_url(f["id"], f["mimeType"])))
    return manifest


def fetch_local(src, out):
    """Copy a local folder laid out like the Drive setup (overviews/ with the docs and the people table)."""
    src = Path(src)
    shutil.copytree(src / "overviews", out / "overviews", ignore=shutil.ignore_patterns("~$*"))
    if (src / "edit-log.csv").is_file():  # changes made through the website (dev server)
        shutil.copy2(src / "edit-log.csv", out / "edit-log.csv")
    docs = [dict(file=p.name, id=None, modified=None, native=False, url=None) for p in sorted((out / "overviews").glob("*.docx"))]
    return {"source": "local", "docs": docs, "people": None}


def fetch(out, env=os.environ, http=None):
    """Fetch into `out` (a fresh temp dir) according to ETL_SOURCE; returns the manifest."""
    out = Path(out)
    mode = env.get("ETL_SOURCE", "local")
    if mode == "local":
        return fetch_local(env["ETL_LOCAL_DIR"], out)
    if mode not in ("oauth", "service_account"):
        raise ValueError(f"ETL_SOURCE must be local, oauth or service_account, not {mode!r}")
    http = http or session(env)
    manifest = fetch_drive(http, env["DRIVE_FOLDER_ID"], out)
    fetch_log(http, env.get("DRIVE_EDIT_LOG_ID"), out)
    return manifest


def changed(manifest, previous):
    """True if any file was added, removed or modified since the previous manifest."""
    sig = lambda m: sorted((d.get("id") or d.get("file"), d.get("modified")) for d in [*m.get("docs", []), m.get("people") or {}] if d)
    return previous is None or sig(manifest) != sig(previous)

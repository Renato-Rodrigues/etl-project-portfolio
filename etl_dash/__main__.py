"""CLI: parse | build | sync | serve | make-testdata. Prints only counts (CI logs are public); values go to files.

Passwords come from the environment only: ETL_VIEWER_PASSWORD, ETL_ADMIN_PASSWORD and, for the hidden test mode,
ETL_TEST_PASSWORD (requires --test-docs).
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from .build import SITE_FILES, build_site, leak_scan
from .crypto import MIN_PASSWORD_LENGTH, TEST_MIN_PASSWORD_LENGTH
from .normalize import build
from .report import issues_markdown
from .sources.overview_docs import list_docs, read_doc
from .sources.people_table import find as find_people, read_people_table
from .testdata import make_testdata
from .validate import validate

REPO = Path(__file__).resolve().parent.parent


def notice(level, message):
    """A data-free message; on GitHub Actions as a warning/error annotation (readable in the run summary)."""
    print(message, file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level} title=ETL dashboard::" + " ".join(message.splitlines()), flush=True)


def fail(message):
    """Stop with a data-free message; on GitHub Actions also as an error annotation (readable in the run summary)."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("::error title=ETL dashboard::" + " ".join(message.splitlines()), flush=True)
    sys.exit(message)


def safe_out(path, allowed):
    """Refuse output folders inside the (public) repo, except git-ignored ones (out/, dist/)."""
    p = Path(path).resolve()
    if p.is_relative_to(REPO) and not any(p.is_relative_to(REPO / a) for a in allowed):
        fail(f"refusing to write into the repository: {path} (use a folder outside it, or {'/ '.join(allowed)}/)")
    return p


def load(docs):
    """Projects from the overview docs in the folder, people from 'ETL people.xlsx' in the data-folder root."""
    table = find_people(docs)
    data = validate(build([read_doc(p) for p in list_docs(docs)], read_people_table(table) if table else []))
    data["people_source"] = "table" if table else "none"
    if not table:
        data["issues"].append(dict(scope="people", project=None, field="ETL people table", severity="warning",
                                   code="no_people_table", message="No people table found in the overview folder.",
                                   hint="Add 'ETL people.xlsx' (or a Google Sheet 'ETL people') to the root of the data folder."))
    return data


def write_report(data, out):
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "issues.md").write_text(issues_markdown(data), encoding="utf-8")


def cmd_parse(args):
    out = safe_out(args.out, ("out",))
    data = load(args.docs)
    write_report(data, out)
    sev = Counter(i["severity"] for i in data["issues"])
    docs = sum(1 for p in data["projects"] if p.get("has_overview_doc"))
    print(f"docs={docs} projects={len(data['projects'])} tasks={len(data['tasks'])} "
          f"demands={len(data['demands'])} people={len(data['people'])} "
          f"warnings={sev['warning']} info={sev['info']}")


TEST_LABEL = dict(mode_badge="test data", mode_label=os.environ.get(
    "ETL_TEST_LABEL", "TEST DATA – a separate copy of the projects, for trying out every feature. Changes here do not affect the real overview docs."))


def passwords_from_env(with_test):
    passwords = {k: os.environ.get(f"ETL_{k.upper()}_PASSWORD") for k in ("viewer", "admin", "test")}
    if not (passwords["viewer"] and passwords["admin"]):
        fail("set ETL_VIEWER_PASSWORD and ETL_ADMIN_PASSWORD (never pass passwords as arguments)")
    if with_test != bool(passwords["test"]):
        fail("the test mode needs ETL_TEST_PASSWORD together with test data (and test data needs the password)")
    if not with_test:
        passwords.pop("test")
    return passwords


def update_config():
    """Update button endpoint (Apps Script web app, or the local dev server): goes into the encrypted data.
    -> (config or None, origins allowed in the page's connect-src)."""
    url, key = os.environ.get("ETL_UPDATE_URL"), os.environ.get("ETL_UPDATE_KEY")
    if not (url and key):
        if url or key or os.environ.get("ETL_EDIT_KEY"):   # half-configured: say what is missing (names only)
            missing = [n for n, v in (("ETL_UPDATE_URL (variable)", url), ("ETL_UPDATE_KEY (secret)", key)) if not v]
            notice("warning", "Update button and website editing are OFF: missing " + " and ".join(missing))
        return None, ()
    o = urlsplit(url)
    origin = f"{o.scheme}://{o.netloc}"
    extra = ("https://script.googleusercontent.com",) if o.netloc == "script.google.com" else ()  # Apps Script redirect
    return {"url": url, "key": key}, (origin, *extra)


def publish(data, test, passwords, site, report, allow_short):
    """Encrypt + write the site, leak-scan it (removing a leaking build), optionally write the local report."""
    min_length = TEST_MIN_PASSWORD_LENGTH if allow_short else MIN_PASSWORD_LENGTH
    update, connect = update_config()
    if update:
        data["update"] = update
        if test:
            test[0]["update"] = update
    # corrections: the edit key lives only in the admin-encrypted block (viewers never get it). The test mode gets
    # its OWN key, which the server maps to the test folder only – it can never write to the real documents.
    admin = {"edit_key": os.environ["ETL_EDIT_KEY"]} if update and os.environ.get("ETL_EDIT_KEY") else {}
    log = data.pop("edit_log", None)
    if log is not None:  # the change log: admins only (it names editors and shows old values)
        admin["log"] = log
    if test:
        test_key = os.environ.get("ETL_TEST_EDIT_KEY") if update and test[0].get("editable") else None
        test = (test[0], {"edit_key": test_key} if test_key else {})
    try:
        out = build_site(data, passwords, site, admin_secrets=admin, test=test, min_length=min_length, connect=connect)
    except ValueError as e:
        fail(f"build refused: {e}")
    files = [out / f for f in SITE_FILES]
    hits = leak_scan(data, files)
    if hits:
        for f in files:  # never leave a leaking build behind (only the files this build wrote)
            f.unlink(missing_ok=True)
        fail(f"LEAK: {len(hits)} readable values found in the build output; build removed")
    if report:
        write_report(data, report)
    size = (out / "index.html").stat().st_size
    note = " SHORT PASSWORDS ALLOWED – test build, do not publish real data with it" if allow_short else ""
    print(f"built index.html ({size // 1024} kB) projects={len(data['projects'])} "
          f"test-mode={'on' if test else 'off'} leak-scan=clean{note}")


def cmd_build(args):
    with_test = bool(args.test_docs)
    passwords = passwords_from_env(with_test)
    site = safe_out(args.out, ("dist", "out"))
    report = safe_out(args.report, ("out",)) if args.report else None
    test = (dict(load(args.test_docs), **TEST_LABEL), {}) if with_test else None
    publish(load(args.docs), test, passwords, site, report, args.allow_short_passwords)


def add_links(data, manifest):
    """Doc links from the Drive manifest (shown as 'Open doc' in the dashboard)."""
    by_file = {d["file"]: d for d in manifest["docs"]}
    for p in data["projects"]:
        meta = by_file.get((p.get("source") or {}).get("file"))
        if meta:
            p["source"].update(url=meta["url"], native=meta["native"], id=meta["id"])
    return data


def explain_fetch_error(e, what):
    """A clear, data-free reason for a failed Drive fetch (CI logs are public)."""
    code = getattr(getattr(e, "response", None), "status_code", None)
    hints = {401: "the Google credentials were rejected – check GOOGLE_SA_KEY / the OAuth secrets",
             403: "no permission – share the folder with the service account's email (Viewer) and enable the Drive API",
             404: "folder not found – check the folder ID, and that it is shared with the service account"}
    if isinstance(e, KeyError):
        return f"{what}: the setting {e} is missing (GitHub secret or variable)"
    if isinstance(e, ValueError) and "Could not deserialize" in str(e) or "json" in type(e).__name__.lower():
        return f"{what}: GOOGLE_SA_KEY is not a valid service-account JSON key (paste the whole file content)"
    if code:
        return f"{what}: Google Drive answered HTTP {code} – {hints.get(code, 'see the Drive API documentation')}"
    return f"{what}: {type(e).__name__}: {str(e)[:200]}"


def cmd_sync(args):
    """Fetch (ETL_SOURCE = local | oauth | service_account) into a temp folder, then build. Prints counts only."""
    import tempfile
    from .sources.drive import fetch
    with_test = bool(os.environ.get("ETL_TEST_PASSWORD"))
    passwords = passwords_from_env(with_test)
    site = safe_out(args.out, ("dist", "out"))
    report = safe_out(args.report, ("out",)) if args.report else None
    with tempfile.TemporaryDirectory(prefix="etl-sync-") as tmp:
        tmp = Path(tmp)
        try:
            manifest = fetch(tmp / "src")
        except Exception as e:  # noqa: BLE001 – reported without data, then the run fails
            fail("sync failed – " + explain_fetch_error(e, "reading DRIVE_FOLDER_ID"))
        data = add_links(load(tmp / "src" / "overviews"), manifest)
        data["people_file"] = manifest.get("people")
        from .writeback import read_log
        data["edit_log"] = read_log(tmp / "src" / "edit-log.csv")
        test = None
        if with_test:
            if os.environ.get("ETL_TEST_DRIVE_FOLDER_ID"):   # a TEST folder in Drive: editable via the companion
                env = dict(os.environ, DRIVE_FOLDER_ID=os.environ["ETL_TEST_DRIVE_FOLDER_ID"], DRIVE_EDIT_LOG_ID="")
                try:
                    tm = fetch(tmp / "test", env=env)
                except Exception as e:  # noqa: BLE001
                    fail("sync failed – " + explain_fetch_error(e, "reading ETL_TEST_DRIVE_FOLDER_ID"))
                tdata = add_links(load(tmp / "test" / "overviews"), tm)
                editable = True
            else:  # a local folder (dev server) or freshly generated made-up data (read-only)
                src = Path(os.environ.get("ETL_TEST_LOCAL_DIR") or make_testdata(tmp / "testdata"))
                tdata = load(src / "overviews")
                editable = bool(os.environ.get("ETL_TEST_LOCAL_DIR"))
            test = (dict(tdata, editable=editable, **TEST_LABEL), {})
        print(f"fetched {len(manifest['docs'])} docs from {manifest['source']}")
        publish(data, test, passwords, site, report, args.allow_short_passwords)


def cmd_serve(args):
    """Local dev server: serves the site over http and answers the update API like the Apps Script companion,
    rebuilding from a local folder (ETL_SOURCE=local). For testing only; binds to 127.0.0.1."""
    import secrets
    import threading
    import time
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    site = safe_out(args.out, ("dist", "out"))
    from .writeback import EditError, apply_edit, log_edit
    key, edit_key, test_edit_key = (secrets.token_urlsafe(16) for _ in range(3))
    sim = Path(args.sim).resolve()
    test_sim = Path(args.test_sim).resolve() if args.test_sim else sim
    os.environ.update(ETL_SOURCE="local", ETL_LOCAL_DIR=str(sim), ETL_TEST_LOCAL_DIR=str(test_sim),
                      ETL_UPDATE_URL=f"http://127.0.0.1:{args.port}/api", ETL_UPDATE_KEY=key, ETL_EDIT_KEY=edit_key,
                      ETL_TEST_EDIT_KEY=test_edit_key)
    roots = {edit_key: sim, test_edit_key: test_sim}   # the folder follows from the key, never from the request

    def root_for(body):
        given = str(body.get("key", ""))
        return next((r for k, r in roots.items() if secrets.compare_digest(given, k)), None)
    edits_at = []
    build_args = argparse.Namespace(out=str(site), report=None, allow_short_passwords=args.allow_short_passwords)
    lock, state = threading.Lock(), {"last": 0.0}

    def rebuild():
        with lock:
            try:
                cmd_sync(build_args)
            except SystemExit as e:  # keep serving; the message has no data in it
                print(f"rebuild failed: {e}")

    rebuild()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(site), **kw)

        def log_message(self, *a):  # quiet: request paths are not interesting and could be noisy
            pass

        def reply(self, code, body):
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            size = int(self.headers.get("Content-Length") or 0)
            if size > 25 * 1024 * 1024:  # proposal uploads are capped at 15 MB (base64 adds a third)
                return self.reply(413, {"ok": False, "message": "request too large"})
            try:
                body = json.loads(self.rfile.read(size) or b"{}")
            except ValueError:
                return self.reply(400, {"ok": False, "message": "bad request"})
            if body.get("action") == "edit":
                return self.edit(body)
            if body.get("action") == "save_project":
                return self.save_project(body)
            if body.get("action") == "save_person":
                return self.save_person(body)
            if not secrets.compare_digest(str(body.get("key", "")), key):
                return self.reply(403, {"ok": False, "message": "not allowed"})
            if body.get("action") == "update":
                if time.time() - state["last"] < args.min_interval:
                    return self.reply(429, {"ok": False, "message": "An update was just requested – try again in a minute."})
                state["last"] = time.time()
                threading.Thread(target=rebuild, daemon=True).start()
                return self.reply(200, {"ok": True, "message": "Update started."})
            return self.reply(400, {"ok": False, "message": "unknown action"})

        def save_person(self, body):
            """Add or update a person in 'ETL people.xlsx' (created on first use)."""
            from .sources.people_table import save_person
            from .writeback import log_edit
            base = root_for(body)
            if base is None:
                return self.reply(403, {"ok": False, "message": "not allowed"})
            editor = str(body.get("editor") or "").strip()[:80]
            if not editor or not isinstance(body.get("person"), dict):
                return self.reply(400, {"ok": False, "message": "editor name and person required"})
            with lock:
                status, message = save_person(base, body["person"], body.get("old_id"), body.get("old"))
                log_edit(base / "overviews", editor, {"file": "ETL people.xlsx", "old": body.get("old_id") or "(new)",
                                                      "new": body["person"].get("id")}, status)
            if status != "ok":
                return self.reply(200, {"ok": False, "message": message})
            threading.Thread(target=rebuild, daemon=True).start()
            return self.reply(200, {"ok": True, "message": "Saved. The dashboard is being rebuilt."})

        def save_project(self, body):
            """Create a project doc, or update one (cell edits + new task rows); optional proposal file/link."""
            from .projectdocs import LABEL, add_task_rows, create_project, reviewed_stamp, save_proposal, set_overview_row
            base = root_for(body)
            if base is None:
                return self.reply(403, {"ok": False, "message": "not allowed"})
            editor = str(body.get("editor") or "").strip()[:80]
            if not editor:
                return self.reply(400, {"ok": False, "message": "editor name required"})
            edits = (body.get("edits") or [])[:200]
            now = time.time()
            edits_at[:] = [t for t in edits_at if now - t < 600]
            if len(edits_at) + max(1, len(edits)) > 60:
                return self.reply(429, {"ok": False, "message": "Too many edits – try again in a few minutes."})
            results, docs, sim_ = [], base / "overviews", base
            try:
                with lock:
                    if body.get("mode") == "create":
                        body["overview"] = dict(body.get("overview") or {}, last_reviewed=reviewed_stamp(editor))
                        pid, name = create_project(sim_, body.get("overview") or {}, body.get("new_tasks") or [],
                                                   body.get("demands") or {}, body.get("focus") or {})
                        log_edit(docs, editor, {"file": name, "new": "(new project)"}, "created")
                    else:
                        name = str(body.get("file") or "")
                        if Path(name).name != name or not (docs / name).is_file():
                            return self.reply(400, {"ok": False, "message": "unknown overview document"})
                        pid = Path(name).stem.split(" - ")[0].strip()   # from the document, not the request
                        for e in edits:  # check everything first: a batch is written completely or not at all
                            try:
                                apply_edit(docs, dict(e, file=name), dry_run=True)
                                results.append({"ok": True})
                            except EditError as err:
                                results.append({"ok": False, "message": str(err), "current": err.current})
                        if not all(r["ok"] for r in results):
                            return self.reply(200, {"ok": False, "results": results,
                                                    "message": "Nothing was saved – please review the marked values."})
                        for e in edits:
                            apply_edit(docs, dict(e, file=name))
                            log_edit(docs, editor, dict(e, file=name), "ok")
                            edits_at.append(now)
                        parsed = read_doc(docs / name)["overview"]
                        for k, v in (body.get("overview_add") or {}).items():   # rows the (older) doc lacks
                            if k in LABEL and k not in parsed and str(v).strip() and k != "last_reviewed":
                                set_overview_row(docs / name, k, v)
                                log_edit(docs, editor, {"file": name, "new": f"{LABEL[k]}: {v}"}, "row added")
                        if body.get("new_tasks"):
                            n = add_task_rows(docs / name, body["new_tasks"][:50])
                            log_edit(docs, editor, {"file": name, "new": f"{n} task row(s)"}, "rows added")
                    prop = body.get("proposal") or {}
                    if prop.get("url") or prop.get("data"):
                        text = save_proposal(sim_, pid, prop.get("name"), prop.get("data"), prop.get("url"))
                        set_overview_row(docs / name, "proposal", text)
                        log_edit(docs, editor, {"file": name, "new": text}, "proposal attached")
                    if body.get("mode") != "create":  # a save from the form counts as a review
                        set_overview_row(docs / name, "last_reviewed", reviewed_stamp(editor))
            except EditError as err:
                return self.reply(200, {"ok": False, "message": str(err), "results": results})
            threading.Thread(target=rebuild, daemon=True).start()
            ok = all(r["ok"] for r in results)
            return self.reply(200, {"ok": ok, "results": results, "file": name,
                                    "message": "Saved. The dashboard is being rebuilt." if ok else "Some changes were not saved."})

        def edit(self, body):
            base = root_for(body)
            if base is None:
                return self.reply(403, {"ok": False, "message": "not allowed"})
            editor = str(body.get("editor") or "").strip()[:80]
            edits = body.get("edits") or []
            if not editor or not isinstance(edits, list) or not 1 <= len(edits) <= 20:
                return self.reply(400, {"ok": False, "message": "editor name and 1–20 edits required"})
            now = time.time()
            edits_at[:] = [t for t in edits_at if now - t < 600]
            if len(edits_at) + len(edits) > 30:
                return self.reply(429, {"ok": False, "message": "Too many edits – try again in a few minutes."})
            results = []
            with lock:
                for e in edits:
                    try:
                        apply_edit(base / "overviews", e)
                        results.append({"ok": True})
                        log_edit(base / "overviews", editor, e, "ok")
                        edits_at.append(now)
                    except EditError as err:
                        results.append({"ok": False, "message": str(err), "current": err.current})
                        log_edit(base / "overviews", editor, e, f"refused: {err}")
            if any(r["ok"] for r in results):
                threading.Thread(target=rebuild, daemon=True).start()
            ok = all(r["ok"] for r in results)
            return self.reply(200, {"ok": ok, "results": results,
                                    "message": "Saved. The dashboard is being rebuilt." if ok else "Some changes were not saved."})

    print(f"serving http://127.0.0.1:{args.port}/  (local simulation; Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


def cmd_testdata(args):
    out = make_testdata(safe_out(args.out, ("out",)))
    print(f"test data written: {sum(1 for _ in (out / 'overviews').glob('*.docx'))} docs + people table")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="etl_dash")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse", help="read sources, write data.json + issues.md")
    p.add_argument("--docs", required=True, help="overview folder: project-overview .docx files + 'ETL people.xlsx'")
    p.add_argument("--out", required=True, help="output folder (keep outside the repo or in ignored out/)")
    p.set_defaults(func=cmd_parse)
    b = sub.add_parser("build", help="parse + encrypt + write the single-file site (passwords from env)")
    b.add_argument("--docs", required=True)
    b.add_argument("--out", default="dist", help="site output folder (default: dist/, ignored by git)")
    b.add_argument("--report", help="optional folder for data.json + issues.md (local review only)")
    b.add_argument("--test-docs", help="made-up test data (hidden test mode, needs ETL_TEST_PASSWORD)")
    b.add_argument("--allow-short-passwords", action="store_true",
                   help=f"test builds only: accept passwords from {TEST_MIN_PASSWORD_LENGTH} characters")
    b.set_defaults(func=cmd_build)
    y = sub.add_parser("sync", help="fetch from ETL_SOURCE (local | oauth | service_account) and build")
    y.add_argument("--out", default="dist")
    y.add_argument("--report", help="optional folder for data.json + issues.md (local review only)")
    y.add_argument("--allow-short-passwords", action="store_true", help="test deployments only")
    y.set_defaults(func=cmd_sync)
    v = sub.add_parser("serve", help="local dev server: site + update API, rebuilding from a local folder")
    v.add_argument("--sim", required=True, help="local folder laid out like the Drive TEST setup")
    v.add_argument("--out", default="out/serve")
    v.add_argument("--test-sim", help="separate folder for the hidden test mode (default: the same as --sim)")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--min-interval", type=float, default=10, help="seconds between accepted update requests")
    v.add_argument("--allow-short-passwords", action="store_true")
    v.set_defaults(func=cmd_serve)
    t = sub.add_parser("make-testdata", help="write a made-up local folder that simulates the Drive TEST setup")
    t.add_argument("--out", required=True)
    t.set_defaults(func=cmd_testdata)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())

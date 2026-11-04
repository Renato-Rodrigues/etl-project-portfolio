"""Assemble the single-file dashboard: web/ sources inlined + encrypted payload -> dist/index.html.

Only ciphertext and static code are written. leak_scan() verifies that no readable value from the data ends up
in the output (run on every build; the build fails on a hit).
"""
import base64
import datetime as dt
import hashlib
import html
import json
import re
from pathlib import Path

from .crypto import MIN_PASSWORD_LENGTH, encrypt

WEB = Path(__file__).resolve().parent.parent / "web"
JS_FILES = ("crypto.js", "app.js")
FONTS = [("IBM Plex Sans", 400, "IBMPlexSans-Regular-Latin1.woff2"), ("IBM Plex Sans", 600, "IBMPlexSans-SemiBold-Latin1.woff2"),
         ("IBM Plex Sans Condensed", 600, "IBMPlexSansCondensed-SemiBold-Latin1.woff2"),
         ("IBM Plex Serif", 600, "IBMPlexSerif-SemiBold-Latin1.woff2")]   # SIL OFL, see web/fonts/LICENSE.txt


def font_css():
    """@font-face rules with the vendored woff2 files inlined (the page loads nothing from outside)."""
    rules = []
    for family, weight, name in FONTS:
        b = base64.b64encode((WEB / "fonts" / name).read_bytes()).decode()
        rules.append(f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:normal;font-display:swap;"
                     f"src:url(data:font/woff2;base64,{b}) format('woff2')}}")
    return "\n".join(rules) + "\n"


def csp_hash(text):
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


def static_sources():
    return {name: (WEB / name).read_text(encoding="utf-8") for name in ("index.html", "app.css", *JS_FILES)}


def assemble(payload, src=None, connect=()):
    src = src or static_sources()
    css, js = font_css() + src["app.css"], "\n".join(src[f] for f in JS_FILES)
    csp = "; ".join([
        "default-src 'none'",
        f"script-src {csp_hash(js)}",
        f"style-src {csp_hash(css)}",
        "img-src data:",
        "font-src data:",
        f"connect-src 'self' {' '.join(connect)}".strip() if connect else "connect-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    ])
    body = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    page = src["index.html"]
    for key, value in (("__CSP__", csp), ("__CSS__", css), ("__JS__", js), ("__PAYLOAD__", body)):
        if page.count(key) != 1:
            raise ValueError(f"template placeholder {key} must occur exactly once")
        page = page.replace(key, value)
    return page


SITE_FILES = ("index.html", "version.txt", "robots.txt")


def build_site(data, passwords, out_dir, admin_secrets=None, test=None, min_length=MIN_PASSWORD_LENGTH, connect=()):
    """passwords = {viewer, admin[, test]}; test = (test_data, test_admin_secrets) for the hidden test mode."""
    test_arg = (test[0], test[1], passwords["test"]) if test else None
    payload = encrypt(data, admin_secrets or {}, passwords["viewer"], passwords["admin"], test=test_arg,
                      min_length=min_length)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(assemble(payload, connect=connect), encoding="utf-8")
    build_id = hashlib.sha256(payload["data"]["ct"].encode()).hexdigest()[:12]
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    (out / "version.txt").write_text(f"{build_id} {stamp}\n", encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- leak scan
ISO_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?(T[\d:+.]+)?$")  # build dates/timestamps are not project data
CIPHERTEXT = re.compile(r'(<script type="application/json" id="payload">).*?(</script>)', re.S)
DATA_URI = re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=]+")


def sensitive_strings(data, min_len=3):
    """Every value and key in the data (strings, numbers >= 1000) that is not already part of the static page,
    plus its HTML-escaped and JSON-escaped forms."""
    static = assemble({}) + "\nUser-agent: *\nDisallow: /\n"
    found = set()

    def add(s):
        s = s.strip()
        if len(s) >= min_len and s not in static and not ISO_DATE.match(s):
            found.update({s, html.escape(s), json.dumps(s)[1:-1]})

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                add(str(k))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            for part in {o, *o.split("\n")}:
                add(part)
        elif isinstance(o, (int, float)) and not isinstance(o, bool) and abs(o) >= 1000:
            add(f"{o:g}" if isinstance(o, float) and not o.is_integer() else str(int(o)))
    walk(data)
    return found


def scannable(text):
    """The output without the parts that are opaque by design (ciphertext, inlined fonts)."""
    return DATA_URI.sub("", CIPHERTEXT.sub(r"\1\2", text))


def leak_scan(data, paths, min_len=3):
    """-> list of (file, leaked value prefix). Empty list = clean. Values match on word boundaries."""
    values = sensitive_strings(data, min_len)
    hits = []
    for path in paths:
        text = scannable(Path(path).read_text(encoding="utf-8", errors="ignore"))
        hits += [(str(path), v[:12] + "…") for v in values
                 if re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", text)]
    return hits

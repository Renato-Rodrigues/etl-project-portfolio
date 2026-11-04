"""Turn the overview docs and the people table into the normalized data model (projects, tasks, demands, …).

Parsing problems found here (bad dates, unknown or ambiguous people, …) are emitted as issues; completeness
and cross-source checks live in validate.py. Examples in comments are synthetic.
"""
import datetime as dt
import re
import unicodedata

from . import SCHEMA_VERSION
from .sources.overview_docs import norm

UNCLEAR = re.compile(r"\btbc\b|\btbd\b|\?|\bx{2,}\b|\bi think\b", re.I)
URL = re.compile(r"https?://\S+")
MONTH = re.compile(r"\b(\d{1,2})\s*/\s*(\d{4}|\d{2})\b")
FLEX = re.compile(r"^\s*flex(ible)?\s*$", re.I)
TEAM_WORDS = {"etl", "iam", "carma", "lut", "get", "icp", "rse", "macro", "esm", "magpie", "pik",
              "sector", "sectors", "people", "team", "teams", "group", "colleagues"}
GROUP_WORDS = {"group", "team", "teams", "colleagues"}   # "X's group" names a team, not a person
PLACEHOLDERS = {"", "tbd", "tbc", "na", "none", "xxx", "x"}
STATUSES = ("active", "proposal", "finished", "rejected")
PEOPLE_FIELDS = ("etl_main", "etl_pi", "etl_other", "pik_other", "project_lead")
TEMPLATE_HINT = re.compile(r"^(project\s+(id|acronym)|<)", re.I)


def issue(issues, project, field, severity, code, message, hint=None, scope="doc"):
    issues.append(dict(scope=scope, project=project, field=field, severity=severity, code=code,
                       message=message, hint=hint))


def unclear(text):
    """tbc / ? / xxx markers, ignoring URLs (Drive links contain '?')."""
    return bool(UNCLEAR.search(URL.sub("", text or "")))


# ---------------------------------------------------------------- values
def parse_month(s):
    """'06/28', '9/2028', '12/2024' -> '2028-06' / '2028-09' / '2024-12'; None if no month found."""
    m = MONTH.search(s or "")
    if not m:
        return None
    month, year = int(m.group(1)), int(m.group(2))
    year += 2000 if year < 100 else 0
    return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None


def parse_duration(raw):
    months = [parse_month(f"{a}/{b}") for a, b in MONTH.findall(raw or "")]
    return dict(start=months[0] if months else None, end=months[1] if len(months) > 1 else None,
                tbc=unclear(raw), raw=raw or "")


def parse_effort(raw):
    raw = (raw or "").strip()
    if FLEX.match(raw):
        return dict(pm=None, flexible=True, raw=raw)
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(pm)?", raw, re.I)
    return dict(pm=float(m.group(1).replace(",", ".")) if m else None, flexible=False, raw=raw)


AMOUNT = re.compile(r"(\d[\d.,]*)\s*(k|m|mio)?\s*(€|eur\b|euro\b|usd\b|\$)?", re.I)


def parse_amount(text):
    """First money amount in free text: '1.234.567,00 €' / '2,345,678 USD' / '500k€' / '300 k€'.
    A bare number counts only with thousands separators, a k/M suffix or a currency (so years are skipped)."""
    for m in AMOUNT.finditer(text or ""):
        num, mult, cur = m.group(1).rstrip(".,"), (m.group(2) or "").lower(), m.group(3)
        if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", num):          # German: 1.234.567,00
            value = float(num.replace(".", "").replace(",", "."))
        elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", num):        # English: 2,345,678
            value = float(num.replace(",", ""))
        elif mult or cur:
            try:
                value = float(num.replace(",", "."))
            except ValueError:
                continue
        else:
            continue
        return value * {"k": 1e3, "m": 1e6, "mio": 1e6}.get(mult, 1)
    return None


def parse_currency(text):
    t = (text or "").lower()
    if "€" in t or "eur" in t:
        return "EUR"
    if "usd" in t or "$" in t:
        return "USD"
    return None


def parse_funding(fields):
    """v1: single 'Funding' text; v2: separate total-for-PIK / of-which-ETL / currency fields."""
    raw = {k: fields.get(k, {}).get("raw", "") for k in ("funding", "funding_pik", "funding_etl", "currency")}
    text = raw["funding"]
    out = dict(raw=" | ".join(v for v in raw.values() if v), currency=parse_currency(raw["currency"] or text),
               pik=parse_amount(raw["funding_pik"]), etl=parse_amount(raw["funding_etl"]),
               secured=fields.get("funding_secured", {}).get("raw", ""), counted_in=None)
    if text:  # v1: '250 k€ for PIK, xxx of that for ETL' / '1.234.567,00 € for ETL'
        scope = "etl" if re.search(r"for\s+etl", text, re.I) and not re.search(r"for\s+pik", text, re.I) else "pik"
        out[scope] = out[scope] or parse_amount(text)
    return out


def split_acronym(name):
    """'ABC (Alpha Beta Collaboration)' -> ('ABC', 'Alpha …'); 'Raw stuff (RAWX)' -> ('RAWX', 'Raw stuff')."""
    m = re.fullmatch(r"\s*(.+?)\s*\((.+)\)\s*", name or "")
    if not m:
        return (name or "").strip(), ""
    outside, inside = m.group(1), m.group(2)
    if re.fullmatch(r"[A-Z0-9][A-Z0-9 _-]{1,15}", inside.strip()):
        return inside.strip(), outside
    return outside, inside


def ascii_key(s):
    return norm(unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode())


def initials(full):
    words = full.split()
    return {(words[0][0] + words[-1][0]).lower(), "".join(w[0] for w in words).lower(),
            (words[0][:2] + words[-1][:2]).lower()} if len(words) >= 2 else set()


# ---------------------------------------------------------------- people
class Roster:
    """People of the people table, indexed by full name, last name, first name, initials and aliases."""

    def __init__(self, people):
        self.people, self.index = people, {}
        for p in people:
            p["id"] = ascii_key(f"{p['first']}{p['last']}")
            p["name"] = f"{p['first']} {p['last']}"
            keys = {("full", ascii_key(p["name"])), ("last", ascii_key(p["last"])), ("first", ascii_key(p["first"]))}
            keys |= {("init", i) for i in initials(p["name"])}
            if p.get("initials"):  # people table: the Person ID is authoritative for initials
                keys.add(("pid", ascii_key(p["initials"])))
            keys |= {("alias", ascii_key(a)) for a in p.get("aliases", [])}   # people table: other spellings
            for k in keys:
                self.index.setdefault(k, set()).add(p["id"])
        self.by_id = {p["id"]: p for p in people}

    def lookup(self, how, token):
        return sorted(self.index.get((how, ascii_key(token)), ()))

    def prefix(self, token):
        key = ascii_key(token)
        return sorted(p["id"] for p in self.people if len(key) >= 3 and ascii_key(p["first"]).startswith(key))


class DocContext:
    """Names written out in full somewhere in the same document: used to read 'Ivan' or 'RS' elsewhere in it."""

    def __init__(self, texts):
        self.by_first, self.by_init = {}, {}
        for text in texts:
            for tok, _, _ in split_people(text):
                clean = tok.rstrip("?").strip()
                words = clean.split()
                if len(words) >= 2 and not _is_team(clean) and all(w[:1].isupper() for w in words):
                    self.by_first.setdefault(ascii_key(words[0]), set()).add(clean)
                    for i in initials(clean):
                        self.by_init.setdefault(i, set()).add(clean)

    def lookup(self, token, as_initials):
        """Exact first name / initials of a name written in full in this doc (unique), else None."""
        hits = (self.by_init if as_initials else self.by_first).get(ascii_key(token), set())
        return next(iter(hits)) if len(hits) == 1 else None

    def prefix(self, token):
        """Longer first names in this doc starting with the token ('Alex' -> 'Alexander …'): candidates only."""
        key = ascii_key(token)
        return sorted(n for k, names in self.by_first.items() if len(key) >= 3 and k != key and k.startswith(key)
                      for n in names)


class PeopleLog:
    """Collects people problems so each (project, name) is reported once, listing where it occurs."""

    def __init__(self):
        self.items = {}

    def add(self, project, code, written, where, severity, message, hint):
        key = (project, code, ascii_key(written))
        item = self.items.setdefault(key, dict(severity=severity, message=message, hint=hint, where=[]))
        if where not in item["where"]:
            item["where"].append(where)

    def flush(self, issues):
        for (project, code, _), it in self.items.items():
            issue(issues, project, "; ".join(it["where"]), it["severity"], code, it["message"], it["hint"])


def _is_team(text):
    words = [ascii_key(w) for w in re.split(r"[\s/]+", text) if w]
    return any(w in GROUP_WORDS for w in words) or all(w in TEAM_WORDS | PLACEHOLDERS for w in words)


def split_people(text):
    """Cell text -> [(token, section, team)]. Handles '[Sub]' tags and 'IAM/CarMa (A, B)' / 'Team: A, B'."""
    out, section = [], ""
    for line in re.split(r"[\n;]|\s/\s", text or ""):
        line = line.strip()
        tag = re.match(r"^\[([^\]]+)\]\s*", line)
        if tag:
            section, line = tag.group(1).strip(), line[tag.end():]
        team = ""
        m = re.match(r"^([A-Za-z/ ]+?)\s*(?:\((.*)\)|:\s*(.*))$", line)
        if m and all(ascii_key(w) in TEAM_WORDS for w in re.split(r"[/ ]", m.group(1)) if w):
            team, line = m.group(1).strip(), (m.group(2) or m.group(3) or "")
        for tok in re.split(r",|\+|\band\b|\(|\)", line):
            tok = tok.strip().strip(".…").strip()
            if tok:
                out.append((tok, section, team))
    return out


def resolve_one(clean, roster, ctx):
    """One written name -> (name, person_id, how, candidate names).

    Every reading of a single word goes into one pool (last name, first name, a name written in full in the same
    doc). It is resolved only if exactly one person remains AND the evidence is more than a bare first name.
    A wrong match is worse than an open question, so everything else stays unresolved with its candidates."""
    names = lambda ids: [roster.by_id[i]["name"] for i in ids]

    def pick(name, how):
        ids = roster.lookup("full", name)
        return name, ids[0] if len(ids) == 1 else None, how, []

    if len(clean.split()) > 1:
        ids = roster.lookup("full", clean)
        return pick(clean, "full") if len(ids) == 1 else (clean, None, None, names(ids))
    alias = roster.lookup("alias", clean)
    if len(alias) == 1:   # an alias from the people table ('Jess', 'RoSa')
        return pick(names(alias)[0], "alias")
    if re.fullmatch(r"[A-Z][a-z]?[A-Z][a-z]?|[A-Z]{2,4}", clean):  # initials: 'FS', 'RoSa'
        ids = roster.lookup("pid", clean)
        if len(ids) == 1:
            return pick(names(ids)[0], "person id")
        ids = roster.lookup("init", clean)
        if len(ids) == 1:
            return pick(names(ids)[0], "init")
        full = ctx.lookup(clean, True)
        if full and (not ids or full in names(ids)):
            return pick(full, "doc context")
        return clean, None, None, names(ids)
    last, first = names(roster.lookup("last", clean)), names(roster.lookup("first", clean))
    full = ctx.lookup(clean, False)
    pool = list(dict.fromkeys(last + first + ([full] if full else [])))
    if len(pool) == 1 and (last or full):
        return pick(pool[0], "last" if last else "doc context")
    extra = ctx.prefix(clean) + ([] if pool else names(roster.prefix(clean)))
    return clean, None, None, list(dict.fromkeys(pool + extra))


def resolve_people(text, roster, ctx, log, project, where, unknown="warning", unknown_hint=None):
    """-> [{name, person_id, how, uncertain, section, team, written, candidates}]; reports problems to the log.
    unknown=None: names outside the roster are expected (e.g. external project leads) and not reported."""
    seen, out = set(), []
    for tok, section, team in split_people(text):
        uncertain = tok.endswith("?")
        clean = tok.rstrip("?").strip().strip(".…").strip()
        if ascii_key(clean) in PLACEHOLDERS or _is_team(clean):
            continue
        name, pid, how, cands = resolve_one(clean, roster, ctx)
        key = pid or ascii_key(name)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(name=name, person_id=pid, how=how, uncertain=uncertain, section=section, team=team,
                        written=tok, candidates=cands))
        if pid:
            continue
        if len(cands) > 1:
            log.add(project, "person_ambiguous", clean, where, "warning",
                    f"'{clean}' is not a unique name – could be: {', '.join(cands)}.", "Write the full name (First Last).")
        elif cands:
            log.add(project, "person_ambiguous", clean, where, "warning",
                    f"'{clean}' is only a first name – probably {cands[0]}?", "Write the full name (First Last).")
        elif unknown:
            log.add(project, "person_unknown", name, where, unknown,
                    f"'{name}' is not in the people table.",
                    unknown_hint or "Write the full name as in the people table, or add the person on the People tab.")
    return out


# ---------------------------------------------------------------- docs
def file_key(filename):
    stem = re.sub(r"\.docx$", "", filename, flags=re.I)
    stem = re.sub(r"project\s+overview|\(outdated\)|\(v2\)", "", stem, flags=re.I)
    return re.sub(r"\s+", " ", stem).strip(" -–")


# Task codes at the start of a v1 description: 'WP2, Task 2.1: Do …' / 'WP1: …' / 'WP3 Case studies, Task 3.2: …'
_CODE = r"(?:WP|T|Task)[\s-]?[A-Z]?[\d.]*\d"
TASK_CODES = re.compile(rf"^((?:{_CODE}[\s,]*)+):\s*", re.I)
TASK_CODE = re.compile(rf"^({_CODE})\b\s*")
SUB_CODE = re.compile(rf",\s*({_CODE})\s*:\s*", re.I)


def task_code(code, desc):
    code = code.rstrip(". ")
    if code:
        return code, desc
    m = TASK_CODES.match(desc)
    if m:
        return m.group(1).strip(" ,"), desc[m.end():].strip()
    m = TASK_CODE.match(desc)
    if not m:
        return "", desc
    code, rest = m.group(1), desc[m.end():]
    sub = SUB_CODE.search(rest.split("\n")[0])
    if sub:  # 'WP3 Case studies, Task 3.2: …' -> 'WP3, Task 3.2'
        code, rest = f"{code}, {sub.group(1)}", rest[:sub.start()] + ": " + rest[sub.end():]
    return code, rest.strip()


def task_rows(doc, sections=None):
    """Raw task rows of a doc, optionally only some sections: [(section, code, cells)]."""
    out = []
    for t in doc["tables"]:
        if t["kind"] in ("led", "contribution", "tasks_unknown") and (sections is None or t["section"] in sections):
            for r in t["rows"]:
                c = r["cells"]
                code, _ = task_code((c.get("id") or "").strip(), (c.get("description") or "").strip())
                out.append((t["section"], code, c))
    return out


def doc_people_texts(doc):
    texts = [doc["overview"].get(f, {}).get("raw", "") for f in PEOPLE_FIELDS]
    for t in doc["tables"]:
        for r in t["rows"]:
            texts += [r["cells"].get(k, "") for k in ("lead", "others", "sector_lead", "project_contact")]
    return texts


def build_tasks(doc, pid, roster, ctx, log, skip_sections=()):
    tasks, demands, snippets, slots = [], [], [], []
    for t in doc["tables"]:
        if t["section"] in skip_sections:
            continue
        loc_base = dict(file=doc["file"], table=t["anchor"], section=t["section"], table_index=t.get("index"),
                        cols=t.get("colpos", {}))
        for r in t["rows"]:
            c = r["cells"]
            loc = dict(loc_base, row_index=r["row_index"], raw=dict(c))   # raw cell texts: old values for edits
            if t["kind"] in ("led", "contribution", "tasks_unknown"):
                code, desc = task_code((c.get("id") or "").strip(), (c.get("description") or "").strip())
                who = "pik" if re.match(r"\s*pik", t["anchor"], re.I) else "etl"
                kind = {"led": f"{who}_led", "contribution": f"{who}_contribution"}.get(t["kind"], "unknown")
                where = f"task {code or desc[:30]}"
                people = lambda k: resolve_people(c.get(k, ""), roster, ctx, log, pid, where, "info")
                tasks.append(dict(project_id=pid, kind=kind, section=t["section"], code=code, description=desc,
                                  effort=parse_effort(c.get("effort")),
                                  start=parse_month(c.get("start")), start_raw=c.get("start", ""),
                                  deadline=parse_month(c.get("deadline")), deadline_raw=c.get("deadline", ""),
                                  lead=people("lead"), others=people("others"),
                                  status=c.get("status", ""), loc=dict(loc, row_key=code or desc[:40])))
            elif t["kind"] == "demands":
                slots.append(dict(project_id=pid, kind="demand", sector=c.get("sector", ""), loc=dict(loc, row_key=c.get("sector", ""))))
                if not any((v or "").strip() for k, v in c.items() if k != "sector"):
                    continue
                where = f"demand {c.get('sector', '')}"
                people = lambda k: resolve_people(c.get(k, ""), roster, ctx, log, pid, where, "info")
                demands.append(dict(project_id=pid, sector=c.get("sector", ""), description=c.get("description", ""),
                                    task_refs=c.get("task_refs", ""), effort=parse_effort(c.get("effort")),
                                    flexibility=c.get("flexibility", ""), priority=c.get("priority", ""),
                                    start=parse_month(c.get("start")),
                                    deadline=parse_month(c.get("deadline")), deadline_raw=c.get("deadline", ""),
                                    sector_lead=people("sector_lead"), project_contact=people("project_contact"),
                                    status=c.get("status", ""), loc=dict(loc, row_key=c.get("sector", ""))))
            elif t["kind"] == "focus":
                slots.append(dict(project_id=pid, kind="focus", topic=c.get("topic", ""), loc=dict(loc, row_key=c.get("topic", ""))))
            elif t["kind"] == "snippets" and any((v or "").strip() for v in c.values()):
                snippets.append(dict(project_id=pid, sector=c.get("sector", ""), text=c.get("snippet", ""),
                                     source=c.get("source", ""), loc=dict(loc, row_key=c.get("sector", ""))))
    return tasks, demands, snippets, slots


def classify_doc(doc, live_names):
    """-> (project id, excluded reason or None, flag). A filled TEMPLATE holding the only copy of a project's
    data becomes that project (flagged) instead of silently disappearing."""
    key = file_key(doc["file"])
    name = split_acronym(doc["overview"].get("name", {}).get("raw", "").strip())[0]
    if key.lower().startswith("template"):
        has_data = bool(name) and not TEMPLATE_HINT.match(name) and len(name.split()) <= 4
        if has_data and ascii_key(name) not in live_names:
            return name, None, "template_holds_project"
        return key, "template", "template_has_data" if has_data else None
    if re.search(r"\(outdated\)", doc["file"], re.I):
        return f"{key} (outdated)", "outdated", None
    return key, None, None


def build_project(doc, pid, excluded, roster, ctx, log, issues):
    ov = doc["overview"]
    raw = lambda f: ov.get(f, {}).get("raw", "").strip()
    acronym, title = split_acronym(raw("name"))
    duration = parse_duration(raw("duration"))
    status = raw("status").lower() if not excluded else ""
    if status and status not in STATUSES:
        issue(issues, pid, ov["status"]["label"], "warning", "invalid", f"Unknown status '{raw('status')}'.",
              "Use one of: Proposal, Active, Finished, Rejected.")
        status = ""
    focus = {r["cells"].get("topic", "").strip(): r["cells"].get("focus_text", "").strip()
             for t in doc["tables"] if t["kind"] == "focus" for r in t["rows"]
             if r["cells"].get("topic", "").strip() and r["cells"].get("focus_text", "").strip()}
    proj = dict(id=pid, name=acronym or pid, title=raw("full_title") or title, parent_id=None, excluded=excluded,
                website=URL.findall(raw("website"))[0] if URL.findall(raw("website")) else "",
                focus=focus,
                has_overview_doc=True, status=status or None, status_source="doc" if status else None,
                start=duration["start"], end=duration["end"], duration=duration,
                funding=parse_funding(ov), funder=raw("funder"),
                partners=raw("partners"), responsible_team=raw("responsible_team"),
                strategy=raw("strategy"), synergies=raw("synergies"), remarks=raw("remarks"),
                mattermost=raw("mattermost"), last_reviewed=raw("last_reviewed"),
                links=dict(internal=ov.get("folder_internal", {}).get("links", []) or URL.findall(raw("folder_internal")),
                           consortium=ov.get("folder_consortium", {}).get("links", []) or URL.findall(raw("folder_consortium"))),
                template_version=raw("template_version") or "v1",
                fields={f: dict(label=v["label"], raw=v["raw"],
                                loc=dict(v["loc"], file=doc["file"], kind="overview") if v.get("loc") else None)
                        for f, v in ov.items()},
                extra_fields=doc["extra"],
                has_demand_table=any(t["kind"] == "demands" for t in doc["tables"]),
                source=dict(file=doc["file"]))
    if excluded:
        return proj
    unknown = {"project_lead": (None, None),
               "pik_other": ("info", "Only needed if the person belongs to the REMIND group; otherwise ignore.")}
    for f in PEOPLE_FIELDS:
        sev, hint = unknown.get(f, ("warning", None))
        proj[f] = resolve_people(raw(f), roster, ctx, log, pid, ov.get(f, {}).get("label", f), sev, hint)
    for label in doc["extra"]:
        issue(issues, pid, label, "info", "unknown_field", f"Unrecognized overview row '{label}'.",
              "Use the labels of the current template.")
    return proj


def _rows_signature(rows):
    sig = lambda c: tuple(" ".join((c.get(k) or "").split()) for k in ("lead", "others", "effort", "deadline"))
    return {code: sig(c) for _, code, c in rows}


def build(docs, people=(), today=None):
    """-> normalized data dict (the 'database')."""
    today = today or dt.date.today()
    month = today.isoformat()[:7]
    issues = []
    roster = Roster([dict(p) for p in people])
    log = PeopleLog()

    # 1. identify docs: live / excluded, sub-projects ('ALPHA-Sub' -> parent 'ALPHA')
    live_names = {ascii_key(file_key(d["file"])) for d in docs
                  if not file_key(d["file"]).lower().startswith("template") and "(outdated)" not in d["file"].lower()}
    entries = []
    for doc in docs:
        pid, excluded, flag = classify_doc(doc, live_names)
        entries.append(dict(doc=doc, pid=pid, excluded=excluded, flag=flag, parent=None, skip=set()))
    ids = {e["pid"] for e in entries if not e["excluded"]}
    by_pid = {e["pid"]: e for e in entries if not e["excluded"]}
    for e in entries:
        prefix = e["pid"].split("-")[0]
        if not e["excluded"] and "-" in e["pid"] and prefix in ids and prefix != e["pid"]:
            e["parent"] = prefix
            by_pid[prefix]["skip"].add(e["pid"][len(prefix) + 1:])

    # 2. build projects and tasks (a parent's stale copy of a sub-project section is skipped before resolving)
    projects, tasks, demands, snippets, slots = [], [], [], [], []
    for e in entries:
        doc, pid = e["doc"], e["pid"]
        ctx = DocContext(doc_people_texts(doc))
        p = build_project(doc, pid, e["excluded"], roster, ctx, log, issues)
        if e["flag"] == "template_holds_project":
            issue(issues, pid, "document", "warning", "template_holds_project",
                  f"The only data for {pid} is in the TEMPLATE document; it is used for now.",
                  "Copy the content into its own overview doc and restore the blank template.")
        if e["parent"]:
            p["parent_id"], p["name"] = e["parent"], pid   # its Name row repeats the parent's name
        projects.append(p)
        if e["excluded"]:
            continue
        sections = {s for s in e["skip"] if any(t["section"].lower() == s.lower() for t in doc["tables"])}
        skip = {t["section"] for t in doc["tables"] if t["section"].lower() in {s.lower() for s in sections}}
        t, d, s, sl = build_tasks(doc, pid, roster, ctx, log, skip)
        tasks += t; demands += d; snippets += s; slots += sl
        for section in sections:
            child = by_pid[f"{pid}-{section}"]
            copy = _rows_signature(task_rows(doc, {x for x in skip if x.lower() == section.lower()}))
            real = _rows_signature(task_rows(child["doc"]))
            differs = sorted(c or "(no code)" for c in set(copy) | set(real) if copy.get(c) != real.get(c))
            if differs:
                issue(issues, pid, f"Tasks ({section})", "warning", "section_copy_differs",
                      f"The '{section}' tasks here differ from '{child['doc']['file']}' ({'; '.join(differs)}); "
                      f"that document is used.", f"Keep the {section} tasks in one place only.")
            else:
                issue(issues, pid, f"Tasks ({section})", "info", "section_copy_ignored",
                      f"The '{section}' tasks repeat '{child['doc']['file']}'; counted once.",
                      f"Keep the {section} tasks in one place only.")

    # 3. outdated docs: point out tasks that exist only there
    live_codes = {}
    for t in tasks:
        live_codes.setdefault(ascii_key(t["project_id"]), set()).add(t["code"])
    for e in entries:
        if e["excluded"] == "outdated":
            codes = {c for _, c, _ in task_rows(e["doc"]) if c}
            only = sorted(codes - live_codes.get(ascii_key(file_key(e["doc"]["file"])), set()))
            msg = f"'{e['doc']['file']}' is marked outdated and is ignored."
            if only:
                msg += f" Tasks found only there: {'; '.join(only)}."
            issue(issues, e["pid"], "document", "warning" if only else "info", "doc_outdated", msg,
                  "Move anything still valid into the current overview doc, then archive this one.")

    # 4. sub-project funding is counted once, at the parent
    by_id = {p["id"]: p for p in projects}
    for p in projects:
        parent = by_id.get(p["parent_id"] or "")
        if parent and p["funding"]["raw"]:
            same = (p["funding"]["pik"], p["funding"]["etl"]) == (parent["funding"]["pik"], parent["funding"]["etl"])
            if same and (p["funding"]["pik"] or p["funding"]["etl"]):
                p["funding"].update(pik=None, etl=None, counted_in=parent["id"])
                issue(issues, p["id"], "Funding", "info", "subproject_repeats_parent",
                      f"Repeats the funding of {parent['id']}; counted only there.",
                      "Leave funding empty in sub-project docs, or merge the sub-project into the parent doc.")

    # 5. status: the doc's Status row > its duration > shown as active (flagged)
    for p in projects:
        if p["excluded"]:
            continue
        if not p["status"]:
            p["status"], p["status_source"] = _status_from_dates(p, month), "doc dates"
        if not p["status"]:
            p["status"], p["status_source"] = "active", "default"
            issue(issues, p["id"], "Status", "warning", "status_unknown",
                  "Status unknown (no Status row, and the duration does not show it); shown as active.",
                  "Fill in the Status row (Proposal / Active / Finished / Rejected).")

    log.flush(issues)
    involved = {}   # person -> projects, derived from the overview docs (team rows and tasks)
    for p in projects:
        if p.get("excluded") or not p.get("has_overview_doc"):
            continue
        for f in PEOPLE_FIELDS:
            for m in p.get(f, []):
                if m.get("person_id"):
                    involved.setdefault(m["person_id"], set()).add(p["id"])
    for t in tasks:
        for m in t["lead"] + t["others"]:
            if m.get("person_id"):
                involved.setdefault(m["person_id"], set()).add(t["project_id"])
    people = [dict(id=p["id"], name=p["name"], first=p["first"], last=p["last"], initials=p.get("initials", ""),
                   email=p.get("email", ""), teams=p["teams"], sectors=p.get("sectors", []), topics=p["topics"],
                   active=p.get("active", True), aliases=p.get("aliases", []), projects=p.get("projects", []),
                   doc_projects=sorted(involved.get(p["id"], ())), source=p.get("source"))
              for p in roster.people]
    # the setup checklist: from the template if it has one, else the longest found in any doc
    lists = sorted((d for d in docs if d.get("checklist")),
                   key=lambda d: (not file_key(d["file"]).lower().startswith("template"), -len(d["checklist"])))
    return dict(schema_version=SCHEMA_VERSION, generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                today=today.isoformat(), projects=projects, tasks=tasks, demands=demands, snippets=snippets,
                people=people, issues=issues, demand_slots=slots, checklist=lists[0]["checklist"] if lists else [],
                sources=[d["file"] for d in docs])


def _status_from_dates(p, month):
    """From the doc's own duration only: ended -> finished, started -> active, otherwise undecided (None)."""
    if p["duration"]["end"] and p["duration"]["end"] < month:
        return "finished"
    if p["duration"]["start"] and p["duration"]["start"] <= month:
        return "active"
    return None

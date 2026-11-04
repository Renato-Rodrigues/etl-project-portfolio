// Dashboard: login -> decrypt (crypto.js) -> views. All data text goes through esc() before reaching innerHTML.
"use strict";
// frame-buster: a meta CSP cannot set frame-ancestors, so refuse to run inside a frame
if (window.top !== window.self) { document.documentElement.textContent = "This page cannot be shown inside a frame."; throw new Error("framed"); }
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const PAYLOAD = JSON.parse(document.getElementById("payload").textContent);

const SECTORS = ["Transport", "Buildings", "Industry", "Energy supply", "SET", "IAM", "CDR / CarMa", "Model core", "RSE", "Other"];
const SECTOR_KEYS = { transport: "Transport", buildings: "Buildings", industry: "Industry", energysupply: "Energy supply",
  power: "Energy supply", set: "SET", iam: "IAM", cdr: "CDR / CarMa", carma: "CDR / CarMa", cdrcarma: "CDR / CarMa",
  modelcore: "Model core", core: "Model core", design: "Model core", remindcore: "Model core", modelformulation: "Model core",
  rse: "RSE", researchsoftware: "RSE", researchsoftwareengineering: "RSE", other: "Other" };
// focus-topic columns of the 'Projects' tab that describe a sector group; the others are themes
const FOCUS_TO_SECTOR = { Transport: "Transport", Buildings: "Buildings", Industry: "Industry", Power: "Energy supply",
  H2: "Energy supply", CDR: "CDR / CarMa", Macro: "IAM" };
const STATUS = { active: ["●", "Active"], proposal: ["◌", "Proposal"], finished: ["✓", "Finished"], rejected: ["✕", "Rejected"] };
const SCOPES = { active: ["Active", ["active"]], pipeline: ["Active + Proposals", ["active", "proposal"]], all: ["All", null] };
const VIEWS = { overview: viewOverview, demands: viewDemands, timeline: viewTimeline, projects: viewProjects, people: viewPeople, info: viewInfo, log: viewLog };

let session = null, D = null, failures = 0;
let state = {};

// ---------------------------------------------------------------- theme (per-viewer convenience only)
const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } } };
function applyTheme(t) { if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; }
applyTheme(store.get("etl-theme"));
$("#theme").textContent = "Theme: " + (document.documentElement.dataset.theme || "auto");
$("#theme").addEventListener("click", () => {
  const order = [null, "light", "dark"], cur = document.documentElement.dataset.theme || null;
  const next = order[(order.indexOf(cur) + 1) % order.length];
  applyTheme(next); store.set("etl-theme", next || "auto");
  $("#theme").textContent = "Theme: " + (next || "auto");
});

// ---------------------------------------------------------------- login
$("#login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const button = $("#login-form button"), input = $("#password");
  button.disabled = true;
  button.textContent = "Unlocking…";
  input.removeAttribute("aria-invalid");
  $("#login-error").textContent = "";
  try {
    session = await unlock(PAYLOAD, input.value);
    input.value = "";
    failures = 0;
    start();
  } catch {
    failures += 1;
    await new Promise((r) => setTimeout(r, Math.min(failures, 5) * 800));   // slows guessing in the UI
    $("#login-error").textContent = "Wrong password.";
    input.setAttribute("aria-invalid", "true");
    input.select();
  } finally {
    button.disabled = false;
    button.textContent = "Unlock";
  }
});
$("#logout").addEventListener("click", () => { session = null; D = null; location.reload(); });

function start() {
  D = prepare(session.data);
  $("#login").hidden = true;
  $("#app").hidden = false;
  // the label of a special data mode travels inside its own encrypted data (nothing in the page reveals it)
  const mode = session.data.mode_label || "";
  $("#role").textContent = mode ? session.data.mode_badge || "special" : session.role;
  $("#log-tab").hidden = !session.admin?.log;
  $("#mode-banner").textContent = mode;
  $("#mode-banner").hidden = !mode;
  $("#built").textContent = "Data as of " + fmtDate(session.data.generated_at);
  setupUpdate();
  window.addEventListener("hashchange", render);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.p) setState({ p: null }); });
  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => state.view === "timeline" && render(), 150); });
  render();
}

// ---------------------------------------------------------------- update button (Apps Script companion / local dev server)
function toast(html, ms = 8000) {
  const t = $("#toast");
  t.innerHTML = html;
  t.hidden = false;
  clearTimeout(t._timer);
  if (ms) t._timer = setTimeout(() => { t.hidden = true; }, ms);
}
async function siteVersion() {
  try { const r = await fetch("version.txt", { cache: "no-store" }); return r.ok ? (await r.text()).trim() : null; } catch { return null; }
}
let BASE_VERSION = null, WATCHING = false;
function watchForNewVersion() {   // offer a reload once the new build is published
  if (WATCHING || !BASE_VERSION) return;
  WATCHING = true;
  let n = 0;
  const timer = setInterval(async () => {
    const v = await siteVersion();
    if (v && v !== BASE_VERSION) {
      clearInterval(timer);
      toast(`New data is available. <button type="button" class="btn" id="reload">Reload</button>`, 0);
      $("#reload").addEventListener("click", () => location.reload());
    }
    if (++n > 72) { clearInterval(timer); WATCHING = false; }   // stop after ~12 minutes
  }, 10000);
}
async function setupUpdate() {
  const cfg = session.data.update, btn = $("#update");
  if (!cfg) return;
  btn.hidden = false;
  const base = await siteVersion();
  BASE_VERSION = base;
  const watch = () => watchForNewVersion();
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Updating…";
    try {
      const r = await fetch(cfg.url, { method: "POST", headers: { "Content-Type": "text/plain;charset=utf-8" },
        body: JSON.stringify({ action: "update", key: cfg.key }) });
      const res = await r.json().catch(() => ({}));
      if (!r.ok || res.ok === false) throw new Error(res.message || `HTTP ${r.status}`);
      toast("Update requested. The page offers to reload when the new data is published (usually 2–4 minutes).");
      watch();
    } catch (e) {
      toast(`The update could not be requested: ${esc(e.message)}`);
    } finally {
      setTimeout(() => { btn.disabled = false; btn.textContent = "Update data"; }, 60000);
    }
  });
}


// ---------------------------------------------------------------- corrections (admin only, phase 6b)
const canEdit = () => Boolean(session?.admin?.edit_key && session.data.update?.url);
/** Admin logged in, but the site has no edit endpoint yet (Apps Script companion not set up): say so. */
function editingOffNote() {
  if (canEdit() || !session?.admin) return "";
  return `<div class="banner">Editing on the website is not switched on yet. It needs the Google Apps Script companion
    (setup guide, step 4) and the GitHub settings <code>ETL_UPDATE_URL</code> and <code>ETL_EDIT_KEY</code>.
    Until then, edit the overview documents directly in Drive.</div>`;
}
const canEditProject = (p) => canEdit() && p?.has_overview_doc && !/^template\b/i.test(p.source?.file || "");   // never write into the template
const FIELD_HINT = { name: "Project acronym (it is also the start of the document name).", status: "Proposal / Active / Finished / Rejected.",
  duration: "MM/YYYY-MM/YYYY; add (tbc) while not final.", funding: "Amount for PIK and the part for ETL, with currency (e.g. 500k EUR).",
  funding_pik: "Amount only, e.g. 500k.", funding_etl: "Amount only.", currency: "EUR / USD.", funding_secured: "Yes / Partly / No (+ short note).",
  project_lead: "Full name (Organisation).", etl_main: "Full names; sub-project tag: [Sub] First Last.", etl_pi: "Full name(s).",
  etl_other: "Full names, or 'sector teams tbd'.", pik_other: "Team: full names, e.g. IAM/CarMa: First Last.",
  funder: "Funding agency – contact person, email.", folder_internal: "Paste the folder URL.", folder_consortium: "Paste the folder URL.",
  strategy: "Our role: Lead / Co-lead / Partner / Subcontractor – then free text.", synergies: "Project acronyms, comma-separated.",
 };
const COL_HINT = { description: "What the task / demand is about.", effort: "Person-months (number) or 'flex'.", start: "MM/YYYY.",
  deadline: "MM/YYYY.", lead: "Full name of the responsible person.", others: "Full names, comma-separated.",
  status: "Planned / Ongoing / Done / At risk / Dropped.", task_refs: "Task IDs, e.g. T2.1.", flexibility: "Low / Medium / High.",
  priority: "Must / Should / Could.", sector_lead: "Full name.", project_contact: "Full name.", snippet: "Short quote from the proposal.",
  source: "e.g. Proposal p. 12." };
const COL_LABEL = { description: "Description", effort: "Effort [PM]", start: "Start", deadline: "Deadline", lead: "Lead", others: "Others",
  status: "Status", task_refs: "Task Nr", flexibility: "Flexibility", priority: "Priority", sector_lead: "Sector lead",
  project_contact: "Project contact", snippet: "Snippet", source: "Source" };
const MONTH_RX = /^(0?[1-9]|1[0-2])\/(\d{2}|\d{4})$/;
const CHECKS = { start: (v) => !v || MONTH_RX.test(v) || "Use MM/YYYY.", deadline: (v) => !v || MONTH_RX.test(v) || /^flex/i.test(v) || "Use MM/YYYY.",
  effort: (v) => !v || /^\d+([.,]\d+)?$/.test(v) || /^flex(ible)?$/i.test(v) || "A number of person-months, or 'flex'.",
  duration: (v) => !v || /^\d{1,2}\/\d{2,4}\s*-\s*\d{1,2}\/\d{2,4}/.test(v) || "Use MM/YYYY-MM/YYYY." };
let EDITS = [];   // edit groups of the current render, referenced by index from data-edit buttons
const pending = new Set();   // "file|table|row|col" saved but not yet in a rebuilt page

function registerEdit(title, items) { EDITS.push({ title, items }); return EDITS.length - 1; }
const editKey = (it) => `${it.file}|${it.table_index}|${it.row}|${it.col}`;
const pencil = (idx, label) => (idx == null ? "" : `<button type="button" class="pencil" data-edit="${idx}" aria-label="${esc("Edit " + label)}" title="Edit">✎</button>`);

function fieldEdit(p, f) {
  const v = p.fields?.[f];
  if (!canEditProject(p) || !v?.loc || ["name", "template_version", "last_reviewed"].includes(f)) return null;
  const idx = registerEdit(`${p.name} · ${v.label}`, [{ key: f, isOverview: true, label: v.label, hint: FIELD_HINT[f], check: CHECKS[f], file: v.loc.file, file_id: p.source?.id,
    table_index: v.loc.table_index, row: v.loc.row, col: v.loc.col, old: v.raw, ref: v, refKey: "raw" }]);
  EDITS[idx].issues = issuesFor(p, v.label);
  return idx;
}
function rowEdit(p, title, loc) {
  if (!canEdit() || !loc || loc.table_index == null) return null;
  const items = Object.entries(loc.cols || {}).filter(([c]) => COL_HINT[c]).map(([c, col]) => ({ key: c, label: COL_LABEL[c], hint: COL_HINT[c],
    check: CHECKS[c], file: loc.file, file_id: p.source?.id, table_index: loc.table_index, row: loc.row_index, col,
    old: loc.raw?.[c] ?? "", ref: loc.raw, refKey: c }));
  return items.length ? registerEdit(`${p.name} · ${title}`, items) : null;
}
function bindEdits(root) { for (const b of $$("button[data-edit]", root)) b.addEventListener("click", (e) => { e.stopPropagation(); openEditor(+b.dataset.edit); }); }

function modalFocus(host, close) {   // keep Tab inside the dialog; give focus back to the opener on close
  const opener = document.activeElement;
  host.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const f = $$("input, textarea, select, button", host).filter((x) => !x.disabled);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  });
  return () => { close(); if (opener && document.contains(opener)) opener.focus(); };
}
// ---------------------------------------------------------------- form controls (shared by every edit form)
const EXAMPLE = { name: "ACRONYM", duration: "01/2026-12/2029 (tbc)", funding_pik: "500k", funding_etl: "300k",
  funding_secured: "Partly – 60% received", project_lead: "Jane Doe (TU Berlin)", partners: "TU Berlin (Jane Doe); University College Cork",
  etl_main: "First Last, First Last; [Sub] First Last", etl_pi: "First Last", etl_other: "First Last, or: sector teams tbd",
  pik_other: "IAM/CarMa: First Last, First Last", funder: "Research Agency X – Jane Doe, jane.doe@example.org",
  folder_internal: "https://drive.google.com/drive/folders/…", folder_consortium: "https://…", mattermost: "~project-name",
  strategy: "Lead – our flagship project on …", synergies: "ACRONYM-1, ACRONYM-2", remarks: "Anything else worth knowing",
  id: "T2.1", description: "Scenario design for …", effort: "6", start: "01/2027",
  deadline: "06/2028", lead: "First Last", others: "First Last, First Last", task_refs: "T2.1", sector_lead: "First Last",
  project_contact: "First Last" };
const STATUS_TASK = ["", "Planned", "Ongoing", "Done", "At risk", "Dropped"];
const CHOICES = { status: ["", "Proposal", "Active", "Finished", "Rejected"], currency: ["", "EUR", "USD", "GBP", "CHF"],
  funding_secured: ["", "Yes", "Partly", "No"], responsible_team: ["", "ETL", "IAM", "CarMa", "GET", "ICP", "RSE", "Macro", "ESM", "LUT"],
  task_status: STATUS_TASK, flexibility: ["", "Low", "Medium", "High"], priority: ["", "Must", "Should", "Could"] };
const PEOPLE_KEYS = new Set(["etl_main", "etl_pi", "etl_other", "pik_other", "lead", "others", "sector_lead", "project_contact"]);
const LONG_KEYS = new Set(["partners", "strategy", "remarks", "funder", "pik_other", "etl_main", "etl_other", "synergies", "description"]);
const MONTH_KEYS = new Set(["start", "deadline"]);
const NOT_A_NAME = /^(etl|iam|carma|lut|get|icp|rse|macro|esm|magpie|pik|sector|sectors|people|team|teams|group|colleagues|tbd|tbc|n\/a|none|-|–)$/i;

const toIsoMonth = (s) => { const m = String(s || "").trim().match(/^(\d{1,2})\/(\d{4}|\d{2})\b/); return m ? `${m[2].length === 2 ? "20" + m[2] : m[2]}-${m[1].padStart(2, "0")}` : ""; };
const fromIsoMonth = (iso) => (iso ? `${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "");

// Longer help for the ⓘ tooltips (the short hint stays visible under the field). Lines: explanation, then examples.
const TIPS = {
  name: ["The project acronym. It is also the start of the document name, so it cannot be changed here.", "ACRONYM", "ACRONYM-Sub (a sub-project)"],
  status: ["Where the project stands. Proposal = submitted or in preparation; Active = approved/running; Finished = ended; Rejected = not funded."],
  duration: ["Start and end month. Use the calendars, or type MM/YYYY-MM/YYYY. Tick tbc while the dates are not final.", "01/2026-12/2029", "03/2027-02/2030 (tbc)"],
  funding_pik: ["Total budget for PIK, amount only (the currency has its own field). k = thousand, M = million.", "500k", "1.2M"],
  funding_etl: ["The part of the PIK budget that goes to ETL. Leave empty in a sub-project if the parent already lists it (counted once).", "300k"],
  currency: ["Currency of the amounts above."],
  funding_secured: ["Is the money contractually secured? Add a short note for partial cases.", "Yes", "Partly – 60% received, rest in 2027"],
  project_lead: ["Who leads the whole project (consortium coordinator), with the organisation if not PIK.", "Jane Doe (TU Berlin)", "First Last (PIK)"],
  partners: ["Main partner organisations outside PIK, with a contact person if known. Separate with ';'.", "TU Berlin (Jane Doe); University College Cork"],
  responsible_team: ["The PIK team doing the REMIND runs / responsible overall."],
  etl_main: ["Who does the day-to-day work and coordination in ETL. Full names, as in the People tab; suggestions appear while typing. For sub-projects prefix the part in brackets.",
    "First Last, First Last", "First Last; [Sub] First Last"],
  etl_pi: ["The ETL principal investigator (guidance / supervision).", "First Last"],
  etl_other: ["Further ETL people involved, or a placeholder while it is open.", "First Last, First Last", "sector teams tbd"],
  pik_other: ["Colleagues from other PIK teams: the team, a colon, then the names.", "IAM/CarMa: First Last, First Last", "LUT: First Last"],
  funder: ["The funding agency, then the contact person and email address.", "Research Agency X – Jane Doe, jane.doe@example.org"],
  folder_internal: ["Link to the internal project folder (proposal, budget, minutes). Paste the full URL.", "https://drive.google.com/drive/folders/…"],
  folder_consortium: ["Link to the folder shared with the whole consortium, if there is one."],
  mattermost: ["The project's Mattermost channel.", "~project-name"],
  strategy: ["Our role (Lead / Co-lead / Partner / Subcontractor), then why the project matters for the group.", "Lead – builds the coupling we need for …"],
  synergies: ["Other projects this one shares work, data or people with: their acronyms.", "ACRONYM-1, ACRONYM-2"],
  remarks: ["Anything else worth knowing that does not fit elsewhere."],
  last_reviewed: ["Filled in automatically: every time this form is saved from the website, the month and your name are written here. It shows how current the overview is, so it cannot be edited by hand.", "11/2026, First Last"],
  proposal: ["The proposal or description of work. Paste a link, or upload the file: it is stored in the project's folder under project_descriptions and linked from the overview."],
  id: ["Task or work-package number from the proposal.", "T2.1", "WP3"],
  description: ["What the task is about, in one or two sentences. Click to see the whole text.", "Scenario design for a net-zero power system"],
  effort: ["Effort in person-months for ETL. Write 'flex' if it is not fixed.", "6", "1.5", "flex"],
  start: ["First month of the task. Use the calendar or type MM/YYYY.", "01/2027"],
  deadline: ["Due month of the task or deliverable. Use the calendar or type MM/YYYY.", "06/2028"],
  lead: ["The person responsible: full name, as in the People tab.", "First Last"],
  others: ["Further people involved: full names, separated by commas.", "First Last, First Last"],
  task_refs: ["Which task(s) of the project need this from the sector group.", "T2.1", "T2.1, T5.4"],
  flexibility: ["How flexible the sector group can be about content or timing. Low = must be delivered as specified."],
  sector_lead: ["Who in the sector group is responsible for delivering it.", "First Last"],
  project_contact: ["Who in the project to talk to about it.", "First Last"],
  full_title: ["The project's full (long) title, as in the proposal.", "Evidence-based assessment of …"],
  website: ["Public project website, if any.", "https://www.example-project.eu"],
  focus_text: ["One line per topic: what the project does on it. Leave empty if the topic is not relevant. Shown as 'sector focus' in the dashboard.",
    "Power: hourly power-system coupling", "Industry: steel and cement demand"],
  _editor: ["Your name is written into the edit log next to every change, because the passwords are shared.", "First Last"],
};
TIPS.status_task = ["Planned / Ongoing / Done / At risk / Dropped."];
function helpTip(key, label) {
  const t = TIPS[key], h = FIELD_HINT[key] || COL_HINT[key];
  if (!t && !h) return "";
  const [text, ...examples] = t || [h];
  const html = `<b>${esc(label)}</b>${esc(text)}${examples.length ? `<span class="tip-ex">Examples:</span><ul>${examples.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}`;
  return `<button type="button" class="help" data-tip="${esc(html)}" aria-label="${esc(`Help for ${label}: ${text}`)}">ⓘ</button>`;
}
function fixIcon(messages) {
  if (!messages?.length) return "";
  const text = messages.join(" · ");
  return `<span class="needs-fix" tabindex="0" role="img" data-tip="${esc(`<b>Needs a fix</b>${esc(text)}`)}" aria-label="${esc("Needs a fix: " + text)}">⚠</span>`;
}

/** The right control for a field: dropdown, calendar, people suggestions, growing text box, or plain input. */
function control(name, key, value, { choiceKey, label = key, compact = false } = {}) {
  value = value ?? "";
  const ph = EXAMPLE[key] ? ` placeholder="${esc("e.g. " + EXAMPLE[key])}"` : "";
  const aria = ` aria-label="${esc(label)}"`;
  const choices = CHOICES[choiceKey || key];
  if (choices) {
    const opts = [...new Set([value, ...choices])];
    return `<select name="${esc(name)}" data-key="${esc(key)}"${aria}>${opts.map((o) => `<option value="${esc(o)}" ${o === value ? "selected" : ""}>${esc(o || "–")}</option>`).join("")}</select>`;
  }
  if (key === "duration") {
    const [a, b] = String(value).split("-");
    return `<input name="${esc(name)}" data-key="duration" value="${esc(value)}"${ph}${aria}>
      <span class="cal-group"><label>from <input type="month" data-dur="from" value="${esc(toIsoMonth(a))}"></label>
      <label>to <input type="month" data-dur="to" value="${esc(toIsoMonth(b))}"></label>
      <label class="inline"><input type="checkbox" data-dur="tbc" ${/tbc|\?/i.test(value) ? "checked" : ""}> tbc</label></span>`;
  }
  if (MONTH_KEYS.has(key)) {
    return `<span class="with-cal"><input name="${esc(name)}" data-key="${esc(key)}" value="${esc(value)}"${ph}${aria}>
      <input type="month" class="cal" data-month-for="${esc(name)}" value="${esc(toIsoMonth(value))}" aria-label="${esc("Pick a month for " + label)}"></span>`;
  }
  const people = PEOPLE_KEYS.has(key) ? ` list="people-list" data-people="1" autocomplete="off"` : "";
  if (LONG_KEYS.has(key) || String(value).length > 60) {
    return `<textarea name="${esc(name)}" data-key="${esc(key)}" class="grow${compact ? " compact" : ""}" rows="1"${ph}${aria}${people}>${esc(value)}</textarea>`;
  }
  return `<input name="${esc(name)}" data-key="${esc(key)}" value="${esc(value)}"${ph}${aria}${people}>`;
}
/** Example + help text + warning/error slots shown under a control. */
const below = (name, key) => `${EXAMPLE[key] ? `<div class="example" data-example-for="${esc(name)}">e.g. ${esc(EXAMPLE[key])}</div>` : ""}
  ${FIELD_HINT[key] || COL_HINT[key] ? `<div class="hint">${esc(FIELD_HINT[key] || COL_HINT[key])}</div>` : ""}
  <div class="field-warn" data-warn-for="${esc(name)}"></div><div class="field-error" data-err-for="${esc(name)}"></div>`;

function peopleDatalist() {
  return `<datalist id="people-list">${(D.people || []).filter((p) => p.active !== false).map((p) => `<option value="${esc(p.name)}">${esc(p.initials || "")}</option>`).join("")}</datalist>`;
}
/** Names in a people field that the people table does not know (or that are ambiguous). Not blocking. */
function checkPeople(text) {
  const exact = new Map(), partial = new Map();
  const put = (m, k, p) => { k = String(k || "").toLowerCase().trim(); if (k) m.set(k, [...(m.get(k) || []), p]); };
  for (const p of D.people || []) {
    put(exact, p.name, p); put(exact, p.initials, p);
    (p.aliases || []).forEach((a) => put(exact, a, p));
    put(partial, p.first, p); put(partial, p.last, p);
  }
  const out = [];
  for (let tok of String(text || "").split(/[,;\n+]| \/ /)) {
    tok = tok.replace(/^\s*\[[^\]]*\]\s*/, "");
    if (tok.includes(":")) tok = tok.split(":").pop();
    tok = tok.replace(/\(.*?\)/g, "").replace(/\?/g, "").trim();
    if (!tok || tok.split(/[\s/]+/).every((w) => NOT_A_NAME.test(w))) continue;
    const hit = exact.get(tok.toLowerCase());
    if (hit && new Set(hit).size === 1) continue;
    const cands = [...new Set(hit || partial.get(tok.toLowerCase()) || [])];
    if (cands.length === 1) out.push(`“${tok}”: write the full name – ${cands[0].name}?`);
    else if (cands.length > 1) out.push(`“${tok}” could be ${cands.map((c) => c.name).join(" / ")}`);
    else out.push(`“${tok}” is not in the people table – check the spelling or add the person on the People tab`);
  }
  return out;
}
/** Behaviour for a rendered form: tooltips, calendars, examples, people checks, growing text boxes. */
function wireForm(host) {
  bindTips(host);
  const form = $("form", host);
  const refresh = (el) => {
    const ex = $(`[data-example-for="${CSS.escape(el.name)}"]`, host);
    if (ex) ex.hidden = Boolean(el.value.trim());
    const warn = $(`[data-warn-for="${CSS.escape(el.name)}"]`, host);
    if (warn && el.dataset.people) {
      const w = checkPeople(el.value);
      warn.textContent = w.length ? "⚠ " + w.join(" · ") : "";
    }
  };
  for (const el of $$("input[name], textarea[name], select[name]", host)) {
    el.addEventListener("input", () => refresh(el));
    el.addEventListener("blur", () => refresh(el));
    refresh(el);
  }
  for (const cal of $$("input[data-month-for]", host)) {
    const text = form.elements[cal.dataset.monthFor];
    cal.addEventListener("change", () => { text.value = fromIsoMonth(cal.value); refresh(text); });
    text.addEventListener("change", () => { cal.value = toIsoMonth(text.value); });
  }
  for (const group of $$(".cal-group", host)) {
    const text = group.previousElementSibling, [from, to, tbc] = ["from", "to", "tbc"].map((k) => $(`[data-dur="${k}"]`, group));
    const compose = () => {
      if (!from.value && !to.value) return;
      text.value = `${fromIsoMonth(from.value)}-${fromIsoMonth(to.value)}${tbc.checked ? " (tbc)" : ""}`;
      refresh(text);
    };
    [from, to, tbc].forEach((el) => el.addEventListener("change", compose));
  }
}
/** Format checks (blocking) for the controls of a form; returns the number of problems. */
function checkFormats(host) {
  let bad = 0;
  for (const el of $$("[data-key]", host)) {
    const check = CHECKS[el.dataset.key]?.(el.value.trim()), slot = $(`[data-err-for="${CSS.escape(el.name)}"]`, host);
    const msg = check && check !== true ? check : "";
    if (slot) slot.textContent = msg;
    el.toggleAttribute("aria-invalid", Boolean(msg));
    if (msg) bad++;
  }
  return bad;
}
async function postEdit(body) {
  const r = await fetch(session.data.update.url, { method: "POST", headers: { "Content-Type": "text/plain;charset=utf-8" },
    body: JSON.stringify({ key: session.admin.edit_key, ...body }) });
  const res = await r.json().catch(() => ({}));
  return { r, res };
}
const editorField = () => `<label class="field editor-field"><span class="field-label">Your name (for the edit log) ${helpTip("_editor", "Your name")}</span>
  <input name="editor" required value="${esc(store.get("etl-editor") || "")}" placeholder="e.g. First Last"></label>`;
FIELD_HINT._editor = "Shown in the edit log next to every change, because the passwords are shared.";

// ---------------------------------------------------------------- single-field / single-row editor (pencils, Fix)
function openEditor(idx) {
  const group = EDITS[idx];
  const host = document.createElement("div");
  host.className = "modal-bg";
  host.innerHTML = `<form class="modal" role="dialog" aria-modal="true" aria-labelledby="edit-title" novalidate>
    <h2 id="edit-title">${esc(group.title)}</h2>
    <p class="small muted">The change is written into the overview document and logged. The dashboard updates after the rebuild.</p>
    ${group.issues?.length ? `<p class="fix-note">${fixIcon(group.issues)} ${esc(group.issues.join(" · "))}</p>` : ""}
    ${group.items.map((it, i) => `<div class="field"><span class="field-label">${esc(it.label)} ${helpTip(it.key, it.label)}${pending.has(editKey(it)) ? ' <span class="pill">saved, rebuilding</span>' : ""}</span>
      ${control(`f${i}`, it.key, it.old, { choiceKey: it.key === "status" && it.table_index !== group.overviewTable ? (it.isOverview ? "status" : "task_status") : undefined, label: it.label })}
      ${below(`f${i}`, it.key)}</div>`).join("")}
    ${editorField()}
    <div class="error" id="edit-msg" role="alert"></div>
    <div class="modal-actions"><button type="button" class="btn-close" data-cancel>Cancel</button><button type="submit" class="btn">Save</button></div></form>
    ${peopleDatalist()}`;
  document.body.appendChild(host);
  wireForm(host);
  const form = $("form", host), close = modalFocus(host, () => host.remove());
  $("[data-cancel]", host).addEventListener("click", close);
  host.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
  $("input[name=f0], textarea[name=f0], select[name=f0]", host)?.focus();
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const editor = form.editor.value.trim(), msg = $("#edit-msg", host);
    if (!editor) { msg.textContent = "Please enter your name."; return; }
    if (checkFormats(host)) { msg.textContent = "Please check the marked values."; return; }
    const changes = group.items.map((it, i) => [it, form[`f${i}`].value.trim()]).filter(([it, v]) => v !== (it.old || "").trim());
    if (!changes.length) { close(); return; }
    store.set("etl-editor", editor);
    $("button[type=submit]", host).disabled = true;
    msg.textContent = "Saving…";
    try {
      const { r, res } = await postEdit({ action: "edit", editor,
        edits: changes.map(([it, value]) => ({ file: it.file, file_id: it.file_id, table_index: it.table_index, row: it.row, col: it.col, old: it.old, new: value })) });
      const results = res.results || changes.map(() => ({ ok: false, message: res.message || `HTTP ${r.status}` }));
      const failed = [];
      results.forEach((x, i) => {
        const [it, value] = changes[i];
        if (x.ok) { it.ref[it.refKey] = value; it.old = value; pending.add(editKey(it)); }
        else failed.push(`${it.label}: ${x.message}${x.current != null ? ` (now: “${x.current}”)` : ""}`);
      });
      if (failed.length) { msg.textContent = failed.join(" · "); $("button[type=submit]", host).disabled = false; return; }
      close();
      toast(`Saved ${changes.length} change${changes.length > 1 ? "s" : ""}. The page offers to reload when the rebuilt data is published.`);
      watchForNewVersion();
      render();
    } catch (e) {
      msg.textContent = `Could not save: ${e.message}`;
      $("button[type=submit]", host).disabled = false;
    }
  });
}

// ---------------------------------------------------------------- project form: create a project / edit all its fields
// Laid out like the overview document: Overview table, task tables, sector requirements, then the proposal.
const V2_FIELDS = [["name", "Name"], ["status", "Status"], ["duration", "Duration"], ["funding_pik", "Funding – total for PIK"],
  ["funding_etl", "Funding – of which ETL"], ["currency", "Currency"], ["funding_secured", "Funding secured"], ["project_lead", "Overall project lead"],
  ["partners", "Other key non-PIK partners"], ["responsible_team", "Mainly responsible PIK team (REMIND runs / overall)?"],
  ["etl_main", "Main ETL researcher (operational / coordination)"], ["etl_pi", "ETL PI (guidance / supervision)"],
  ["etl_other", "Other ETL involvement"], ["pik_other", "Other involved PIK teams and colleagues"],
  ["funder", "Funding agency, main contact person (with email address)"], ["folder_internal", "Link to internal project folder"],
  ["folder_consortium", "Link to project folder shared with entire consortium"], ["full_title", "Full title"],
  ["website", "Project website"], ["mattermost", "Mattermost channel"],
  ["strategy", "Strategic considerations / our role"], ["synergies", "Synergies with (other projects)"], ["remarks", "Other remarks"],
  ["last_reviewed", "Last reviewed (MM/YYYY, name)"]];
const TASK_COLS = { led: [["id", "", "ID"], ["description", "Description"], ["effort", "Effort [PM]"], ["start", "Start"], ["deadline", "Dead-line"],
  ["lead", "ETL lead"], ["others", "others"], ["status", "Status"]],
  contribution: [["id", "", "ID"], ["description", "Description"], ["effort", "Effort [PM]"], ["start", "Start"], ["deadline", "Dead-line"],
  ["lead", "PIK lead"], ["others", "ETL contr."], ["status", "Status"]] };
const DEMAND_COLS = [["description", "Description: what is needed from the sector"], ["task_refs", "Task Nr"], ["effort", "Effort [PM]"],
  ["flexibility", "Flexibility"], ["deadline", "Dead-line"], ["sector_lead", "Sector lead"], ["project_contact", "Project contact"], ["status", "Status"]];
const MAX_UPLOAD = 15 * 1024 * 1024;

function issuesFor(p, field) { return (p?.issues || []).filter((i) => i.field === field).map((i) => i.message); }

function openProjectForm(p) {
  const create = !p, cells = [];   // cells: existing doc cells shown in the form -> cell edits on save
  const cell = (loc, col, value, key) => { cells.push({ loc, col, value: value ?? "", key }); return cells.length - 1; };
  const th = (key, label) => `<th scope="col">${esc(label)} ${helpTip(key, label)}</th>`;
  const overviewRow = ([k, label]) => {
    const f = p?.fields?.[k], value = f?.raw ?? "", issues = issuesFor(p, f?.label ?? label);
    const rowHead = `<th scope="row">${esc(label)} ${helpTip(k, label)} ${fixIcon(issues)}</th>`;
    if (!create && k === "name") return `<tr>${rowHead}<td><b>${esc(value || p.name)}</b> <span class="small muted">(the name is part of the file name and cannot be changed here)</span></td></tr>`;
    if (k === "last_reviewed") return `<tr>${rowHead}<td>${esc(value) || '<span class="muted">not yet</span>'} <span class="small muted">· updated automatically when you save</span></td></tr>`;
    const name = !create && f?.loc ? `c${cell(f.loc, f.loc.col, value, k)}` : `o_${k}`;
    return `<tr${issues.length ? ' class="needs-fix-row"' : ""}>${rowHead}<td>${control(name, k, value, { label })}${below(name, k)}</td></tr>`;
  };
  const taskCell = (t, c, label) => {
    const pos = c === "id" ? 0 : t.loc.cols?.[c];
    if (c === "id") return `<td><b>${esc(t.code || "–")}</b> ${fixIcon(issuesFor(p, `task ${t.code || t.description.slice(0, 30)}`))}</td>`;
    if (pos == null) return `<td class="muted">–</td>`;
    const v = t.loc.raw?.[c] ?? "", name = `c${cell(t.loc, pos, v, c)}`;
    return `<td class="cellwrap">${control(name, c, v, { choiceKey: c === "status" ? "task_status" : undefined, label: `${t.code} ${label}`, compact: true })}${below(name, c)}</td>`;
  };
  const taskTable = (kind, caption) => {
    const cols = TASK_COLS[kind], rows = (p?.tasks || []).filter((t) => t.loc?.table_index != null && (kind === "led") === t.kind.includes("led"));
    let section = null;
    const body = rows.map((t) => {
      const head = t.section !== section ? (section = t.section, t.section ? `<tr class="section-row"><td colspan="${cols.length}">${esc(t.section)}</td></tr>` : "") : "";
      return head + `<tr>${cols.map(([c, label]) => taskCell(t, c, label)).join("")}</tr>`;
    }).join("");
    return `<p class="caption">${esc(caption)}</p><div class="table-wrap"><table class="form-table doc-like"><thead><tr>${cols.map(([c, l, aria]) => th(c, l || aria)).join("")}</tr></thead>
      <tbody data-new-tasks="${kind}">${body}</tbody></table></div>
      <button type="button" class="btn-close" data-add-task="${kind}">+ Add ${kind === "led" ? "ETL-led" : "ETL-contribution"} task</button>`;
  };
  const slots = create ? SECTORS.map((s) => ({ sector: s })) : (D.demand_slots || []).filter((s) => s.project_id === p.id && s.kind !== "focus");
  const demandRows = slots.map((s, i) => `<tr><th scope="row">${esc(s.sector)} ${fixIcon(issuesFor(p, `demand ${s.sector}`))}</th>${DEMAND_COLS.map(([c, label]) => {
    if (create) return `<td class="cellwrap">${control(`d${i}_${c}`, c, "", { choiceKey: c === "status" ? "task_status" : undefined, label: `${s.sector} ${label}`, compact: true })}${below(`d${i}_${c}`, c)}</td>`;
    const pos = s.loc.cols?.[c], v = s.loc.raw?.[c] ?? "";
    if (pos == null) return `<td class="muted">–</td>`;
    const name = `c${cell(s.loc, pos, v, c)}`;
    return `<td class="cellwrap">${control(name, c, v, { choiceKey: c === "status" ? "task_status" : undefined, label: `${s.sector} ${label}`, compact: true })}${below(name, c)}</td>`;
  }).join("")}</tr>`).join("");
  const FOCUS_TOPICS = ["Macro", "Power", "Transport", "Buildings", "Industry", "CDR", "Region focus", "EU", "Sector coupling", "H2", "Finance", "Policies", "Investment/Cost"];
  const focusSlots = create ? FOCUS_TOPICS.map((t) => ({ topic: t })) : (D.demand_slots || []).filter((s) => s.project_id === p.id && s.kind === "focus");
  const generalIssues = (p?.issues || []).filter((i) => /requirements|^tasks?\b/i.test(i.field || "")).map((i) => i.message);
  const host = document.createElement("div");
  host.className = "modal-bg";
  host.innerHTML = `<form class="modal wide doc-form" role="dialog" aria-modal="true" aria-labelledby="pf-title" novalidate>
    <h2 id="pf-title" class="doc-title">Project overview${create ? " – new project" : ` – ${esc(p.name)}`}</h2>
    <p class="small muted">${create ? "Creates a new overview document (template v2) in the overview folder." : `Changes are written into ${esc(p.source.file)}.`}
      Everything is logged with your name. You can keep editing the document directly as well – both routes end up in the same file.
      Hover ⓘ for help; ⚠ marks values that cannot be read or need a fix.</p>
    <h3 class="doc-h2">Overview</h3>
    <table class="doc-table"><tbody>${V2_FIELDS.map(overviewRow).join("")}</tbody></table>
    <h3 class="doc-h3">Short summary of tasks and responsibilities ${fixIcon(generalIssues.filter((m) => /task/i.test(m)))}</h3>
    ${taskTable("led", "ETL-led tasks:")}
    ${taskTable("contribution", "ETL-contribution tasks:")}
    <p class="caption">REMIND requirements / sector requirements: ${fixIcon(generalIssues.filter((m) => /sector|requirement/i.test(m)))}</p>
    ${slots.length ? `<div class="table-wrap"><table class="form-table doc-like"><thead><tr><th scope="col">Sector</th>${DEMAND_COLS.map(([c, l]) => th(c, l)).join("")}</tr></thead>
      <tbody>${demandRows}</tbody></table></div>` : `<p class="small muted">This document has no sector requirements table yet – add it from the current template in the document.</p>`}
    <p class="caption">Focus topics: ${helpTip("focus_text", "Focus topics")}</p>
    ${focusSlots.length ? `<table class="doc-table"><tbody>${focusSlots.map((s, i) => {
      if (create) return `<tr><th scope="row">${esc(s.topic)}</th><td>${control(`f_${i}`, "focus_text", "", { label: s.topic })}</td></tr>`;
      const pos = s.loc.cols?.focus_text, v = s.loc.raw?.focus_text ?? "";
      return `<tr><th scope="row">${esc(s.topic)}</th><td>${pos == null ? "–" : control(`c${cell(s.loc, pos, v, "focus_text")}`, "focus_text", v, { label: s.topic })}</td></tr>`; }).join("")}</tbody></table>`
      : `<p class="small muted">This document has no focus-topics table yet – add it from the current template.</p>`}
    <h3 class="doc-h3">Proposal / description of work ${helpTip("proposal", "Proposal")}</h3>
    <div class="form-grid">
      <label class="field"><span class="field-label">Link</span><input name="proposal_url" placeholder="e.g. https://drive.google.com/file/d/…"></label>
      <label class="field"><span class="field-label">…or upload a file (PDF, Word, ≤ 15 MB)</span><input type="file" name="proposal_file" accept=".pdf,.docx,.doc,.odt,.pptx,.xlsx,.txt,.md"></label>
    </div>
    ${editorField()}
    <div class="error" id="pf-msg" role="alert"></div>
    <div class="modal-actions"><button type="button" class="btn-close" data-cancel>Cancel</button><button type="submit" class="btn">${create ? "Create project" : "Save changes"}</button></div></form>
    ${peopleDatalist()}`;
  document.body.appendChild(host);
  wireForm(host);
  const form = $("form", host), close = modalFocus(host, () => host.remove()), msg = $("#pf-msg", host);
  let newTasks = 0;
  $("[data-cancel]", host).addEventListener("click", close);
  host.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
  for (const btn of $$("[data-add-task]", host)) btn.addEventListener("click", () => {
    const kind = btn.dataset.addTask, i = newTasks++;
    const row = document.createElement("tr");
    row.className = "new";
    row.innerHTML = TASK_COLS[kind].map(([c, l, aria]) => `<td class="cellwrap">${control(`n${i}_${c}`, c, "", { choiceKey: c === "status" ? "task_status" : undefined, label: `new task ${l || aria}`, compact: true })}${below(`n${i}_${c}`, c)}</td>`).join("")
      + `<input type="hidden" name="n${i}_kind" value="${kind}">`;
    $(`[data-new-tasks="${kind}"]`, host).appendChild(row);
    wireForm(row.closest(".modal-bg"));
    form.elements[`n${i}_id`].focus();
  });
  form.querySelector(".doc-table input, .doc-table textarea, .doc-table select")?.focus();
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const val = (n) => (form.elements[n]?.value ?? "").trim(), editor = val("editor");
    if (!editor) { msg.textContent = "Please enter your name."; return; }
    if (create && !/^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$/.test(val("o_name"))) {
      $('[data-err-for="o_name"]', host).textContent = "Use the project acronym (letters, digits, - _ .).";
      msg.textContent = "Please check the marked values."; return;
    }
    if (checkFormats(host)) { msg.textContent = "Please check the marked values."; return; }
    const overview = {}, overviewAdd = {};
    for (const [k] of V2_FIELDS) {
      if (create) overview[k] = val(`o_${k}`);
      else if (form.elements[`o_${k}`] && val(`o_${k}`)) overviewAdd[k] = val(`o_${k}`);
    }
    const edits = cells.map((c, i) => ({ c, value: val(`c${i}`) })).filter(({ c, value }) => value !== String(c.value).trim())
      .map(({ c, value }) => ({ table_index: c.loc.table_index, row: c.loc.row ?? c.loc.row_index, col: c.col, old: c.value, new: value, file_id: p?.source?.id }));
    const tasks = [];
    for (let i = 0; i < newTasks; i++) {
      const t = Object.fromEntries(TASK_COLS.led.map(([c]) => [c, val(`n${i}_${c}`)]));
      if (Object.values(t).some(Boolean)) tasks.push({ ...t, kind: val(`n${i}_kind`) });
    }
    const focus = create ? Object.fromEntries(focusSlots.map((s, i) => [s.topic, val(`f_${i}`)])) : {};
    const demands = create ? Object.fromEntries(slots.map((s, i) => [s.sector, Object.fromEntries(DEMAND_COLS.map(([c]) => [c, val(`d${i}_${c}`)]))])) : {};
    const file = form.proposal_file.files[0], url = val("proposal_url");
    if (url && !/^https:\/\/\S+$/.test(url)) { msg.textContent = "The proposal link must start with https://"; return; }
    if (file && file.size > MAX_UPLOAD) { msg.textContent = "The file is larger than 15 MB."; return; }
    let proposal = null;
    if (file) proposal = { name: file.name, data: await new Promise((res, rej) => {
      const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1]); r.onerror = rej; r.readAsDataURL(file); }) };
    else if (url) proposal = { url };
    if (!create && !edits.length && !tasks.length && !proposal && !Object.keys(overviewAdd).length) { close(); return; }
    store.set("etl-editor", editor);
    $("button[type=submit]", host).disabled = true;
    msg.textContent = "Saving…";
    try {
      const { r, res } = await postEdit({ action: "save_project", editor, mode: create ? "create" : "update", file: p?.source?.file,
        file_id: p?.source?.id, project_id: p?.id, overview, overview_add: overviewAdd, edits, new_tasks: tasks, demands, focus, proposal });
      const failed = (res.results || []).map((x) => (x.ok ? null : `${x.message}${x.current != null ? ` (now: “${x.current}”)` : ""}`)).filter(Boolean);
      if (!r.ok || res.ok === false) { msg.textContent = [res.message || `HTTP ${r.status}`, ...failed].join(" · "); $("button[type=submit]", host).disabled = false; return; }
      close();
      toast(`${create ? "Project created" : "Changes saved"}. The page offers to reload when the rebuilt data is published.`);
      watchForNewVersion();
    } catch (e) {
      msg.textContent = `Could not save: ${e.message}`;
      $("button[type=submit]", host).disabled = false;
    }
  });
}

// ---------------------------------------------------------------- data
function sectorOf(s) { return SECTOR_KEYS[String(s || "").toLowerCase().replace(/[^a-z]/g, "")] || (s ? "Other" : null); }
function prepare(data) {
  const projects = data.projects.filter((p) => !p.excluded);
  const byId = Object.fromEntries(projects.map((p) => [p.id, p]));
  for (const p of projects) {
    Object.assign(p, { tasks: [], demands: [], snippets: [], issues: [], sectors: {}, themes: {} });
    for (const [topic, text] of Object.entries(p.focus || {})) {
      const s = FOCUS_TO_SECTOR[topic];
      if (s) (p.sectors[s] ||= { demands: [], focus: [] }).focus.push({ topic, text });
      else p.themes[topic] = text;
    }
  }
  for (const t of data.tasks) byId[t.project_id]?.tasks.push(t);
  for (const d of data.demands) {
    const p = byId[d.project_id]; if (!p) continue;
    d.group = sectorOf(d.sector);
    p.demands.push(d);
    (p.sectors[d.group] ||= { demands: [], focus: [] }).demands.push(d);
  }
  for (const s of data.snippets) byId[s.project_id]?.snippets.push(s);
  const general = [];
  for (const i of data.issues) (byId[i.project]?.issues ?? general).push(i);
  return { ...data, projects, byId, general };
}
function inScope() {
  const allowed = SCOPES[state.scope][1];
  return D.projects.filter((p) => !allowed || allowed.includes(p.status))
    .sort((a, b) => a.name.localeCompare(b.name));
}
const warnings = (p) => p.issues.filter((i) => i.severity === "warning").length;

// ---------------------------------------------------------------- formatting
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const nowMonth = () => { const d = new Date(); return d.getFullYear() * 12 + d.getMonth(); };
const mIndex = (s) => (s ? +s.slice(0, 4) * 12 + (+s.slice(5, 7) - 1) : null);
const fmtMonth = (s) => (s ? `${MONTHS[+s.slice(5, 7) - 1]} ${s.slice(0, 4)}` : "–");
function fmtDate(iso) { const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); }
function fmtMoney(v, cur) {
  if (v == null) return "–";
  const opts = { notation: "compact", maximumFractionDigits: 1 };
  return cur ? new Intl.NumberFormat("en", { ...opts, style: "currency", currency: cur }).format(v) : new Intl.NumberFormat("en", opts).format(v);
}
const fmtPM = (v) => (v == null ? "–" : `${Math.round(v * 10) / 10} PM`);
function people(list) {
  if (!list || !list.length) return "–";
  return list.map((m) => esc((m.section && m.section !== "Main" ? `[${m.section}] ` : "") + m.name + (m.uncertain ? "?" : "")) +
    (m.candidates?.length ? ` <span class="muted small">(${esc(m.candidates.join(" / "))}?)</span>` : "")).join(", ");
}
const statusChip = (s, p) => {
  const unsure = p && p.status_source === "default";   // no Status row, and the duration does not show it
  return `<span class="chip ${esc(s)}"${unsure ? ' title="Status not confirmed – see Review"' : ""}><span aria-hidden="true">${(STATUS[s] || ["?"])[0]}</span>${esc((STATUS[s] || [s, s])[1])}${unsure ? "?" : ""}</span>`;
};
const projLink = (p) => `<a href="${esc(hrefWith({ p: p.id }))}">${esc(p.name)}</a>`;

// ---------------------------------------------------------------- routing
function readState() {
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const q = new URLSearchParams(query || "");
  return { view: VIEWS[path] ? path : "overview", scope: SCOPES[q.get("scope")] ? q.get("scope") : "active",
    group: q.get("group") || "", layer: q.get("layer") || "", sev: q.get("sev") || "warning",
    sort: q.get("sort") || "name", dir: q.get("dir") || "asc", q: q.get("q") || "", p: q.get("p") || null };
}
function hrefWith(patch) {
  const s = { ...state, ...patch };
  const q = new URLSearchParams();
  for (const k of ["scope", "group", "layer", "sev", "sort", "dir", "q", "p"]) {
    const dflt = { scope: "active", sev: "warning", sort: "name", dir: "asc" }[k] ?? "";
    if (s[k] && s[k] !== dflt) q.set(k, s[k]);
  }
  const qs = q.toString();
  return `#/${s.view}${qs ? "?" + qs : ""}`;
}
function setState(patch, replace = false) {
  const url = hrefWith(patch);
  if (replace) { history.replaceState(null, "", url); state = readState(); } else location.hash = url;
}

function render() {
  const prev = state.view;
  state = readState();
  for (const a of $$("nav.tabs a")) {
    a.href = hrefWith({ view: a.dataset.view, p: null, group: "", layer: "" });
    a.toggleAttribute("aria-current", a.dataset.view === state.view);
    if (a.dataset.view === state.view) a.setAttribute("aria-current", "page");
  }
  renderFilters();
  EDITS = [];
  VIEWS[state.view]($("#view"));
  bindEdits($("#view"));
  renderDrawer();
  if (prev && prev !== state.view) $("#view").focus({ preventScroll: true });
}

function seg(name, options, current) {
  return `<span class="seg" role="group" aria-label="${esc(name)}">${options.map(([v, label]) =>
    `<button type="button" data-set="${esc(name)}" data-value="${esc(v)}" aria-pressed="${v === current}">${esc(label)}</button>`).join("")}</span>`;
}
function renderFilters() {
  const parts = state.view === "people" || state.view === "log" ? [] : [`<span><span class="filter-label">Projects</span>${seg("scope", Object.entries(SCOPES).map(([k, v]) => [k, v[0]]), state.scope)}</span>`];
  if (state.view === "demands") {
    parts.push(`<span><span class="filter-label">Show</span>${seg("layer", [["demands", "Sector demands"], ["focus", "Focus topics"]], layer())}</span>`);
  }
  if (state.view === "demands" || state.view === "timeline") {
    parts.push(`<label><span class="filter-label">Sector group</span><select id="group">
      <option value="">${state.view === "timeline" ? "All ETL" : "All sector groups"}</option>
      ${SECTORS.map((s) => `<option ${s === state.group ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></label>`);
  }
  if (state.view === "info") parts.push(`<span><span class="filter-label">Show</span>${seg("sev", [["warning", "Warnings"], ["all", "All notes"]], state.sev)}</span>`);
  const el = $("#filters");
  el.innerHTML = parts.join("");
  for (const b of $$("button[data-set]", el)) b.addEventListener("click", () => setState({ [b.dataset.set]: b.dataset.value }));
  $("#group", el)?.addEventListener("change", (e) => setState({ group: e.target.value }));
}
const layer = () => state.layer || "demands";   // sector demands by default; focus topics on request

// ---------------------------------------------------------------- tooltip
function bindTips(root) {
  const tip = $("#tooltip");
  const show = (el, x, y) => {
    tip.innerHTML = el.dataset.tip;
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    tip.style.left = Math.min(x + 14, innerWidth - r.width - 8) + "px";
    tip.style.top = Math.min(y + 14, innerHeight - r.height - 8) + "px";
  };
  for (const el of $$("[data-tip]", root)) {
    el.addEventListener("mousemove", (e) => show(el, e.clientX, e.clientY));
    el.addEventListener("mouseleave", () => { tip.hidden = true; });
    el.addEventListener("focus", () => { const r = el.getBoundingClientRect(); show(el, r.right, r.top); });
    el.addEventListener("blur", () => { tip.hidden = true; });
  }
}
function bindOpen(root) {
  for (const el of $$("[data-open]", root)) {
    const open = () => setState({ p: el.dataset.open });
    el.addEventListener("click", (e) => { if (!e.target.closest("a")) open(); });
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  }
}

// ---------------------------------------------------------------- Overview
function viewOverview(root) {
  const P = inScope(), now = nowMonth();
  const tasks = P.flatMap((p) => p.tasks), demands = P.flatMap((p) => p.demands);
  const pm = tasks.reduce((s, t) => s + (t.effort.pm || 0), 0);
  const upcoming = [...tasks.map((t) => ({ kind: "Task", label: t.code || t.description, text: t.description, when: t.deadline, p: D.byId[t.project_id] })),
    ...demands.map((d) => ({ kind: "Demand", label: d.group, text: d.description, when: d.deadline, p: D.byId[d.project_id] }))]
    .filter((x) => x.when && mIndex(x.when) >= now).sort((a, b) => a.when.localeCompare(b.when));
  const soon = upcoming.filter((x) => mIndex(x.when) <= now + 3).length;
  const docs = P.filter((p) => p.has_overview_doc);
  const warn = P.reduce((s, p) => s + warnings(p), 0);
  const counts = Object.fromEntries(Object.keys(STATUS).map((s) => [s, P.filter((p) => p.status === s).length]));
  const coverage = SECTORS.map((s) => [s, P.filter((p) => p.sectors[s]).length]);
  const maxCov = Math.max(1, ...coverage.map((c) => c[1]));
  const attention = docs.filter((p) => warnings(p)).sort((a, b) => warnings(b) - warnings(a)).slice(0, 6);
  root.innerHTML = `
    <section class="grid kpis" aria-label="Key figures">
      ${kpi(P.length, "Projects", Object.entries(counts).filter(([, n]) => n).map(([s, n]) => `${n} ${STATUS[s][1].toLowerCase()}`).join(" · "))}
      ${kpi(`${docs.length}`, "With overview doc", `of ${P.length} in view`)}
      ${kpi(fmtPM(pm), "ETL effort in tasks", `${tasks.length} tasks · ${tasks.filter((t) => t.effort.flexible).length} flexible`)}
      ${kpi(demands.length, "Sector demands", demands.length ? `${new Set(demands.map((d) => d.group)).size} sector groups` : "none recorded yet")}
      ${kpi(soon, "Deadlines · next 3 months", upcoming.length ? `next: ${fmtMonth(upcoming[0].when)}` : "none upcoming")}
      ${kpi(warn, "Open data issues", "missing or unclear entries", hrefWith({ view: "info", p: null }))}
    </section>
    <div class="grid two">
      <section class="card"><div class="card-head"><h2>Next deadlines</h2><a href="${esc(hrefWith({ view: "timeline", p: null }))}">Timeline →</a></div>
        ${upcoming.length ? `<ul class="deadlines">${upcoming.slice(0, 8).map((x) => `<li><span class="when">${fmtMonth(x.when)}</span>
          <span>${projLink(x.p)} · <span class="pill">${esc(x.kind)}</span> ${esc(x.label)}
          ${x.text && x.text !== x.label ? `<div class="small muted">${esc(x.text.slice(0, 110))}</div>` : ""}</span></li>`).join("")}</ul>`
          : `<p class="empty">No dated tasks or demands ahead.</p>`}
      </section>
      <section class="card"><div class="card-head"><h2>Sector coverage</h2><a href="${esc(hrefWith({ view: "demands", p: null }))}">Demands →</a></div>
        <p class="small muted">Projects in view with a sector demand or a focus topic in their overview doc.</p>
        <div class="bars">${coverage.map(([s, n]) => `<span>${esc(s)}</span>
          <svg class="track" viewBox="0 0 100 10" preserveAspectRatio="none" data-tip="<b>${esc(s)}</b>${n} project${n === 1 ? "" : "s"}" aria-hidden="true">
            <rect class="trackbg" width="100" height="10"/><rect class="fill" width="${((n / maxCov) * 100).toFixed(1)}" height="10"/></svg>
          <span class="num small">${n}</span>`).join("")}</div>
      </section>
    </div>
    <section class="card mt"><div class="card-head"><h2>Overview docs needing attention</h2><a href="${esc(hrefWith({ view: "info", p: null }))}">All issues →</a></div>
      ${attention.length ? `<div class="table-wrap"><table><thead><tr><th>Project</th><th>Status</th><th>Warnings</th><th class="hide-sm">Top issue</th></tr></thead><tbody>
        ${attention.map((p) => { const i = p.issues.find((x) => x.severity === "warning");
          return `<tr class="clickable" tabindex="0" data-open="${esc(p.id)}"><td>${esc(p.name)}</td><td>${statusChip(p.status, p)}</td>
          <td class="num">${warnings(p)}</td><td class="hide-sm">${esc(i.field)}: ${esc(i.message)}</td></tr>`; }).join("")}</tbody></table></div>`
        : `<p class="empty">No open issues in the overview docs.</p>`}
    </section>`;
  bindTips(root); bindOpen(root);
}
function kpi(value, label, sub, href) {
  const inner = `<div class="value">${esc(value)}</div><div class="label">${esc(label)}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}`;
  return href ? `<a class="card kpi" href="${esc(href)}">${inner}</a>` : `<div class="card kpi">${inner}</div>`;
}

// ---------------------------------------------------------------- Demands by group
function viewDemands(root) {
  const L = layer(), sectors = state.group ? [state.group] : SECTORS;
  const P = inScope().filter((p) => (L === "demands" ? p.has_overview_doc : Object.values(p.sectors).some((s) => s.focus.length)));
  const cellItems = (p, s) => (p.sectors[s] ? p.sectors[s][L === "demands" ? "demands" : "focus"] : []);
  const maxPM = Math.max(1, ...P.flatMap((p) => sectors.map((s) => cellItems(p, s).reduce((a, d) => a + (d.effort?.pm || 0), 0))));
  const shade = (pm) => `seq-${pm ? Math.min(5, 1 + Math.floor((pm / maxPM) * 4.999)) : 1}`;
  const banner = L === "demands" && !D.demands.length
    ? `<div class="banner">No sector demands are recorded in the overview docs yet – the “REMIND requirements / sector requirements”
       tables are empty or missing (see <a href="${esc(hrefWith({ view: "info", p: null }))}">Review</a>).
       <button type="button" class="btn-close" data-set="layer" data-value="focus">Show the focus topics instead</button></div>` : "";
  const cell = (p, s) => {
    const items = cellItems(p, s);
    if (!items.length) return `<td><span class="sr-only">none</span></td>`;
    const tip = `<b>${esc(p.name)} · ${esc(s)}</b>` + items.map((x) => L === "demands"
      ? `${esc(x.description || "(no description)")} <span class="muted">${x.effort?.pm != null ? fmtPM(x.effort.pm) : ""} ${x.deadline ? "· " + fmtMonth(x.deadline) : ""}</span>`
      : `<span class="muted">${esc(x.topic)}:</span> ${esc(x.text)}`).join("<br>");
    const pm = items.reduce((a, d) => a + (d.effort?.pm || 0), 0);
    const mark = L === "demands"
      ? `<span class="cell-btn ${shade(pm)}">${pm ? Math.round(pm) : items.length}</span>`
      : `<span class="dot" aria-hidden="true"></span>`;
    return `<td><span class="cell-btn" role="button" tabindex="0" data-open="${esc(p.id)}" data-tip="${esc(tip)}"
      aria-label="${esc(`${p.name}, ${s}: ${items.length} ${L === "demands" ? "demand(s)" : "focus topic(s)"}`)}">${mark}</span></td>`;
  };
  const detail = sectors.map((s) => {
    const rows = P.filter((p) => cellItems(p, s).length);
    if (!rows.length) return "";
    return `<section class="card"><h3>${esc(s)}</h3><ul class="deadlines">${rows.map((p) => cellItems(p, s).map((x) => `<li>
      <span class="when">${L === "demands" ? (x.deadline ? fmtMonth(x.deadline) : "no date") : esc(x.topic)}</span>
      <span>${projLink(p)} – ${esc(L === "demands" ? x.description : x.text)}
      ${L === "demands" ? `<div class="small muted">${x.effort?.pm != null ? fmtPM(x.effort.pm) + " · " : ""}sector lead: ${people(x.sector_lead)} · contact: ${people(x.project_contact)}</div>` : ""}</span></li>`).join("")).join("")}</ul></section>`;
  }).join("");
  root.innerHTML = `${banner}
    <section class="card"><div class="card-head"><h2>${L === "demands" ? "What projects need from each sector group" : "Sector focus of each project"}</h2>
      <span class="legend">${L === "demands" ? `<span><span class="sw seq-2"></span>fewer person-months</span><span><span class="sw seq-5"></span>more (number = PM, or count if no effort given)</span>`
        : `<span><span class="dot dot-legend"></span>focus topic in the overview doc</span>`}</span></div>
      ${P.length ? `<div class="table-wrap"><table class="matrix"><thead><tr><th>Project</th>${sectors.map((s) => `<th class="sector" scope="col">${esc(s)}</th>`).join("")}</tr></thead>
        <tbody>${P.map((p) => `<tr><td class="name">${projLink(p)} ${p.status !== "active" ? statusChip(p.status, p) : ""}</td>${sectors.map((s) => cell(p, s)).join("")}</tr>`).join("")}</tbody></table></div>`
        : `<p class="empty">No projects in this view.</p>`}
    </section>
    <div class="grid two mt">${detail || ""}</div>`;
  for (const b of $$("button[data-set]", root)) b.addEventListener("click", () => setState({ [b.dataset.set]: b.dataset.value }));
  bindTips(root); bindOpen(root);
}

// ---------------------------------------------------------------- Timeline
function viewTimeline(root) {
  const g = state.group;
  const all = inScope().filter((p) => !g || p.sectors[g]);
  const dated = all.filter((p) => p.start && p.end).sort((a, b) => a.start.localeCompare(b.start) || a.name.localeCompare(b.name));
  const undated = all.filter((p) => !(p.start && p.end));
  const marks = (p) => g
    ? (p.sectors[g]?.demands || []).filter((d) => d.deadline).map((d) => ({ cls: "mk-demand", m: d.deadline, tip: `<b>${esc(p.name)} · ${esc(g)} demand</b>${esc(d.description)}<br><span class="muted">${fmtMonth(d.deadline)}</span>` }))
    : p.tasks.filter((t) => t.deadline).map((t) => ({ cls: "mk-task", m: t.deadline, tip: `<b>${esc(p.name)} · ${esc(t.code || "task")}</b>${esc(t.description)}<br><span class="muted">deadline ${fmtMonth(t.deadline)} · lead ${people(t.lead)}</span>` }));
  if (!dated.length) {
    root.innerHTML = `<section class="card"><p class="empty">No ${g ? `projects with ${esc(g)} demands or focus` : "dated projects"} in this view.</p></section>`;
    return;
  }
  const now = nowMonth();
  let lo = Math.min(...dated.map((p) => mIndex(p.start)), now), hi = Math.max(...dated.map((p) => mIndex(p.end)), now) + 1;
  hi += 6; lo -= lo % 12; hi += (12 - (hi % 12)) % 12;   // room for the "tbc" label after the last bar
  const labelW = 170, rowH = 30, top = 26, W = Math.max(720, $("#view").clientWidth - 42);
  const x = (m) => labelW + ((m - lo) / (hi - lo)) * (W - labelW - 12);
  const H = top + dated.length * rowH + 8;
  const years = []; for (let m = lo; m <= hi; m += 12) years.push(m);
  const step = years.length > 14 ? 2 : 1;
  const svg = `<svg width="${W}" height="${H}" role="img" aria-label="Project timeline">
    <g class="axis">${years.map((m, i) => `<line class="gridline" x1="${x(m)}" x2="${x(m)}" y1="${top - 6}" y2="${H}"/>${i % step === 0 && m < hi ? `<text x="${x(m) + 4}" y="14">${m / 12}</text>` : ""}`).join("")}</g>
    ${dated.map((p, i) => { const y = top + i * rowH, x0 = x(mIndex(p.start)), x1 = x(mIndex(p.end) + 1);
      const tbc = p.duration?.tbc ? " tbc" : "", room = x1 + 34 < W;
      const tip = `<b>${esc(p.name)}</b>${esc(p.title || "")}<br>${fmtMonth(p.start)} – ${fmtMonth(p.end)}${tbc ? " (tbc)" : ""} · ${esc((STATUS[p.status] || [, p.status])[1])}`;
      return `<g class="row"><rect class="rowbg" x="0" y="${y}" width="${W}" height="${rowH}"/>
        <text x="0" y="${y + 19}">${esc(p.name.length > 22 ? p.name.slice(0, 21) + "…" : p.name)}</text>
        <rect class="bar ${esc(p.status)}" x="${x0}" y="${y + 9}" width="${Math.max(3, x1 - x0)}" height="12" rx="4"/>
        ${tbc ? `<text class="tbc-label" x="${room ? x1 + 6 : x1 - 6}" y="${y + 19}" text-anchor="${room ? "start" : "end"}">tbc</text>` : ""}
        <rect class="hit" x="0" y="${y}" width="${W}" height="${rowH}" tabindex="0" role="button" data-open="${esc(p.id)}" data-tip="${esc(tip)}" aria-label="${esc(`${p.name}: ${fmtMonth(p.start)} to ${fmtMonth(p.end)}`)}"/>
        ${marks(p).map((k) => { const cx = x(mIndex(k.m) + 0.5), cy = y + 15;
          return k.cls === "mk-task" ? `<path class="${k.cls}" d="M${cx} ${cy - 7}L${cx + 7} ${cy}L${cx} ${cy + 7}L${cx - 7} ${cy}Z" data-tip="${esc(k.tip)}" tabindex="0"/>`
            : `<circle class="${k.cls}" cx="${cx}" cy="${cy}" r="6" data-tip="${esc(k.tip)}" tabindex="0"/>`; }).join("")}</g>`; }).join("")}
    <line class="today" x1="${x(now + new Date().getDate() / 31)}" x2="${x(now + new Date().getDate() / 31)}" y1="${top - 10}" y2="${H}"/>
  </svg>`;
  root.innerHTML = `<section class="card"><div class="card-head"><h2>${g ? `${esc(g)}: projects and demand deadlines` : "All ETL: projects and task deadlines"}</h2>
      <span class="legend"><span><span class="sw sw-bar"></span>active</span>
        <span><span class="sw sw-outline"></span>proposal</span>
        <span><span class="sw sw-finished"></span>finished</span>
        <span>${g ? '<span class="lg-demand">●</span> demand deadline' : '<span class="lg-task">◆</span> task deadline'}</span><span><span class="sw sw-today"></span>today</span>
        <span class="muted">tbc = dates not final</span></span></div>
      <div class="gantt">${svg}</div>
      ${undated.length ? `<p class="small muted">Not shown (no start/end dates): ${undated.map(projLink).join(", ")}</p>` : ""}
      <details><summary class="small">Show as table</summary><div class="table-wrap"><table><thead><tr><th>Project</th><th>Start</th><th>End</th><th>Status</th><th>${g ? "Demand" : "Task"} deadlines</th></tr></thead>
        <tbody>${dated.map((p) => `<tr><td>${projLink(p)}</td><td>${fmtMonth(p.start)}</td><td>${fmtMonth(p.end)}${p.duration?.tbc ? " (tbc)" : ""}</td><td>${statusChip(p.status, p)}</td>
          <td>${marks(p).map((k) => fmtMonth(k.m)).join(", ") || "–"}</td></tr>`).join("")}</tbody></table></div></details>
    </section>`;
  bindTips(root); bindOpen(root);
}

// ---------------------------------------------------------------- Projects (master list)
const COLUMNS = [
  ["name", "Project", (p) => p.name], ["status", "Status", (p) => p.status], ["start", "Start", (p) => p.start || ""],
  ["end", "End", (p) => p.end || ""], ["lead", "Main ETL researcher", (p) => (p.etl_main || []).map((m) => m.name).join(", ")],
  ["funding", "ETL funding", (p) => p.funding?.etl ?? -1], ["tasks", "Tasks", (p) => p.tasks.length], ["issues", "Warnings", (p) => warnings(p)],
];
function viewProjects(root) {
  root.innerHTML = `${editingOffNote()}<section class="card"><div class="card-head"><h2>Master list</h2>
    ${canEdit() ? `<button type="button" class="btn" id="new-project">+ New project</button>` : ""}
    <label><span class="sr-only">Search projects</span><input type="search" id="q" placeholder="Search name, title, people…" value="${esc(state.q)}"></label></div>
    <div id="list"></div></section>`;
  const draw = () => {
    const q = state.q.toLowerCase();
    const col = COLUMNS.find((c) => c[0] === state.sort) || COLUMNS[0], dir = state.dir === "desc" ? -1 : 1;
    const rows = inScope().filter((p) => !q || [p.name, p.title, p.funder, p.partners, ...["etl_main", "etl_pi", "etl_other"].flatMap((f) => (p[f] || []).map((m) => m.name))]
      .some((v) => String(v || "").toLowerCase().includes(q)))
      .sort((a, b) => { const va = col[2](a), vb = col[2](b); return (va > vb ? 1 : va < vb ? -1 : 0) * dir; });
    $("#list", root).innerHTML = `<div class="table-wrap"><table><thead><tr>${COLUMNS.map(([k, label]) => `<th scope="col" aria-sort="${k === col[0] ? (dir > 0 ? "ascending" : "descending") : "none"}">
      <button type="button" data-sort="${k}">${esc(label)}${k === col[0] ? (dir > 0 ? " ▲" : " ▼") : ""}</button></th>`).join("")}<th>Doc</th></tr></thead>
      <tbody>${rows.map((p) => `<tr class="clickable" tabindex="0" data-open="${esc(p.id)}">
        <td><b>${esc(p.name)}</b>${p.title ? `<div class="small muted">${esc(p.title.slice(0, 90))}</div>` : ""}</td><td>${statusChip(p.status, p)}</td>
        <td class="num">${fmtMonth(p.start)}</td><td class="num">${fmtMonth(p.end)}${p.duration?.tbc ? " <span class=\"muted\">tbc</span>" : ""}</td>
        <td>${people(p.etl_main)}</td>
        <td class="num">${p.funding?.counted_in ? `<span class="muted small">in ${esc(p.funding.counted_in)}</span>` : fmtMoney(p.funding?.etl, p.funding?.currency)}</td>
        <td class="num">${p.tasks.length || "–"}</td><td class="num">${warnings(p) ? `<span class="chip warning">⚠ ${warnings(p)}</span>` : "–"}</td>
        <td>${p.has_overview_doc ? "✓" : "<span class=\"muted\">–</span>"}</td></tr>`).join("") || `<tr><td colspan="9" class="empty">No matching projects.</td></tr>`}</tbody></table></div>
      <p class="small muted">${rows.length} project${rows.length === 1 ? "" : "s"}.</p>`;
    for (const b of $$("button[data-sort]", root)) b.addEventListener("click", () =>
      setState({ sort: b.dataset.sort, dir: state.sort === b.dataset.sort && state.dir === "asc" ? "desc" : "asc" }));
    bindOpen($("#list", root));
  };
  $("#q", root).addEventListener("input", (e) => { setState({ q: e.target.value }, true); draw(); });
  $("#new-project", root)?.addEventListener("click", () => openProjectForm(null));
  draw();
}

// ---------------------------------------------------------------- Project drawer
function renderDrawer() {
  const host = $("#drawer"), p = state.p && D.byId[state.p];
  if (!p) { if (!host.hidden) { host.hidden = true; host.innerHTML = ""; } return; }
  const f = p.funding || {};
  const fact = (k, v) => (v && v !== "–" ? `<dt>${esc(k)}</dt><dd>${v}</dd>` : "");
  const seen = new Set();
  const links = [...(p.links?.internal || []).map((u) => ["internal folder", u]), ...(p.links?.consortium || []).map((u) => ["consortium folder", u]),
    ...(p.website ? [["website", p.website]] : [])].filter(([, u]) => !seen.has(u) && seen.add(u)).map(([l, u]) => /^https?:\/\//.test(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(l)}</a>` : esc(u));
  const parent = p.parent_id && D.byId[p.parent_id], children = D.projects.filter((c) => c.parent_id === p.id);
  host.hidden = false;
  host.innerHTML = `<div class="drawer-bg" data-close></div>
    <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
      <header><div><h2 id="drawer-title">${esc(p.name)} ${statusChip(p.status, p)}</h2>${p.title ? `<div class="muted">${esc(p.title)}</div>` : ""}
        ${parent ? `<div class="small">Sub-project of ${projLink(parent)}</div>` : ""}${children.length ? `<div class="small">Sub-projects: ${children.map(projLink).join(", ")}</div>` : ""}</div>
        ${canEditProject(p) ? `<button type="button" class="btn" id="edit-project">Edit project</button>` : ""}
        <button type="button" class="btn-close close" data-close>Close ✕</button></header>
      <section><dl class="facts">
        ${fact("Duration", `${fmtMonth(p.start)} – ${fmtMonth(p.end)}${p.duration?.tbc ? " (tbc)" : ""}`)}
        ${fact("Funding for ETL", f.counted_in ? `counted in ${esc(f.counted_in)}` : f.etl != null ? fmtMoney(f.etl, f.currency) : "")}
        ${fact("Funding for PIK", f.pik != null && !f.counted_in ? fmtMoney(f.pik, f.currency) : "")}
        ${fact("Funding secured", esc(f.secured))}
        ${fact("Funding (as written)", f.raw && (f.etl == null && f.pik == null) ? esc(f.raw) : "")}
        ${fact("Funder / contact", esc(p.funder))}
        ${fact("Overall project lead", (p.project_lead || []).length ? people(p.project_lead) : "")}
        ${fact("Partners", esc(p.partners))}
        ${fact("Responsible PIK team", esc(p.responsible_team))}
        ${fact("Main ETL researcher", (p.etl_main || []).length ? people(p.etl_main) : "")}
        ${fact("ETL PI", (p.etl_pi || []).length ? people(p.etl_pi) : "")}
        ${fact("Other ETL", (p.etl_other || []).length ? people(p.etl_other) : "")}
        ${fact("Other PIK teams", groupByTeam(p.pik_other))}
        ${fact("Strategy / our role", esc(p.strategy))}
        ${fact("Synergies", esc(p.synergies))}
        ${fact("Remarks", esc(p.remarks))}
        ${fact("Links", links.join(" · "))}
        ${fact("Source", `${esc(p.source?.file || "")}${p.last_reviewed ? " · reviewed " + esc(p.last_reviewed) : ""}`)}
      </dl></section>
      ${Object.keys(p.sectors).length || Object.keys(p.themes).length ? `<section><h3>Sector focus & themes</h3><dl class="facts">
        ${Object.entries(p.sectors).map(([s, v]) => fact(s, [...v.focus.map((x) => esc(x.text)), ...v.demands.map((d) => `<b>Demand:</b> ${esc(d.description)}${d.deadline ? " · " + fmtMonth(d.deadline) : ""}`)].join("<br>"))).join("")}
        ${Object.entries(p.themes).map(([k, v]) => fact(k, esc(v))).join("")}</dl></section>` : ""}
      ${p.tasks.length ? `<section><h3>Tasks</h3><div class="table-wrap"><table><thead><tr><th></th><th>Description</th><th>Effort</th><th>Deadline</th><th>Lead</th><th>Others</th></tr></thead>
        <tbody>${p.tasks.map((t) => `<tr><td>${esc(t.code)}${t.section ? `<div class="small muted">${esc(t.section)}</div>` : ""}<div class="small muted">${t.kind.includes("led") ? "led" : "contrib."}</div></td>
          <td class="wrap">${esc(t.description)}</td><td class="num">${t.effort.flexible ? "flex" : fmtPM(t.effort.pm)}</td>
          <td class="num">${t.deadline ? fmtMonth(t.deadline) : esc(t.deadline_raw || "–")}</td><td>${people(t.lead)}</td><td>${people(t.others)}</td></tr>`).join("")}</tbody></table></div></section>` : ""}
      ${p.snippets.length ? `<section><h3>Project description snippets</h3>${p.snippets.map((s) => `<p><b>${esc(s.sector)}</b> – ${esc(s.text)} <span class="muted small">${esc(s.source)}</span></p>`).join("")}</section>` : ""}
      ${p.issues.length ? `<section><h3>Missing or unclear information</h3>${issueList(p.issues, p)}</section>` : ""}
      ${canEditProject(p) ? `<section class="small muted">Changes are written into ${esc(p.source.file)} and logged with your name.</section>` : ""}
    </aside>`;
  for (const el of $$("[data-close]", host)) el.addEventListener("click", () => setState({ p: null }));
  bindEdits(host);
  $("#edit-project", host)?.addEventListener("click", () => openProjectForm(p));
  $(".close", host).focus();
}

function groupByTeam(list) {
  if (!list || !list.length) return "";
  const teams = {};
  for (const m of list) (teams[m.team || ""] ||= []).push(m.name + (m.uncertain ? "?" : ""));
  return Object.entries(teams).map(([t, names]) => esc((t ? t + ": " : "") + names.join(", "))).join("<br>");
}


// ---------------------------------------------------------------- People
const PERSON_FIELDS = [["id", "Person ID (initials)", "2–8 letters, unique, e.g. FS or ReRo"], ["first", "First name", ""], ["last", "Last name", ""],
  ["email", "Email", "name@pik-potsdam.de"], ["teams", "PIK team(s)", "comma-separated, e.g. ETL, RSE"],
  ["sectors", "Sector group(s)", "comma-separated: " + SECTORS.join(", ")], ["topics", "Topics", "free text"],
  ["aliases", "Aliases", "other spellings used in the docs, e.g. Jess, RoSa"]];
const listText = (v) => (Array.isArray(v) ? v.join(", ") : v || "");
const PERSON_EXAMPLE = { id: "FS", first: "Felix", last: "Example", email: "first.last@pik-potsdam.de", teams: "ETL, RSE",
  sectors: "", topics: "energy system, hydrogen", aliases: "Fel, FeSc" };
function viewPeople(root) {
  const q = state.q.toLowerCase(), showAll = state.sev === "all";
  const list = (D.people || []).filter((p) => (showAll || p.active !== false) && (!q ||
    [p.name, p.initials, p.email, listText(p.teams), listText(p.sectors), p.topics, ...(p.doc_projects || [])].some((v) => String(v || "").toLowerCase().includes(q))))
    .sort((a, b) => (a.last || a.name).localeCompare(b.last || b.name));
  const source = { table: "the ETL people table in the overview folder", none: "no people table yet" }[D.people_source] || "";
  root.innerHTML = `<section class="card"><div class="card-head"><h2>People</h2>
      ${canEdit() ? `<button type="button" class="btn" id="add-person">+ Add person</button>` : ""}
      <label><span class="sr-only">Search people</span><input type="search" id="q" placeholder="Search name, team, topic, project…" value="${esc(state.q)}"></label></div>
    <p class="small muted">Source: ${esc(source)}.${D.people_source === "none" && canEdit() ? " The first person added here creates the table." : ""}
      Projects are taken from the overview docs (team rows and tasks).</p>
    <div class="table-wrap"><table><thead><tr><th>Name</th><th>ID</th><th>Email</th><th>PIK team(s)</th><th>Sector group(s)</th><th class="hide-sm">Topics</th><th>Projects</th>${canEdit() ? "<th></th>" : ""}</tr></thead>
      <tbody>${list.map((p, i) => `<tr${p.active === false ? ' class="muted"' : ""}><td><b>${esc(p.name)}</b>${p.active === false ? ' <span class="pill">left</span>' : ""}</td>
        <td>${esc(p.initials || "–")}</td><td>${p.email ? `<a href="mailto:${esc(p.email)}">${esc(p.email)}</a>` : '<span class="muted">–</span>'}</td>
        <td>${esc(listText(p.teams)) || "–"}</td><td>${esc(listText(p.sectors)) || "–"}</td><td class="hide-sm small">${esc(p.topics || "")}</td>
        <td>${(p.doc_projects || []).map((id) => (D.byId[id] ? projLink(D.byId[id]) : esc(id))).join(", ") || "–"}</td>
        ${canEdit() ? `<td><button type="button" class="pencil" data-person="${i}" aria-label="${esc("Edit " + p.name)}">✎</button></td>` : ""}</tr>`).join("")
        || `<tr><td colspan="8" class="empty">No matching people.</td></tr>`}</tbody></table></div>
    <p class="small muted">${list.length} people. <a href="${esc(hrefWith({ sev: showAll ? "warning" : "all" }))}">${showAll ? "Hide people who left" : "Show people who left"}</a></p></section>`;
  $("#q", root).addEventListener("input", (e) => { setState({ q: e.target.value }, true); viewPeople(root); $("#q", root).focus(); const v = $("#q", root).value; $("#q", root).setSelectionRange(v.length, v.length); });
  $("#add-person", root)?.addEventListener("click", () => openPersonForm(null));
  for (const b of $$("button[data-person]", root)) b.addEventListener("click", () => openPersonForm(list[+b.dataset.person]));
}
function personRecord(p) {   // the record as stored in the people table (for the concurrency check)
  return { id: p.initials || "", first: p.first || "", last: p.last || "", email: p.email || "", teams: p.teams || [],
    sectors: p.sectors || [], topics: p.topics || "", active: p.active !== false, aliases: p.aliases || [] };
}
function openPersonForm(p) {
  const rec = p ? personRecord(p) : { active: true };
  const host = document.createElement("div");
  host.className = "modal-bg";
  host.innerHTML = `<form class="modal" role="dialog" aria-modal="true" aria-labelledby="pp-title" novalidate>
    <h2 id="pp-title">${p ? esc("Edit " + p.name) : "Add person"}</h2>
    <p class="small muted">Saved in the ETL people table (root of the overview folder) and logged with your name.</p>
    ${PERSON_FIELDS.map(([k, label, hint]) => k === "sectors"
      ? `<fieldset class="field"><legend class="field-label">${esc(label)}</legend><div class="checks">${SECTORS.map((s) =>
          `<label class="inline"><input type="checkbox" name="sector" value="${esc(s)}" ${(rec.sectors || []).includes(s) ? "checked" : ""}> ${esc(s)}</label>`).join("")}</div></fieldset>`
      : `<div class="field"><span class="field-label">${esc(label)} <button type="button" class="help" data-tip="${esc(`<b>${esc(label)}</b>${esc(hint)}`)}" aria-label="${esc("Help: " + hint)}">ⓘ</button></span>
      <input name="${k}" value="${esc(listText(rec[k]))}"${k === "email" ? ' type="email"' : ""}${k === "teams" ? ' list="team-list"' : ""} placeholder="${esc("e.g. " + PERSON_EXAMPLE[k])}" aria-label="${esc(label)}">
      <div class="example" data-example-for="${k}">e.g. ${esc(PERSON_EXAMPLE[k])}</div><div class="hint">${esc(hint)}</div></div>`).join("")}
    <datalist id="team-list">${["ETL", "IAM", "CarMa", "GET", "ICP", "RSE", "Macro", "ESM", "LUT"].map((t) => `<option value="${t}">`).join("")}</datalist>
    <label class="field"><span class="field-label">Active</span><select name="active"><option value="yes" ${rec.active !== false ? "selected" : ""}>Yes – in the group</option>
      <option value="no" ${rec.active === false ? "selected" : ""}>No – has left (kept so older docs still resolve)</option></select></label>
    <label class="field"><span class="field-label">Your name (for the edit log)</span><input name="editor" required value="${esc(store.get("etl-editor") || "")}"></label>
    <div class="error" id="pp-msg" role="alert"></div>
    <div class="modal-actions"><button type="button" class="btn-close" data-cancel>Cancel</button><button type="submit" class="btn">Save</button></div></form>`;
  document.body.appendChild(host);
  wireForm(host);
  const form = $("form", host), close = modalFocus(host, () => host.remove()), msg = $("#pp-msg", host);
  $("[data-cancel]", host).addEventListener("click", close);
  host.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
  form.elements.id.focus();
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const v = (n) => form.elements[n].value.trim(), person = Object.fromEntries(PERSON_FIELDS.filter(([k]) => k !== "sectors").map(([k]) => [k, v(k)]));
    person.sectors = $$("input[name=sector]:checked", host).map((x) => x.value);
    person.active = form.active.value === "yes";
    const editor = v("editor");
    if (!editor) { msg.textContent = "Please enter your name."; return; }
    if (!/^[A-Za-z][A-Za-z.-]{1,7}$/.test(person.id)) { msg.textContent = "Person ID: 2–8 letters (initials)."; return; }
    if (!person.first || !person.last) { msg.textContent = "First and last name are required."; return; }
    if (person.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(person.email)) { msg.textContent = "The email address looks invalid."; return; }
    const clash = (D.people || []).find((x) => (x.initials || "").toLowerCase() === person.id.toLowerCase() && x !== p);
    if (clash) { msg.textContent = `Person ID ${person.id} is already used by ${clash.name}.`; return; }
    store.set("etl-editor", editor);
    $("button[type=submit]", host).disabled = true;
    msg.textContent = "Saving…";
    try {
      const r = await fetch(session.data.update.url, { method: "POST", headers: { "Content-Type": "text/plain;charset=utf-8" },
        body: JSON.stringify({ action: "save_person", key: session.admin.edit_key, editor, person, old_id: p ? rec.id || null : null, old: p ? rec : null }) });
      const res = await r.json().catch(() => ({}));
      if (!r.ok || res.ok === false) throw new Error(res.message || `HTTP ${r.status}`);
      close();
      toast("Saved. The page offers to reload when the rebuilt data is published.");
      watchForNewVersion();
    } catch (e) {
      msg.textContent = `Not saved: ${e.message}`;
      $("button[type=submit]", host).disabled = false;
    }
  });
}

// ---------------------------------------------------------------- Change log (admin only)
function viewLog(root) {
  const log = session.admin?.log;
  if (!log) { root.innerHTML = `<section class="card"><p class="empty">The change log is only available with the admin password.</p></section>`; return; }
  const q = state.q.toLowerCase();
  const rows = log.filter((e) => !q || Object.values(e).some((v) => String(v || "").toLowerCase().includes(q)));
  root.innerHTML = `<section class="card"><div class="card-head"><h2>Change log</h2>
      <label><span class="sr-only">Search the log</span><input type="search" id="q" placeholder="Search editor, document, value…" value="${esc(state.q)}"></label></div>
    <p class="small muted">Changes made through this website (newest first), as of the last sync. Direct edits in the documents appear in their own version history.</p>
    <div class="table-wrap"><table><thead><tr><th>When</th><th>Who</th><th>Document</th><th>Where</th><th>Old</th><th>New</th><th>Result</th></tr></thead>
      <tbody>${rows.map((e) => `<tr><td class="num">${esc(fmtDate(e.time))}<div class="small muted">${esc(String(e.time || "").slice(11, 16))}</div></td>
        <td>${esc(e.editor)}</td><td>${esc(e.file)}</td><td class="small">${esc(e.where)}</td>
        <td class="wrap small">${esc(e.old)}</td><td class="wrap small">${esc(e.new)}</td>
        <td>${/^(ok|created|rows added|row added|proposal attached)$/i.test(e.result) ? esc(e.result) : `<span class="chip warning">${esc(e.result)}</span>`}</td></tr>`).join("")
        || `<tr><td colspan="7" class="empty">No changes logged yet.</td></tr>`}</tbody></table></div>
    <p class="small muted">${rows.length} of ${log.length} entries.</p></section>`;
  $("#q", root).addEventListener("input", (e) => { setState({ q: e.target.value }, true); viewLog(root); const el = $("#q", root); el.focus(); el.setSelectionRange(el.value.length, el.value.length); });
}

// ---------------------------------------------------------------- Information
function issueFix(i, p) {
  if (!p || !canEditProject(p) || !p.fields) return "";
  const f = Object.keys(p.fields).find((k) => p.fields[k].label === i.field);
  const idx = f ? fieldEdit(p, f) : null;
  if (idx != null) return `<button type="button" class="btn-close fix" data-edit="${idx}">Fix</button>`;
  return /sector requirements|^tasks?\b/i.test(i.field || "") && p.has_overview_doc
    ? `<a class="btn-close fix" href="${esc(hrefWith({ p: p.id }))}">Open</a>` : "";
}
function issueList(list, p) {
  return list.map((i) => `<div class="issue"><span class="ico" aria-label="${esc(i.severity)}">${i.severity === "warning" ? "⚠️" : "ℹ️"}</span>
    <div class="issue-main"><span class="where">${esc(i.field || "")}</span> <span class="issue-msg">${esc(i.message)}</span>
      ${i.hint ? `<div class="hint">${esc(i.hint)}</div>` : ""}</div><div class="issue-action">${issueFix(i, p)}</div></div>`).join("");
}
function viewInfo(root) {
  const P = inScope(), sev = state.sev;
  const pick = (list) => (sev === "all" ? list : list.filter((i) => i.severity === "warning"));
  const groups = [...P.filter((p) => p.has_overview_doc), ...P.filter((p) => !p.has_overview_doc)]
    .map((p) => [p, pick(p.issues)]).filter(([, l]) => l.length);
  const general = pick(D.general);
  const total = groups.reduce((s, [, l]) => s + l.length, 0) + general.length;
  root.innerHTML = `<section class="card"><h2>Missing or unclear information</h2>
      <p>${total} ${sev === "all" ? "notes" : "warnings"} for the projects in view, across ${groups.length} project${groups.length === 1 ? "" : "s"}
        <span class="muted">· data updated ${esc(fmtDate(D.generated_at))}</span></p>
      <p class="small muted">Fix them in the overview document${canEdit() ? " or with the Fix buttons below" : ""}. The dashboard updates on the next sync.</p></section>
    <div class="issue-grid mt">
      ${groups.map(([p, l]) => `<section class="card"><div class="card-head"><h3>${projLink(p)} ${statusChip(p.status, p)}</h3>
        <span class="small muted">${esc(p.source?.file || "")}</span></div>${issueList(l, p)}</section>`).join("")}
      ${general.length ? `<section class="card"><h3>General</h3>${issueList(general)}</section>` : ""}
      ${!total ? `<section class="card"><p class="empty">Nothing to fix here.</p></section>` : ""}
    </div>
    ${D.checklist?.length ? `<details class="card mt"><summary><h2 class="inline-h">Steps when setting up a new project</h2></summary><ul class="checklist">
      ${D.checklist.map((c) => `<li class="l${Math.min(c.level, 1)}">${esc(c.text)}</li>`).join("")}</ul></details>` : ""}`;
}

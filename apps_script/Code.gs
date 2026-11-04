/**
 * ETL dashboard companion (Google Apps Script, runs as its owner inside Google).
 *
 *  1. Watcher: every 5 minutes, checks the overview folder (docs + 'ETL people' table) for changes and, once they have
 *     settled (no further change for 2 minutes), starts the GitHub "Sync and deploy" workflow.
 *  2. Web app (doPost), called by the dashboard:
 *       update        "Update data" button (update key; any logged-in viewer)
 *       edit          corrections of single cells (edit key; admin only)
 *       save_project  create a project doc / update one / attach a proposal (edit key; admin only)
 *     Same JSON API and rules as the local dev server (python -m etl_dash serve, etl_dash/writeback.py, projectdocs.py).
 *
 * Script properties (Project settings > Script properties) – never put them in the code:
 *   ROOT_FOLDER_ID          the data folder (= DRIVE_FOLDER_ID): 'ETL people' sheet + subfolders 'overviews' and
 *                           'project_descriptions' (one subfolder per project; proposals go there)
 *   GITHUB_REPO             owner/name
 *   GITHUB_WORKFLOW         deploy.yml
 *   GITHUB_TOKEN            fine-grained token, this repository only, permission "Actions: Read and write"
 *   UPDATE_KEY_SHA256       hex SHA-256 of ETL_UPDATE_KEY
 *   EDIT_KEY_SHA256         hex SHA-256 of ETL_EDIT_KEY (the key itself is only in the admin-encrypted page block)
 *   TEST_EDIT_KEY_SHA256    optional: hex SHA-256 of ETL_TEST_EDIT_KEY – this key can only write to the TEST folders
 *   EDIT_LOG_SHEET_ID       a Google Sheet; one row per change (time, editor, file, location, old, new, result)
 *   TEST_ROOT_FOLDER_ID     optional: the TEST data folder (= ETL_TEST_DRIVE_FOLDER_ID); edits made in test mode go there
 * Setup: run setup() once (installs the 5-minute trigger), then Deploy > New deployment > Web app,
 *        "Execute as: Me", "Who has access: Anyone"; put the web-app URL into the GitHub variable ETL_UPDATE_URL.
 * Only native Google Docs are edited; rows are only appended (tasks, a missing overview row); nothing is deleted.
 */
const PROPS = PropertiesService.getScriptProperties();
const SETTLE_MS = 2 * 60 * 1000;
const MIN_INTERVAL_S = 120;
const MAX_LEN = 2000;

function setup() {
  for (const t of ScriptApp.getProjectTriggers()) ScriptApp.deleteTrigger(t);
  ScriptApp.newTrigger("checkForChanges").timeBased().everyMinutes(5).create();
  PROPS.setProperty("LAST_SIGNATURE", signature_());
}

/** The data folder's parts: root (people table), overviews/ (docs), project_descriptions/ (proposals). */
function subfolder_(root, name, create) {
  const it = root.getFoldersByName(name);
  if (it.hasNext()) return it.next();
  if (create) return root.createFolder(name);
  throw new Error("the data folder has no '" + name + "' subfolder");
}
function layout_(rootId) {
  const root = DriveApp.getFolderById(rootId);
  return { root: rootId, docs: subfolder_(root, "overviews", false).getId(),
           descriptions: subfolder_(root, "project_descriptions", true).getId() };
}

/** Ids + last-modified times of the overview docs and of the root (people table). */
function signature_() {
  const parts = [], f = layout_(PROPS.getProperty("ROOT_FOLDER_ID"));
  for (const id of [f.docs, f.root]) {
    const files = DriveApp.getFolderById(id).getFiles();
    while (files.hasNext()) {
      const x = files.next();
      parts.push(x.getId() + ":" + x.getLastUpdated().getTime());
    }
  }
  return parts.sort().join("|");
}

function checkForChanges() {
  const sig = signature_();
  if (sig === PROPS.getProperty("LAST_SIGNATURE")) {
    PROPS.deleteProperty("PENDING_SIGNATURE");
    PROPS.deleteProperty("PENDING_SINCE");
    return;
  }
  if (sig !== PROPS.getProperty("PENDING_SIGNATURE")) {   // new or still changing: wait until it settles
    PROPS.setProperties({ PENDING_SIGNATURE: sig, PENDING_SINCE: String(Date.now()) });
    return;
  }
  if (Date.now() - Number(PROPS.getProperty("PENDING_SINCE")) < SETTLE_MS) return;
  if (dispatch_().ok) {
    PROPS.setProperty("LAST_SIGNATURE", sig);
    PROPS.deleteProperty("PENDING_SIGNATURE");
    PROPS.deleteProperty("PENDING_SINCE");
  }
}

/** Starts the GitHub workflow. -> {ok, message} */
function dispatch_() {
  const repo = PROPS.getProperty("GITHUB_REPO"), workflow = PROPS.getProperty("GITHUB_WORKFLOW") || "deploy.yml";
  const res = UrlFetchApp.fetch(`https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`, {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + PROPS.getProperty("GITHUB_TOKEN"), Accept: "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28" },
    payload: JSON.stringify({ ref: "main" }),
    muteHttpExceptions: true,
  });
  const ok = res.getResponseCode() === 204;
  if (!ok) console.error("workflow dispatch failed: HTTP " + res.getResponseCode());   // no data in the log
  return { ok, message: ok ? "Update started." : "The update could not be started – please try again later." };
}

function sha256Hex_(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8)
    .map((b) => ((b + 256) % 256).toString(16).padStart(2, "0")).join("");
}

function reply_(body) {
  return ContentService.createTextOutput(JSON.stringify(body)).setMimeType(ContentService.MimeType.JSON);
}

/** Dashboard API. Apps Script web apps always answer HTTP 200, so errors are {ok: false, message}. */
function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return reply_({ ok: false, message: "bad request" }); }
  if (body.action === "edit" || body.action === "save_project" || body.action === "save_person") {
    const f = foldersForKey_(body.key);   // the key decides the folders – never a field of the request
    if (!f) return reply_({ ok: false, message: "not allowed" });
    const cache = CacheService.getScriptCache(), n = Number(cache.get("edit-count") || 0);
    if (n > 60) return reply_({ ok: false, message: "Too many edits – try again in a few minutes." });
    cache.put("edit-count", String(n + 1), 600);
    const lock = LockService.getScriptLock();
    lock.waitLock(30000);
    try { return reply_(body.action === "edit" ? editCells_(body, f) : body.action === "save_person" ? savePerson_(body, f) : saveProject_(body, f)); }
    catch (err) { console.error("edit failed"); return reply_({ ok: false, message: String(err.message || err) }); }
    finally { lock.releaseLock(); }
  }
  if (!body.key || sha256Hex_(String(body.key)) !== PROPS.getProperty("UPDATE_KEY_SHA256")) {
    return reply_({ ok: false, message: "not allowed" });
  }
  if (body.action === "update") {
    const cache = CacheService.getScriptCache();
    if (cache.get("last-update")) return reply_({ ok: false, message: "An update was just requested – try again in a minute." });
    cache.put("last-update", "1", MIN_INTERVAL_S);
    return reply_(dispatch_());
  }
  return reply_({ ok: false, message: "unknown action" });
}

function doGet() {
  return reply_({ ok: true, service: "etl-dashboard-companion" });
}

// ---------------------------------------------------------------- corrections (cell edits)
const norm_ = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
const EDITABLE_HEADERS = [/^description/, /^effort/, /^start/, /^deadline/, /lead$/, /^(others|etlcontr|pikcontr)/, /^status/,
  /^(tasknr|projecttasks|taskids?)/, /^flexib/, /^priority/, /^projectcontact/, /^snippet/, /^source$/];
const OVERVIEW_LABELS = [/^name/, /^duration/, /^funding/, /^overallprojectlead/, /^mainetlresearcher/, /^etlpi/, /^status/];

function foldersForKey_(key) {
  const h = key ? sha256Hex_(String(key)) : "";
  if (h && h === PROPS.getProperty("EDIT_KEY_SHA256")) {
    return layout_(PROPS.getProperty("ROOT_FOLDER_ID"));
  }
  if (h && h === PROPS.getProperty("TEST_EDIT_KEY_SHA256") && PROPS.getProperty("TEST_ROOT_FOLDER_ID")) {
    return layout_(PROPS.getProperty("TEST_ROOT_FOLDER_ID"));
  }
  return null;
}

/** Spreadsheet-safe text: a leading = + - @ would otherwise be run as a formula. */
function safe_(v) {
  const t = v == null ? "" : String(v);
  return /^[=+\-@]/.test(t) ? "'" + t : t;
}

function clean_(v) {
  const t = String(v == null ? "" : v).replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, "").replace(/\r\n/g, "\n").trim();
  if (t.length > MAX_LEN) throw new Error("too long (max " + MAX_LEN + " characters)");
  return t;
}

/** The overview doc, only if it is a native Google Doc directly inside the configured folder. */
function openDoc_(fileId, folderId) {
  if (!fileId) throw new Error("unknown document (no file id)");
  const file = DriveApp.getFileById(fileId);
  if (file.getMimeType() !== MimeType.GOOGLE_DOCS) {
    throw new Error("only native Google Docs can be edited – convert the .docx (File > Save as Google Docs)");
  }
  let inside = false;
  const parents = file.getParents();
  while (parents.hasNext()) if (parents.next().getId() === folderId) inside = true;
  if (!inside) throw new Error("the document is not in the overview folder");
  return DocumentApp.openById(fileId);
}

/** Cell of a row at a grid column (a merged cell spans several grid columns). */
function cellAt_(row, col) {
  let pos = 0;
  for (let i = 0; i < row.getNumCells(); i++) {
    const c = row.getCell(i), span = (c.getColSpan && c.getColSpan()) || 1;
    if (col < pos + span) return c;
    pos += span;
  }
  return null;
}

function isOverview_(table) {
  let hits = 0;
  for (let r = 0; r < table.getNumRows(); r++) {
    if (OVERVIEW_LABELS.some((rx) => rx.test(norm_(table.getRow(r).getCell(0).getText())))) hits++;
  }
  return hits >= 2;
}

function allowed_(tables, ti, row, col) {
  const t = tables[ti];
  if (!t || row < 0 || row >= t.getNumRows()) return false;
  if (ti === tables.findIndex(isOverview_)) {   // values only; the name (= file name) and template version stay
    const label = norm_(t.getRow(row).getCell(0).getText());
    return col === 1 && !/^(name|templateversion|lastreviewed)/.test(label);   // 'Last reviewed' is stamped on save
  }
  if (row < 1) return false;
  const header = cellAt_(t.getRow(0), col);
  return Boolean(header) && EDITABLE_HEADERS.some((rx) => rx.test(norm_(header.getText())));
}

function log_(editor, file, where, oldV, newV, result) {
  const id = PROPS.getProperty("EDIT_LOG_SHEET_ID");
  if (id) SpreadsheetApp.openById(id).getSheets()[0].appendRow([new Date(), editor, file, where, oldV, newV, result].map((v, i) => (i ? safe_(v) : v)));
}

/** Checks a batch without writing: -> results (all ok, or the failures with the current values). */
function checkEdits_(doc, edits) {
  const tables = doc.getBody().getTables();
  return (edits || []).slice(0, 200).map((e) => {
    try {
      const ti = Number(e.table_index), r = Number(e.row), c = Number(e.col);
      if (!allowed_(tables, ti, r, c)) return { ok: false, message: "this cell cannot be edited" };
      clean_(e.new);
      const current = cellAt_(tables[ti].getRow(r), c).getText().trim();
      return current === String(e.old || "").trim() ? { ok: true }
        : { ok: false, message: "the value was changed in the document in the meantime", current };
    } catch (err) { return { ok: false, message: String(err.message || err) }; }
  });
}

function applyEdits_(doc, edits, editor) {
  const tables = doc.getBody().getTables(), results = [];
  for (const e of (edits || []).slice(0, 200)) {
    const where = [e.table_index, e.row, e.col].join("/");
    try {
      const ti = Number(e.table_index), r = Number(e.row), c = Number(e.col);
      if (!allowed_(tables, ti, r, c)) throw new Error("this cell cannot be edited");
      const cell = cellAt_(tables[ti].getRow(r), c);
      const current = cell.getText().trim(), oldV = String(e.old || "").trim(), newV = clean_(e.new);
      if (current !== oldV) {
        results.push({ ok: false, message: "the value was changed in the document in the meantime", current });
        log_(editor, doc.getName(), where, oldV, newV, "conflict");
        continue;
      }
      cell.setText(newV);
      results.push({ ok: true });
      log_(editor, doc.getName(), where, oldV, newV, "ok");
    } catch (err) {
      results.push({ ok: false, message: String(err.message || err) });
      log_(editor, doc.getName(), where, e.old, e.new, "refused: " + err.message);
    }
  }
  return results;
}

function editCells_(body, f) {
  const editor = clean_(body.editor).slice(0, 80);
  if (!editor) throw new Error("editor name required");
  const byFile = {};
  for (const e of body.edits || []) (byFile[e.file_id] = byFile[e.file_id] || []).push(e);
  let results = [];
  for (const id of Object.keys(byFile)) {
    const doc = openDoc_(id, f.docs);
    results = results.concat(applyEdits_(doc, byFile[id], editor));
    doc.saveAndClose();
  }
  const ok = results.length > 0 && results.every((r) => r.ok);
  if (results.some((r) => r.ok)) dispatch_();
  return { ok, results, message: ok ? "Saved. The dashboard is being rebuilt." : "Some changes were not saved." };
}

// ---------------------------------------------------------------- people table ('ETL people' Google Sheet in the data-folder root)
const PEOPLE_COLS = [["id", "Person ID"], ["first", "First name"], ["last", "Last name"], ["email", "Email"], ["teams", "PIK team(s)"],
  ["sectors", "Sector group(s)"], ["topics", "Topics"], ["active", "Active"], ["aliases", "Aliases"]];

function personRow_(p) {
  return PEOPLE_COLS.map(([k]) => {
    const v = p[k];
    if (k === "active") return v === false || /^(no|false|0)$/i.test(String(v)) ? "No" : "Yes";
    return safe_(clean_(Array.isArray(v) ? v.join(", ") : v));
  });
}

function savePerson_(body, f) {
  const editor = clean_(body.editor).slice(0, 80), p = body.person || {};
  if (!editor) throw new Error("editor name required");
  if (!/^[A-Za-z][A-Za-z.\-]{1,7}$/.test(String(p.id || ""))) throw new Error("Person ID: 2–8 letters (initials)");
  if (!String(p.first || "").trim() || !String(p.last || "").trim()) throw new Error("first and last name are required");
  if (p.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(p.email)) throw new Error("email address looks invalid");
  const files = DriveApp.getFolderById(f.root).getFilesByName("ETL people");
  if (!files.hasNext()) throw new Error("create the 'ETL people' Google Sheet in the root of the data folder first (upload ETL people.xlsx as a Google Sheet)");
  const file = files.next();
  if (file.getMimeType() !== MimeType.GOOGLE_SHEETS) throw new Error("'ETL people' must be a native Google Sheet");
  const sheet = SpreadsheetApp.openById(file.getId()).getSheets()[0], values = sheet.getDataRange().getValues();
  const header = values[0].map((h) => norm_(h)), col = PEOPLE_COLS.map(([, label]) => header.indexOf(norm_(label)));
  if (col.some((c) => c < 0)) throw new Error("the people sheet does not have the expected columns");
  const idCol = col[0], rowOf = (id) => values.findIndex((r, i) => i > 0 && String(r[idCol]).toLowerCase() === String(id).toLowerCase());
  const row = personRow_(p), full = new Array(values[0].length).fill("");
  col.forEach((c, i) => { full[c] = row[i]; });
  if (body.old_id == null) {
    if (rowOf(p.id) > 0) throw new Error("Person ID " + p.id + " is already used");
    sheet.appendRow(full);
  } else {
    const r = rowOf(body.old_id);
    if (r < 1) throw new Error(body.old_id + " is no longer in the people table");
    if (String(p.id).toLowerCase() !== String(body.old_id).toLowerCase() && rowOf(p.id) > 0) throw new Error("Person ID " + p.id + " is already used");
    const before = personRow_(PEOPLE_COLS.reduce((o, [k], i) => Object.assign(o, { [k]: values[r][col[i]] }), {}));
    const expected = personRow_(body.old || {});
    if (JSON.stringify(before) !== JSON.stringify(expected)) throw new Error("this person was changed in the people table in the meantime – reload the page");
    sheet.getRange(r + 1, 1, 1, full.length).setValues([full.map((v, i) => (col.indexOf(i) >= 0 ? v : values[r][i]))]);
  }
  log_(editor, "ETL people", p.id, body.old_id || "(new)", p.id, "ok");
  dispatch_();
  return { ok: true, message: "Saved. The dashboard is being rebuilt." };
}

// ---------------------------------------------------------------- projects: create / update / proposal
const V2_LABELS = [["name", "Name"], ["status", "Status (Proposal / Active / Finished / Rejected)"], ["duration", "Duration"],
  ["funding_pik", "Funding – total for PIK"], ["funding_etl", "Funding – of which ETL"], ["currency", "Currency"],
  ["funding_secured", "Funding secured (Yes / Partly / No)"], ["project_lead", "Overall project lead"],
  ["partners", "Other key non-PIK partners"], ["responsible_team", "Mainly responsible PIK team (REMIND runs / overall)?"],
  ["etl_main", "Main ETL researcher (operational / coordination)"], ["etl_pi", "ETL PI (guidance / supervision)"],
  ["etl_other", "Other ETL involvement"], ["pik_other", "Other involved PIK teams and colleagues"],
  ["funder", "Funding agency, main contact person (with email address)"],
  ["folder_internal", "Link to internal project folder (with proposal / description of work etc)"],
  ["folder_consortium", "Link to project folder shared with entire consortium"],
  ["proposal", "Proposal / description of work (file or link)"], ["mattermost", "Mattermost channel"],
  ["strategy", "Strategic considerations / our role"], ["synergies", "Synergies with (other projects)"], ["remarks", "Other remarks"],
  ["last_reviewed", "Last reviewed (MM/YYYY, name)"], ["template_version", "Template version"]];
const LED_HEADER = ["", "Description", "Effort [PM]", "Start", "Dead- line", "ETL lead", "others", "Status"];
const CON_HEADER = ["", "Description", "Effort [PM]", "Start", "Dead- line", "PIK lead", "ETL contr.", "Status"];
const TASK_KEYS = ["id", "description", "effort", "start", "deadline", "lead", "others", "status"];
const DEMAND_HEADER = ["Sector", "Description: what is needed from the sector", "Task Nr", "Effort [PM]", "Flexibility",
  "Dead- line", "Sector lead", "Project contact", "Status"];
const DEMAND_KEYS = ["description", "task_refs", "effort", "flexibility", "deadline", "sector_lead", "project_contact", "status"];
const SECTORS = ["Transport", "Buildings", "Industry", "Energy supply", "SET", "IAM", "CDR / CarMa", "Model core", "RSE", "Other"];

function projectFolder_(descriptionsId, pid) {
  if (!descriptionsId) throw new Error("DESCRIPTIONS_FOLDER_ID is not set");
  const parent = DriveApp.getFolderById(descriptionsId), it = parent.getFoldersByName(pid);
  return it.hasNext() ? it.next() : parent.createFolder(pid);
}

function saveProposal_(descriptionsId, pid, prop) {
  if (prop.url) {
    const url = clean_(prop.url);
    if (!/^https:\/\/\S+$/.test(url)) throw new Error("proposal link must start with https://");
    projectFolder_(descriptionsId, pid).createFile("proposal-link.txt", url + "\n");
    return url;
  }
  const name = String(prop.name || "").replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "_").trim();
  if (!/\.(pdf|docx|doc|odt|pptx|xlsx|txt|md)$/i.test(name)) throw new Error("file type not allowed");
  const bytes = Utilities.base64Decode(String(prop.data || ""));
  if (!bytes.length || bytes.length > 15 * 1024 * 1024) throw new Error("file must be between 1 byte and 15 MB");
  return projectFolder_(descriptionsId, pid).createFile(Utilities.newBlob(bytes, undefined, name)).getUrl();
}

function setOverviewRow_(doc, key, value) {
  const tables = doc.getBody().getTables(), t = tables[tables.findIndex(isOverview_)];
  if (!t) throw new Error("the document has no overview table");
  const label = V2_LABELS.find((x) => x[0] === key)[1], prefix = norm_(label).slice(0, 12);
  for (let r = 0; r < t.getNumRows(); r++) {
    if (norm_(t.getRow(r).getCell(0).getText()).indexOf(prefix) === 0) { t.getRow(r).getCell(1).setText(value); return; }
  }
  const row = t.appendTableRow();
  row.appendTableCell(label).editAsText().setBold(true).setItalic(true);
  row.appendTableCell(value);
}

/** Task tables: header row has a 'Description' column; ETL-led tables have 'others', contribution tables 'contr.'. */
function taskTable_(tables, kind) {
  const ov = tables.findIndex(isOverview_);
  return tables.find((x, i) => {
    if (i === ov || x.getNumRows() < 1) return false;
    const h = norm_(x.getRow(0).getText());
    return h.indexOf("description") >= 0 && (kind === "led" ? h.indexOf("others") >= 0 : h.indexOf("contr") >= 0);
  });
}

function appendTasks_(doc, tasks) {
  const tables = doc.getBody().getTables();
  let added = 0;
  for (const kind of ["led", "contribution"]) {
    const rows = tasks.filter((t) => t.kind === kind);
    if (!rows.length) continue;
    const t = taskTable_(tables, kind);
    if (!t) throw new Error("the document has no ETL-" + kind + " task table");
    for (const task of rows) {
      const row = t.appendTableRow();
      TASK_KEYS.forEach((k) => row.appendTableCell(clean_(task[k])));
      added++;
    }
  }
  return added;
}

function createDoc_(folderId, overview, tasks, demands) {
  const pid = clean_(overview.name);
  if (!/^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,39}$/.test(pid)) throw new Error("Name: use the project acronym");
  const folder = DriveApp.getFolderById(folderId), name = pid + " - Project overview";
  if (folder.getFilesByName(name).hasNext()) throw new Error("a project overview for " + pid + " already exists");
  const doc = DocumentApp.create(name), body = doc.getBody();
  body.appendParagraph("Project overview").setHeading(DocumentApp.ParagraphHeading.TITLE);
  body.appendParagraph("Overview").setHeading(DocumentApp.ParagraphHeading.HEADING2);
  body.appendTable(V2_LABELS.map(([k, label]) => [label, k === "template_version" ? "v2" : clean_(overview[k])]));
  body.appendParagraph("Short summary of tasks and responsibilities").setHeading(DocumentApp.ParagraphHeading.HEADING3);
  for (const [kind, caption, header] of [["led", "ETL-led tasks:", LED_HEADER], ["contribution", "ETL-contribution tasks:", CON_HEADER]]) {
    body.appendParagraph(caption).editAsText().setBold(true);
    const rows = tasks.filter((t) => t.kind === kind).map((t) => TASK_KEYS.map((k) => clean_(t[k])));
    body.appendTable([header].concat(rows.length ? rows : [TASK_KEYS.map(() => "")]));
  }
  body.appendParagraph("REMIND requirements / sector requirements:");
  body.appendTable([DEMAND_HEADER].concat(SECTORS.map((s) => [s].concat(DEMAND_KEYS.map((k) => clean_(((demands || {})[s] || {})[k]))))));
  doc.saveAndClose();
  DriveApp.getFileById(doc.getId()).moveTo(folder);
  return { pid, id: doc.getId(), name };
}

function hasOverviewRow_(doc, key) {
  const tables = doc.getBody().getTables(), t = tables[tables.findIndex(isOverview_)];
  const prefix = norm_(V2_LABELS.find((x) => x[0] === key)[1]).slice(0, 12);
  for (let r = 0; t && r < t.getNumRows(); r++) if (norm_(t.getRow(r).getCell(0).getText()).indexOf(prefix) === 0) return true;
  return false;
}

function saveProject_(body, f) {
  const editor = clean_(body.editor).slice(0, 80);
  if (!editor) throw new Error("editor name required");
  let results = [], pid, fileId, name;
  if (body.mode === "create") {
    const created = createDoc_(f.docs, body.overview || {}, body.new_tasks || [], body.demands || {});
    pid = created.pid; fileId = created.id; name = created.name;
    projectFolder_(f.descriptions, pid);
    log_(editor, name, "", "", "(new project)", "created");
  } else {
    fileId = body.file_id;
    const doc = openDoc_(fileId, f.docs);
    name = doc.getName();
    pid = name.split(" - ")[0].trim();   // from the document, not the request
    if (!/^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,39}$/.test(pid)) throw new Error("the document name does not start with a project acronym");
    results = checkEdits_(doc, body.edits);   // a batch is written completely or not at all
    if (!results.every((r) => r.ok)) { doc.saveAndClose(); return { ok: false, results, message: "Nothing was saved – please review the marked values." }; }
    results = applyEdits_(doc, body.edits, editor);
    for (const [k, v] of Object.entries(body.overview_add || {})) {   // only rows the (older) doc does not have yet
      if (k !== "last_reviewed" && V2_LABELS.some((x) => x[0] === k) && String(v).trim() && !hasOverviewRow_(doc, k)) setOverviewRow_(doc, k, clean_(v));
    }
    if ((body.new_tasks || []).length) log_(editor, name, "", "", appendTasks_(doc, body.new_tasks.slice(0, 50)) + " task row(s)", "rows added");
    doc.saveAndClose();
  }
  const prop = body.proposal || {};
  const doc2 = openDoc_(fileId, f.docs);
  if (prop.url || prop.data) {
    const link = saveProposal_(f.descriptions, pid, prop);
    setOverviewRow_(doc2, "proposal", link);
    log_(editor, name, "proposal", "", link, "proposal attached");
  }
  // a save from the form counts as a review: 'MM/YYYY, editor'
  setOverviewRow_(doc2, "last_reviewed", Utilities.formatDate(new Date(), "Europe/Berlin", "MM/yyyy") + ", " + editor);
  doc2.saveAndClose();
  dispatch_();
  const ok = results.every((r) => r.ok);
  return { ok, results, file: name, message: ok ? "Saved. The dashboard is being rebuilt." : "Some changes were not saved." };
}

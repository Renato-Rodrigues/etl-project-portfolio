# Setting up Google Drive, GitHub and the Apps Script companion

Order: 1 → 2 → 3 → 4. Start with the **TEST** folder in your personal Google account. Switch to the shared
drive only once everything works (step 5). The pipeline only reads; the companion (step 4) writes only when someone saves a change on the website.

## 1. TEST folder in Google Drive

1. Create a folder, e.g. `ETL dashboard TEST`, with a subfolder `overviews`.
2. Upload the made-up test data (`python -m etl_dash make-testdata --out ../local_drive_sim`): the `.docx` files
   (overview docs and `ETL people.xlsx`) into `overviews/`, and the blank template into a `template/` folder next to it.
   Or upload copies of the real docs, as you prefer.
   Tip: when uploading, enable *Settings → Convert uploads* to get native Google Docs/Sheets (needed later for
   write-back; read-only syncing works with both).
3. Note the ID of the data folder from its URL (`…/folders/<FOLDER_ID>`). Layout:
   `ETL people` (people table) in the root, and the subfolders `overviews/` (one doc per project), `template/` and
   `project_descriptions/` (one subfolder per project).

## 2. Google access: use a service account (2b) unless you need to run as yourself

The service account needs no OAuth consent screen: share the folder with its email like with a person. The OAuth
route (2a) requires a published consent screen, because Drive read access is a restricted scope.

## 2a. Access mode "oauth" (runs as you)

1. <https://console.cloud.google.com> → new project `etl-dashboard` → *APIs & Services → Library* → enable **Google Drive API**.
2. *OAuth consent screen* (Google Auth Platform): Audience External; Branding: app name `ETL dashboard` (no "Google"
   in the name), **select** your address in the support-email dropdown, developer email, and leave all app-domain links
   empty (otherwise Save stays disabled). Scope `…/auth/drive.readonly`; add yourself as a test user. **Then click "Publish app" (status "In production")**. In "Testing" status the refresh token
   expires after 7 days. An unverified app is fine for your own use (you click through one warning).
3. *Credentials → Create credentials → OAuth client ID → Desktop app*; download the JSON.
4. Get a refresh token once on your machine:
   ```sh
   pip install google-auth-oauthlib
   python -c "from google_auth_oauthlib.flow import InstalledAppFlow as F; f=F.from_client_secrets_file('client.json',['https://www.googleapis.com/auth/drive.readonly']); c=f.run_local_server(port=0); print(c.refresh_token)"
   ```
   Keep `client.json` and the token out of the repository (e.g. in a password manager).

## 2b. Access mode "service_account" (recommended)

1. Google Cloud project with the **Google Drive API** enabled → *IAM & Admin → Service accounts → Create*
   `etl-dashboard-reader` (no roles). If creating a key is blocked by an organization policy, use a project
   without an organization (personal account) or ask the organization's admin.
2. *Keys → Add key → JSON*, download it. Alternative without a long-lived key: Workload Identity Federation with
   GitHub OIDC (more setup).
3. In Drive, share the overview folder with the service-account email as **Viewer**. On a
   Shared Drive, add it as a member with the Viewer role.
4. PIK Workspace may block sharing with addresses outside `pik-potsdam.de`. If so, ask PIK IT for an exception
   for this account, or create the service account in a PIK-owned Google Cloud project.

## 3. GitHub repository, secrets and Pages

1. Create the repository (public, as decided) and push this code. *Settings → Pages → Source: GitHub Actions*.
2. *Settings → Secrets and variables → Actions*:

   | Name | Kind | Value |
   |---|---|---|
   | `ETL_SOURCE` | variable | `oauth` or `service_account` |
   | `DRIVE_FOLDER_ID` | secret | the data folder root (step 1) |
   | `ETL_TEST_DRIVE_FOLDER_ID` | secret | optional: the root of the TEST data folder (hidden test mode) |
   | `DRIVE_EDIT_LOG_ID` | secret | optional: the companion's edit-log sheet, shown in the Change log tab |
   | `GOOGLE_OAUTH_CLIENT_JSON`, `GOOGLE_OAUTH_REFRESH_TOKEN` | secret | mode oauth (2a) |
   | `GOOGLE_SA_KEY` | secret | mode service_account (2b): the whole JSON |
   | `ETL_VIEWER_PASSWORD`, `ETL_ADMIN_PASSWORD` | secret | the dashboard passwords |
   | `ETL_TEST_PASSWORD` | secret | optional: the hidden test mode (made-up data) |
   | `ALLOW_SHORT_PASSWORDS` | variable | `true` only while testing; production needs ≥ 20 characters |
   | `ETL_UPDATE_URL` | variable | Apps Script web-app URL (step 4) |
   | `ETL_UPDATE_KEY` | secret | a random string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(24))"` |
   | `ETL_EDIT_KEY` | secret | another random string: enables corrections and new projects for the admin password |

3. *Actions → Sync and deploy → Run workflow*. The log shows only counts.
4. Pin the actions in `.github/workflows/*.yml` to commit SHAs (supply-chain hygiene).

## 4. Apps Script companion (automatic updates + update button)

1. <https://script.google.com> → New project `ETL dashboard companion`. Paste `apps_script/Code.gs`. In
   *Project settings*, show `appsscript.json` and paste `apps_script/appsscript.json`.
2. *Project settings → Script properties*: `ROOT_FOLDER_ID` (the same folder as `DRIVE_FOLDER_ID`), optionally
   `TEST_ROOT_FOLDER_ID` (= `ETL_TEST_DRIVE_FOLDER_ID`), `GITHUB_REPO` (`owner/name`),
   `GITHUB_WORKFLOW` (`deploy.yml`), `GITHUB_TOKEN` and `UPDATE_KEY_SHA256`.
   - `GITHUB_TOKEN` is a fine-grained token for this repository only, with "Actions: Read and write".
   - For `UPDATE_KEY_SHA256`:
     `python -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" <ETL_UPDATE_KEY>`
   For corrections and new projects, also set `EDIT_KEY_SHA256` (hash of `ETL_EDIT_KEY`, same command),
   `EDIT_LOG_SHEET_ID` (an empty Google Sheet used as the edit log). Editing works on **native Google Docs**
   only: convert uploaded .docx files (File → Save as Google Docs) first.
3. Run `setup` once (authorize when asked). This installs the 5-minute change watcher.
4. *Deploy → New deployment → Web app*: Execute as **Me**, Who has access **Anyone**. Copy the URL into the GitHub
   variable `ETL_UPDATE_URL`, then run the workflow once so the page learns the URL.

## 5. Moving to the shared drive (later, after your go-ahead)

Change `DRIVE_FOLDER_ID` (and `ETL_SOURCE=service_account` with step 2b), update the companion's `ROOT_FOLDER_ID`,
run the workflow. The PROD owner of the companion and the GitHub token should be a
functional account rather than a personal one.

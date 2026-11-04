# Operations and local testing

## Local simulation of the whole setup (no Google, no GitHub)

```sh
python -m etl_dash make-testdata --out ../local_drive_sim        # made-up overview docs + people table, laid out like the TEST folder
set ETL_VIEWER_PASSWORD=view & set ETL_ADMIN_PASSWORD=edit         # (PowerShell: $env:ETL_VIEWER_PASSWORD="view" …)
python -m etl_dash serve --sim ../local_drive_sim --allow-short-passwords
```
Open <http://127.0.0.1:8765/>. Edit a doc in `../local_drive_sim/overviews` (e.g. fill a sector demand), click
**Update data**: the local server rebuilds, and the page offers to reload. This is the same API the Apps Script
companion provides in Google.

## Two ways to change project information

1. **Directly in the overview document** (Google Docs / Word), as today. The next sync, triggered by the 5-minute
   watcher or the Update button, picks it up.
2. **On the website** (admin password): *Edit project* in a project's panel, *Fix* next to an issue, the pencils, or
   *+ New project* on the Projects tab. Changes are written into the same document and logged with the editor's name.
   A proposal can be linked or uploaded; the file goes into `project_descriptions/<ID>/` and the overview doc links it.

Both routes edit the same file. If someone changed a value in the document after the dashboard was built, the
website refuses to overwrite it and shows the current value.

## Passwords and modes

| Password | Opens | Notes |
|---|---|---|
| viewer | real data | everyone in the group |
| admin ("edit") | real data + admin features (corrections, phase 6b) | few people |
| test (optional) | made-up test data, with admin features | hidden: the page looks the same with or without it |

- Production builds need passwords of **at least 20 characters**, e.g. 4–5 random words. The encrypted page is
  public, so short passwords can be guessed offline.
- `--allow-short-passwords` (variable `ALLOW_SHORT_PASSWORDS=true` in GitHub) accepts 4+ characters. Use it for
  test builds only, never for real data you want to keep confidential.
- The login delay after wrong attempts is only a UI courtesy; the real protection is the password strength (PBKDF2,
  600 000 iterations).
- Changing a password: update the secret, run the workflow, share the new password.

## What is published

`index.html` (code + ciphertext), `version.txt` (build id + time) and `robots.txt`. The build fails, and removes
its output, if any readable value from the data appears outside the ciphertext.

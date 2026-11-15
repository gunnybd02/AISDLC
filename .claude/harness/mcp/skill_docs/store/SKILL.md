---
name: store
description: Keep the session's ledger database safe on Google Drive - after each commit export the ledger with run ledger export and upload the copy with the Drive tool create_file, one file per commit, same schema, never change or trash a stored file.
---
# Store
A cloud machine's ledger is lost with the machine. After each commit, a whole copy of it goes to the user's Google
Drive folder, the store. The harness makes the copy; the Drive tool uploads it. Every copy has the same schema, so
they can be read together later.

## When to use
- Right after each commit: the answer of `step_done` or `git.commit` ends with a line that starts with `Store:`.
- When the user asks to save, back up or sync the session's database.

## Steps
1. `run("ledger", "export", {})`. The harness copies the whole ledger to a temp folder, checks that its schema is
   exactly the harness's, and answers with one Drive call.
2. Make that call with the Google Drive tool `create_file`, with exactly the values of the answer:
   | Field | Value |
   |---|---|
   | `title` | the name the answer gives |
   | `parentId` | the store folder's id |
   | `contentMimeType` | `application/x-sqlite3` |
   | `disableConversionToGoogleType` | `true` |
   | `base64Content` | `sha256:<hash>:<path>`, as given: the app reads the file itself; never type the file's bytes |
3. Tell the user in one line: the file's name, and that it is in the store.
4. One upload per commit. A failed upload: say so, and try once more at the next commit; never upload the live
   ledger file, and never read `.claude/state/`.

## The name of a copy
`<session>__<UTC time>__<newest commit>__s<schema>.db`
- The newest copy of a session is that session's whole ledger; older ones are its history.
- Copies whose last part (`s` and 8 characters) is the same have exactly the same schema.

## When it cannot be done
| Answer | Meaning | Move |
|---|---|---|
| `no store folder` | no folder id is set on this machine | ask the user for the Drive folder's id, then `run("ledger", "export", {"folder": "<id>"})`; the lasting place is the environment variable `HARNESS_DRIVE_FOLDER` |
| `the ledger's schema is not the harness's` | the ledger drifted from `schema.sql` | do not upload; tell the user, `run("health", "doctor", {})` |
| no Google Drive tool in this session | the connector is not on | tell the user the copy was not uploaded and where it is |

## Notes
- The store only grows. Never change, rename, move or trash a file in it; the harness asks the user before any
  Drive file is trashed or moved (`drive.remove`, `drive.move`).
- The folder id is the user's own: never write it into a file of a repository, a commit or a pull request.
- A copy holds the whole ledger: plans, commits, verify receipts, the session's records. It goes only to the store.

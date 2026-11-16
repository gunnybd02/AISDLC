---
name: store
description: Keep the session's ledger database safe on Google Drive - when to export and upload a copy (after a push, when a plan closes, when the end of a turn is held), run ledger export and the Drive tool create_file, store_status, which session and when a copy is from, never change or trash a stored file.
---
# Store
A cloud machine's ledger is lost with the machine. Whole copies of it go to the user's Google Drive folder, the
store. The harness makes a copy and knows which copies the store holds; the Drive tool uploads. Every copy has the
same schema and says by itself which ledger and session it is from, so they can be read together later.

## When to upload
A commit does not upload. A copy is due at a checkpoint:
| Checkpoint | How you learn it | `reason` |
|---|---|---|
| after a push or a merge request | the answer ends with a line that starts with `Store:` | `push` |
| a plan is closed | you closed it (`plan_close`, or the last `step_done` of a plan) | `plan-close` |
| the end of a turn is held | the turn does not end: `store.unsaved` (commits, plan events or pushes are in no copy) | `turn-end` |
| the user asks to save or back up | their words | `manual` |
| a child of an orchestra run hands back | its handback answer says so | `handback` |

One upload covers everything before it: at most one per checkpoint, never one per commit.

## Steps
1. `run("ledger", "export", {"reason": "<reason>"})`. The harness keeps the copy's record in the ledger, copies the
   whole ledger into `.harness-export/` of the folder the call is made from (git ignores it), checks that its schema
   is exactly the harness's, and answers with one Drive call.
2. Make that call with the Google Drive tool `create_file` (its name may show the connector's id in place of
   `Google_Drive`), with exactly the values of the answer:
   | Field | Value |
   |---|---|
   | `title` | the name the answer gives |
   | `parentId` | the store folder's id |
   | `contentMimeType` | `application/x-sqlite3` |
   | `disableConversionToGoogleType` | `true` |
   | `base64Content` | `sha256:<hash>:<path>`, as given: the app reads the file itself; never type the file's bytes |
3. The harness sees Drive's answer and keeps that the store holds the copy; it tells you so in a note. Tell the user in
   one line: the file's name, and that it is in the store.
4. `run("ledger", "store_status", {})` says the newest copy the store holds and the work that is in no copy yet.

## Which session, and when
`<session>__<ledger>-<number>__<UTC time>__<reason>__<newest commit>__s<schema>.db`
- `<ledger>-<number>`: the ledger's id (6 characters) and the copy's number. The highest number of a ledger is its
  whole content; lower numbers are its history. A session that starts again on a new machine has a new ledger id.
- Inside each copy, the table `pl_notes` holds its record (`kind = 'store.export'`: ledger, number, session, reason,
  time, commit, repository, branch) and the ledger's id (`kind = 'store.ledger'`).
- Copies whose last part (`s` and 8 characters) is the same have exactly the same schema.

## When it cannot be done
| Answer | Meaning | Move |
|---|---|---|
| `no store folder` | no folder id is set on this machine | the store is off; when the user wants it, ask for the Drive folder's id and pass `{"folder": "<id>"}`; the lasting place is the environment variable `HARNESS_DRIVE_FOLDER` |
| `the ledger's schema is not the harness's` | the ledger drifted from `schema.sql` | do not upload; tell the user, `run("health", "doctor", {})` |
| Drive: `can't be sent by reference` | the Drive tool reads a file only from the session's own folders | export again with `{"into": "<a folder inside this session's working folder>"}`, then the new call |
| no Google Drive tool, or the upload fails | the copy is not in the store | tell the user; the turn ends, and the next checkpoint tries again with a new copy |

## Notes
- The store only grows. Never change, rename, move or trash a file in it; the harness asks the user before any
  Drive file is trashed or moved (`drive.remove`, `drive.move`).
- The end of a turn is held once for the same work: when the upload cannot be done, say so and end the turn.
- Never upload the live ledger file, and never read `.claude/state/`.
- The folder id is the user's own: never write it into a file of a repository, a commit or a pull request.

## Copies of an orchestra run
A session of a delegated plan adds its plan marker to every copy's name: `...__orch.<plan id>.<child name>__...db`
for a child, `...__orch.<plan id>.parent__...db` for the parent; the record says it too (`plan`). One Drive search,
name contains `orch.<plan id>.`, lists every database of that run. The parent's plan is delivered, and a child's
session archived, only once that child's copy is in the store (`guide("orchestrate", "skills")`).

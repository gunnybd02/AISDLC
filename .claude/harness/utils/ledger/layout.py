"""Layout: the folders of the store for delegated plans (the user's design of 2026-11-21):

  store/<project>/P<plan>-<title>/            the parent's final ledger copy (plan-close)
  store/<project>/P<plan>-<title>/<child>/    the child's ticket CSV and its final ledger copy (stop)

The project is the repository's name. Copies made along the way (turn-end, handback, push) stay in the store's db
folder as the safety net (store.py). Harness code cannot call Drive: path_words gives the model the calls that find or
make each level not known yet, and keeps the path as asked (store.path rows); placed, run by the hook on each Drive
answer, keeps a level's id (store.folder rows: target its name, key its parent's id) when its name is on an asked path
and its parent is the store folder or a folder already kept. The first folder seen for a name and parent counts."""
from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from harness.utils.ledger.store import FOLDER, FOLDER_MIME, folder, folder_entries, note
from harness.utils.shapes import PlanStore

if TYPE_CHECKING:
    from harness.utils.contracts import Event

PATH = "store.path"  # target = a folder path the harness asked for (names joined by /), key = the store folder's id
SLUG = re.compile(r"[^a-z0-9]+")
PARENT_ASKED = re.compile(r"parentId\s*=\s*\\*'([A-Za-z0-9_-]{10,})")  # the folder a search call names


def slug(text: str, most: int = 40) -> str:
    """A title as a folder name: lower case words joined by -, at most most characters.

    Args:
        text: the title.
        most: the longest result.

    Returns:
        The slug; "plan" when nothing is left.
    """
    return SLUG.sub("-", str(text).lower()).strip("-")[:most].rstrip("-") or "plan"


def project_of(repo_url: str) -> str:
    """The project folder's name: the repository's name, without .git.

    Args:
        repo_url: the repository's URL (https or ssh).

    Returns:
        Its last part, e.g. AISDLC; "project" for none.
    """
    name = str(repo_url).strip().rstrip("/").replace(":", "/").split("/")[-1]
    return (name[:-4] if name.endswith(".git") else name) or "project"


def plan_path(repo_url: str, plan: int | str, title: str, child: str = "") -> list[str]:
    """The folders of a delegated plan in the store: [project, P<plan>-<title>] and the child's subtask folder.

    Args:
        repo_url: the repository the plan works in.
        plan: the plan's number.
        title: the plan's title.
        child: a child's name; "" for the plan's own folder.

    Returns:
        The names, from the store folder down, e.g. ["AISDLC", "P51-login-page", "api"].
    """
    return [project_of(repo_url), f"P{plan}-{slug(title)}"] + ([child] if child else [])


def folder_id(port: PlanStore, name: str, parent: str) -> str:
    """The Drive id of the folder of this name under this parent, as a Drive answer showed it (the first one seen).

    Args:
        port: the harness ledger.
        name: the folder's name.
        parent: its parent's Drive id.

    Returns:
        Its id; "" when no answer showed it.
    """
    rows = port.rows("SELECT text FROM pl_notes WHERE kind = ? AND target = ? AND key = ? ORDER BY at, rowid LIMIT 1",
                     (FOLDER, name, parent)) if parent else []
    return rows[0]["text"] if rows else ""


def held_path(port: PlanStore, names: list[str]) -> tuple[str, int]:
    """How far down a path of the store the ledger knows the folders.

    Args:
        port: the harness ledger.
        names: the path's names from the store folder down (plan_path).

    Returns:
        (the id of the deepest known folder, the number of levels known); (the store folder, 0) when none is known,
        ("", 0) when no store folder is set.
    """
    parent, known = folder(), 0
    if not parent:
        return "", 0
    for name in names:
        found = folder_id(port, name, parent)
        if not found:
            break
        parent, known = found, known + 1
    return parent, known


def path_words(port: PlanStore, sid: str, names: list[str]) -> tuple[str, str]:
    """Keep that the harness asks for this path, and say the Drive calls that find or make each level not known yet.

    Args:
        port: the harness ledger.
        sid: the session that asks.
        names: the path's names from the store folder down (plan_path).

    Returns:
        (the words for the model, "" when every level is known; the deepest folder's id, or the placeholder the model
        fills with the id Drive gives).
    """
    joined = "/".join(names)
    if not port.rows("SELECT 1 AS x FROM pl_notes WHERE kind = ? AND target = ? AND key = ? LIMIT 1",
                     (PATH, joined, folder())):
        port.write(lambda con, rec: note(con, PATH, joined, folder(), "", sid, int(time.time() * 1000)))
    parent, known = held_path(port, names)
    if known == len(names):
        return "", parent
    lines = [f"First find the store's folder {joined}, one level at a time; the harness reads each answer of Drive and "
             "keeps the folder's id:"]
    for i in range(known, len(names)):
        under = parent if i == known else f"<the id Drive gave for {names[i - 1]}>"
        lines.append(f"{i + 1}. search_files with the query: title = '{names[i]}' and mimeType = '{FOLDER_MIME}' and "
                     f"parentId = '{under}'. If Drive lists none, make it: create_file with title {names[i]}, "
                     f"contentMimeType {FOLDER_MIME}, parentId {under}.")
    return "\n".join(lines), f"<the id Drive gave for {names[-1]}>"


def asked_names(port: PlanStore) -> set[str]:
    """The folder names of every path the harness asked for under the store folder.

    Args:
        port: the harness ledger.

    Returns:
        The names.
    """
    rows = port.rows("SELECT target FROM pl_notes WHERE kind = ? AND key = ?", (PATH, folder())) if folder() else []
    return {n for r in rows for n in str(r["target"]).split("/") if n}


def placed(port: PlanStore, event: Event) -> list[str]:
    """Keep the id of each level of an asked path that a Drive tool's answer shows: a folder whose name is on an asked
    path and whose parent (its parentId or parents, else the folder the call names) is the store folder or a folder
    already kept; the first one seen for a name and parent counts.

    Args:
        port: the harness ledger.
        event: the PostToolUse hook call of an MCP tool; its input and response are read.

    Returns:
        A note per folder newly kept.
    """
    root = folder()
    if not root or not str(event.tool or "").startswith("mcp__") or event.kind != "PostToolUse":
        return []
    wanted = asked_names(port)
    if not wanted:
        return []
    named = PARENT_ASKED.search(json.dumps(event.input or {}, ensure_ascii=False))
    known = {root} | {str(r["text"]) for r in port.rows("SELECT text FROM pl_notes WHERE kind = ?", (FOLDER,))}
    news: dict[tuple[str, str], str] = {}
    for entry in folder_entries(event.response):
        name, parents = str(entry.get("title") or entry.get("name")), entry.get("parents")
        parent = str(entry.get("parentId") or (parents[0] if isinstance(parents, list) and parents else "")
                     or (named.group(1) if named else ""))
        if entry.get("mimeType") == FOLDER_MIME and name in wanted and parent in known \
                and not folder_id(port, name, parent):
            news.setdefault((name, parent), str(entry["id"]))
    at = int(time.time() * 1000)
    if news:
        port.write(lambda con, rec: [note(con, FOLDER, n, p, i, event.session, at) for (n, p), i in news.items()])
    return [f"The store's {n} folder is Drive folder {i}." for (n, _), i in news.items()]

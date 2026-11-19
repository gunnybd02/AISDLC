"""Ending: the end of a delegated plan with a plan branch (docs/system.md sections 5 and 10, part 7). Land calls it:

- stops: once every child's pull request is merged into the plan branch, one signed stop order per accepted child that
  takes orders (utils/orchestra/orders.py) and has not been sent one: it uploads its ledger copy and ends;
- form: form 2, one question for the user: merge the plan branch into the base (each plan pull request at its head),
  delete the children's branches and the plan branch, archive every child session (earlier ones too). The facts are
  kept in the ticket (FORM) and hashed into the question's code;
- accepts: the user's Allow writes the form's pass and one merge pass per plan pull request (utils/forge/merges.py),
  so the merge tool lets exactly those merges through; Deny writes nothing;
- finish: after the plan pull requests merged and with the form allowed, delete the branches (a branch GitHub will not
  delete is named for the user) and give the archive_session call of every child session; the pass is used."""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from typing import Any

from harness.utils.contracts import now
from harness.utils.forge import merges
from harness.utils.git.github import GitHubError
from harness.utils.orchestra import crew, orders
from harness.utils.orchestra.brief import branch
from harness.utils.orchestra.locked import LOCK, slug_of
from harness.utils.plan import tickets
from harness.utils.shapes import PlanStore, Ticket

FORM = "endForm"  # the parent's ticket: {code, plan, prs: [{slug, number, sha, base}], branches, sessions}
ENDED = "ended"  # the parent's ticket: {at, deleted, kept, sessions} once finish ran
ASKED = re.compile(r"^End plan \d+: .+ \[(?P<code>e[0-9a-f]{12})\]\?")
ALLOW_LABEL, NO_LABEL = "Allow", "Deny"
ARCHIVE = "mcp__claude-code-remote__archive_session"
FREE = "SELECT 1 AS x FROM pl_asks WHERE sid = '' AND key = ? AND used = 0"


def stops(port: PlanStore, sid: str) -> list[str]:
    """The stop order of each accepted child that takes orders and was not sent one yet.

    Args:
        port: the ledger port.
        sid: the parent's session.

    Returns:
        One line per order to send (orders.give).
    """
    ticket = port.ticket(sid) or {}
    plan = crew.delegated(ticket)
    if plan is None:
        return []
    sent = {r["target"] for r in port.rows("SELECT target, text FROM pl_notes WHERE kind = 'order.sent' AND sid = ?",
                                           (sid,)) if json.loads(r["text"] or "{}").get("kind") == "stop"}
    lines = []
    for card in plan["children"]:
        entry = (ticket.get("crew") or {}).get(card["name"]) or {}
        if entry.get("state") == crew.ACCEPTED and card["name"] not in sent:
            lines.append(orders.give(port, sid, card["name"], "stop"))
    return [line for line in lines if line]


def facts(ticket: Ticket, github: Callable[..., Any]) -> dict[str, Any]:
    """What form 2 is about, read now: each plan pull request at its head, the branches to delete, the sessions.

    Args:
        ticket: the parent's ticket.
        github: call(method, path, fields?) -> the JSON answer.

    Returns:
        {plan, base, prs: [{slug, number, sha, merged}], branches: [{slug, ref}], sessions}.

    Raises:
        GitHubError: a plan pull request cannot be read.
    """
    plan, held = crew.delegated(ticket) or {}, (ticket or {}).get(LOCK) or {}
    team = ticket.get("crew") or {}
    prs, branches = [], []
    for unit in held.get("units", []):
        slug, pr = slug_of(unit, plan.get("root") or ""), unit.get("pr") or {}
        if pr.get("number"):
            seen = github("GET", f"repos/{slug}/pulls/{pr['number']}")
            prs.append({"slug": slug, "number": pr["number"], "sha": str((seen.get("head") or {}).get("sha") or ""),
                        "merged": bool(seen.get("merged")), "base": unit.get("base", "main")})
        branches += [{"slug": slug, "ref": branch(plan["id"], name)} for name, e in team.items()
                     if e.get("state") == crew.ACCEPTED] + [{"slug": slug, "ref": held.get("branch", "")}]
    sessions = [s for e in team.values() for s in list(e.get("sessions") or []) + [e.get("sid")] if s]
    return {"plan": plan.get("id"), "base": prs[0]["base"] if prs else "main", "prs": prs,
            "branches": [dict(t) for t in {json.dumps(b, sort_keys=True): b for b in branches}.values()],
            "sessions": list(dict.fromkeys(sessions))}


def question(held: dict[str, Any]) -> str:
    """Form 2's question for these facts, its code the hash of them all."""
    code = "e" + hashlib.sha256(json.dumps({k: held[k] for k in ("plan", "prs", "branches", "sessions")},
                                           sort_keys=True).encode("utf-8")).hexdigest()[:12]
    merging = ", ".join(f"PR #{p['number']} at {p['sha'][:12]}" for p in held["prs"]) or "nothing"
    names = ", ".join(b["ref"] for b in held["branches"])
    return (f"End plan {held['plan']}: merge plan/p{held['plan']} into {held['base']} ({merging}), delete "
            f"{len(held['branches'])} branches ({names}), archive {len(held['sessions'])} child sessions [{code}]?")


def allowed(port: PlanStore, ticket: Ticket) -> bool:
    """Whether the user allowed the form 2 the ticket holds, and finish has not used it."""
    code = ((ticket or {}).get(FORM) or {}).get("code")
    return bool(code) and bool(port.rows(FREE, (code,)))


def form(port: PlanStore, sid: str, github: Callable[..., Any]) -> str:
    """Form 2 to ask, or, once allowed, the merges to make.

    Args:
        port: the ledger port.
        sid: the parent's session.
        github: the GitHub call.

    Returns:
        The words for the parent's model.
    """
    ticket = port.ticket(sid) or {}
    if allowed(port, ticket):
        todo = [p for p in ticket[FORM]["prs"] if not p.get("merged")]
        return ("Form 2 is allowed. " + " ".join(
            f"Merge PR #{p['number']} of {p['slug']} with the merge tool, expectedHeadSha {p['sha']}." for p in todo)
            + " Then run('orchestra', 'land', {}) again.")
    try:
        held = facts(ticket, github)
    except GitHubError as e:
        return f"Form 2 cannot be made: a plan pull request cannot be read ({str(e)[-200:]})."
    asked = question(held)
    code = ASKED.match(asked)["code"]
    port.write(lambda con, rec: tickets.save(con, {**tickets.latest(con, sid), FORM: {**held, "code": code}}))
    return ("Ask the user form 2 now with AskUserQuestion, one question, exactly:\n" + asked + "\nOptions: \""
            f"{ALLOW_LABEL}\", \"{NO_LABEL}\". Never fill in the answer. On Allow merge each plan pull request with the "
            "merge tool and its expectedHeadSha, then run('orchestra', 'land', {}) again; on Deny nothing changes.")


def accepts(port: PlanStore, sid: str, answers: dict[str, str]) -> list[str]:
    """The user's Allow to form 2: its pass and one merge pass per plan pull request at its head.

    Args:
        port: the ledger port.
        sid: the session the form was asked in.
        answers: {question: label} of an AskUserQuestion call.

    Returns:
        One GATE note when form 2 was allowed; [] otherwise.
    """
    for asked, label in (answers or {}).items():
        found = ASKED.match(str(asked))
        held = ((port.ticket(sid) or {}).get(FORM) or {}) if found else {}
        if not found or str(label).strip() != ALLOW_LABEL or held.get("code") != found["code"]:
            continue
        codes = [held["code"]] + [merges.code_of(*p["slug"].split("/", 1), int(p["number"]), p["sha"])
                                  for p in held.get("prs", []) if p.get("sha") and not p.get("merged")]
        stamp = int(time.time() * 1000)
        port.write(lambda con, rec: con.executemany(
            "INSERT OR REPLACE INTO pl_asks (sid, key, at, used) VALUES ('', ?, ?, 0)", [(c, stamp) for c in codes]))
        return [f"GATE: the user allows form 2 [{held['code']}]: merge each plan pull request with the merge tool and its "
                "expectedHeadSha, then run('orchestra', 'land', {}) again."]
    return []


def finish(port: PlanStore, sid: str, github: Callable[..., Any]) -> list[str]:
    """After the plan pull requests merged, with form 2 allowed: delete the branches, give the archive calls, use the
    pass.

    Args:
        port: the ledger port.
        sid: the parent's session.
        github: the GitHub call.

    Returns:
        The lines: what was deleted, what was kept and why, and one archive_session call per child session.
    """
    held = (port.ticket(sid) or {}).get(FORM) or {}
    deleted, kept = [], []
    for b in held.get("branches", []):
        try:
            github("DELETE", f"repos/{b['slug']}/git/refs/heads/{b['ref']}")
            deleted.append(b["ref"])
        except GitHubError as e:
            kept.append(f"{b['ref']} ({str(e)[-120:]})")

    def write(con: Any, rec: Any) -> None:
        con.execute("UPDATE pl_asks SET used = 1 WHERE sid = '' AND key = ?", (held.get("code"),))
        tickets.save(con, {**tickets.latest(con, sid), ENDED: {"at": now(), "deleted": deleted, "kept": kept,
                                                                "sessions": held.get("sessions", [])}})
    port.write(write)
    lines = [f"Deleted the branches {', '.join(deleted)}." if deleted else "No branch was deleted."]
    if kept:
        lines.append(f"GitHub kept {', '.join(kept)}: ask the user to delete them on GitHub.")
    lines += [f"Archive the child session {s} now: {ARCHIVE} {json.dumps({'session_id': s})}"
              for s in held.get("sessions", [])]
    return lines

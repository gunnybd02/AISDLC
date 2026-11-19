"""Orders: the signed one-way messages a parent sends a running child (docs/system.md section 8, part 6). A child never
messages up (auto mode refuses it); the parent sends an order down with send_message, and the child's harness checks it
where it arrives (a ReadNotifications answer). An order is one LINE and a body up to END:

    orch <plan> | child <name> | issue #<N> <sha12> | round <n> | kind <fix|answer|stop> | mac <32 hex>
    <the reason of a fix, the answer, or nothing for stop>
    end of order

mac is HMAC-SHA256 with the child's own key (made at spawn, in its card block) over every field and the sha256 of the
body, cut to 32 hex. round counts every order to this child from 1: only the next one counts, so an order cannot be
sent twice. A valid order unlocks one action (fix and answer: one more round of the card plan; stop: the end); an
invalid one unlocks nothing. No order widens the scope, touches the locked tests or approves anything."""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import re
import secrets
from typing import Any

from harness.utils.plan import tickets
from harness.utils.shapes import PlanStore

KINDS = ("fix", "answer", "stop")
END = "end of order"
LINE = re.compile(r"orch (?P<plan>\d+) \| child (?P<name>[a-z0-9][a-z0-9-]{0,39}) \| issue #(?P<issue>\d+) "
                  r"(?P<sha>[0-9a-f]{12}) \| round (?P<round>\d+) \| kind (?P<kind>[a-z]+) \| mac (?P<mac>[0-9a-f]{32})")
MOST = 4000  # characters of a body
KEYS = "orderKeys"  # the parent's ticket: {child name: its key}, made at its first spawn and kept


def new_key() -> str:
    """A fresh key for one child: 32 hex characters from the system's random source."""
    return secrets.token_hex(16)


def key_for(port: PlanStore, sid: str, name: str) -> str:
    """The order key of a child: made at its first spawn and kept in the parent's ticket, so a fresh session of the
    same child gets the same key.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.

    Returns:
        The key.
    """
    def write(con: Any, rec: Any) -> str:
        ticket = tickets.latest(con, sid) or {}
        held = dict(ticket.get(KEYS) or {})
        if not held.get(name):
            held[name] = new_key()
            tickets.save(con, {**ticket, KEYS: held})
        return held[name]
    return port.write(write)


def of_role(role: Any) -> dict[str, Any]:
    """The order fields a child's brief gave it: {key, cloud (the parent's cloud session), rounds}; {} for none.

    Args:
        role: the child's role (utils/orchestra/child.parse).

    Returns:
        The fields, or {}.
    """
    held = ((role or {}).get("record") or {}).get("orders") or {}
    return held if isinstance(held, dict) and held.get("key") else {}


def plain(body: str) -> str:
    """The body as it is signed: HTML entities undone, each line stripped, empty lines dropped (a relay may indent,
    escape or change line ends; the words stay).

    Args:
        body: the body as written or as it arrived.

    Returns:
        The lines, joined by newlines.
    """
    lines = [line.strip() for line in html.unescape(str(body or "")).replace("\r", "").split("\n")]
    return "\n".join(line for line in lines if line)


def mac_of(key: str, plan: int, name: str, issue: int, sha: str, n: int, kind: str, body: str) -> str:
    """The signature of one order.

    Args:
        key: the child's key.
        plan, name, issue, sha, n, kind: the fields of the line (sha: the issue block's sha256, its first 12 hex).
        body: the body (plain() is applied).

    Returns:
        32 hex characters of HMAC-SHA256.
    """
    digest = hashlib.sha256(plain(body).encode("utf-8")).hexdigest()
    fields = json.dumps([int(plan), name, int(issue), sha[:12], int(n), kind, digest])
    return hmac.new(key.encode("utf-8"), fields.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def text(key: str, plan: int, name: str, issue: int, sha: str, n: int, kind: str, body: str = "") -> str:
    """The whole message of one order: its line, its body and END.

    Raises:
        ValueError: an unknown kind, or a body longer than MOST.
    """
    if kind not in KINDS:
        raise ValueError(f"an order is {', '.join(KINDS)}, not {kind}")
    if len(body or "") > MOST:
        raise ValueError(f"the body of an order holds at most {MOST} characters")
    line = (f"orch {int(plan)} | child {name} | issue #{int(issue)} {sha[:12]} | round {int(n)} | kind {kind} | "
            f"mac {mac_of(key, plan, name, issue, sha, n, kind, body)}")
    return "\n".join([line] + ([plain(body)] if plain(body) else []) + [END])


def parse(said: str) -> list[dict[str, Any]]:
    """Every order in a text: its fields and its body (up to END, else to the next order or the end of the text).

    Args:
        said: a text that may hold orders (a notification answer, flattened).

    Returns:
        One dict per order: plan, name, issue, sha, round (ints where numbers), kind, mac, body (plain).
    """
    said = html.unescape(str(said or ""))
    found = list(LINE.finditer(said))
    out = []
    for n, m in enumerate(found):
        rest = said[m.end():found[n + 1].start() if n + 1 < len(found) else len(said)]
        cut = re.search(r"^\s*" + re.escape(END) + r"\s*$", rest, re.M)
        body = rest[:cut.start()] if cut else rest
        out.append({"plan": int(m["plan"]), "name": m["name"], "issue": int(m["issue"]), "sha": m["sha"],
                    "round": int(m["round"]), "kind": m["kind"], "mac": m["mac"], "body": plain(body)})
    return out


def check(order: dict[str, Any], plan: int, name: str, issue: int, sha: str, key: str, last: int) -> str:
    """Why an order does not count for this child; "" when it does.

    Args:
        order: one order of parse().
        plan, name, issue, sha: the child's plan number, name, issue number and issue sha (from its card block).
        key: the child's key.
        last: the round of the last valid order it took (0 for none).

    Returns:
        The reason, or "".
    """
    if not key:
        return "this child has no order key: its brief named none"
    if order.get("kind") not in KINDS:
        return f"kind {order.get('kind')} is no order ({', '.join(KINDS)})"
    if (order.get("plan"), order.get("name")) != (int(plan), name):
        return f"it is for child {order.get('name')} of plan {order.get('plan')}, not {name} of plan {plan}"
    if (order.get("issue"), order.get("sha")) != (int(issue), str(sha)[:12]):
        return f"it names issue #{order.get('issue')} {order.get('sha')}, not #{issue} {str(sha)[:12]}"
    if order.get("round") != last + 1:
        return f"its round is {order.get('round')}, the next one is {last + 1}: an old or skipped order"
    want = mac_of(key, plan, name, issue, sha, order["round"], order["kind"], order.get("body", ""))
    if not hmac.compare_digest(want, str(order.get("mac"))):
        return "its mac is wrong: the order was changed or not signed with this child's key"
    return ""

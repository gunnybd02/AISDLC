"""plans_settle (docs 04, section 6): the desk plans still open (their newest event is neither delivered nor dropped),
what proves their end, and ending them.
- proof: a commit of the plan number in rec_commits proves delivered; else a closed ticket that held the plan proves
  its closeReason (delivered, else dropped); else nothing.
- write: ends the proven plans, except one whose session still runs with an open ticket.
- drop: ends unproven plans of sessions that no longer run, after the user's one Yes in a form ('Cho ph\u00e9p', kept as a
  one-use pass plans-drop:<plans> in pl_asks); the open holder ticket closes abandoned."""
import re
import time

from harness.utils.git.asks import take

DEAD_AFTER = 6 * 3600 * 1000  # a session the hook has not seen for 6 hours no longer runs
ALLOW_LABEL, NO_LABEL = "Cho ph\u00e9p", "Kh\u00f4ng"
DROP_RE = re.compile("^Cho ph\u00e9p b\u1ecf plan (?P<plans>pd-[^?]+)\\?$")
ACCEPTED = "GATE: the user allows dropping {plans}; run plans_settle with the same drop list again, once."


def open_plans(port):
    out = []
    for r in port.rows("SELECT DISTINCT plan_id FROM pl_plan_revs ORDER BY at"):
        found = port.revision(r["plan_id"])
        if found and found["event"] not in ("delivered", "dropped"):
            ref = next(iter(port.rows("SELECT ref FROM pl_plan_events WHERE plan_id = ? AND event = 'approved' "
                                      "ORDER BY n DESC LIMIT 1", (r["plan_id"],))), None)
            out.append({**found, "ref": ref["ref"] if ref else None})
    return out


def proof(port, plan):
    if plan["ref"] is not None and port.rows("SELECT 1 FROM rec_commits WHERE plan_id = ?", (plan["ref"],)):
        return "delivered"
    holder = port.holder(plan["plan_id"])
    if holder and holder["state"] == "closed":
        return "delivered" if holder.get("closeReason") == "delivered" else "dropped"
    return None


def alive(port, sid):
    rows = port.rows("SELECT last_at FROM sessions WHERE sid = ?", (sid,))
    return bool(rows) and rows[0]["last_at"] >= int(time.time() * 1000) - DEAD_AFTER


def settle(port, write=False, drop=None):
    plans = open_plans(port)
    if drop:
        return drop_plans(port, plans, sorted(set(drop)))
    lines = []
    for p in plans:
        found, holder = proof(port, p), port.holder(p["plan_id"])
        running = alive(port, p["sid"]) and holder and holder["state"] == "open"
        state = f"proven {found}" if found else "unproven"
        if write and found and not running:
            port.end_plan(p, found)
            state = f"ended {found}"
        lines.append(f"{p['plan_id']} (no {p['ref'] or '-'}, {p['event']}): {state}; session {p['sid'] or '-'} "
                     f"{'runs' if alive(port, p['sid']) else 'no longer runs'}")
    return "\n".join(lines) or "No plan is open."


def drop_plans(port, plans, names):
    known = {p["plan_id"]: p for p in plans}
    for name in names:
        p = known.get(name)
        if p is None:
            raise ValueError(f"{name} is no open plan")
        if proof(port, p):
            raise ValueError(f"{name} is proven: settle it with write: true")
        if alive(port, p["sid"]):
            raise ValueError(f"{name}: its session still runs")
    key = "plans-drop:" + ",".join(names)
    if not take(port, key):
        q = f"{ALLOW_LABEL} b\u1ecf plan {', '.join(names)}?"
        return (f"Dropping plans needs the user's Yes. Ask now with AskUserQuestion, one question, exactly: {q} "
                f"Options: \"{ALLOW_LABEL}\", \"{NO_LABEL}\". Never fill in the answer. Then run the same drop again.")
    for name in names:
        port.end_plan(known[name], "dropped", abandon=True)
    return f"Dropped {', '.join(names)}; their open tickets closed abandoned."


def accepts(port, answers):
    """Keep the user's Yes to a drop form as a one-use pass; the notes for the model."""
    notes = []
    for q, label in (answers or {}).items():
        m = DROP_RE.match(str(q))
        if m and str(label).strip() == ALLOW_LABEL:
            key = "plans-drop:" + ",".join(sorted(x.strip() for x in m["plans"].split(",")))
            port.write(lambda con, rec, key=key: con.execute(
                "INSERT OR REPLACE INTO pl_asks (sid, key, at, used) VALUES ('', ?, ?, 0)", (key, int(time.time() * 1000))))
            notes.append(ACCEPTED.format(plans=m["plans"]))
    return notes

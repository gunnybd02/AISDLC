"""step_done: the one way a plan's change is committed (the single writer of commits). The model asks; the harness
checks, then commits or refuses:
- the plan is approved and not delivered, and its repository still stands on the commit of the approval;
- its latest verify passed, and every file of the plan is still what that verify saw;
- no changed file holds a secret (a private key, a cloud or forge token);
- something of the plan changed.
Then it stages and commits only the plan's changed files with the message, and the plan is delivered
(utils/plan/closing.py checks the commit it made, as it checks any)."""
import os
import re

from harness.utils.git.commit import changed, commit
from harness.utils.git.facts import head, top
from harness.utils.plan.closing import delivery, from_repo
from harness.utils.plan.verify import blobs

LONGEST_MESSAGE = 2000
SECRETS = {
    "a private key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY"),
    "an AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "a GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "a GitLab token": re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    "a Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "an API key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{32,}\b"),
}


class StepError(ValueError):
    pass


def secret_in(path):
    """The kind of secret the file holds, or "" (a file that is gone or not text holds none that can be read)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(2_000_000)
    except OSError:
        return ""
    return next((kind for kind, pattern in SECRETS.items() if pattern.search(text)), "")


def message_of(message):
    text = str(message).strip()
    if not text:
        raise StepError("say what the commit does: the message is empty")
    if len(text) > LONGEST_MESSAGE:
        raise StepError(f"the message is longer than {LONGEST_MESSAGE} characters")
    return text


def step_done(port, plan_id, message):
    """Commit the verified change of an approved plan, or say why not."""
    text = message_of(message)
    plan = port.approved_plan(plan_id)
    if plan is None:
        raise StepError(f"no approved plan {plan_id} waits for delivery")
    repo = top(plan["root"])
    if not repo:
        raise StepError(f"the plan's root {plan['root']} is not in a git repository")
    if not plan.get("base") or head(repo) != plan["base"]:
        raise StepError("the repository moved since the approval (or had no commit then): present a new plan")
    receipt = port.receipt(plan)
    if not receipt or not receipt.get("ok"):
        raise StepError(f"plan {plan_id} has no passing verify: run('verify', 'run', {{'plan': '{plan_id}'}}) first")
    moved = sorted(p for p, b in blobs(plan).items() if receipt["files"].get(p) != b)
    if moved:
        raise StepError(f"changed since the verify: {', '.join(moved)}; run the verify again")
    paths = changed(repo, list(from_repo(repo, plan["root"], dict.fromkeys(plan["files"] + plan["tests"]))))
    if not paths:
        raise StepError(f"no file of plan {plan_id} changed: nothing to commit")
    for path in paths:
        kind = secret_in(os.path.join(repo, path))
        if kind:
            raise StepError(f"{path} holds {kind}: take it out (and revoke it), verify again, then step_done")
    sha = commit(repo, paths, text)
    notes = delivery(port, "", True, plan)
    return "\n".join([f"Committed {sha[:12]} ({', '.join(paths)})."] + notes)

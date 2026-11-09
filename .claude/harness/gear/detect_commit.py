"""CommitGate: the findings of a commit before it runs. What is staged and the plan's latest verify receipt come from
the port's commit_view, called only for a commit: {repo, staged: {path: blob id}, receipt: {ok, files: {path: blob id}}}.
- plan.none: no approved plan in the session;
- commit.unverified: the plan has no passing verify receipt;
- commit.outside: a staged file the plan does not name;
- commit.changed: a staged file whose content is not the one the verify saw."""
import os

from harness.gear.detect_plan import key, relative
from harness.utils.contracts import Detector, Finding


class CommitGate(Detector):
    def detect(self, event, facts):
        target, plan = facts.get("git_commit"), facts.get("plan")
        if event.kind != "PreToolUse" or not target:
            return []
        if plan is None:
            return [Finding("plan.none", f"git commit in {target['repo']}")]
        commit = facts["commit_view"](target["repo"], plan)
        receipt = commit.get("receipt")
        if not receipt or not receipt.get("ok"):
            return [Finding("commit.unverified", f"plan {plan['plan_id']} has no passing verify")]
        named = {key(p) for p in plan["files"] + plan["tests"]}
        seen = {key(p): h for p, h in (receipt.get("files") or {}).items()}
        out = []
        for path, sha in sorted(commit["staged"].items()):
            rel = relative(os.path.join(commit["repo"], path), plan["root"])
            if rel not in named:
                out.append(Finding("commit.outside", f"{path} is not a file of plan {plan['plan_id']}"))
            elif seen.get(rel) != sha:
                out.append(Finding("commit.changed", f"{path} changed after the verify"))
        return out

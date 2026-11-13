"""CommitGate: the findings of a commit before it runs. What is staged and the plan's latest verify receipt come from
the port's commit_view, called only for a safe commit:
{repo, plan_repo, staged: {path: blob id}, receipt: {ok, files: {path: blob id}}}.
- commit.unsafe: the gate cannot see the whole commit (translate_git says why); refused before anything else;
- plan.none: no approved plan in the session;
- commit.outside: the commit is in another repository than the plan's, or stages a file the plan does not name;
- commit.unverified: the plan has no passing verify receipt;
- commit.changed: a staged file whose content is not the one the verify saw."""
import os

from harness.utils.contracts import Detector, Finding
from harness.utils.plan.files import key, named, rel_key, relative


class CommitGate(Detector):
    def detect(self, event, facts):
        target, plan = facts.get("git_commit"), facts.get("plan")
        if event.kind != "PreToolUse" or not target:
            return []
        if target.get("unsafe"):
            return [Finding("commit.unsafe", target["unsafe"])]
        if plan is None:
            return [Finding("plan.none", f"git commit in {target['repo']}")]
        commit = facts["commit_view"](target["repo"], plan)
        if not commit["plan_repo"] or key(commit["repo"]) != key(commit["plan_repo"]):
            return [Finding("commit.outside", f"{commit['repo']} is not the repository of plan {plan['plan_id']}")]
        receipt = commit.get("receipt")
        if not receipt or not receipt.get("ok"):
            return [Finding("commit.unverified", f"plan {plan['plan_id']} has no passing verify")]
        seen = {rel_key(p): h for p, h in (receipt.get("files") or {}).items()}
        out = []
        for path, sha in sorted(commit["staged"].items()):
            rel = relative(os.path.join(commit["repo"], path), plan["root"])
            if rel not in named(plan):
                out.append(Finding("commit.outside", f"{path} is not a file of plan {plan['plan_id']}"))
            elif seen.get(rel) != sha:
                out.append(Finding("commit.changed", f"{path} changed after the verify"))
        return out

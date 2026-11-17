"""Fitness (spec 13 section 6): adding to the harness stays small. A new detector takes four files (its module, its
ITEMS line, its pipeline line and its rule row) and never the runner or the arbiter; a new MCP action takes one file.
Each is planted in a copy of the tree and proven through that copy's own entries, and every net stays clean."""
import json
import unittest
from pathlib import Path

from harness.assemble.engine.loader import Loader
from harness.nets import (bridges_net, config_net, english_net, entry_net, hints_net, imports_net, layout_net,
                          owners_net, size_net, verdict_net)
from harness.tests import entry_of
from harness.tests.e2e import copy_tree, run

NETS = (layout_net, imports_net, bridges_net, size_net, verdict_net, config_net, entry_net, hints_net, owners_net,
        english_net)
DETECTOR = '''"""Fit: a detector planted by the fitness test."""
from __future__ import annotations

from harness.utils.contracts import Detector, Event, Finding
from harness.utils.shapes import Facts


class Fit(Detector):
    """A shell line that holds fit-me: fit.flagged."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report fit.flagged for a shell line that holds fit-me."""
        command = str(event.input.get("command", ""))
        return [Finding("fit.flagged", command)] if "fit-me" in command else []
'''
ACTION = '''"""fit: an action planted by the fitness test."""
from __future__ import annotations

from typing import Any

from harness.utils.contracts import READ, ActionContext, McpAction

ACTIONS = [("fit.hello", "Hello")]


class Hello(McpAction):
    """fit.hello: a greeting."""
    block, name, effect = "fit", "hello", READ
    summary = "Greet a person by name"
    args_schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    needs = ()

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Hello, the name."""
        return f"Hello, {args['name']}"
'''
SAME = ("harness/assemble/engine/runner.py", "harness/gear/decide/arbiter.py")


def snapshot(home: Path) -> dict[str, str]:
    """{posix path: text} of every file of the tree but the state."""
    return {p.relative_to(home).as_posix(): p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(home.rglob("*")) if p.is_file() and "state" not in p.relative_to(home).parts
            and "__pycache__" not in p.parts}


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """The files added or changed between two snapshots."""
    return sorted(rel for rel, text in after.items() if before.get(rel) != text)


class FitnessTest(unittest.TestCase):
    def clean(self, home):
        self.assertEqual(Loader(home).problems(), [])
        for net in NETS:
            with self.subTest(net=net.__name__):
                self.assertEqual(net.check(home), [])

    def test_a_new_detector_touches_at_most_four_files(self):
        home = copy_tree(self)
        before = snapshot(home)
        (home / "harness/gear/detect/fit.py").write_text(DETECTOR, encoding="utf-8")
        index = home / "harness/gear/__init__.py"
        index.write_text(index.read_text(encoding="utf-8").replace(
            "\n]", '\n    {"kind": "detector", "name": "fit", "ref": "harness.gear.detect.fit:Fit"},\n]'), encoding="utf-8")
        floor = home / "harness/assemble/pipelines/base.json"
        data = json.loads(floor.read_text(encoding="utf-8"))
        floor.write_text(json.dumps({**data, "detectors": data["detectors"] + ["fit"]}, indent=2), encoding="utf-8")
        row = {"finding": "fit.flagged", "verdict": "refuse", "why": "The fitness test refuses fit-me.",
               "test": "harness/tests/assemble/test_fitness.py#test_a_new_detector_touches_at_most_four_files"}
        (home / "harness/gear/rules/fit.json").write_text(json.dumps({"rules": [row]}), encoding="utf-8")
        touched = changed(before, snapshot(home))
        self.assertLessEqual(len(touched), 4, touched)
        self.assertFalse(set(touched) & set(SAME))  # never the runner or the arbiter
        self.clean(home)
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "echo fit-me"},
                   "session_id": "s", "cwd": str(home)}
        code, out, err = run(entry_of(home, "hook"), json.dumps(payload))
        self.assertEqual(code, 0, err)
        answer = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(answer["permissionDecision"], "deny")
        self.assertIn("The fitness test refuses fit-me.", answer["permissionDecisionReason"])

    def test_a_new_action_touches_one_file(self):
        home = copy_tree(self)
        before = snapshot(home)
        (home / "harness/mcp/actions/fit.py").write_text(ACTION, encoding="utf-8")
        self.assertEqual(changed(before, snapshot(home)), ["harness/mcp/actions/fit.py"])
        self.clean(home)
        lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}),
                 json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                     "name": "run", "arguments": {"block": "fit", "action": "hello", "args": {"name": "Ann"}}}})]
        code, out, err = run(entry_of(home, "mcp_server"), "\n".join(lines) + "\n")
        self.assertEqual(code, 0, err)
        answers = {a["id"]: a for a in map(json.loads, out.splitlines())}
        self.assertEqual(answers[2]["result"]["content"][0]["text"], "Hello, Ann")


if __name__ == "__main__":
    unittest.main()

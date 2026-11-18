"""h10.maint-grant: utils/maint/grant.py and entry/hook.py read the same rows the same way."""
import importlib.util
import json
import re
import time
import unittest

from harness.utils.ledger import mask
from harness.utils.maint import grant
from harness.tests import CLAUDE_DIR, entry_of

HOOK = (entry_of(CLAUDE_DIR, "hook")).read_text(encoding="utf-8")


def rows_of(*texts):
    return lambda sql, args: [{"text": t, "why": "w"} for t in texts[:1]]


class GrantTest(unittest.TestCase):
    def test_the_hook_reads_the_same_rows(self):
        self.assertIn(f'GRANT = "{grant.KIND}"', HOOK)
        self.assertIn(f'LATEST = "{grant.LATEST}"', HOOK)
        self.assertIn(f"MAX_MINUTES = {grant.MAX_MINUTES}", HOOK)
        hook_question = re.search(r'PAUSE = re.compile\("(.*)"\)', HOOK).group(1).encode().decode("unicode_escape")
        self.assertEqual(hook_question, grant.QUESTION.pattern)

    def test_the_hook_masks_the_shapes_the_ledger_masks(self):
        """s7.grant.trace: the trace of the hook (standard library only) redacts what utils/ledger/mask.py redacts."""
        spec = importlib.util.spec_from_file_location("harness_hook_entry", entry_of(CLAUDE_DIR, "hook"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual([(p.pattern, p.flags) for p in module.SECRET_SHAPES],
                         [(p.pattern, p.flags) for p in mask.SECRETS.values()])
        self.assertEqual(module.REDACTED, mask.REDACTED)
        payload = {"tool_input": {"command": "ls\nAKIA" + "A" * 16, "description": "List it", "other": "x"}}
        self.assertEqual(module.summary(payload), {"command": "ls\n[redacted]", "description": "List it"})

    def test_a_grant_lasts_until_its_end_and_never_past_the_longest(self):
        now = 1000.0
        self.assertIsNone(grant.active(rows_of(), now))
        self.assertEqual(grant.active(rows_of(json.dumps({"until": now + 60})), now)["until"], now + 60)
        for text in (json.dumps({"until": now - 1}), json.dumps({"until": now + 121 * 60}), "{", "[]"):
            with self.subTest(text=text):
                self.assertIsNone(grant.active(rows_of(text), now))
        self.assertIsNotNone(grant.active(rows_of(json.dumps({"until": time.time() + 5}))))


class ChildScopeTest(unittest.TestCase):
    """The plan doors' grant of a file (utils/plan/grants.py) in a child session: its scope is its card's."""

    def port(self, record):
        child = {"name": "api", "plan": 7, "record": record,
                 "card": {"change": ["app/orders.py", "app/views/"], "tests": ["tests/test_orders.py"],
                          "acTests": ["tests/test_orders_ac.py"]}}
        return type("Port", (), {"ticket": lambda self, sid: {"child": child}})()

    def test_a_registered_child_adds_only_files_of_its_scope(self):
        """s3.child.scope: change and tests (a folder holds its files) pass; anything else is refused with the issue."""
        from harness.utils.plan import grants
        port = self.port({"issue": {"number": 41}})
        for rel in ("app/orders.py", "app/views/list.py", "tests/test_orders.py"):
            grants.not_locked(port, "c1", rel)  # no refusal
        with self.assertRaisesRegex(grants.DoorError, r"app/other\.py is outside the scope of issue #41"):
            grants.not_locked(port, "c1", "app/other.py")
        with self.assertRaisesRegex(grants.DoorError, "acceptance test the orchestrator locked"):
            grants.not_locked(port, "c1", "tests/test_orders_ac.py")
        grants.not_locked(self.port({}), "c1", "app/other.py")  # a child without an issue keeps the old doors


if __name__ == "__main__":
    unittest.main()

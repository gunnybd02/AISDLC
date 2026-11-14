"""h3.three-tools: the actions of the server, pinned. A new or lost action changes this list on purpose; the doctor checks
each against its entry (block, name, effect, ports)."""
import unittest

from harness.assemble.engine.checks import action_problems
from harness.assemble.engine.loader import Loader
from harness.utils.contracts import READ, WRITE
from tests import CLAUDE_DIR

PINNED = {
    "health.doctor": READ, "health.items": READ,
    "ledger.db_query": READ, "ledger.plans_settle": WRITE,
    "maint.grant": READ, "maint.status": READ,
    "plan.plan_present": WRITE, "plan.plan_status": READ, "plan.plan_revise": WRITE, "plan.plan_show": READ,
    "plan.plan_drop": WRITE,
    "plan.step_done": WRITE, "plan.step_skip": WRITE, "plan.plan_close": READ,
    "verify.run": WRITE,
    "git.run": WRITE, "git.commit": WRITE, "git.push": WRITE, "git.mr_open": WRITE,
}


def entries():
    return [e for f in Loader(CLAUDE_DIR).action_files() for e in Loader.actions(f)]


class ActionRegistryTest(unittest.TestCase):
    def test_the_actions_of_the_server_are_the_pinned_ones(self):
        self.assertEqual({f"{b}.{n}": cls.effect for b, n, cls in entries()}, PINNED)

    def test_each_action_matches_its_entry(self):
        self.assertEqual(action_problems(entries()), [])


if __name__ == "__main__":
    unittest.main()

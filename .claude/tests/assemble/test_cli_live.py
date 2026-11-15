"""h22.live-update: live update brings the newest main of the harness's own clone into a running session: it pins the
code that runs now, fast-forwards the clone, and the new code goes in force only with the user's Cho phép of
exactly its sha; an update over local changes, or off main, is refused."""
import re
import shutil
import subprocess
import unittest

from harness.assemble.engine.cli_live import update_door
from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from harness.utils.gateway.release import current, stamp
from tests import tree
from tests.e2e import copy_tree

HEALTH = ("harness", "mcp", "actions", "health.py")
OLD, NEW = "Every problem of the tree", "Every problem of the tree, as the doctor sees it"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


class LiveUpdateTest(unittest.TestCase):
    def setUp(self):
        self.origin = tree(self, {".gitignore": ".claude/state/\n__pycache__/\n"})
        shutil.copytree(copy_tree(self), self.origin / ".claude")
        for args in (("init", "-q", "-b", "main"), ("config", "user.name", "t"), ("config", "user.email", "t@t"),
                     ("add", "-A"), ("commit", "-q", "-m", "start")):
            git(self.origin, *args)
        clone = tree(self, {}) / "clone"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(clone)], check=True, capture_output=True)
        self.home = clone / ".claude"
        self.port = LedgerPort(self.home)

    def merge_on_origin(self):
        """A change merged on the origin's main: the health block's summary."""
        path = self.origin / ".claude" / "/".join(HEALTH)
        path.write_text(path.read_text(encoding="utf-8").replace(OLD, NEW, 1), encoding="utf-8")
        git(self.origin, "commit", "-q", "-am", "Say what the doctor sees")

    def allow(self, text):
        q = re.search(r"exactly: (.+?\?) Options", text).group(1)
        event = Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}]}, "s1", "/tmp")
        Act(self.port).run(event, {"answers": {q: "Cho phép"}}, Verdict("allow"))

    def test_an_update_pins_what_runs_and_goes_in_force_only_with_the_users_word(self):
        running = stamp(self.home)
        code, text = update_door(self.port, self.home)
        self.assertEqual(code, 0, text)
        self.assertIn("Up to date", text)
        self.assertEqual(current(self.home), running)  # pinned: the code that ran is the release in force

        self.merge_on_origin()
        code, text = update_door(self.port, self.home)
        self.assertEqual(code, 0, text)
        self.assertIn("Publishing needs the user's word", text)
        self.assertEqual(current(self.home), running)  # pulled and built, not in force
        self.assertIn(NEW, (self.home / "/".join(HEALTH)).read_text(encoding="utf-8"))

        self.allow(text)
        code, text = update_door(self.port, self.home)
        self.assertEqual(code, 0, text)
        self.assertIn("is in force", text)
        self.assertEqual(current(self.home), stamp(self.home))
        self.assertNotEqual(current(self.home), running)

    def test_an_update_over_local_changes_or_off_main_is_refused(self):
        self.merge_on_origin()
        path = self.home / "/".join(HEALTH)
        path.write_text(path.read_text(encoding="utf-8") + "\n# a local edit\n", encoding="utf-8")
        code, text = update_door(self.port, self.home)
        self.assertEqual(code, 1)
        self.assertIn("local changes", text)
        self.assertNotIn(NEW, path.read_text(encoding="utf-8"))

        git(self.home.parent, "checkout", "-q", "--", ".")
        git(self.home.parent, "checkout", "-q", "-b", "mine")
        code, text = update_door(self.port, self.home)
        self.assertEqual(code, 1)
        self.assertIn("not main", text)


if __name__ == "__main__":
    unittest.main()

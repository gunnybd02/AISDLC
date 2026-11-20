"""h22.live-update: live update brings the newest main of the harness's own clone into a running session: it pins the
code that runs now, fast-forwards the clone, and the new code goes in force only with the user's Allow of
exactly its sha; an update over local changes, or off main, is refused."""
import json
import re
import shutil
import subprocess
import unittest

from harness.assemble.engine.cli_live import session_update, update_door
from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from harness.utils.gateway.release import build, current, previous, stamp
from harness.tests import anchor_of, tree
from harness.tests.e2e import copy_tree, run

HEALTH = ("harness", "mcp", "actions", "health.py")
LIVE = ("harness", "assemble", "engine", "cli_live.py")
WIRE = ("harness", "assemble", "engine", "cli_wire.py")
OLD, NEW = "Every problem of the tree", "Every problem of the tree, as the doctor sees it"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


class LiveUpdateTest(unittest.TestCase):
    def setUp(self):
        self.origin = tree(self, {".gitignore": ".claude/state/\n__pycache__/\n"})
        copy = copy_tree(self)
        shutil.copytree(copy, self.origin / ".claude")
        shutil.copy(copy.parent / "anchor.py", self.origin / "anchor.py")
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

    def change_on_origin(self, rel, old, new, message):
        path = self.origin / ".claude" / "/".join(rel)
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        git(self.origin, "commit", "-q", "-am", message)

    def started(self):
        """What a session reads when it begins; it always says how to reach the tools without the MCP server."""
        text = session_update(self.home)
        boot = (anchor_of(self.home)).as_posix()
        self.assertIn(f'If it has none, the same from the shell: python3 "{boot}" cli tool guide <block>', text)
        self.assertIn(f'python3 "{boot}" cli tool run <block> <action>', text)
        self.assertIn(f'Read the skill work before any work: guide, name work, mode skills (from the shell: python3 '
                      f'"{boot}" cli tool guide work --mode skills)', text)
        return text

    def test_an_update_pins_what_runs_and_puts_merged_main_in_force_with_no_form(self):
        running = stamp(self.home)
        code, text = update_door(self.port, self.home)
        self.assertEqual(code, 0, text)
        self.assertIn("Up to date", text)
        self.assertEqual(current(self.home), running)  # pinned: the code that ran is the release in force

        self.merge_on_origin()
        code, text = update_door(self.port, self.home)
        self.assertEqual(code, 0, text)
        self.assertNotIn("Publishing needs the user's word", text)  # the merge was the user's word
        self.assertIn("is in force", text)
        self.assertIn(NEW, (self.home / "/".join(HEALTH)).read_text(encoding="utf-8"))
        self.assertEqual(current(self.home), stamp(self.home))
        self.assertNotEqual(current(self.home), running)

    def test_merged_main_with_a_broken_doctor_is_not_put_in_force(self):
        running = stamp(self.home)
        update_door(self.port, self.home)  # pins what runs
        self.change_on_origin(HEALTH, OLD, NEW, "Say what the doctor sees")
        (self.origin / ".claude" / "harness" / "stray.py").write_text("x = 1\n", encoding="utf-8")  # off the layout
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", "A file the layout refuses")
        code, text = update_door(self.port, self.home)
        self.assertEqual(code, 1, text)
        self.assertIn("finds problems", text)
        self.assertEqual(current(self.home), running)

    def merge_event(self, owner, repo, response):
        return Event("PostToolUse", "mcp__github__merge_pull_request",
                     {"owner": owner, "repo": repo, "pullNumber": 7}, "s1", "/tmp", response)

    def test_a_merge_of_the_harness_repo_puts_its_main_in_force(self):
        running = stamp(self.home)
        update_door(self.port, self.home)  # pins what runs
        self.merge_on_origin()
        owner, repo = self.origin.parent.name, self.origin.name
        notes = Act(self.port).run(self.merge_event(owner, repo, {"merged": True, "sha": "abc"}), {},
                                   Verdict("allow"))
        self.assertTrue(any("After the merge" in n and "is in force" in n for n in notes), notes)
        self.assertEqual(current(self.home), stamp(self.home))
        self.assertNotEqual(current(self.home), running)

    def test_another_repo_or_a_failed_merge_changes_nothing(self):
        running = stamp(self.home)
        update_door(self.port, self.home)
        self.merge_on_origin()
        owner, repo = self.origin.parent.name, self.origin.name
        for event in (self.merge_event("someone", "other", {"merged": True}),
                      self.merge_event(owner, repo, "Pull Request is not mergeable"),
                      Event("PostToolUse", "mcp__github__get_pull_request", {"owner": owner, "repo": repo}, "s1",
                            "/tmp", {"merged": True})):
            notes = Act(self.port).run(event, {}, Verdict("allow"))
            self.assertFalse(any("After the merge" in n for n in notes), notes)
        self.assertEqual(current(self.home), running)
        self.assertNotIn(NEW, (self.home / "/".join(HEALTH)).read_text(encoding="utf-8"))

    def test_a_publish_keeps_the_release_it_replaced_as_previous(self):
        running = stamp(self.home)
        update_door(self.port, self.home)
        self.assertIsNone(previous(self.home))
        self.merge_on_origin()
        update_door(self.port, self.home)
        self.assertNotEqual(current(self.home), running)
        self.assertEqual(previous(self.home), running)

    def test_an_update_to_a_release_marked_bad_keeps_the_one_in_force(self):
        running = stamp(self.home)
        update_door(self.port, self.home)
        self.merge_on_origin()
        git(self.home.parent, "pull", "-q", "--ff-only")
        sha = build(self.home)  # the release of the new main
        (self.home / "state" / "live" / "bad").write_text(f"{sha}\n", encoding="utf-8")
        code, text = update_door(self.port, self.home)
        self.assertEqual(code, 1, text)
        self.assertIn("failed once", text)
        self.assertEqual(current(self.home), running)
        self.assertIn("failed once", session_update(self.home))
        self.assertEqual(current(self.home), running)

    def test_a_file_git_does_not_track_under_harness_stops_the_update(self):
        self.merge_on_origin()
        loose = self.home / "harness" / "loose.py"
        loose.write_text("x = 1\n", encoding="utf-8")
        code, text = update_door(self.port, self.home)
        self.assertEqual(code, 1)
        self.assertIn("does not track", text)
        self.assertNotIn(NEW, (self.home / "/".join(HEALTH)).read_text(encoding="utf-8"))
        loose.unlink()
        code, text = update_door(self.port, self.home)
        self.assertEqual(code, 0, text)

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

    def test_a_session_starts_on_the_newest_main_when_its_doctor_is_clean(self):
        running = stamp(self.home)
        self.assertIn("up to date", self.started())
        self.assertEqual(current(self.home), running)  # pinned
        self.merge_on_origin()
        text = self.started()
        self.assertIn("brought up to date", text)
        self.assertEqual(current(self.home), stamp(self.home))  # in force without a form: the session has not begun
        self.assertNotEqual(current(self.home), running)

    def test_the_release_put_in_force_at_start_writes_the_hint(self):
        # the machine was prepared with this code; main now names another skill to read first
        self.change_on_origin(LIVE, "Read the skill work before any work: guide, name work,",
                              "Read the skill flow before any work: guide, name flow,", "Name the skill flow")
        text = session_update(self.home)
        self.assertIn("brought up to date", text)
        self.assertIn("Read the skill flow before any work", text)  # the new release's words
        self.assertNotIn("Read the skill work", text)
        self.assertIn(f'python3 "{anchor_of(self.home).as_posix()}" cli tool run <block> <action>', text)
        code, out, err = run(anchor_of(self.home), "{}", args=("session_start",))  # the next start runs the release
        self.assertEqual(code, 0, err)
        again = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("up to date", again)
        self.assertIn("Read the skill flow before any work", again)  # its own words

    def test_a_release_that_cannot_say_the_hint_leaves_the_old_one(self):
        self.change_on_origin(WIRE, '("status", "publish", "update", "hint")', '("status", "publish", "update")',
                              "Lose the hint door")
        text = self.started()  # the hint of the code that ran: the session still reads how to reach the tools
        self.assertIn("brought up to date", text)

    def test_the_hint_door_prints_the_hint(self):
        code, out, err = run(anchor_of(self.home), args=("cli", "live", "hint"))
        self.assertEqual(code, 0, out + err)
        self.assertTrue(out.strip().startswith("Its tools: mcp__harness__find"), out)
        self.assertIn("cli tool guide work --mode skills", out)

    def test_a_session_keeps_its_harness_when_the_newest_main_is_broken_or_mixed(self):
        bad = self.origin / ".claude" / "harness" / "mcp" / "actions" / "broken.py"
        bad.write_text("ACTIONS = [(\"health.x\", \"Missing\")]\n", encoding="utf-8")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", "Break the actions")
        running = stamp(self.home)
        text = self.started()
        self.assertIn("finds problems", text)
        self.assertEqual(current(self.home), running)  # the broken main never runs
        path = self.home / "/".join(HEALTH)
        path.write_text(path.read_text(encoding="utf-8") + "\n# a local edit\n", encoding="utf-8")
        self.assertIn("local changes", self.started())
        self.assertEqual(current(self.home), running)

    def test_the_entry_never_blocks_a_session_from_starting(self):
        lone = copy_tree(self)  # a home in no git clone
        code, out, err = run(anchor_of(lone), "{}", args=("session_start",))
        self.assertEqual(code, 0, err)
        context = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(context["hookEventName"], "SessionStart")
        self.assertIn("keeps release", context["additionalContext"])
        self.assertIn(f'python3 "{(anchor_of(lone)).as_posix()}" cli tool run', context["additionalContext"])


if __name__ == "__main__":
    unittest.main()

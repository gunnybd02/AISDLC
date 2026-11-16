"""orchestra and the store: every copy of an orchestra run carries its plan marker; the hook reads Drive's own answer
to find each child's copy; a plan is delivered and a child archived only once its database is in the store (newer
than its handback), or the user waived it for a child that can never upload."""
import time
import unittest

from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from harness.utils.ledger import store
from harness.utils.orchestra import cleanup, crew, land, review, synced
from harness.tests.utils.test_review import UNITS, FakeGitHub, Scenario

land.WAIT = 0

FOLDER = "1AbCdEfGhIjKlMnOpQrStUv"


def title(sid, draft, name, seconds=None):
    """A store copy's name for a child of a plan, as store.begin makes it."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(time.time() + 5 if seconds is None else seconds))
    return f"{store.session_part(sid)}__abcdef-002__{stamp}__handback__orch.{draft}.{name}__1234567__s0123abcd.db"


class SyncedTest(Scenario):
    def drive_answer(self, files, sid="s1"):
        """The hook's Act on a Drive search whose answer lists files."""
        answer = {"files": [{"id": f"1File{i:06d}xyz", "title": t} for i, t in enumerate(files)]}
        return Act(self.port).run(Event("PostToolUse", "mcp__caaed075-x__search_files", {"query": "q"}, sid, "/w",
                                        answer), {}, Verdict("allow"))

    def accepted_and_merged(self):
        github = FakeGitHub(self.repo)
        self.hand_back()
        review.check(self.port, "s1", "hello", UNITS, [])
        review.accept(self.port, "s1", "hello", UNITS, github)
        self.port.write(lambda con, rec: __import__("harness.utils.plan.tickets", fromlist=["x"]).save(
            con, {**self.port.ticket("s1"), "phase": "deliver"}))  # the parent's own step is done
        return github

    def test_every_copy_of_a_run_carries_its_plan_marker(self):
        ticket = self.port.ticket("s1")
        self.assertEqual(crew.store_tag(ticket), f"orch.{ticket['draft']}.parent")
        self.assertEqual(crew.store_tag({"child": {"draft": "pd-x1", "name": "api"}}), "orch.pd-x1.api")
        self.assertEqual(crew.store_tag({}), "")
        record = store.begin(self.port, "s1", "handback", tag="orch.pd-x1.api")
        self.assertIn("__handback__orch.pd-x1.api__", record["title"])
        self.assertEqual(record["plan"], "orch.pd-x1.api")
        self.assertNotIn("orch", store.begin(self.port, "s1", "manual", tag="bad tag")["title"])

    def test_the_hook_keeps_a_childs_copy_from_drives_own_answer(self):
        draft = self.port.ticket("s1")["draft"]
        notes = self.drive_answer([title("session_child0001", draft, "hello"),
                                   title("session_other999", draft, "hello"),   # another session's copy
                                   title("session_child0001", "pd-other", "hello")])  # another plan's
        self.assertEqual(len(notes), 1)
        stored = self.port.ticket("s1")["crew"]["hello"]["stored"]
        self.assertEqual(stored["fileId"], "1File000000xyz")
        self.assertEqual(self.drive_answer([title("session_child0001", draft, "hello")], sid="s9"), [])

    def test_a_copy_named_by_the_childs_own_id_from_its_receipt_is_its_own(self):
        """In the cloud a child's harness knows itself by another id than its cloud session's (found live)."""
        self.hand_back(receipt={"session": "8aa3f275-9f8b-56b3"})
        review.check(self.port, "s1", "hello", UNITS, [])
        draft = self.port.ticket("s1")["draft"]
        self.assertEqual(len(self.drive_answer([title("8aa3f275-9f8b-56b3", draft, "hello")])), 1)
        self.assertEqual(self.drive_answer([title("someone-else", draft, "hello")]), [])

    def test_land_delivers_only_when_every_child_is_in_the_store(self):
        github = self.accepted_and_merged()
        text = land.land(self.port, "s1", UNITS, [], github, folder=FOLDER)
        self.assertIn("Not synced yet: hello (no copy found)", text)
        self.assertIn(f"title contains 'orch.{self.port.ticket('s1')['draft']}.' and parentId = '{FOLDER}'", text)
        self.assertEqual(self.port.ticket("s1")["state"], "open")
        draft = self.port.ticket("s1")["draft"]
        self.drive_answer([title("session_child0001", draft, "hello", seconds=time.time() - 3600)])
        self.assertIn("older than its handback", land.land(self.port, "s1", UNITS, [], github, folder=FOLDER))
        self.drive_answer([title("session_child0001", draft, "hello")])
        text = land.land(self.port, "s1", UNITS, [], github, folder=FOLDER)
        self.assertIn("is delivered", text)
        self.assertIn(f"orch.{draft}.parent", text)  # the parent saves its own ledger too

    def test_a_child_that_can_never_upload_passes_only_with_the_users_allow(self):
        github = self.accepted_and_merged()
        draft = self.port.ticket("s1")["draft"]
        question = synced.waiver_question(draft, "hello")["question"]
        Act(self.port).run(Event("PostToolUse", "AskUserQuestion", {}, "s1", "/w"),
                           {"answers": {question: "Deny"}}, Verdict("allow"))
        self.assertIn("Not synced yet", land.land(self.port, "s1", UNITS, [], github, folder=FOLDER))
        notes = Act(self.port).run(Event("PostToolUse", "AskUserQuestion", {}, "s1", "/w"),
                                   {"answers": {question: "Allow"}}, Verdict("allow"))
        self.assertIn("close without the database of hello", " ".join(notes))
        self.assertIn("is delivered", land.land(self.port, "s1", UNITS, [], github, folder=FOLDER))

    def test_remove_archives_a_ticked_child_only_once_it_is_in_the_store(self):
        self.hand_back()
        review.check(self.port, "s1", "hello", UNITS, [])
        review.forget(self.port, "s1", "hello", "done")
        form = cleanup.checklist(self.port.ticket("s1"))[0]
        Act(self.port).run(Event("PostToolUse", "AskUserQuestion", {}, "s1", "/w"),
                           {"answers": {form["question"]: "hello"}}, Verdict("allow"))
        self.assertIn("not archived yet", cleanup.remove(self.port, "s1", FOLDER))
        self.drive_answer([title("session_child0001", self.port.ticket("s1")["draft"], "hello")])
        self.assertIn("archive_session", cleanup.remove(self.port, "s1", FOLDER))  # the tick waited


if __name__ == "__main__":
    unittest.main()

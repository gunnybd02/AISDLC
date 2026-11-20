"""orchestra, part 1: the card rules (docs/05-orchestra.md 5.1), the delegated opening (section 6), the brief (10) and
the parent's spawn, started and status, through the real ledger port and the real actions."""
import json
import subprocess
import unittest
from unittest import mock

from harness.assemble.engine.ports import LedgerPort
from harness.mcp.actions.orchestra import Spawn, Started, Status, source_url
from harness.mcp.actions.plan import PlanPresent
from harness.utils.contracts import YES, ActionContext, ActionError
from harness.utils.orchestra import brief, card, crew
from harness.utils.plan import desk
from harness.utils.plan.approval import approvals
from harness.tests.e2e import copy_tree, git_repo

GOOD = {"name": "api", "unit": "home", "goal": "List the orders of a user",
        "ac": ["GET /orders returns the user's orders", "an unknown user gets 404"],
        "change": ["app/orders.py"], "tests": ["tests/test_orders.py"]}
PLAN = {"title": "Split the work", "what": ["w"], "files": ["notes.md"]}


def children(n):
    """n good cards named c1..cn."""
    return [{**GOOD, "name": f"c{i}"} for i in range(1, n + 1)]


class CardTest(unittest.TestCase):
    def test_a_criterion_of_filler_words_names_no_case(self):
        faults = card.card_problems([{**GOOD, "ac": ["It works as expected"]}])
        self.assertEqual(len(faults), 1)
        self.assertIn(card.NO_CASE, faults[0])

    def test_every_fault_is_named_at_once(self):
        bad = [{**GOOD, "goal": "x" * 201, "unit": "nowhere"}, {**GOOD, "session": "Main"},
               {**GOOD, "name": "b", "session": "main", "actions": ["merge"]}, {"name": "Bad Name"}]
        text = " | ".join(card.card_problems(bad))
        for part in ("goal is one sentence", "unit 'nowhere'", "two children have this name",
                     "named by another card", "only action a child may take is push", "each child has a name"):
            self.assertIn(part, text)

    def test_several_children_may_share_a_unit_in_the_cloud(self):
        self.assertEqual(card.card_problems(children(3)), [])

    def test_a_card_is_cleaned(self):
        got = card.clean_card({**GOOD, "goal": "a | b", "ac": ["one thing; other | third"],
                               "read": ["x.py", "x.py", "y.py"]})
        self.assertEqual((got["goal"], got["ac"], got["read"]), ("a / b", ["one thing, other, third"], ["x.py", "y.py"]))

    def test_the_grant_and_the_card_files(self):
        items = {**PLAN, "children": [GOOD, {**GOOD, "name": "web", "change": ["web/a.js"], "actions": ["push"]}]}
        g = card.grant(items)
        self.assertEqual((g["units"], g["count"], g["actions"]), ([], 2, {"api": [], "web": ["push"]}))
        wide = card.with_card_files(items)
        self.assertEqual(wide["files"], ["notes.md", "app/orders.py", "web/a.js"])
        self.assertEqual(wide["tests"], ["tests/test_orders.py"])
        self.assertIs(card.with_card_files(PLAN), PLAN)

    def test_a_card_names_its_acceptance_tests_and_the_parent_may_write_them(self):
        """s1.card.ac-tests: acTests are files, never change paths, at most 8; s1.card.shown: they are tests of the
        parent plan."""
        good = {**GOOD, "acTests": ["tests/ac/test_orders_ac.py"]}
        self.assertEqual(card.card_problems([good]), [])
        wide = card.with_card_files({**PLAN, "children": [good]})
        self.assertEqual(wide["tests"], ["tests/test_orders.py", "tests/ac/test_orders_ac.py"])
        bad = [{**GOOD, "acTests": ["app/orders.py"]}, {**GOOD, "name": "b", "acTests": ["tests/ac/"]},
               {**GOOD, "name": "c", "acTests": [f"t{i}.py" for i in range(9)]}]
        text = " | ".join(card.card_problems(bad))
        for part in ("never a change or test path too: app/orders.py", "acTests are files", "acTests is at most 8 paths"):
            self.assertIn(part, text)


class BriefTest(unittest.TestCase):
    def test_the_brief_talks_through_the_branch_never_by_message(self):
        text = brief.brief(7, "pd-x", GOOD, "session_parent01", rounds=3)
        self.assertNotIn("send_message", text)
        self.assertIn("your branch, CI and your draft pull request are how you talk", text)
        self.assertIn(".harness/notes/api/ on your branch", text)
        self.assertIn("Read every note there before you start", text)

    def test_the_brief_sends_the_child_to_the_ledger_door_not_the_file(self):
        text = brief.brief(7, "pd-x", GOOD, "session_parent01", rounds=3)
        self.assertIn("run('ledger', 'db_query', {sql})", text)
        self.assertIn("Never open the ledger file (harness.db)", text)

    def test_the_brief_says_who_it_is_and_that_send_backs_are_its_plan(self):
        text = brief.brief(7, "pd-x", GOOD, "session_parent01", rounds=3)
        self.assertTrue(text.startswith('You are child session "api" of the delegated plan 7, approved by the user in '
                                        "the orchestrator session session_parent01."))
        for part in ("never call AskUserQuestion", "orch/p7/api", "Each send-back and answer", "act on them",
                     "AC1: GET /orders returns the user's orders  (behaviour p7.api.ac1)", "p7.api.ac2",
                     "run('orchestra', 'take')", "Change: app/orders.py"):
            self.assertIn(part, text)
        block = text[text.index(brief.CARD_OPEN) + len(brief.CARD_OPEN):text.index(brief.CARD_CLOSE)]
        body = json.loads(block)
        self.assertEqual((body["parent"], body["branch"], body["card"]["name"], body["draft"]),
                         ("session_parent01", "orch/p7/api", "api", "pd-x"))

    def test_the_brief_and_the_card_block_name_the_issue_and_the_ticket_file(self):
        """s5.brief.issue: what part 4 checks from the child."""
        issue = {"repo": "o/r", "number": 41, "url": "https://github.com/o/r/issues/41", "sha": "a" * 64}
        made = {"title": "pd-x__0123456789ab.csv", "sha256": "b" * 64, "path": "/w/x.csv"}
        text = brief.brief(7, "pd-x", GOOD, "session_parent01", rounds=3, start="plan/p7", issue=issue, ticket_file=made)
        self.assertIn("issue #41 (https://github.com/o/r/issues/41)", text)
        self.assertIn("ticket file pd-x__0123456789ab.csv", text)
        self.assertIn("Every commit names #41", text)
        block = text[text.index(brief.CARD_OPEN) + len(brief.CARD_OPEN):text.index(brief.CARD_CLOSE)]
        body = json.loads(block)
        self.assertEqual(body["issue"], issue)
        self.assertEqual(body["ticket"], {"title": made["title"], "sha256": made["sha256"]})  # never its local path
        self.assertNotIn("issue", json.loads(brief.card_block(7, GOOD, "s", "pd-x").splitlines()[1]))

    def test_the_create_session_call(self):
        call = brief.create_call(7, GOOD, "the brief", "https://github.com/o/r", "m1")
        self.assertEqual(call, {"title": "Orchestra p7: api", "prompt": "the brief", "tags": ["orchestra",
                                "orchestra:p7"], "source_url": "https://github.com/o/r", "model": "m1"})
        self.assertNotIn("source_url", brief.create_call(7, GOOD, "b", ""))

    def test_a_child_opens_on_sonnet_unless_a_model_is_named(self):
        """s2.spawn.sonnet-default: no model named gives the default; a named model stays (its form comes later)."""
        self.assertEqual(brief.create_call(7, GOOD, "b", "")["model"], "claude-sonnet-5-5")
        self.assertEqual(brief.create_call(7, GOOD, "b", "", "claude-opus-5-5")["model"], "claude-opus-5-5")

    def test_the_source_url_has_no_user_part_and_no_loopback(self):
        repo = git_repo(self, {"a.py": "X = 1\n"})
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://tok:x@github.com/o/r"], check=True)
        self.assertEqual(source_url(str(repo)), "https://github.com/o/r")
        subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", "http://127.0.0.1:9/git/o/r"], check=True)
        self.assertEqual(source_url(str(repo)), "")


class CrewTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self)
        self.repo = git_repo(self, {"notes.md": "n\n"})
        self.port = LedgerPort(self.claude_dir)
        self.port.touch_session("s1")
        self.ctx = ActionContext({"plans": self.port, "session": lambda: "s1", "limits": lambda: {"children": 3, "rounds": 3}, "units": dict,
                                  "github": lambda *a: {}})
        draft = {"repo": "o/r", "number": 5, "url": "https://github.com/o/r/pull/5"}  # every child gets a draft; its
        stub = mock.patch("harness.utils.orchestra.draft.open_draft", return_value=draft)  # own tests are test_draft's
        stub.start()
        self.addCleanup(stub.stop)

    def approve(self, extra=None, n=2):
        items = {**desk.normalize(desk.clean({**PLAN, "children": children(n), **(extra or {})})),
                 "root": str(self.repo)}
        plan_id, _, q = self.port.present(items, sid="s1")
        return plan_id, approvals(self.port, "s1", {q: YES})

    def test_approval_makes_a_delegated_ticket_with_a_pending_row_per_child(self):
        _, note = self.approve()
        ticket = self.port.ticket("s1")
        self.assertEqual((ticket["grant"]["count"], ticket["crew"]), (2, {}))
        self.assertIn("app/orders.py", note[0])  # the approval note names the card files too
        self.assertIn("app/orders.py", ticket["plan"]["files"])
        rows = self.port.rows("SELECT name, state FROM pl_children ORDER BY name")
        self.assertEqual([(r["name"], r["state"]) for r in rows], [("c1", "pending"), ("c2", "pending")])

    def test_spawn_answers_the_call_and_writes_nothing(self):
        self.approve()
        text = Spawn().run(self.ctx, {"name": "c1"})
        call = json.loads(text[text.index("\n{") + 1:])
        self.assertTrue(call["prompt"].startswith('You are child session "c1" of the delegated plan'))
        self.assertIn("run('orchestra', 'started'", text)
        self.assertEqual(self.port.ticket("s1")["crew"], {})

    def test_spawn_gives_a_declared_unit_to_the_child(self):
        self.approve(extra={"children": [{**GOOD, "name": "c1", "unit": "api"}]})
        units = {"api": {"repo": "https://github.com/me/shop", "path": "services/api", "verify": ["npm", "test"],
                         "base": "develop"}}
        ctx = ActionContext({"plans": self.port, "session": lambda: "s1", "limits": lambda: {"children": 3, "rounds": 3}, "units": lambda: units,
                             "github": lambda *a: {}})
        text = Spawn().run(ctx, {"name": "c1"})
        call = json.loads(text[text.index("\n{") + 1:])
        self.assertEqual(call["source_url"], "https://github.com/me/shop")
        self.assertIn("Work only in the unit api, in the folder services/api of its repository. Once the orchestrator "
                      "accepts it, your branch becomes a pull request into develop.", call["prompt"])
        block = call["prompt"][call["prompt"].index(brief.CARD_OPEN) + len(brief.CARD_OPEN):
                               call["prompt"].index(brief.CARD_CLOSE)]
        self.assertEqual(json.loads(block)["unit"], units["api"])

    def test_started_records_a_running_child_once(self):
        self.approve()
        started = Started().run(self.ctx, {"name": "c1", "sid": "session_child0001"})
        self.assertIn("1 of 3 running", started)
        self.assertNotIn("digest", started)  # digest reads no branch
        self.assertIn("To look at it, run('orchestra', 'check', {name})", started)
        entry = self.port.ticket("s1")["crew"]["c1"]
        self.assertEqual((entry["state"], entry["sid"], entry["reportSid"]), ("running", "session_child0001", "s1"))
        with self.assertRaisesRegex(ActionError, "has started already"):
            Spawn().run(self.ctx, {"name": "c1"})
        with self.assertRaisesRegex(ActionError, "one session is one child"):
            Started().run(self.ctx, {"name": "c2", "sid": "session_child0001"})
        with self.assertRaisesRegex(ActionError, "no session id"):
            Started().run(self.ctx, {"name": "c2", "sid": "abc"})
        self.assertIn("- c1 | home | running | session session_child0001", Status().run(self.ctx, {}))
        self.assertIn("- c2 | home | pending", Status().run(self.ctx, {}))

    def test_no_more_than_three_run_at_once(self):
        self.approve(n=4)
        for i in range(1, 4):
            Started().run(self.ctx, {"name": f"c{i}", "sid": f"session_child000{i}"})
        with self.assertRaisesRegex(ActionError, "3 children run already"):
            Spawn().run(self.ctx, {"name": "c4"})

    def test_the_children_cap_comes_from_the_limits(self):
        self.approve()
        one = ActionContext({"plans": self.port, "session": lambda: "s1", "units": dict,
                             "limits": lambda: {"children": 1, "rounds": 3}})
        Started().run(one, {"name": "c1", "sid": "session_child0001"})
        with self.assertRaisesRegex(ActionError, "1 children run already"):
            Spawn().run(one, {"name": "c2"})
        self.assertIn("1 of 1 may run", Status().run(one, {}).replace("0 of 1 accepted; ", ""))

    def test_a_cloud_child_needs_change_paths(self):
        items = {**desk.normalize(desk.clean({**PLAN, "children": [{k: v for k, v in GOOD.items() if k != "change"}]})),
                 "root": str(self.repo)}
        _, _, q = self.port.present(items, sid="s1")
        approvals(self.port, "s1", {q: YES})
        with self.assertRaisesRegex(ActionError, "names no files to change"):
            Spawn().run(self.ctx, {"name": "api"})

    def test_spawn_needs_an_approved_delegated_plan_and_a_child_of_it(self):
        with self.assertRaisesRegex(ActionError, "no delegated plan"):
            Spawn().run(self.ctx, {"name": "c1"})
        self.approve()
        with self.assertRaisesRegex(ActionError, "no child of plan"):
            Spawn().run(self.ctx, {"name": "zz"})

    def test_no_other_plan_while_a_delegated_plan_runs(self):
        draft, _ = self.approve()
        with self.assertRaisesRegex(ActionError, "delegated plan .* runs in this session"):
            PlanPresent().run(self.ctx, {"plan": {"title": "Other", "what": ["w"], "files": ["x.py"]}})
        other, _, q = self.port.present({**desk.normalize(desk.clean({**PLAN, "title": "Other"})),
                                         "root": str(self.repo)}, sid="")
        self.assertIn("was not opened", " ".join(approvals(self.port, "s1", {q: YES})))
        self.assertEqual(self.port.ticket("s1")["draft"], draft)
        self.assertEqual(crew.blocks_other(self.port.ticket("s1"), draft), "")


if __name__ == "__main__":
    unittest.main()

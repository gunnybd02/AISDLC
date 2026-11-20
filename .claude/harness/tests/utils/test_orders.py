"""Orders (utils/orchestra/orders.py): the parent's signed one-way messages to a running child. A signed order checks
out; any change, an old round, another child or another key fails with why; orders are found in notification text."""
import json
import unittest

from harness.assemble.engine.runner import Act
from harness.mcp.actions.orchestra_parent import Answer, Reject
from harness.utils.contracts import ActionContext, Event, Verdict
from harness.utils.orchestra import orders
from harness.utils.plan import tickets as plan_tickets
from harness.tests.utils.test_review import UNITS, URL, Scenario, git

KEY = "0123456789abcdef0123456789abcdef"
SHA = "7719dfaab165839f614f8ee106899ea6b26379c6cc19688a5db5e0fd235f1146"
FIELDS = (22, "hello", 77, SHA)


def order(n=1, kind="fix", body="AC2 still fails: hello('') returns 'Hello, '.", key=KEY):
    return orders.text(key, *FIELDS, n, kind, body)


def check(said, last=0, key=KEY):
    found = orders.parse(said)
    return found, [orders.check(o, *FIELDS, key, last) for o in found]


class OrdersTest(unittest.TestCase):
    def test_a_signed_order_checks_out_and_any_change_fails_with_why(self):
        """s1.orders.sign-check"""
        text = order()
        self.assertTrue(text.startswith("orch 22 | child hello | issue #77 7719dfaab165 | round 1 | kind fix | mac "))
        self.assertTrue(text.endswith("\nend of order"))
        (o,), (why,) = check(text)
        self.assertEqual((why, o["kind"], o["body"]), ("", "fix", "AC2 still fails: hello('') returns 'Hello, '."))
        cases = {
            "its mac is wrong": text.replace("AC2 still", "AC1 still"),  # the body changed
            "its round is 1, the next one is 2": text,  # replayed after round 1 was taken
            "not hello of plan 22": order().replace("child hello", "child other"),
            "not #77 7719dfaab165": text.replace("#77", "#78"),
        }
        for reason, said in cases.items():
            with self.subTest(reason=reason):
                last = 1 if "next one is 2" in reason else 0
                self.assertIn(reason, check(said, last=last)[1][0])
        self.assertIn("its mac is wrong", check(text, key="f" * 32)[1][0])  # another key
        self.assertIn("its mac is wrong", check(text.replace("kind fix", "kind stop"))[1][0])
        self.assertIn("no order key", check(text, key="")[1][0])
        self.assertEqual(check(order(n=2, kind="stop", body=""), last=1)[1], [""])
        with self.assertRaises(ValueError):
            orders.text(KEY, *FIELDS, 1, "merge", "")

    def test_orders_are_found_in_notification_text_as_relayed(self):
        """s1.orders.parse: indented, escaped and wrapped as a notification; two orders in one answer."""
        relayed = "\n".join("    " + line for line in order().split("\n")).replace("'", "&#x27;")
        answer = ('--- Notification 1 of 2 from session_parent ---\n<message from-session="session_parent">\n'
                  f"{relayed}\n</message>\n--- Notification 2 of 2 ---\n{order(2, 'answer', 'Use 400.')}\n0 remaining")
        found, why = check(answer)
        self.assertEqual([o["round"] for o in found], [1, 2])
        self.assertEqual(why[0], "")
        self.assertEqual(found[1]["body"], "Use 400.")
        self.assertEqual(orders.parse("no order here"), [])
        self.assertEqual(len(orders.new_key()), 32)
        self.assertNotEqual(orders.new_key(), orders.new_key())


class SendTest(Scenario):
    """Part 6, the parent's side: reject and answer post a comment on the draft and give the signed order for the
    running child; the hook records the order sent, so the next one has the next round."""

    def ctx(self):
        if not hasattr(self, "github"):
            self.github = self.drafted()  # every child has a draft: the talk goes there
        return ActionContext({"plans": self.port, "session": lambda: "s1", "units": lambda: UNITS,
                              "limits": lambda: {"children": 3, "rounds": 3}, "github": self.github})

    def call_of(self, text):
        return json.loads(text[text.index(orders.SEND) + len(orders.SEND):].split(". Its harness")[0])

    def test_reject_and_answer_give_the_signed_order_and_post_the_comment(self):
        """s3.orders.sent: the order carries the words and the comment's URL; no note is committed on the branch."""
        key = orders.key_for(self.port, "s1", "hello")
        self.hand_back()
        text = Reject().run(self.ctx(), {"name": "hello", "why": "AC2 is not tested"})
        comment = f"{URL}/pull/5#issuecomment-701"
        self.assertIn(f"The send-back 1 is the comment {comment} on its draft.", text)
        self.assertNotIn("nothing is sent to the child", text)
        self.assertIn("Send hello its signed order (fix, round 1) now", text)
        call = self.call_of(text)
        self.assertEqual(call["session_id"], "session_child0001")
        (order,) = orders.parse(call["message"])
        self.assertEqual(orders.check(order, self.plan, "hello", orders.NO_ISSUE, orders.NO_SHA, key, 0), "")
        self.assertEqual(order["body"], f"AC2 is not tested (the comment: {comment})")
        files = git(self.origin, "ls-tree", "-r", "--name-only", f"orch/p{self.plan}/hello")
        self.assertNotIn(".harness/notes", files)  # the talk is the comment, never a commit on the child's branch
        answer = Answer().run(self.ctx(), {"name": "hello", "text": "Use 400."})
        self.assertIn("(answer, round 1)", answer)  # round 1 was given, not seen sent: it is given again

    def test_a_child_that_takes_no_orders_gets_the_fresh_session_path(self):
        """s3.orders.fallback: no key (spawned before orders) or no session: the note and spawn, as before."""
        self.hand_back()
        text = Reject().run(self.ctx(), {"name": "hello", "why": "AC2 is not tested"})
        self.assertIn("nothing is sent to the child", text)
        self.assertIn("run('orchestra', 'spawn', {name: 'hello'})", text)
        self.assertNotIn(orders.SEND, text)
        self.assertEqual(orders.target_of({}, "hello"), {})

    def test_the_hook_records_an_order_sent_and_the_next_has_the_next_round(self):
        """s3.orders.recorded"""
        orders.key_for(self.port, "s1", "hello")
        self.hand_back()
        call = self.call_of(Reject().run(self.ctx(), {"name": "hello", "why": "AC2 is not tested"}))
        notes = Act(self.port).run(Event("PostToolUse", orders.SEND, call, "s1", "/w", "Message sent."), {},
                                   Verdict("allow"))
        self.assertIn("The harness recorded order fix round 1 to hello.", notes)
        rows = self.port.rows("SELECT target, key, text FROM pl_notes WHERE kind = 'order.sent'")
        self.assertEqual([(r["target"], r["key"]) for r in rows], [("hello", "1")])
        self.assertEqual(json.loads(rows[0]["text"])["to"], "session_child0001")
        self.assertIn("(answer, round 2)", Answer().run(self.ctx(), {"name": "hello", "text": "Use 400."}))
        other = Act(self.port).run(Event("PostToolUse", "mcp__x__send_message", {"message": "hello"}, "s1", "/w", "ok"),
                                   {}, Verdict("allow"))
        self.assertFalse(any("recorded order" in n for n in other))


class ArriveTest(unittest.TestCase):
    """Part 6, the child's side: its hook checks each order in a ReadNotifications answer, records it, and a valid one
    unlocks one action; an invalid one unlocks nothing."""
    PARENT = "session_parent01"

    def setUp(self):
        from harness.assemble.engine.ports import LedgerPort
        from harness.utils.orchestra import brief, work
        from harness.tests import tree
        from harness.tests.e2e import copy_tree, git_repo
        from harness.tests.utils.test_work import CARD
        self.port, self.repo, origin = LedgerPort(copy_tree(self)), git_repo(self, {"a.py": "X = 1\n"}), tree(self, {})
        git(origin, "init", "-q", "--bare")
        git(self.repo, "remote", "add", "origin", str(origin))
        prompt = brief.brief(7, "pd-x", CARD, "s-harness", rounds=3, cloud=self.PARENT, key=KEY)
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": prompt}, "c1", str(self.repo)), {}, Verdict("allow"))
        work.take(self.port, "c1", str(self.repo))
        self.port.write(lambda con, rec: plan_tickets.save(con, {**plan_tickets.latest(con, "c1"), "phase": "deliver"}))

    def read(self, *messages, sid="c1", sender=PARENT):
        answer = "\n".join(f'<message from-session="{sender}">\n{m}\n</message>' for m in messages)
        return Act(self.port).run(Event("PostToolUse", "ReadNotifications", {}, sid, str(self.repo),
                                        f"Exactly {len(messages)} notification.\n{answer}\n0 remaining"), {},
                                  Verdict("allow"))

    def order(self, n, kind="fix", body="AC2 fails: hello('') must raise ValueError."):
        return orders.text(KEY, 7, "api", orders.NO_ISSUE, orders.NO_SHA, n, kind, body)

    def received(self):
        return [(int(r["key"]), json.loads(r["text"])["valid"])
                for r in self.port.rows("SELECT key, text FROM pl_notes WHERE kind = 'order.received' ORDER BY rowid")]

    def test_a_valid_fix_or_answer_reopens_the_card_plan_for_one_round(self):
        """s4.orders.fix-resumes"""
        notes = self.read(self.order(1))
        self.assertTrue(any(n.startswith("The orchestrator's order fix (round 1) is valid") for n in notes))
        self.assertTrue(any("Its words: AC2 fails" in n for n in notes))
        ticket = self.port.ticket("c1")
        self.assertEqual((ticket["phase"], ticket[orders.TAKEN]["round"]), ("execute", 1))
        self.assertTrue(any("order answer (round 2) is valid" in n for n in self.read(self.order(2, "answer", "Use 400."))))
        self.assertEqual(self.received(), [(1, True), (2, True)])

    def test_a_valid_stop_ends_the_child(self):
        """s4.orders.stop"""
        notes = self.read(self.order(1, "stop", ""))
        self.assertTrue(any("order stop (round 1) is valid: your work is over" in n for n in notes))
        self.assertEqual(self.port.ticket("c1")[orders.TAKEN]["kind"], "stop")
        self.assertEqual(self.port.ticket("c1")["phase"], "deliver")  # stop opens nothing

    def test_an_invalid_or_replayed_order_unlocks_nothing_and_is_recorded(self):
        """s4.orders.invalid: a replay, a changed body, a wrong key, another sender; none moves the plan."""
        self.read(self.order(1))
        self.port.write(lambda con, rec: plan_tickets.save(con, {**plan_tickets.latest(con, "c1"), "phase": "deliver"}))
        cases = [(self.order(1), "the next one is 2"),
                 (self.order(2).replace("must raise", "may skip"), "its mac is wrong"),
                 (orders.text("f" * 32, 7, "api", 0, orders.NO_SHA, 2, "fix", "x"), "its mac is wrong")]
        for said, why in cases:
            with self.subTest(why=why):
                notes = self.read(said)
                self.assertTrue(any(n.startswith("An order (round") and why in n for n in notes), notes)
        notes = self.read(self.order(2), sender="session_other")
        self.assertTrue(any("does not name the parent's session session_parent01" in n for n in notes))
        self.assertEqual(self.port.ticket("c1")["phase"], "deliver")
        self.assertEqual(self.received(), [(1, True), (1, False), (2, False), (2, False), (2, False)])
        self.assertEqual(self.read(self.order(2), sid="s9"), [])  # no child: nothing is read


class NoCatchUpTest(unittest.TestCase):
    """The parent never writes on a child's branch after the start (its words are comments), so an order moves
    nothing and a child's push needs no catch-up; step_done follows only the child's own signal commits."""
    PARENT = ArriveTest.PARENT
    setUp, read, order = ArriveTest.setUp, ArriveTest.read, ArriveTest.order

    def push(self):
        from harness.utils.orchestra import work
        return work.push(self.port, "c1", lambda repo, args: Verdict("allow"))

    def child_commits(self, rel, text):
        (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / rel).write_text(text, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", f"child: {rel}")

    def test_a_valid_fix_order_moves_nothing(self):
        """s5.catchup.gone: the order reopens the work; the branch and its tree stay as they were."""
        self.push()
        before = git(self.repo, "rev-parse", "HEAD")
        notes = self.read(self.order(1))
        self.assertTrue(any("order fix (round 1) is valid" in n for n in notes))
        self.assertFalse(any("took in" in n for n in notes))
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), before)
        self.assertFalse((self.repo / ".harness").exists())

    def step(self):
        """step_done of the child; its refusal, or "" when it went on."""
        from harness.utils.plan.steps import StepError, step_done
        try:
            step_done(self.port, "c1", "Add a docstring")
        except StepError as e:
            return str(e)
        return ""

    def handed_back(self):
        """The child's harness makes its empty signal commit and keeps it on the ticket, as work.handback does."""
        from harness.utils.contracts import now
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "Handback of api (plan 7)")
        sha = git(self.repo, "rev-parse", "HEAD").strip()
        self.port.write(lambda con, rec: plan_tickets.save(con, {**plan_tickets.latest(con, "c1"),
                                                                 "handback": {"sha": sha, "at": now()}}))
        self.push()

    def test_after_a_handback_and_a_fix_order_step_done_goes_on(self):
        """s5.catchup.gone: live run 6 refused here; the signal commit is the harness's own move."""
        self.push()
        self.handed_back()
        self.read(self.order(1))
        (self.repo / "app").mkdir(exist_ok=True)
        (self.repo / "app" / "orders.py").write_text('"""Orders."""\nORDERS = []\n', encoding="utf-8")
        self.assertNotIn("the repository moved", self.step())

    def test_a_commit_the_harness_did_not_make_is_still_refused_after_a_handback(self):
        """s5.catchup.gone: a foreign commit is no move."""
        self.push()
        self.handed_back()
        self.read(self.order(1))
        self.child_commits("a.py", "X = 3\n")
        self.assertIn("the repository moved", self.step())


class ChildCommitTest(unittest.TestCase):
    """Live run 6: the git.commit door wrote no "#N name: " prefix in a child, so harness ci failed its subjects rule."""

    def test_a_git_commit_of_a_child_names_its_issue_once(self):
        """s2.ship.child-subject"""
        from harness.assemble.engine.ports import LedgerPort
        from harness.utils.orchestra import brief, work
        from harness.utils.plan.ship import git_commit
        from harness.tests.e2e import copy_tree, git_repo
        from harness.tests.utils.test_work import CARD
        port, repo = LedgerPort(copy_tree(self)), git_repo(self, {"a.py": "X = 1\n"})
        card = {**CARD, "change": ["docs/notes.md"], "tests": []}
        Act(port).run(Event("UserPromptSubmit", "", {"prompt": brief.brief(7, "pd-x", card, "s-p", rounds=3)}, "c1",
                            str(repo)), {}, Verdict("allow"))
        work.take(port, "c1", str(repo))

        def numbered(con, rec):
            fresh = plan_tickets.latest(con, "c1")
            role = {**fresh["child"], "record": {"issue": {"number": 41}}}
            plan_tickets.save(con, {**fresh, "child": role})
        port.write(numbered)
        allow = lambda repo, paths, text: Verdict("allow")  # noqa: E731
        for message, n in (("Write the notes", 1), ("#41 api: Write more notes", 2)):
            (repo / "docs").mkdir(exist_ok=True)
            (repo / "docs" / "notes.md").write_text("notes\n" * n, encoding="utf-8")
            git_commit(port, "c1", ["docs/notes.md"], message, allow)
            self.assertEqual(git(repo, "log", "-1", "--format=%s").strip(),
                             "#41 api: " + message.removeprefix("#41 api: "))


if __name__ == "__main__":
    unittest.main()

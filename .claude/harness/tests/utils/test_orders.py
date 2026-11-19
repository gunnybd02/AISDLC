"""Orders (utils/orchestra/orders.py): the parent's signed one-way messages to a running child. A signed order checks
out; any change, an old round, another child or another key fails with why; orders are found in notification text."""
import json
import unittest

from harness.assemble.engine.runner import Act
from harness.mcp.actions.orchestra_parent import Answer, Reject
from harness.utils.contracts import ActionContext, Event, Verdict
from harness.utils.orchestra import orders
from harness.tests.utils.test_review import UNITS, Scenario, git

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
    """Part 6, the parent's side: reject and answer push the note and give the signed order for the running child; the
    hook records the order sent, so the next one has the next round."""

    def ctx(self):
        return ActionContext({"plans": self.port, "session": lambda: "s1", "units": lambda: UNITS,
                              "limits": lambda: {"children": 3, "rounds": 3}})

    def call_of(self, text):
        return json.loads(text[text.index(orders.SEND) + len(orders.SEND):].split(". Its harness")[0])

    def test_reject_and_answer_give_the_signed_order_and_still_push_the_note(self):
        """s3.orders.sent"""
        key = orders.key_for(self.port, "s1", "hello")
        self.hand_back()
        text = Reject().run(self.ctx(), {"name": "hello", "why": "AC2 is not tested"})
        self.assertIn(f"The note is .harness/notes/hello/sendback-1.md on orch/p{self.plan}/hello", text)
        self.assertNotIn("nothing is sent to the child", text)
        self.assertIn("Send hello its signed order (fix, round 1) now", text)
        call = self.call_of(text)
        self.assertEqual(call["session_id"], "session_child0001")
        (order,) = orders.parse(call["message"])
        self.assertEqual(orders.check(order, self.plan, "hello", orders.NO_ISSUE, orders.NO_SHA, key, 0), "")
        self.assertEqual(order["body"], "AC2 is not tested")
        note = git(self.origin, "show", f"orch/p{self.plan}/hello:.harness/notes/hello/sendback-1.md")
        self.assertIn("AC2 is not tested", note)  # the note stays on the branch, as record and fallback
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


if __name__ == "__main__":
    unittest.main()

"""Orders (utils/orchestra/orders.py): the parent's signed one-way messages to a running child. A signed order checks
out; any change, an old round, another child or another key fails with why; orders are found in notification text."""
import unittest

from harness.utils.orchestra import orders

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


if __name__ == "__main__":
    unittest.main()

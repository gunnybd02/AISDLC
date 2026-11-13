"""h10.maint-grant: utils/maint/grant.py and entry/hook.py read the same rows the same way."""
import json
import re
import time
import unittest

from harness.utils.maint import grant
from tests import CLAUDE_DIR

HOOK = (CLAUDE_DIR / "entry" / "hook.py").read_text(encoding="utf-8")


def rows_of(*texts):
    return lambda sql, args: [{"text": t, "why": "w"} for t in texts[:1]]


class GrantTest(unittest.TestCase):
    def test_the_hook_reads_the_same_rows(self):
        self.assertIn(f'GRANT = "{grant.KIND}"', HOOK)
        self.assertIn(f'LATEST = "{grant.LATEST}"', HOOK)
        self.assertIn(f"MAX_MINUTES = {grant.MAX_MINUTES}", HOOK)
        hook_question = re.search(r'PAUSE = re.compile\("(.*)"\)', HOOK).group(1).encode().decode("unicode_escape")
        self.assertEqual(hook_question, grant.QUESTION.pattern)

    def test_a_grant_lasts_until_its_end_and_never_past_the_longest(self):
        now = 1000.0
        self.assertIsNone(grant.active(rows_of(), now))
        self.assertEqual(grant.active(rows_of(json.dumps({"until": now + 60})), now)["until"], now + 60)
        for text in (json.dumps({"until": now - 1}), json.dumps({"until": now + 121 * 60}), "{", "[]"):
            with self.subTest(text=text):
                self.assertIsNone(grant.active(rows_of(text), now))
        self.assertIsNotNone(grant.active(rows_of(json.dumps({"until": time.time() + 5}))))


if __name__ == "__main__":
    unittest.main()

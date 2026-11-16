"""Upkeep of the ledger (docs/12-ledger.md): finished days are counted once into usage_daily; rows older than 180
days go only after the roll-up; one backup copy a day with a fixed retention; a second run changes nothing."""
import sqlite3
import unittest
from unittest import mock

from harness.assemble.engine.ports import LedgerPort
from harness.utils.ledger import upkeep
from harness.tests import tree

DAY = 86400000
NOW = 1794000000000  # a fixed time: 2026-11-07 UTC


class UpkeepTest(unittest.TestCase):
    def setUp(self):
        self.home = tree(self, {})
        self.port = LedgerPort(self.home)
        self.port.write(lambda con, rec: self.fill(con))

    def fill(self, con):
        con.execute("INSERT INTO sessions (sid, started_at, last_at, project, harness_ver) VALUES ('s1', 1, 1, 'proj', 'rel1')")
        calls = [("s1", "Read", NOW - DAY), ("s1", "Read", NOW - DAY), ("s2", "Read", NOW - DAY), ("s1", "Bash", NOW - DAY),
                 ("s1", "Read", NOW - 2 * DAY), ("s1", "Read", NOW), ("s1", "Old", NOW - 200 * DAY)]
        con.executemany("INSERT INTO act_tool_calls (sid, agent, tool, service, at, plan_id, uid) VALUES (?, '', ?, '', ?, 0, '')", calls)
        con.execute("INSERT INTO act_skill_loads (sid, agent, skill, via, epoch, at, uid) VALUES ('s1', '', 'work', 'guide', 0, ?, '')", (NOW - DAY,))
        rules = [("u1", "plan.none", "deny", NOW - DAY), ("u2", "plan.none", "allow", NOW - DAY), ("u3", "git.push", "ask", NOW - DAY),
                 ("u4", "plan.none", "deny", NOW - 200 * DAY)]
        con.executemany("INSERT INTO act_rule_decisions (uid, sid, agent, plan_id, rule, kind, tool, service, verdict, detail, at) "
                        "VALUES (?, 's1', '', 0, ?, 'finding', 'Write', '', ?, '', ?)", rules)
        con.executemany("INSERT INTO pl_prompts (sid, n, text, chars, cut, from_peer, source, uuid, at) VALUES ('s1', ?, 'p', 1, 0, 0, 'live', '', ?)",
                        [(1, NOW - 200 * DAY), (2, NOW - DAY)])

    def rows(self, sql):
        return [tuple(r[k] for k in r.keys()) for r in self.port.rows(sql)]

    def run_upkeep(self):
        with mock.patch.object(upkeep, "now", lambda: NOW):
            return self.port.upkeep()

    def test_finished_days_are_counted_once_then_old_rows_go_and_a_second_run_changes_nothing(self):
        yesterday = upkeep.day_of(NOW - DAY)
        said = self.run_upkeep()
        self.assertIn("rolled up 3 day(s)", said)  # yesterday, the day before, and the day 200 days ago; not today
        self.assertIn("pruned 1 of act_rule_decisions, 1 of act_tool_calls, 1 of pl_prompts", said)
        totals = self.rows("SELECT project, harness_ver, kind, name, calls, sessions, blocks FROM usage_daily WHERE day = '%s' "
                           "ORDER BY kind, name, project" % yesterday)
        self.assertEqual(totals, [("proj", "rel1", "rule", "git.push", 1, 1, 1), ("proj", "rel1", "rule", "plan.none", 2, 1, 1),
                                  ("proj", "rel1", "skill", "work", 1, 1, 0), ("proj", "rel1", "tool", "Bash", 1, 1, 0),
                                  ("", "", "tool", "Read", 1, 1, 0),  # a session with no row: no project
                                  ("proj", "rel1", "tool", "Read", 2, 1, 0)])
        self.assertEqual(self.rows("SELECT name, calls FROM usage_daily WHERE day = '%s'" % upkeep.day_of(NOW - 200 * DAY)),
                         [("plan.none", 1), ("Old", 1)])  # the total of a pruned day is kept for good
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_daily WHERE day = '%s'" % upkeep.day_of(NOW)), [(0,)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM act_tool_calls WHERE tool = 'Old'"), [(0,)])
        self.assertEqual(self.rows("SELECT n FROM pl_prompts"), [(2,)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM act_skill_loads"), [(1,)])  # skill loads are never pruned
        before = self.rows("SELECT * FROM usage_daily ORDER BY 1, 2, 3, 4, 5, 6")
        self.assertEqual(self.run_upkeep(), "")  # the same day again: nothing to do
        self.assertEqual(self.rows("SELECT * FROM usage_daily ORDER BY 1, 2, 3, 4, 5, 6"), before)

    def test_no_prune_when_the_roll_up_fails_and_the_fault_never_raises(self):
        with mock.patch.object(upkeep, "rollup", side_effect=sqlite3.OperationalError("disk full")), \
                mock.patch.object(upkeep, "prune") as prune:
            said = self.run_upkeep()
        self.assertIn("upkeep stopped (OperationalError: disk full)", said)
        prune.assert_not_called()
        self.assertEqual(self.rows("SELECT COUNT(*) FROM act_tool_calls WHERE tool = 'Old'"), [(1,)])

    def test_one_backup_a_day_and_the_newest_7_4_weeks_and_6_months_stay(self):
        self.assertIn("backup harness-%s.db" % upkeep.day_of(NOW), self.run_upkeep())
        folder = self.home / "state" / upkeep.BACKUPS
        copy = sqlite3.connect(folder / ("harness-%s.db" % upkeep.day_of(NOW)))
        self.addCleanup(copy.close)
        self.assertEqual(copy.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)  # a whole copy of the ledger
        self.assertNotIn("backup", self.run_upkeep())  # once a day
        days = [upkeep.day_of(NOW - n * DAY) for n in range(200)]
        for day in days:
            (folder / f"harness-{day}.db").write_bytes(b"x")
        with mock.patch.object(upkeep, "now", lambda: NOW):
            self.port.upkeep()
        left = sorted(p.stem[len("harness-"):] for p in folder.glob("harness-*.db"))
        self.assertEqual(set(left), upkeep.kept_days(days, upkeep.day_of(NOW)))
        self.assertEqual(left[-7:], sorted(days)[-7:])  # the newest 7
        from datetime import date, timedelta
        today = date.fromisoformat(upkeep.day_of(NOW))
        monday = today - timedelta(days=today.weekday())
        sundays = [min(today, monday - timedelta(weeks=n) + timedelta(days=6)).isoformat() for n in range(4)]
        self.assertLessEqual(set(sundays), set(left))  # the newest day of each of the last 4 weeks, Monday first
        months = sorted({d[:7] for d in left})
        self.assertEqual(len(months), 6)  # the newest of each of the last 6 months
        for month in months[:-1]:
            last = max(d for d in days if d.startswith(month))
            self.assertIn(last, left)
        self.assertEqual(len(left), len(set(sorted(days)[-7:]) | set(sundays) | {max(d for d in days if d.startswith(m)) for m in months}))
        self.assertEqual(upkeep.kept_days([], "2026-11-07"), set())


if __name__ == "__main__":
    unittest.main()

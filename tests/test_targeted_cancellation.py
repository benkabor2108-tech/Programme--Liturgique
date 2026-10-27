import unittest
from copy import deepcopy
from history_protection import cancel_selected_celebrations_non_destructive


class TargetedCancellationTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "history": [
                {"date": "2026-10-25", "codes": {"r1": "F1"}},
                {"date": "2026-10-31", "codes": {"r1": "F2"}},
                {"date": "2026-11-01", "codes": {"r1": "F3"}},
                {"date": "2026-11-08", "codes": {"r1": "F4"}},
            ],
            "attendance": {"2026-10": {"protected": True}},
            "program_drafts": {"other": {"rows": []}},
            "audit_log": [], "people": {"F1": {"reading_count": 2}},
        }

    def test_only_selected_dates_cancelled_without_deletion(self):
        original = deepcopy(self.state)
        seen = []
        def rebuild(state, active):
            seen.extend(row["date"] for row in active)
            return {"people": {"F1": {"reading_count": len(active)}}}
        ok, message, result = cancel_selected_celebrations_non_destructive(
            self.state, ["2026-10-31", "2026-11-01"], rebuild,
            reason="Essai remplacé", timestamp="2026-10-27T12:00:00Z",
        )
        self.assertTrue(ok, message)
        self.assertEqual(self.state, original)
        self.assertEqual(len(result["history"]), 4)
        self.assertEqual([r.get("history_status") for r in result["history"]],
                         [None, "cancelled", "cancelled", None])
        self.assertEqual(seen, ["2026-10-25", "2026-11-08"])
        self.assertEqual(result["attendance"], original["attendance"])
        self.assertEqual(result["program_drafts"], original["program_drafts"])
        self.assertEqual(result["audit_log"][-1]["dates"], ["2026-10-31", "2026-11-01"])

    def test_missing_confirmation_reason_does_not_modify(self):
        ok, _, result = cancel_selected_celebrations_non_destructive(
            self.state, ["2026-11-01"], lambda s, rows: s, reason=""
        )
        self.assertFalse(ok)
        self.assertIs(result, self.state)


if __name__ == "__main__":
    unittest.main()

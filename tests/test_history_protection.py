import unittest
from copy import deepcopy
from datetime import date

from history_protection import (
    active_history_rows,
    cancel_latest_month_non_destructive,
    cancelled_history_rows,
    latest_active_history_month,
)
from scripts.whatsapp_automation import next_published_sunday


class HistoryProtectionTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "history": [
                {"date": "2026-09-06", "codes": {"r1": "F1"}},
                {"date": "2026-09-13", "codes": {"r1": "M1"}},
                {"date": "2026-10-04", "codes": {"r1": "F2"}},
                {"date": "2026-10-11", "codes": {"r1": "M2"}},
            ],
            "people": {"sentinel": {"reading_count": 99}},
            "reading_cycle_seen": {"FR": ["F2"], "MO": ["M2"]},
            "reading_pairs": [["F2", "M2"]],
            "monition_pairs": [],
            "next_first_language": "FR",
            "attendance": {"2026-09-12": {"kept": True}},
            "auth_security": {"adjoints": {"a": {"active": True}}},
            "whatsapp_contacts": {"F1": {"number": "+22600000000"}},
            "liturgical_drafts": {"2026-10-04|romain": {"monition": "Conserver"}},
            "future_key": {"must": "survive"},
            "audit_log": [],
        }

    @staticmethod
    def fake_rebuild(state, history):
        return {
            "people": {"rebuilt": {"reading_count": len(history)}},
            "reading_cycle_seen": {"FR": [], "MO": []},
            "reading_pairs": [],
            "monition_pairs": [],
            "next_first_language": "MO",
            "history": deepcopy(history),
            "attendance": {},
            "auth_security": {},
        }

    def test_cancel_latest_month_keeps_all_history_rows(self):
        before = deepcopy(self.state)
        ok, message, result = cancel_latest_month_non_destructive(
            self.state,
            self.fake_rebuild,
            [
                "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
                "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
            ],
            reason="Programme remplacé",
            timestamp="2026-09-15T10:00:00+00:00",
        )

        self.assertTrue(ok)
        self.assertIn("sans suppression", message)
        self.assertEqual(len(result["history"]), len(before["history"]))
        self.assertEqual(len(cancelled_history_rows(result["history"])), 2)
        self.assertEqual(len(active_history_rows(result["history"])), 2)
        self.assertEqual(result["future_key"], before["future_key"])
        self.assertEqual(result["attendance"], before["attendance"])
        self.assertEqual(result["auth_security"], before["auth_security"])
        self.assertEqual(result["liturgical_drafts"], before["liturgical_drafts"])
        self.assertEqual(result["people"]["rebuilt"]["reading_count"], 2)
        self.assertEqual(result["next_first_language"], "MO")
        self.assertEqual(result["audit_log"][-1]["action"], "history_month_cancelled")
        self.assertTrue(result["audit_log"][-1]["preserved"])

        # La fonction ne modifie pas l'objet source reçu en argument.
        self.assertEqual(self.state, before)

    def test_latest_active_month_ignores_cancelled_rows(self):
        history = deepcopy(self.state["history"])
        history[-1]["history_status"] = "cancelled"
        history[-2]["history_status"] = "cancelled"
        self.assertEqual(latest_active_history_month(history), (2026, 9, 2))

    def test_second_cancellation_archives_previous_active_month(self):
        ok, _, first = cancel_latest_month_non_destructive(
            self.state,
            self.fake_rebuild,
            timestamp="2026-09-15T10:00:00+00:00",
        )
        self.assertTrue(ok)
        ok, _, second = cancel_latest_month_non_destructive(
            first,
            self.fake_rebuild,
            timestamp="2026-09-15T10:01:00+00:00",
        )
        self.assertTrue(ok)
        self.assertEqual(len(active_history_rows(second["history"])), 0)
        self.assertEqual(len(cancelled_history_rows(second["history"])), 4)

    def test_whatsapp_automation_skips_cancelled_programme(self):
        state = {
            "history": [
                {"date": "2026-10-04", "history_status": "cancelled", "codes": {"r1": "F1"}},
                {"date": "2026-10-11", "codes": {"r1": "F2"}},
            ]
        }
        sunday, row = next_published_sunday(state, date(2026, 9, 15))
        self.assertEqual(sunday, date(2026, 10, 11))
        self.assertEqual(row["codes"]["r1"], "F2")

    def test_no_active_month_is_a_noop(self):
        state = deepcopy(self.state)
        for row in state["history"]:
            row["history_status"] = "cancelled"
        ok, message, result = cancel_latest_month_non_destructive(
            state,
            self.fake_rebuild,
            timestamp="2026-09-15T10:00:00+00:00",
        )
        self.assertFalse(ok)
        self.assertIn("Aucun mois actif", message)
        self.assertEqual(result, state)


if __name__ == "__main__":
    unittest.main()

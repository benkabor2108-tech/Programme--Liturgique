from datetime import date
import unittest

from whatsapp_reminder_preview import display_rows, preview_rows, preview_summary


class WhatsAppReminderPreviewTests(unittest.TestCase):
    def _state(self):
        return {
            "history": [
                {
                    "date": "2026-10-03",
                    "codes": {"r1": "M1", "r2": "M2", "m_mon": "M3"},
                },
                {
                    "date": "2026-10-04",
                    "codes": {"r1": "F1", "r2": "M1", "f_mon": "F2", "m_mon": "M4"},
                },
            ],
            "names": {
                "M1": "Lecteur commun",
                "M2": "Lecteur samedi",
                "M3": "Moniteur samedi",
                "F1": "Lecteur dimanche",
                "F2": "Moniteur dimanche",
                "M4": "Moniteur mooré dimanche",
            },
            "whatsapp_contacts": {
                "M1": {"number": "+22670000001", "consent": True, "enabled": True},
                "M2": {"number": "+22670000002", "consent": True, "enabled": True},
                "M3": {"number": "", "consent": False, "enabled": False},
                "F1": {"number": "+22670000004", "consent": True, "enabled": True},
                "F2": {"number": "+22670000005", "consent": True, "enabled": True},
                "M4": {"number": "+22670000006", "consent": True, "enabled": True},
            },
            "whatsapp_send_log": {
                "2026-10-04|mercredi|M1": {"status": "sent"},
            },
        }

    def test_preview_groups_same_member_across_saturday_and_sunday(self):
        rows = preview_rows(self._state(), date(2026, 9, 30))
        by_name = {row["name"]: row for row in rows}
        common = by_name["Lecteur commun"]
        self.assertIn("Samedi 03/10/2026", common["services"])
        self.assertIn("Dimanche 04/10/2026", common["services"])
        self.assertEqual(sum(1 for row in rows if row["code"] == "M1"), 1)

    def test_preview_uses_wednesday_and_friday_dates_for_anchor_sunday(self):
        rows = preview_rows(self._state(), date(2026, 9, 30))
        self.assertTrue(rows)
        self.assertEqual(rows[0]["weekend_sunday"], "2026-10-04")
        self.assertEqual(rows[0]["wednesday_date"], "2026-09-30")
        self.assertEqual(rows[0]["friday_date"], "2026-10-02")

    def test_preview_marks_sent_blocked_and_pending_without_numbers(self):
        rows = preview_rows(self._state(), date(2026, 9, 30))
        by_code = {row["code"]: row for row in rows}
        self.assertEqual(by_code["M1"]["wednesday_status"], "✅ Envoyé")
        self.assertEqual(by_code["M1"]["friday_status"], "⏳ À envoyer")
        self.assertEqual(by_code["M3"]["wednesday_status"], "⛔ Bloqué")
        self.assertFalse(by_code["M3"]["ready"])
        rendered = str(display_rows(rows))
        self.assertNotIn("226700000", rendered)

    def test_summary_counts_unique_recipients(self):
        rows = preview_rows(self._state(), date(2026, 9, 30))
        summary = preview_summary(rows)
        self.assertEqual(summary["recipients"], 6)
        self.assertEqual(summary["blocked"], 1)
        self.assertEqual(summary["wednesday_sent"], 1)
        self.assertEqual(summary["weekend_label"], "04/10/2026")

    def test_cancelled_weekend_is_ignored(self):
        state = self._state()
        for row in state["history"]:
            row["history_status"] = "cancelled"
        self.assertEqual(preview_rows(state, date(2026, 9, 30)), [])


if __name__ == "__main__":
    unittest.main()

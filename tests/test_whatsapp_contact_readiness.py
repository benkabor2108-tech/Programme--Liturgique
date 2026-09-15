from datetime import date
import unittest

from whatsapp_readiness import (
    contact_readiness,
    display_rows,
    future_readiness_rows,
    readiness_summary,
    scheduled_assignments,
)


class WhatsAppContactReadinessTests(unittest.TestCase):
    def test_contact_requires_number_consent_and_enabled(self):
        ready, reasons = contact_readiness({"number": "", "consent": False, "enabled": False})
        self.assertFalse(ready)
        self.assertEqual(
            reasons,
            ["numéro absent ou invalide", "consentement absent", "rappels désactivés"],
        )

        ready, reasons = contact_readiness(
            {"number": "+226 70 00 00 00", "consent": True, "enabled": True}
        )
        self.assertTrue(ready)
        self.assertEqual(reasons, [])

    def test_assignments_deduplicate_same_member(self):
        row = {
            "codes": {
                "r1": "F1",
                "r2": "M1",
                "f_mon": "F2",
                "m_mon": "M2",
                "f_ann": "F1",
                "m_ann": "M3",
            }
        }
        assignments = scheduled_assignments(row)
        self.assertEqual([code for code, _ in assignments], ["F1", "M1", "F2", "M2", "M3"])
        self.assertIn("1re lecture", assignments[0][1])
        self.assertIn("Annonces", assignments[0][1])

    def test_future_rows_exclude_cancelled_and_past_programs(self):
        state = {
            "names": {"F1": "Alice", "M1": "Blaise", "F2": "Claire"},
            "whatsapp_contacts": {
                "F1": {"number": "+22670000000", "consent": True, "enabled": True},
                "M1": {"number": "", "consent": False, "enabled": False},
                "F2": {"number": "+22671000000", "consent": True, "enabled": True},
            },
            "history": [
                {"date": "2026-09-06", "codes": {"r1": "F2"}},
                {"date": "2026-09-20", "history_status": "cancelled", "codes": {"r1": "F2"}},
                {"date": "2026-10-04", "codes": {"r1": "F1", "r2": "M1"}},
            ],
        }
        rows = future_readiness_rows(state, reference_day=date(2026, 9, 15))
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["code"] for row in rows}, {"F1", "M1"})
        self.assertTrue(next(row for row in rows if row["code"] == "F1")["ready"])
        self.assertFalse(next(row for row in rows if row["code"] == "M1")["ready"])

    def test_future_rows_ignore_saturday_programs(self):
        state = {
            "names": {"F1": "Samedi", "F2": "Dimanche"},
            "whatsapp_contacts": {
                "F1": {"number": "+22670000000", "consent": True, "enabled": True},
                "F2": {"number": "+22671000000", "consent": True, "enabled": True},
            },
            "history": [
                {"date": "2026-10-03", "codes": {"r1": "F1"}},
                {"date": "2026-10-04", "codes": {"r1": "F2"}},
            ],
        }
        rows = future_readiness_rows(state, reference_day=date(2026, 10, 1))
        self.assertEqual([row["code"] for row in rows], ["F2"])

    def test_summary_counts_unique_blockers_and_sundays(self):
        rows = [
            {"date": "2026-10-04", "code": "F1", "name": "Alice", "ready": True},
            {"date": "2026-10-04", "code": "M3", "name": "Brigitte", "ready": False},
            {"date": "2026-10-11", "code": "M3", "name": "Brigitte", "ready": False},
            {"date": "2026-10-11", "code": "F2", "name": "Claire", "ready": True},
        ]
        summary = readiness_summary(rows)
        self.assertEqual(summary["assignments"], 4)
        self.assertEqual(summary["ready"], 2)
        self.assertEqual(summary["blocked"], 2)
        self.assertEqual(summary["sundays"], 2)
        self.assertEqual(summary["blocker_codes"], ["M3"])
        self.assertEqual(summary["blocker_names"], ["Brigitte"])

    def test_display_rows_never_exposes_phone_number(self):
        rows = [
            {
                "date_label": "04/10/2026",
                "name": "Brigitte",
                "code": "M3",
                "role": "1re lecture",
                "status": "⛔ À compléter",
                "reason_label": "numéro absent ou invalide",
                "number": "+22670000000",
            }
        ]
        projected = display_rows(rows)
        self.assertEqual(len(projected), 1)
        self.assertNotIn("number", projected[0])
        self.assertNotIn("Numéro", projected[0])
        self.assertNotIn("+22670000000", str(projected[0]))


if __name__ == "__main__":
    unittest.main()

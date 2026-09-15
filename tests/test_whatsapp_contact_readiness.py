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

    def test_future_rows_include_saturday_and_sunday_programs(self):
        state = {
            "names": {"M1": "Samedi", "F2": "Dimanche"},
            "whatsapp_contacts": {
                "M1": {"number": "+22670000000", "consent": True, "enabled": True},
                "F2": {"number": "+22671000000", "consent": True, "enabled": True},
            },
            "history": [
                {"date": "2026-10-03", "codes": {"r1": "M1"}},
                {"date": "2026-10-04", "codes": {"r1": "F2"}},
                {"date": "2026-10-05", "codes": {"r1": "F2"}},
            ],
        }
        rows = future_readiness_rows(state, reference_day=date(2026, 10, 1))
        self.assertEqual([row["code"] for row in rows], ["M1", "F2"])
        self.assertEqual([row["service_day"] for row in rows], ["samedi", "dimanche"])
        self.assertEqual(rows[0]["celebration_label"], "Samedi 03/10/2026")
        self.assertEqual(rows[1]["celebration_label"], "Dimanche 04/10/2026")

    def test_saturday_three_moore_readers_are_all_checked(self):
        state = {
            "names": {"M1": "A", "M2": "B", "M3": "C"},
            "whatsapp_contacts": {
                "M1": {"number": "+22670000001", "consent": True, "enabled": True},
                "M2": {"number": "+22670000002", "consent": True, "enabled": True},
                "M3": {"number": "", "consent": False, "enabled": False},
            },
            "history": [
                {"date": "2026-10-03", "codes": {"r1": "M1", "r2": "M2", "m_mon": "M3"}},
            ],
        }
        rows = future_readiness_rows(state, reference_day=date(2026, 10, 1))
        self.assertEqual([row["code"] for row in rows], ["M1", "M2", "M3"])
        self.assertEqual(sum(1 for row in rows if not row["ready"]), 1)
        self.assertEqual(next(row for row in rows if not row["ready"])["code"], "M3")

    def test_summary_counts_unique_blockers_and_celebrations(self):
        rows = [
            {"date": "2026-10-03", "service_day": "samedi", "code": "M1", "name": "A", "ready": True},
            {"date": "2026-10-04", "service_day": "dimanche", "code": "M3", "name": "Brigitte", "ready": False},
            {"date": "2026-10-11", "service_day": "dimanche", "code": "M3", "name": "Brigitte", "ready": False},
            {"date": "2026-10-11", "service_day": "dimanche", "code": "F2", "name": "Claire", "ready": True},
        ]
        summary = readiness_summary(rows)
        self.assertEqual(summary["assignments"], 4)
        self.assertEqual(summary["ready"], 2)
        self.assertEqual(summary["blocked"], 2)
        self.assertEqual(summary["celebrations"], 3)
        self.assertEqual(summary["saturdays"], 1)
        self.assertEqual(summary["sundays"], 2)
        self.assertEqual(summary["blocker_codes"], ["M3"])
        self.assertEqual(summary["blocker_names"], ["Brigitte"])

    def test_display_rows_never_exposes_phone_number(self):
        rows = [
            {
                "celebration_label": "Samedi 03/10/2026",
                "date_label": "03/10/2026",
                "name": "Brigitte",
                "code": "M3",
                "role": "Monition + P.U. — Mooré",
                "status": "⛔ À compléter",
                "reason_label": "numéro absent ou invalide",
                "number": "+22670000000",
            }
        ]
        projected = display_rows(rows)
        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["Célébration"], "Samedi 03/10/2026")
        self.assertNotIn("number", projected[0])
        self.assertNotIn("Numéro", projected[0])
        self.assertNotIn("+22670000000", str(projected[0]))


if __name__ == "__main__":
    unittest.main()
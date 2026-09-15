from datetime import date
import unittest

from scripts import whatsapp_automation as wa


class WhatsAppAutomationTests(unittest.TestCase):
    def test_principal_authorization_defaults_to_false(self):
        self.assertFalse(wa.automation_authorized({}))
        self.assertFalse(wa.automation_authorized({"whatsapp_automation_authorized": False}))
        self.assertTrue(wa.automation_authorized({"whatsapp_automation_authorized": True}))

    def test_next_published_sunday_ignores_cancelled_history(self):
        state = {
            "history": [
                {
                    "date": "2026-10-04",
                    "history_status": "cancelled",
                    "codes": {"r1": "F1"},
                },
                {
                    "date": "2026-10-11",
                    "codes": {"r1": "F2"},
                },
            ]
        }
        sunday, row = wa.next_published_sunday(state, date(2026, 9, 30))
        self.assertEqual(sunday, date(2026, 10, 11))
        self.assertEqual(row["codes"]["r1"], "F2")

    def test_next_published_weekend_groups_saturday_and_sunday(self):
        state = {
            "history": [
                {"date": "2026-10-03", "codes": {"r1": "M1"}},
                {"date": "2026-10-04", "codes": {"r1": "F2"}},
                {"date": "2026-10-10", "codes": {"r1": "M2"}},
            ]
        }
        sunday, services = wa.next_published_weekend(state, date(2026, 10, 1))
        self.assertEqual(sunday, date(2026, 10, 4))
        self.assertEqual([day for day, _ in services], [date(2026, 10, 3), date(2026, 10, 4)])

    def test_next_published_weekend_ignores_cancelled_and_past_service(self):
        state = {
            "history": [
                {"date": "2026-10-03", "codes": {"r1": "M1"}},
                {
                    "date": "2026-10-04",
                    "history_status": "cancelled",
                    "codes": {"r1": "F1"},
                },
                {"date": "2026-10-10", "codes": {"r1": "M2"}},
                {"date": "2026-10-11", "codes": {"r1": "F2"}},
            ]
        }
        sunday, services = wa.next_published_weekend(state, date(2026, 10, 4))
        self.assertEqual(sunday, date(2026, 10, 11))
        self.assertEqual([day for day, _ in services], [date(2026, 10, 10), date(2026, 10, 11)])

    def test_contact_readiness_requires_number_consent_and_activation(self):
        number, ready, reasons = wa.contact_readiness(
            {"number": "+22670000000", "consent": True, "enabled": True}
        )
        self.assertEqual(number, "22670000000")
        self.assertTrue(ready)
        self.assertEqual(reasons, [])

        number, ready, reasons = wa.contact_readiness(
            {"number": "", "consent": False, "enabled": False}
        )
        self.assertEqual(number, "")
        self.assertFalse(ready)
        self.assertIn("numéro absent ou invalide", reasons)
        self.assertIn("consentement absent", reasons)
        self.assertIn("rappels désactivés", reasons)

    def test_build_jobs_exposes_readiness_reasons_without_numbers_in_reason(self):
        state = {
            "names": {"F1": "Lecteur 1", "M1": "Lecteur 2"},
            "whatsapp_contacts": {
                "F1": {"number": "+22670000000", "consent": True, "enabled": True},
                "M1": {"number": "", "consent": False, "enabled": False},
            },
            "whatsapp_send_log": {},
        }
        row = {"codes": {"r1": "F1", "r2": "M1"}}
        jobs = wa.build_jobs(state, date(2026, 10, 4), row, "mercredi")
        by_code = {job["code"]: job for job in jobs}
        self.assertTrue(by_code["F1"]["ready"])
        self.assertEqual(by_code["F1"]["not_ready_reasons"], [])
        self.assertFalse(by_code["M1"]["ready"])
        self.assertIn("consentement absent", by_code["M1"]["not_ready_reasons"])
        self.assertNotIn("226", " ".join(by_code["M1"]["not_ready_reasons"]))

    def test_weekend_jobs_deduplicate_member_and_combine_services(self):
        state = {
            "names": {"M1": "Lecteur commun", "M2": "Lecteur samedi", "F1": "Lecteur dimanche"},
            "whatsapp_contacts": {
                "M1": {"number": "+22670000001", "consent": True, "enabled": True},
                "M2": {"number": "+22670000002", "consent": True, "enabled": True},
                "F1": {"number": "+22670000003", "consent": True, "enabled": True},
            },
            "whatsapp_send_log": {},
        }
        saturday = {"codes": {"r1": "M1", "r2": "M2"}}
        sunday = {"codes": {"r1": "F1", "m_ann": "M1"}}
        jobs = wa.build_weekend_jobs(
            state,
            date(2026, 10, 4),
            [(date(2026, 10, 3), saturday), (date(2026, 10, 4), sunday)],
            "mercredi",
        )
        self.assertEqual([job["code"] for job in jobs], ["M1", "M2", "F1"])
        common = jobs[0]
        self.assertEqual(len(common["assignments"]), 2)
        self.assertIn("Samedi 03/10/2026", common["service_label"])
        self.assertIn("Dimanche 04/10/2026", common["service_label"])
        self.assertIn("1re lecture", common["role"])
        self.assertIn("Annonces", common["role"])

    def test_send_key_is_scoped_by_weekend_kind_and_member(self):
        sunday = date(2026, 10, 4)
        self.assertEqual(
            wa.send_key(sunday, "mercredi", "F1"),
            "2026-10-04|mercredi|F1",
        )
        self.assertNotEqual(
            wa.send_key(sunday, "mercredi", "F1"),
            wa.send_key(sunday, "vendredi", "F1"),
        )

    def test_saturday_and_sunday_same_member_share_one_send_key(self):
        state = {
            "names": {"M1": "Lecteur commun"},
            "whatsapp_contacts": {
                "M1": {"number": "+22670000001", "consent": True, "enabled": True},
            },
            "whatsapp_send_log": {},
        }
        saturday = {"codes": {"r1": "M1"}}
        sunday = {"codes": {"m_ann": "M1"}}
        jobs = wa.build_weekend_jobs(
            state,
            date(2026, 10, 4),
            [(date(2026, 10, 3), saturday), (date(2026, 10, 4), sunday)],
            "vendredi",
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["send_key"], "2026-10-04|vendredi|M1")

    def test_build_jobs_detects_already_sent(self):
        sunday = date(2026, 10, 4)
        state = {
            "names": {"F1": "Lecteur 1"},
            "whatsapp_contacts": {
                "F1": {"number": "+22670000000", "consent": True, "enabled": True},
            },
            "whatsapp_send_log": {
                wa.send_key(sunday, "mercredi", "F1"): {"status": "sent"}
            },
        }
        row = {"codes": {"r1": "F1"}}
        jobs = wa.build_jobs(state, sunday, row, "mercredi")
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0]["already_sent"])

    def test_reminder_dates_match_wednesday_and_friday_offsets(self):
        sunday = date(2026, 10, 4)
        self.assertEqual(wa.reminder_date(sunday, "mercredi"), date(2026, 9, 30))
        self.assertEqual(wa.reminder_date(sunday, "vendredi"), date(2026, 10, 2))

    def test_saturday_uses_following_sunday_for_reminder_dates(self):
        saturday = date(2026, 10, 3)
        anchor = wa.weekend_anchor(saturday)
        self.assertEqual(anchor, date(2026, 10, 4))
        self.assertEqual(wa.reminder_date(anchor, "mercredi"), date(2026, 9, 30))
        self.assertEqual(wa.reminder_date(anchor, "vendredi"), date(2026, 10, 2))


if __name__ == "__main__":
    unittest.main()

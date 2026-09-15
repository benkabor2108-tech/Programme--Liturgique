from datetime import date
import unittest

from scripts import whatsapp_global_readiness as gate


class WhatsAppGlobalReadinessTests(unittest.TestCase):
    def test_principal_authorization_defaults_to_false(self):
        self.assertFalse(gate.automation_authorized({}))
        self.assertTrue(gate.automation_authorized({"whatsapp_automation_authorized": True}))

    def test_blocks_if_any_future_assignment_is_not_ready(self):
        state = {
            "names": {"F1": "Lecteur F1", "M3": "Lecteur M3"},
            "whatsapp_contacts": {
                "F1": {"number": "+22670000000", "consent": True, "enabled": True},
                "M3": {"number": "", "consent": False, "enabled": False},
            },
            "history": [
                {"date": "2026-10-04", "codes": {"r1": "F1", "r2": "M3"}},
                {"date": "2026-10-11", "codes": {"r1": "F1"}},
            ],
        }
        summary, blocked = gate.evaluate_state(state, date(2026, 9, 15))
        self.assertEqual(summary["sundays"], 2)
        self.assertEqual(summary["assignments"], 3)
        self.assertEqual(summary["blocked"], 1)
        self.assertEqual(blocked[0]["code"], "M3")

    def test_all_future_programs_must_be_green_not_only_next_sunday(self):
        state = {
            "whatsapp_contacts": {
                "F1": {"number": "+22670000000", "consent": True, "enabled": True},
                "M5": {"number": "", "consent": False, "enabled": False},
            },
            "history": [
                {"date": "2026-10-04", "codes": {"r1": "F1"}},
                {"date": "2026-10-18", "codes": {"r1": "M5"}},
            ],
        }
        summary, blocked = gate.evaluate_state(state, date(2026, 9, 15))
        self.assertEqual(summary["ready"], 1)
        self.assertEqual(summary["blocked"], 1)
        self.assertEqual([row["code"] for row in blocked], ["M5"])

    def test_blocker_lines_never_expose_phone_numbers(self):
        blocked = [{
            "date_label": "04/10/2026",
            "code": "M3",
            "reasons": ["numéro absent ou invalide", "consentement absent"],
        }]
        text = "\n".join(gate.blocker_lines(blocked))
        self.assertIn("M3", text)
        self.assertIn("consentement absent", text)
        self.assertNotIn("226", text)

    def test_missing_runtime_configuration_is_detected(self):
        values = {name: "ok" for name in gate.REQUIRED_RUNTIME_ENV}
        self.assertEqual(gate.missing_runtime_config(values), [])
        missing_key = gate.REQUIRED_RUNTIME_ENV[0]
        values[missing_key] = ""
        self.assertEqual(gate.missing_runtime_config(values), [missing_key])


if __name__ == "__main__":
    unittest.main()

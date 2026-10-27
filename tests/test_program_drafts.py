import unittest
from copy import deepcopy
from datetime import date
from program_drafts import store_draft, validate_draft, publish_draft


class DraftPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.state = {"history": [], "program_drafts": [], "next_first_language": "FR"}
        self.state["program_drafts"] = {}
        self.rows = [{"date": "2026-11-01", "codes": {
            "r1": "F1", "r2": "M1", "f_mon": "F2", "m_mon": "M2",
            "f_ann": "F3", "m_ann": "M3"}}]
        self.sundays = lambda y, m: [date(2026, 11, 1)]
        self.allowed = lambda state, lang, d: ["F1", "F2", "F3"] if lang == "FR" else ["M1", "M2", "M3"]

    def test_draft_does_not_publish(self):
        key = store_draft(self.state, 2026, 11, self.rows, "adjoint")
        self.assertEqual(self.state["history"], [])
        self.assertEqual(key, "2026-11")

    def test_invalid_duplicate_rejected(self):
        store_draft(self.state, 2026, 11, self.rows, "adjoint")
        self.state["program_drafts"]["2026-11"]["rows"][0]["codes"]["f_ann"] = "F1"
        with self.assertRaises(ValueError):
            validate_draft(self.state, self.state["program_drafts"]["2026-11"], self.sundays, self.allowed)

    def test_publish_only_when_explicitly_called(self):
        store_draft(self.state, 2026, 11, self.rows, "adjoint")
        def assign(state, code, role, day):
            state.setdefault("assigned", []).append((code, role))
        result = publish_draft(self.state, "2026-11", self.sundays, self.allowed, assign, deepcopy)
        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(len(result["assigned"]), 6)
        self.assertEqual(self.state["history"], [])
        self.assertNotIn("2026-11", result["program_drafts"])


if __name__ == "__main__":
    unittest.main()

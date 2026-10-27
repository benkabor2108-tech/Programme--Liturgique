import unittest
from copy import deepcopy
from datetime import date
from bilingual_weekends import weekend_dates, generate_bilingual_weekends
from program_drafts import store_draft, validate_draft


class WeekendTests(unittest.TestCase):
    def test_november_dates(self):
        sundays = lambda y, m: [date(2026, 11, d) for d in (1, 8, 15, 22, 29)]
        days = weekend_dates(sundays, 2026, 11)
        self.assertEqual(len(days), 10)
        self.assertEqual(days[0].isoformat(), "2026-10-31")
        self.assertEqual(days[-1].isoformat(), "2026-11-29")

    def test_no_duplicate_per_weekend_and_no_publication(self):
        fr = [f"F{i}" for i in range(1, 11)]
        mo = [f"M{i}" for i in range(1, 9)]
        people = {c: {"next_role": None, "reading_count": 0, "monition_count": 0,
                      "announcement_count": 0, "last_service": None,
                      "last_announcement": None} for c in fr + mo}
        state = {"history": [], "people": people, "names": {c: c for c in people},
                 "next_first_language": "FR", "reading_pairs": [], "monition_pairs": []}
        def assign(s, code, role, d):
            p = s["people"][code]
            p["next_role"] = "MONITION" if role == "LECTURE" else ("LECTURE" if role == "MONITION" else p["next_role"])
            p[{"LECTURE": "reading_count", "MONITION": "monition_count", "ANNONCE": "announcement_count"}[role]] += 1
            p["last_service"] = d.isoformat()
        sundays = lambda y, m: [date(2026, 11, d) for d in (1, 8, 15, 22, 29)]
        refs = {d.isoformat(): {"r1": "A", "r2": "B", "ev": "C"} for d in sundays(2026, 11)}
        rows, simulated = generate_bilingual_weekends(state, 2026, 11, refs, 2026, sundays, deepcopy,
            lambda s, lang, d: fr if lang == "FR" else mo, assign)
        self.assertEqual(len(rows), 10)
        self.assertEqual(state["history"], [])
        for i in range(0, 10, 2):
            codes = list(rows[i]["codes"].values()) + list(rows[i + 1]["codes"].values())
            self.assertEqual(len(codes), len(set(codes)))
        store_draft(state, 2026, 11, rows, "adjoint")
        self.assertTrue(validate_draft(state, state["program_drafts"]["2026-11"], sundays,
            lambda s, lang, d: fr if lang == "FR" else mo))
        self.assertEqual(len(simulated["history"]), 10)


if __name__ == "__main__":
    unittest.main()

from datetime import date
from pathlib import Path
import unittest

from weekend_generation import service_day_label, weekend_service_days


ROOT = Path(__file__).resolve().parents[1]


class WeekendGenerationTests(unittest.TestCase):
    def test_october_2026_contains_all_saturdays_and_sundays(self):
        days = weekend_service_days(2026, 10)
        self.assertEqual(
            [day.isoformat() for day in days],
            [
                "2026-10-03", "2026-10-04",
                "2026-10-10", "2026-10-11",
                "2026-10-17", "2026-10-18",
                "2026-10-24", "2026-10-25",
                "2026-10-31",
            ],
        )
        self.assertTrue(all(day.weekday() in (5, 6) for day in days))

    def test_service_day_labels(self):
        self.assertEqual(service_day_label(date(2026, 10, 3)), "Samedi")
        self.assertEqual(service_day_label(date(2026, 10, 4)), "Dimanche")
        with self.assertRaises(ValueError):
            service_day_label(date(2026, 10, 5))

    def test_wrapper_targets_weekend_generation_without_rewriting_core(self):
        wrapper = (ROOT / "liturgie_app.py").read_text(encoding="utf-8")
        core = (ROOT / "liturgie_app_core.py").read_text(encoding="utf-8")
        self.assertIn("weekend_service_days", wrapper)
        self.assertIn("service_day_label", wrapper)
        self.assertIn("month_dates = {d.isoformat() for d in weekend_service_days", wrapper)
        self.assertIn("month_sundays = weekend_service_days", wrapper)
        self.assertIn("jour_service", wrapper)
        # Le cœur historique reste inchangé; la correction passe par la couche protégée.
        self.assertIn("def sundays(year, month):", core)
        self.assertIn("d.weekday() == 6", core)


if __name__ == "__main__":
    unittest.main()

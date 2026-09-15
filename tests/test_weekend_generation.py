from datetime import date
from pathlib import Path
import unittest

from weekend_generation import (
    liturgical_reference_day,
    liturgical_reference_days,
    service_day_label,
    weekend_service_days,
)


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

    def test_saturday_uses_following_sunday_references(self):
        self.assertEqual(
            liturgical_reference_day(date(2026, 10, 3)),
            date(2026, 10, 4),
        )
        self.assertEqual(
            liturgical_reference_day(date(2026, 10, 4)),
            date(2026, 10, 4),
        )
        # Cas important : samedi en fin de mois, dimanche dans le mois suivant.
        self.assertEqual(
            liturgical_reference_day(date(2026, 10, 31)),
            date(2026, 11, 1),
        )

    def test_reference_days_are_unique_sundays_including_next_month(self):
        refs = liturgical_reference_days(weekend_service_days(2026, 10))
        self.assertEqual(
            [day.isoformat() for day in refs],
            ["2026-10-04", "2026-10-11", "2026-10-18", "2026-10-25", "2026-11-01"],
        )

    def test_wrapper_targets_weekend_generation_without_rewriting_core(self):
        wrapper = (ROOT / "liturgie_app.py").read_text(encoding="utf-8")
        core = (ROOT / "liturgie_app_core.py").read_text(encoding="utf-8")
        self.assertIn("weekend_service_days", wrapper)
        self.assertIn("service_day_label", wrapper)
        self.assertIn("month_dates = {d.isoformat() for d in weekend_service_days", wrapper)
        self.assertIn("month_sundays = weekend_service_days", wrapper)
        self.assertIn("jour_service", wrapper)
        self.assertIn("date_reference", wrapper)
        self.assertIn("liturgical_reference_day", wrapper)
        self.assertIn("AELF samedi = dimanche suivant", wrapper)
        self.assertIn("saisie manuelle samedi = dimanche suivant", wrapper)
        self.assertIn("saisie manuelle par dimanche de référence", wrapper)
        self.assertIn("reference_days = liturgical_reference_days(month_sundays)", wrapper)
        self.assertIn("samedi trois lecteurs mooréphones", wrapper)
        self.assertIn("is_saturday = sunday.weekday() == 5", wrapper)
        self.assertIn("r1_lang = r2_lang = \"MO\"", wrapper)
        self.assertIn("troisième lecteur mooréphone", wrapper)
        self.assertIn("codes samedi sans lecteur français", wrapper)
        self.assertIn("sunday.weekday() == 6", wrapper)
        self.assertIn("Les 3 lecteurs du samedi", wrapper)
        # Le cœur historique reste inchangé; la correction passe par la couche protégée.
        self.assertIn("def sundays(year, month):", core)
        self.assertIn("d.weekday() == 6", core)


if __name__ == "__main__":
    unittest.main()

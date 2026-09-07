import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.liturgical_drafts_automation import targets_for


TZ = ZoneInfo("Africa/Ouagadougou")


class LiturgicalDraftAutomationTests(unittest.TestCase):
    def test_tuesday_before_18_is_locked(self):
        now = datetime(2026, 9, 8, 17, 59, tzinfo=TZ)
        self.assertEqual(targets_for(now), [])

    def test_tuesday_at_18_prepares_next_sunday(self):
        now = datetime(2026, 9, 8, 18, 0, tzinfo=TZ)
        targets = targets_for(now)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["date"].isoformat(), "2026-09-13")
        self.assertEqual(targets[0]["rule"], "mardi à 18 h 00")

    def test_major_celebration_is_prepared_five_days_before(self):
        now = datetime(2026, 12, 20, 18, 0, tzinfo=TZ)
        targets = targets_for(now)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["date"].isoformat(), "2026-12-25")
        self.assertIn("Nativité", targets[0]["celebration_hint"])
        self.assertEqual(targets[0]["rule"], "5 jours avant à 18 h 00")

    def test_major_sunday_is_not_duplicated(self):
        # Pâques 2026 tombe le dimanche 5 avril : le mardi 31 mars est J-5.
        now = datetime(2026, 3, 31, 18, 0, tzinfo=TZ)
        targets = targets_for(now)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["date"].isoformat(), "2026-04-05")
        self.assertIn("Pâques", targets[0]["celebration_hint"])
        self.assertEqual(targets[0]["rule"], "5 jours avant à 18 h 00")


if __name__ == "__main__":
    unittest.main()

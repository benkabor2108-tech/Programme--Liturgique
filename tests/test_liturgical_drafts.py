import io
import unittest
from datetime import date, datetime
from zipfile import ZipFile

from liturgical_drafts import (
    APP_TIMEZONE,
    availability_for,
    build_draft,
    build_word_document,
    easter_sunday,
    extract_liturgical_context,
    liturgical_season,
    major_celebrations,
)


class LiturgicalDraftTests(unittest.TestCase):
    def test_sunday_unlocks_tuesday_at_18(self):
        sunday = date(2026, 9, 13)
        before = datetime(2026, 9, 8, 17, 59, tzinfo=APP_TIMEZONE)
        at = datetime(2026, 9, 8, 18, 0, tzinfo=APP_TIMEZONE)
        self.assertFalse(availability_for(sunday, "dimanche", before)["available"])
        self.assertTrue(availability_for(sunday, "dimanche", at)["available"])

    def test_major_event_unlocks_five_days_before(self):
        christmas = date(2026, 12, 25)
        before = datetime(2026, 12, 20, 17, 59, tzinfo=APP_TIMEZONE)
        at = datetime(2026, 12, 20, 18, 0, tzinfo=APP_TIMEZONE)
        self.assertFalse(availability_for(christmas, "event", before)["available"])
        self.assertTrue(availability_for(christmas, "event", at)["available"])

    def test_easter_and_major_calendar(self):
        self.assertEqual(easter_sunday(2026), date(2026, 4, 5))
        self.assertEqual(major_celebrations(2026)[date(2026, 12, 25)], "Nativité du Seigneur — Noël")

    def test_liturgical_season_detection(self):
        self.assertEqual(liturgical_season(date(2026, 9, 13), "24e dimanche du Temps ordinaire"), "Temps ordinaire")
        self.assertEqual(liturgical_season(date(2026, 12, 6), "2e dimanche de l'Avent"), "Temps de l’Avent")
        self.assertEqual(liturgical_season(date(2026, 12, 25), "Nativité du Seigneur — Noël"), "Temps de Noël")
        self.assertEqual(liturgical_season(date(2026, 4, 5), "Dimanche de Pâques — Résurrection du Seigneur"), "Temps pascal")

    def test_extract_context_and_build_draft(self):
        payload = {
            "messes": [{
                "nom": "24e dimanche du Temps ordinaire",
                "lectures": [
                    {"type": "lecture_1", "ref": "Ex 32, 7-11.13-14", "contenu": "<p>Le Seigneur se souvient de son alliance.</p>"},
                    {"type": "psaume", "ref": "Ps 50", "contenu": "<p>Pitié pour moi, mon Dieu, dans ta miséricorde.</p>"},
                    {"type": "lecture_2", "ref": "1 Tm 1, 12-17", "contenu": "<p>Le Christ est venu sauver les pécheurs.</p>"},
                    {"type": "evangile", "ref": "Lc 15, 1-32", "contenu": "<p>Il y a de la joie pour un pécheur qui se convertit.</p>"},
                ],
            }]
        }
        context = extract_liturgical_context(payload, date(2026, 9, 13), "romain")
        self.assertEqual(context["parts"]["ev"]["ref"], "Lc 15, 1-32")
        self.assertEqual(context["liturgical_season"], "Temps ordinaire")
        draft = build_draft(context)
        self.assertIn("Frères et sœurs", draft["monition"])
        self.assertIn("Temps ordinaire", draft["monition"])
        self.assertIn("«", draft["monition"])
        self.assertEqual(len(draft["intentions"]), 4)
        self.assertIn("Burkina Faso", draft["intentions"][1])
        self.assertIn("prisonniers", draft["intentions"][2])
        self.assertIn("n’ont pas pu venir", draft["intentions"][3])

    def test_word_document_is_valid_and_simplified(self):
        meta = {
            "date_label": "13/09/2026",
            "celebration": "24e dimanche du Temps ordinaire",
            "liturgical_season": "Temps ordinaire",
            "refs": {"r1": "Ex 32", "ps": "Ps 50", "r2": "1 Tm 1", "ev": "Lc 15"},
            "zone": "romain",
            "zone_label": "Calendrier romain",
        }
        data = build_word_document(
            meta,
            "Monition de test.",
            "Introduction de test.",
            [f"Intention {i}." for i in range(1, 5)],
            "Conclusion de test. Amen.",
            "Seigneur, nous te prions.",
        )
        self.assertGreater(len(data), 10000)
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertIn("word/document.xml", archive.namelist())
            xml = archive.read("word/document.xml").decode("utf-8")
            self.assertIn("MONITION DU 13/09/2026", xml)
            self.assertIn("PRIÈRE UNIVERSELLE DU 13/09/2026", xml)
            self.assertIn("Intention 4.", xml)
            self.assertNotIn("Temps ordinaire", xml)
            self.assertNotIn("Ex 32", xml)
            self.assertNotIn("Introduction de test", xml)
            self.assertNotIn("Seigneur, nous te prions.", xml)
            self.assertNotIn("Conclusion de test", xml)


if __name__ == "__main__":
    unittest.main()

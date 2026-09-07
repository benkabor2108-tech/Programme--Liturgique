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
        draft = build_draft(context)
        self.assertIn("Frères et sœurs", draft["monition"])
        self.assertEqual(len(draft["intentions"]), 6)

    def test_word_document_is_valid_docx(self):
        meta = {
            "date_label": "13/09/2026",
            "celebration": "24e dimanche du Temps ordinaire",
            "refs": {"r1": "Ex 32", "ps": "Ps 50", "r2": "1 Tm 1", "ev": "Lc 15"},
            "zone": "romain",
            "zone_label": "Calendrier romain",
        }
        data = build_word_document(
            meta,
            "Monition de test.",
            "Introduction de test.",
            [f"Intention {i}." for i in range(1, 7)],
            "Conclusion de test. Amen.",
            "Seigneur, nous te prions.",
        )
        self.assertGreater(len(data), 10000)
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertIn("word/document.xml", archive.namelist())


if __name__ == "__main__":
    unittest.main()

import unittest

from liturgical_drafts_pdf import build_reader_pdf


class ReaderPDFTests(unittest.TestCase):
    def test_pdf_is_generated_with_unicode_content(self):
        meta = {
            "celebration": "29e dimanche du Temps ordinaire",
            "date_label": "18/10/2026",
            "refs": {"r1": "Is 45", "ps": "Ps 95", "r2": "1 Th 1", "ev": "Mt 22"},
        }
        pdf = build_reader_pdf(
            meta,
            "Frères et sœurs, accueillons la Parole de Dieu.",
            [f"Pour les familles et les personnes éprouvées {i}. Prions le Seigneur." for i in range(4)],
        )
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 4000)

    def test_pdf_handles_free_draft_without_date(self):
        pdf = build_reader_pdf({}, "Bienvenue à toutes et à tous.", ["Pour notre communauté."])
        self.assertTrue(pdf.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()

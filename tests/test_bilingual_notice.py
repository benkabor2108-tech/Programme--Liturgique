"""Contrôle de la notice AELF et de l'absence d'anciennes consignes samedi."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BilingualNoticeTests(unittest.TestCase):
    def test_aelf_notice_matches_four_roles(self):
        source = (ROOT / "liturgie_app.py").read_text(encoding="utf-8")
        self.assertIn("quatre intervenants", source)
        self.assertIn("deux lectures en langues opposées", source)
        self.assertIn("Aucune annonce n’est programmée", source)
        self.assertNotIn("Les 3 intervenants du samedi sont tous mooréphones", source)

    def test_generator_has_four_bilingual_roles_without_announcements(self):
        source = (ROOT / "program_drafts.py").read_text(encoding="utf-8")
        self.assertIn('ROLES = ("r1", "r2", "f_mon", "m_mon")', source)


if __name__ == "__main__":
    unittest.main()

import unittest

from liturgical_drafts_free import ENDING, library, new_record, normalize_intention, propose_orientation


class ReaderWorkshopTests(unittest.TestCase):
    def test_ending_not_duplicated(self):
        self.assertEqual(normalize_intention("Pour les malades. Prions le Seigneur."), "Pour les malades\n" + ENDING)
        self.assertEqual(normalize_intention("Pour les malades"), "Pour les malades\n" + ENDING)

    def test_orientation_targets(self):
        for target in ("both", "monition", "priere"):
            with self.subTest(target=target):
                proposal = propose_orientation("Anniversaire de la paroisse", target)
                self.assertEqual(len(proposal["intentions"]), 4)
                self.assertEqual(bool(proposal["monition"]), target != "priere")
                self.assertEqual("Anniversaire de la paroisse" in proposal["intentions"][2], target != "monition")

    def test_optional_orientation(self):
        self.assertIsNone(propose_orientation("", "both"))
        with self.assertRaises(ValueError):
            propose_orientation("x" * 501, "both")

    def test_old_drafts_unchanged(self):
        state = {"liturgical_drafts": {"2026-10-11|romain": {"monition": "Historique"}}}
        library(state)[new_record()["id"]] = new_record()
        self.assertEqual(state["liturgical_drafts"]["2026-10-11|romain"]["monition"], "Historique")


if __name__ == "__main__":
    unittest.main()

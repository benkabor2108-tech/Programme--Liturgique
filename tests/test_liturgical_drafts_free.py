import unittest

from liturgical_drafts_free import ENDING, library, new_record, normalize_intention, propose_orientation, integrate_event, reader_export_readiness


class ReaderWorkshopTests(unittest.TestCase):
    def test_generated_fields_are_applied_before_streamlit_widgets(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "liturgical_drafts_free.py").read_text(encoding="utf-8")
        self.assertLess(source.index('if pending_fields_key in st.session_state:'),
                        source.index('monition = st.text_area('))
        self.assertIn('st.session_state[pending_fields_key] = pending_fields', source)
        self.assertIn('st.session_state[pending_fields_key] = {', source)
        self.assertNotIn('st.session_state[f"reader_monition_{identity}"] = proposal["monition"]', source)
        self.assertNotIn('st.session_state[f"reader_intention_{identity}_{i}"] = intention', source)

    def test_aelf_date_widget_is_updated_before_creation(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "liturgical_drafts_free.py").read_text(encoding="utf-8")
        pre_widget = source.index('if pending_date_key in st.session_state:')
        widget = source.index('date_text = st.text_input(')
        self.assertLess(pre_widget, widget)
        self.assertIn('st.session_state[pending_date_key] = liturgical_day.isoformat()', source)
        self.assertNotIn('st.session_state[f"reader_date_{identity}"] = liturgical_day.isoformat()', source)

    def test_proclamation_export_requires_monition_and_four_intentions(self):
        prayers = ["Intention 1", "Intention 2", "Intention 3", "Intention 4"]
        self.assertEqual(reader_export_readiness("Monition", prayers), (True, []))
        self.assertEqual(reader_export_readiness("", prayers), (False, []))
        self.assertEqual(reader_export_readiness("Monition", prayers[:2]), (False, [3, 4]))
        self.assertEqual(reader_export_readiness("Monition", [prayers[0], "", *prayers[2:]]), (False, [2]))

    def test_empty_intention_does_not_become_prayer(self):
        self.assertEqual(normalize_intention(""), "")

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

    def test_event_placed_in_matching_intention(self):
        base = {"monition": "Bienvenue.", "intentions": ["I1", "I2", "I3", "I4"]}
        cases = [
            ("personnes déplacées", 2),
            ("paix au Burkina Faso", 1),
            ("anniversaire paroissial", 3),
            ("vocations dans l'Église", 0),
        ]
        for event, index in cases:
            with self.subTest(event=event):
                result = integrate_event(base, event, "both")
                self.assertIn("Prions le Seigneur.", result["intentions"][index])
                self.assertIn(event, result["intentions"][index])
                self.assertEqual(len(result["intentions"]), 4)
                self.assertIn("Bienvenue.", result["monition"])

    def test_optional_orientation(self):
        self.assertIsNone(propose_orientation("", "both"))
        with self.assertRaises(ValueError):
            propose_orientation("x" * 501, "both")

    def test_workshop_requires_confirmed_persistence_and_preserves_versions(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "liturgical_drafts_free.py").read_text(encoding="utf-8")
        self.assertIn('if not callable(persist_callback):', source)
        self.assertIn('if not persist_callback(show_success=False):', source)
        self.assertIn('"intentions": [normalize_intention(value) for value in intentions]', source)
        self.assertIn('"liturgical_meta": record.get("liturgical_meta", {})', source)

    def test_invalid_library_never_overwritten(self):
        state = {"reader_liturgical_texts": ["unexpected"]}
        with self.assertRaises(ValueError):
            library(state)
        self.assertEqual(state["reader_liturgical_texts"], ["unexpected"])

    def test_old_drafts_unchanged(self):
        state = {"liturgical_drafts": {"2026-10-11|romain": {"monition": "Historique"}}}
        library(state)[new_record()["id"]] = new_record()
        self.assertEqual(state["liturgical_drafts"]["2026-10-11|romain"]["monition"], "Historique")


if __name__ == "__main__":
    unittest.main()

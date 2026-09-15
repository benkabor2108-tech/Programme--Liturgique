from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CORE = (ROOT / "liturgie_app_core.py").read_text(encoding="utf-8")
WRAPPER = (ROOT / "liturgie_app.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "whatsapp-reminders.yml").read_text(encoding="utf-8")


class WhatsAppUiGuardTests(unittest.TestCase):
    def test_checkpoint_version_is_contact_readiness(self):
        self.assertIn("v3.10.10-whatsapp-contact-readiness", WRAPPER)

    def test_streamlit_next_sunday_ignores_cancelled_history(self):
        marker = "def next_published_sunday(state, reference_day=None):"
        start = CORE.index(marker)
        section = CORE[start:start + 900]
        self.assertIn("if not is_history_row_active(row):", section)

    def test_ui_validates_number_before_marking_contact_ready(self):
        self.assertGreaterEqual(CORE.count("normalize_whatsapp_number(number)"), 2)

    def test_ui_explains_meta_templates_are_separate(self):
        self.assertIn("Cloud API utilise des templates Meta approuvés séparément", CORE)
        self.assertIn("modifier ce texte ne modifie pas le template", CORE)

    def test_ui_reports_production_automation_pause(self):
        self.assertIn("en pause de sécurité dans cette version", CORE)
        self.assertIn("Géré par GitHub Actions — envoi en pause", CORE)

    def test_wrapper_adds_contact_readiness_dashboard(self):
        self.assertIn("Préparation à l", WRAPPER)
        self.assertIn("automatisation WhatsApp", WRAPPER)
        self.assertIn("future_readiness_rows", WRAPPER)
        self.assertIn("whatsapp_display_rows", WRAPPER)
        self.assertIn("Aucune activation n", WRAPPER)
        self.assertIn("faite automatiquement", WRAPPER)

    def test_production_workflow_is_paused(self):
        self.assertIn('WHATSAPP_AUTOMATION_ENABLED: "false"', WORKFLOW)

    def test_production_workflow_requires_global_readiness_when_enabled(self):
        self.assertIn("scripts/whatsapp_global_readiness.py", WORKFLOW)
        self.assertIn('if [[ "$enabled" == "true" && "$dry_run" != "true" ]]', WORKFLOW)
        self.assertIn("Vérification globale obligatoire avant envoi de production", WORKFLOW)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CORE = (ROOT / "liturgie_app_core.py").read_text(encoding="utf-8")
WRAPPER = (ROOT / "liturgie_app.py").read_text(encoding="utf-8")


class RoleGuardRegressionTests(unittest.TestCase):
    def test_roles_are_distinct_and_staff_scope_is_explicit(self):
        self.assertIn('if role in ("principal", "adjoint"):', CORE)
        self.assertIn('return current_role() == "principal"', CORE)
        self.assertIn('return current_role() == "adjoint"', CORE)
        self.assertIn('return current_role() in ("principal", "adjoint")', CORE)

    def test_generation_is_principal_only(self):
        marker = 'with generate_tab:'
        start = CORE.index(marker)
        section = CORE[start:start + 2500]
        self.assertIn('if not IS_ADMIN:', section)
        self.assertIn(
            'La génération et la validation d\'un nouveau programme sont réservées à l\'administrateur principal.',
            section,
        )

    def test_member_changes_are_principal_only(self):
        marker = 'with members_tab:'
        start = CORE.index(marker)
        section = CORE[start:start + 3500]
        self.assertIn('if not IS_ADMIN:', section)
        self.assertIn(
            'Les changements de noms, statuts, ajouts et retraits sont réservés à l\'administrateur.',
            section,
        )

    def test_adjoint_scope_is_attendance_and_whatsapp(self):
        self.assertIn('CAN_EDIT_ATTENDANCE = staff_mode()', CORE)
        self.assertIn('if IS_ADJOINT:', CORE)
        self.assertIn('st.subheader("📲 Rappels WhatsApp")', CORE)
        self.assertIn('Les numéros de téléphone restent masqués', CORE)
        self.assertIn('Ancienne feuille en lecture seule pour l\'administrateur adjoint.', CORE)

    def test_private_liturgical_drafts_tab_is_principal_only(self):
        self.assertIn('is_principal = st.session_state.get("auth_role") == "principal"', WRAPPER)
        self.assertIn('if not (is_main_tabs and is_principal):', WRAPPER)
        self.assertIn('["📝 Monitions & P.U."]', WRAPPER)

    def test_role_banner_describes_limited_adjoint_rights(self):
        self.assertIn('droits limités aux présences en cours', CORE)
        self.assertIn('et aux rappels WhatsApp', CORE)


if __name__ == "__main__":
    unittest.main()

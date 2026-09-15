from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)

# 1) Wrapper / runtime UI
path = Path("liturgie_app.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.10-whatsapp-contact-readiness"',
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.12-whatsapp-admin-activation"',
    "version",
)
text = replace_once(
    text,
    "'        \"whatsapp_send_log\": {},\\n        \"liturgical_drafts\": {},\\n        \"audit_log\": [],\\n',",
    "'        \"whatsapp_send_log\": {},\\n        \"whatsapp_automation_authorized\": False,\\n        \"liturgical_drafts\": {},\\n        \"audit_log\": [],\\n',",
    "state default",
)
text = replace_once(
    text,
    "'\"history\", \"attendance\", \"attendance_ignored\", \"auth_security\", \"whatsapp_send_log\", \"liturgical_drafts\", \"audit_log\"]:\\n',",
    "'\"history\", \"attendance\", \"attendance_ignored\", \"auth_security\", \"whatsapp_send_log\", \"whatsapp_automation_authorized\", \"liturgical_drafts\", \"audit_log\"]:\\n',",
    "state preservation",
)
anchor = '        with st.expander("📱 Numéros et consentements", expanded=False):\\n'
activation = '''        st.divider()\n        st.markdown("### 🚦 Autorisation de l'envoi automatique")\n        _wa_authorized = bool(state.get("whatsapp_automation_authorized", False))\n        _wa_all_ready = bool(_wa_rows) and _wa_summary.get("blocked", 0) == 0\n        if _wa_authorized:\n            st.success("Autorisation principale activée. Le gate global reste obligatoire avant chaque envoi réel.")\n        else:\n            st.info("Autorisation principale désactivée : aucun rappel Cloud API ne peut partir automatiquement.")\n\n        if IS_ADMIN:\n            with st.form("whatsapp_automation_authorization_form"):\n                _wa_requested = st.checkbox(\n                    "Autoriser les rappels automatiques WhatsApp Cloud API",\n                    value=_wa_authorized,\n                    help=(\n                        "Cette autorisation ne contourne jamais les contrôles de readiness. "\n                        "Si un contact programmé est incomplet, le workflow restera bloqué."\n                    ),\n                )\n                _wa_save_auth = st.form_submit_button("💾 Enregistrer l'autorisation")\n            if _wa_save_auth:\n                if _wa_requested and not _wa_all_ready:\n                    st.error(\n                        "Activation refusée : tous les contacts des programmes futurs doivent d'abord être prêts. "\n                        "Vous pourrez réessayer dès que les numéros et consentements manquants auront été renseignés."\n                    )\n                elif bool(_wa_requested) == _wa_authorized:\n                    st.info("Aucun changement à enregistrer.")\n                else:\n                    state["whatsapp_automation_authorized"] = bool(_wa_requested)\n                    state.setdefault("audit_log", []).append({\n                        "type": "whatsapp_automation_authorization_changed",\n                        "enabled": bool(_wa_requested),\n                        "timestamp": now_ouaga().isoformat(),\n                        "actor": "Administrateur principal",\n                    })\n                    if persist(show_success=False):\n                        if _wa_requested:\n                            st.success("Autorisation WhatsApp automatique activée. Les gates de sécurité restent obligatoires.")\n                        else:\n                            st.success("Autorisation WhatsApp automatique désactivée.")\n                        st.rerun()\n\n        with st.expander("📱 Numéros et consentements", expanded=False):\n'''
text = replace_once(text, anchor, activation, "activation UI")
text = replace_once(
    text,
    '        "Mode de sécurité actuel : l\'envoi automatique reste en pause tant que le readiness complet "\\n        "n\'est pas vert. Les rappels assistés et les simulations restent disponibles."\\n',
    '        "L\'administrateur principal peut maintenant autoriser ou désactiver l\'envoi automatique depuis Membres > WhatsApp. "\\n        "Même autorisé, aucun envoi réel ne part si le gate global de readiness n\'est pas entièrement vert."\\n',
    "guide activation",
)
path.write_text(text, encoding="utf-8")

# 2) Reminder engine requires stored principal authorization for real sends.
path = Path("scripts/whatsapp_automation.py")
text = path.read_text(encoding="utf-8")
insert = '''\n\ndef automation_authorized(state: dict) -> bool:\n    """Autorisation métier persistée par l'administrateur principal."""\n    return bool(state.get("whatsapp_automation_authorized", False)) if isinstance(state, dict) else False\n'''
text = replace_once(text, '\ndef next_published_sunday(state: dict, reference_day: date):\n', insert + '\n\ndef next_published_sunday(state: dict, reference_day: date):\n', "automation helper")
text = replace_once(
    text,
    '    missing = whatsapp_config_missing(cfg)\n    if missing:\n',
    '    if not automation_authorized(state):\n        print("[preflight] Autorisation principale WhatsApp désactivée; aucun message envoyé.")\n        return 0\n\n    missing = whatsapp_config_missing(cfg)\n    if missing:\n',
    "production state authorization",
)
path.write_text(text, encoding="utf-8")

# 3) Global gate is silent/green while principal authorization is OFF; strict once ON.
path = Path("scripts/whatsapp_global_readiness.py")
text = path.read_text(encoding="utf-8")
insert = '''\n\ndef automation_authorized(state: dict) -> bool:\n    return bool(state.get("whatsapp_automation_authorized", False)) if isinstance(state, dict) else False\n'''
text = replace_once(text, '\ndef evaluate_state(state: dict, reference_day: date) -> tuple[dict, list[dict]]:\n', insert + '\n\ndef evaluate_state(state: dict, reference_day: date) -> tuple[dict, list[dict]]:\n', "global helper")
text = replace_once(
    text,
    '    summary, blocked = evaluate_state(state, reference_day)\n\n    if not summary["assignments"]:\n',
    '    if not automation_authorized(state):\n        print("[global-readiness] Autorisation principale désactivée — aucun envoi de production autorisé.")\n        return 0\n\n    summary, blocked = evaluate_state(state, reference_day)\n\n    if not summary["assignments"]:\n',
    "global state authorization",
)
path.write_text(text, encoding="utf-8")

# 4) Tests
path = Path("tests/test_whatsapp_automation.py")
text = path.read_text(encoding="utf-8")
needle = 'class WhatsAppAutomationTests(unittest.TestCase):\n'
addition = '''class WhatsAppAutomationTests(unittest.TestCase):\n    def test_principal_authorization_defaults_to_false(self):\n        self.assertFalse(wa.automation_authorized({}))\n        self.assertFalse(wa.automation_authorized({"whatsapp_automation_authorized": False}))\n        self.assertTrue(wa.automation_authorized({"whatsapp_automation_authorized": True}))\n\n'''
text = replace_once(text, needle, addition, "automation tests")
path.write_text(text, encoding="utf-8")

path = Path("tests/test_whatsapp_global_readiness.py")
text = path.read_text(encoding="utf-8")
needle = 'class WhatsAppGlobalReadinessTests(unittest.TestCase):\n'
addition = '''class WhatsAppGlobalReadinessTests(unittest.TestCase):\n    def test_principal_authorization_defaults_to_false(self):\n        self.assertFalse(gate.automation_authorized({}))\n        self.assertTrue(gate.automation_authorized({"whatsapp_automation_authorized": True}))\n\n'''
text = replace_once(text, needle, addition, "global tests")
path.write_text(text, encoding="utf-8")

path = Path("tests/test_whatsapp_ui_guards.py")
text = path.read_text(encoding="utf-8")
text = text.replace('v3.10.10-whatsapp-contact-readiness', 'v3.10.12-whatsapp-admin-activation')
text = replace_once(
    text,
    '    def test_production_workflow_is_paused(self):\n        self.assertIn(\'WHATSAPP_AUTOMATION_ENABLED: "false"\', WORKFLOW)\n',
    '    def test_production_workflow_uses_two_key_activation(self):\n        self.assertIn(\'WHATSAPP_AUTOMATION_ENABLED: "true"\', WORKFLOW)\n        self.assertIn("whatsapp_global_readiness.py", WORKFLOW)\n        self.assertIn("whatsapp_automation_authorized", WRAPPER)\n        self.assertIn("Autoriser les rappels automatiques WhatsApp Cloud API", WRAPPER)\n',
    "ui workflow guard",
)
path.write_text(text, encoding="utf-8")

print("v3.10.12 patch applied")

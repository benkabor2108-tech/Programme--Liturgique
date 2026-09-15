from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


# 1) Version wrapper
app_path = Path("liturgie_app.py")
app = app_path.read_text(encoding="utf-8")
app = replace_once(
    app,
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.8-role-guards"',
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.9-whatsapp-readiness"',
    "version marker",
)
app_path.write_text(app, encoding="utf-8")


# 2) Streamlit core: cancelled history, number validation and truthful WhatsApp UI
core_path = Path("liturgie_app_core.py")
core = core_path.read_text(encoding="utf-8")
core = replace_once(
    core,
    "from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle\n",
    "from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle\n"
    "from history_protection import is_history_row_active\n",
    "history protection import",
)
core = replace_once(
    core,
    '''    for row in state.get("history", []) or []:\n        try:\n            day = date.fromisoformat(str(row.get("date", "")))\n''',
    '''    for row in state.get("history", []) or []:\n        if not is_history_row_active(row):\n            continue\n        try:\n            day = date.fromisoformat(str(row.get("date", "")))\n''',
    "next published sunday cancellation filter",
)
ready_marker = '            ready = bool(number and consent and enabled)\n'
if core.count(ready_marker) != 2:
    raise SystemExit(f"number readiness: expected 2 matches, found {core.count(ready_marker)}")
core = core.replace(
    ready_marker,
    '            normalized_number, _number_error = normalize_whatsapp_number(number)\n'
    '            ready = bool(normalized_number and consent and enabled)\n',
    2,
)
core = replace_once(
    core,
    '    st.subheader("🤖 Automatisation complète — préparation")\n',
    '    st.subheader("🤖 Automatisation complète — préparation")\n'
    '    st.warning(\n'
    '        "Envoi automatique GitHub Actions en pause de sécurité dans cette version : "\n'
    '        "aucun rappel Cloud API ne partira tant que la validation finale Meta et contacts n\'est pas levée."\n'
    '    )\n'
    '    st.caption(\n'
    '        "La production automatique est orchestrée par GitHub Actions. "\n'
    '        "Streamlit ne peut pas lire les secrets GitHub ni confirmer leur état en temps réel."\n'
    '    )\n',
    "automation status banner",
)
core = replace_once(
    core,
    '''            "Mode sécurisé : automatisation désactivée. "\n            "Aucun message WhatsApp ne peut partir automatiquement depuis cette version."\n''',
    '''            "Configuration locale Streamlit inactive. "\n            "Les envois automatiques de production sont gérés séparément par GitHub Actions."\n''',
    "local Streamlit config wording",
)
core = replace_once(
    core,
    '        "État": "À brancher",\n',
    '        "État": "Géré par GitHub Actions — envoi en pause 🔒",\n',
    "scheduler wording",
)
core = replace_once(
    core,
    '''        st.markdown(\n            "**Pour passer à l'envoi automatique plus tard :** "\n            "il restera à renseigner les identifiants API réels, faire approuver "\n            "les deux modèles WhatsApp, puis brancher un ordonnanceur fiable. "\n            "Aucun secret n'est nécessaire aujourd'hui."\n        )\n''',
    '''        st.markdown(\n            "**Pour réactiver l'envoi automatique :** vérifier les contacts du prochain dimanche, "\n            "confirmer que les deux templates Meta sont APPROVED dans la bonne langue, puis lever "\n            "la pause dans le workflow GitHub. Les numéros et secrets restent masqués."\n        )\n''',
    "automation activation guidance",
)
core = replace_once(
    core,
    '''    current = state.get("whatsapp_templates", {}) if isinstance(state.get("whatsapp_templates"), dict) else {}\n''',
    '''    st.info(\n        "Ces textes pilotent l'envoi assisté via WhatsApp (wa.me). "\n        "L'envoi automatique Cloud API utilise des templates Meta approuvés séparément ; "\n        "modifier ce texte ne modifie pas le template enregistré chez Meta."\n    )\n\n    current = state.get("whatsapp_templates", {}) if isinstance(state.get("whatsapp_templates"), dict) else {}\n''',
    "template distinction notice",
)
core_path.write_text(core, encoding="utf-8")


# 3) Automation engine: explicit readiness reasons + preflight-only mode
wa_path = Path("scripts/whatsapp_automation.py")
wa = wa_path.read_text(encoding="utf-8")
wa = replace_once(
    wa,
    '''def normalize_number(value: str) -> str:\n    digits = re.sub(r"\\D", "", str(value or ""))\n    if not (8 <= len(digits) <= 15):\n        return ""\n    return digits\n\n\n''',
    '''def normalize_number(value: str) -> str:\n    digits = re.sub(r"\\D", "", str(value or ""))\n    if not (8 <= len(digits) <= 15):\n        return ""\n    return digits\n\n\ndef contact_readiness(contact: dict) -> tuple[str, bool, list[str]]:\n    """Évalue un contact sans exposer son numéro dans les diagnostics."""\n    contact = contact if isinstance(contact, dict) else {}\n    number = normalize_number(contact.get("number", ""))\n    reasons = []\n    if not number:\n        reasons.append("numéro absent ou invalide")\n    if not bool(contact.get("consent")):\n        reasons.append("consentement absent")\n    if not bool(contact.get("enabled")):\n        reasons.append("rappels désactivés")\n    return number, not reasons, reasons\n\n\n''',
    "contact readiness helper",
)
wa = replace_once(
    wa,
    '''        number = normalize_number(contact.get("number", ""))\n        ready = bool(number and contact.get("consent") and contact.get("enabled"))\n        key = send_key(sunday, kind, code)\n        jobs.append({\n            "code": code,\n            "name": str(names.get(code, code)),\n            "role": role_for_code(row, code),\n            "number": number,\n            "ready": ready,\n            "already_sent": key in log,\n            "send_key": key,\n        })\n''',
    '''        number, ready, not_ready_reasons = contact_readiness(contact)\n        key = send_key(sunday, kind, code)\n        jobs.append({\n            "code": code,\n            "name": str(names.get(code, code)),\n            "role": role_for_code(row, code),\n            "number": number,\n            "ready": ready,\n            "not_ready_reasons": not_ready_reasons,\n            "already_sent": key in log,\n            "send_key": key,\n        })\n''',
    "build jobs readiness",
)
wa = replace_once(
    wa,
    '''    parser.add_argument("--kind", choices=["auto", "mercredi", "vendredi"], default=env("WHATSAPP_REMINDER_KIND", "auto"))\n    parser.add_argument("--reference-date", help="Date YYYY-MM-DD pour un test reproductible.")\n    args = parser.parse_args()\n''',
    '''    parser.add_argument("--kind", choices=["auto", "mercredi", "vendredi"], default=env("WHATSAPP_REMINDER_KIND", "auto"))\n    parser.add_argument("--reference-date", help="Date YYYY-MM-DD pour un test reproductible.")\n    parser.add_argument(\n        "--readiness-only",\n        action="store_true",\n        help="Contrôle le prochain dimanche sans envoyer ni journaliser.",\n    )\n    parser.add_argument(\n        "--require-complete",\n        action="store_true",\n        default=as_bool(env("WHATSAPP_REQUIRE_COMPLETE", "false")),\n        help="Échoue en mode readiness si un contact ou un paramètre WhatsApp manque.",\n    )\n    args = parser.parse_args()\n''',
    "readiness CLI arguments",
)
wa = replace_once(
    wa,
    '''    if not sunday or not row:\n        print("[info] Aucun dimanche futur publié; aucun rappel à envoyer.")\n        return 0\n\n    expected_day = reminder_date(sunday, kind)\n''',
    '''    if not sunday or not row:\n        print("[info] Aucun dimanche futur publié; aucun rappel à envoyer.")\n        return 0\n\n    if args.readiness_only:\n        jobs = build_jobs(state, sunday, row, "mercredi")\n        ready_jobs = [job for job in jobs if job["ready"]]\n        not_ready = [job for job in jobs if not job["ready"]]\n        missing_config = whatsapp_config_missing(cfg)\n        print(\n            f"[readiness] dimanche={sunday:%d/%m/%Y} "\n            f"prêts={len(ready_jobs)} non_configurés={len(not_ready)}"\n        )\n        for job in not_ready:\n            reasons = ", ".join(job.get("not_ready_reasons", [])) or "configuration incomplète"\n            print(f"[warning] {job['code']} — {job['name']} — {reasons}")\n        if missing_config:\n            print("[warning] paramètres WhatsApp manquants: " + ", ".join(missing_config))\n        if args.require_complete and (not_ready or missing_config):\n            print("[readiness] INCOMPLET")\n            return 2\n        print("[readiness] COMPLET")\n        return 0\n\n    expected_day = reminder_date(sunday, kind)\n''',
    "readiness-only mode",
)
wa = replace_once(
    wa,
    '''    print(f"[plan] dimanche={sunday:%d/%m/%Y} rappel={kind} prêts={len(pending)} déjà_envoyés={len(already_sent)} non_configurés={len(not_ready)}")\n\n    if cfg["dry_run"]:\n''',
    '''    print(f"[plan] dimanche={sunday:%d/%m/%Y} rappel={kind} prêts={len(pending)} déjà_envoyés={len(already_sent)} non_configurés={len(not_ready)}")\n    for job in not_ready:\n        reasons = ", ".join(job.get("not_ready_reasons", [])) or "configuration incomplète"\n        print(f"[warning] {job['code']} — {job['name']} — {reasons}")\n\n    if cfg["dry_run"]:\n''',
    "not-ready diagnostics",
)
wa_path.write_text(wa, encoding="utf-8")


# 4) Documentation: record the v3.10.9 safety gate and optional WABA secret
setup_path = Path("WHATSAPP_AUTOMATION_SETUP.md")
setup = setup_path.read_text(encoding="utf-8")
if "WHATSAPP_WABA_ID" not in setup:
    setup = replace_once(
        setup,
        "- `WHATSAPP_PHONE_NUMBER_ID`\n- `WHATSAPP_ACCESS_TOKEN`\n",
        "- `WHATSAPP_PHONE_NUMBER_ID`\n- `WHATSAPP_ACCESS_TOKEN`\n- `WHATSAPP_WABA_ID` (recommandé pour vérifier automatiquement le statut des templates Meta)\n",
        "WABA secret documentation",
    )
appendix = '''\n\n## Garde de sécurité v3.10.9\n\nL'envoi automatique de production est volontairement **en pause** tant que le contrôle de readiness n'est pas complet. Le moteur et les dry-runs restent disponibles, ainsi que l'envoi assisté depuis l'application.\n\nLe workflow `whatsapp-readiness.yml` vérifie sans envoyer de message :\n\n- l'accès au numéro expéditeur Meta ;\n- la configuration du prochain dimanche publié ;\n- le numéro, le consentement et l'activation pour chaque membre programmé ;\n- l'absence de programme annulé dans la cible ;\n- et, si `WHATSAPP_WABA_ID` est configuré, le statut et la langue des deux templates Meta.\n\nLa présence d'un contact non prêt ne doit jamais être contournée en inventant un consentement ou un numéro. Le contact est simplement exclu des envois jusqu'à régularisation.\n\nLes textes éditables dans Streamlit servent à l'envoi assisté `wa.me`. Les templates utilisés par la Cloud API sont gérés et approuvés séparément dans Meta ; modifier un texte Streamlit ne modifie pas le template Meta.\n'''
if "## Garde de sécurité v3.10.9" not in setup:
    setup += appendix
setup_path.write_text(setup, encoding="utf-8")

print("v3.10.9 source patch applied")

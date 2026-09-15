from pathlib import Path

path = Path(__file__).resolve().parents[1] / "liturgie_app.py"
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: attendu 1 occurrence, trouvé {count}")
    text = text.replace(old, new, 1)


replace_once(
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.14-anticipated-mass-references"',
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.15-weekend-whatsapp-readiness"',
    "version v3.10.15",
)
replace_once(
    '_wa_c1.metric("Dimanches futurs", _wa_summary["sundays"])',
    '_wa_c1.metric("Célébrations futures", _wa_summary["celebrations"])',
    "métrique célébrations futures",
)
replace_once(
    '"Tous les contacts des programmes futurs sont prêts. "',
    '"Tous les contacts des célébrations futures du week-end sont prêts. "',
    "message readiness complète",
)
replace_once(
    '"Activation refus\\xe9e : tous les contacts des programmes futurs doivent d\\\'abord \\xeatre pr\\xeats. "',
    '"Activation refus\\xe9e : tous les contacts des célébrations futures du week-end doivent d\\\'abord \\xeatre pr\\xeats. "',
    "message activation refusée",
)
replace_once(
    '        _wa_rows = future_readiness_rows(state, reference_day=_now.date())\\n',
    '        # Readiness sécurité : samedi + dimanche. Les envois automatiques du samedi restent désactivés.\\n        _wa_rows = future_readiness_rows(state, reference_day=_now.date())\\n',
    "commentaire sécurité week-end",
)
replace_once(
    '            with st.expander("Voir tous les membres programmés et leur état WhatsApp", expanded=False):\\n',
    '            st.caption("Le contrôle de préparation couvre samedi + dimanche ; les rappels automatiques du samedi ne sont pas encore activés.")\\n\\n            with st.expander("Voir tous les membres programmés et leur état WhatsApp", expanded=False):\\n',
    "caption week-end",
)

path.write_text(text, encoding="utf-8")
print("v3.10.15 weekend readiness UI patch applied")

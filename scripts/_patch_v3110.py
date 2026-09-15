from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


path = Path("liturgie_app.py")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.9-whatsapp-readiness"',
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.10-whatsapp-contact-readiness"',
    "version marker",
)

import_marker = '''from state_store import (
    StateConflictError, StateNotFoundError, load_state_record, save_state_if_revision,
)

'''
text = replace_once(
    text,
    import_marker,
    import_marker + '''from whatsapp_readiness import (
    display_rows as whatsapp_display_rows,
    future_readiness_rows,
    readiness_summary,
)

''',
    "WhatsApp readiness imports",
)

runtime_tail = '''    return source


_original_tabs = st.tabs
'''
readiness_patch = '''    source = _replace_once(
        source,
        '        with st.expander("📱 Numéros et consentements", expanded=False):\\n',
        '''        st.markdown("### 🧭 Préparation à l'automatisation WhatsApp")
        _wa_rows = future_readiness_rows(state, reference_day=_now.date())
        _wa_summary = readiness_summary(_wa_rows)
        if _wa_rows:
            _wa_c1, _wa_c2, _wa_c3, _wa_c4 = st.columns(4)
            _wa_c1.metric("Dimanches futurs", _wa_summary["sundays"])
            _wa_c2.metric("Affectations", _wa_summary["assignments"])
            _wa_c3.metric("Prêtes", _wa_summary["ready"])
            _wa_c4.metric("À compléter", _wa_summary["blocked"])

            _wa_blocked = [row for row in _wa_rows if not row.get("ready")]
            if _wa_blocked:
                _wa_names = ", ".join(_wa_summary["blocker_names"])
                st.warning(
                    f"Automatisation maintenue en pause : {_wa_summary['blocked']} affectation(s) "
                    f"concernent des contacts incomplets. Membres à régulariser : {_wa_names}."
                )
                st.dataframe(
                    whatsapp_display_rows(_wa_blocked),
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(
                    "Renseignez uniquement un numéro réel et cochez le consentement après accord explicite du membre. "
                    "Aucune activation n'est faite automatiquement."
                )
            else:
                st.success(
                    "Tous les contacts des programmes futurs sont prêts. "
                    "La réactivation automatique reste conditionnée au readiness GitHub/Meta."
                )

            with st.expander("Voir tous les membres programmés et leur état WhatsApp", expanded=False):
                st.dataframe(
                    whatsapp_display_rows(_wa_rows),
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.info("Aucun programme futur actif n'est publié : aucune readiness WhatsApp à contrôler.")

        with st.expander("📱 Numéros et consentements", expanded=False):
''',
        "tableau de readiness WhatsApp",
    )

    source = _replace_once(
        source,
        '''    st.subheader("🤖 Automatisation future")
    st.write(
        "L'application est techniquement préparée pour une automatisation complète des rappels. "
        "Cette évolution nécessitera un accès officiel à WhatsApp Business API, des modèles "
        "de messages approuvés et un ordonnanceur externe fiable pour déclencher les envois "
        "aux heures prévues."
    )
    st.success(
        "Sécurité actuelle : l'automatisation complète est désactivée. "
        "Aucun rappel WhatsApp ne peut partir automatiquement à l'insu du responsable."
    )
''',
        '''    st.subheader("🤖 Automatisation Cloud API")
    st.write(
        "Le moteur WhatsApp Cloud API est piloté par GitHub Actions. Avant toute réactivation, "
        "un contrôle de readiness vérifie le numéro expéditeur Meta, les templates approuvés "
        "et la configuration des contacts réellement programmés."
    )
    st.success(
        "Mode de sécurité actuel : l'envoi automatique reste en pause tant que le readiness complet "
        "n'est pas vert. Les rappels assistés et les simulations restent disponibles."
    )
''',
        "guide WhatsApp actuel",
    )

''' + runtime_tail
text = replace_once(text, runtime_tail, readiness_patch, "runtime tail")

namespace_marker = '''        "save_state_if_revision": save_state_if_revision,
'''
text = replace_once(
    text,
    namespace_marker,
    namespace_marker
    + '''        "future_readiness_rows": future_readiness_rows,
        "readiness_summary": readiness_summary,
        "whatsapp_display_rows": whatsapp_display_rows,
''',
    "runtime namespace",
)

path.write_text(text, encoding="utf-8")
print("v3.10.10 wrapper patch applied")

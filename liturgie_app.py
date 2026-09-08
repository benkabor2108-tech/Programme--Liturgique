"""Entrée Streamlit du Programme liturgique.

Le cœur historique de l'application reste dans ``liturgie_app_core.py``.
Cette fine couche ajoute de manière isolée l'onglet privé de rédaction des
monitions et prières universelles, sans modifier la logique de programmation.
"""
from pathlib import Path

import streamlit as st

from liturgical_drafts import persist_liturgical_state, render_liturgical_drafts_tab

APP_VERSION_OVERRIDE = "2026.09.08-persistant-supabase-v3.10.2-monitions-pu-save-word-fix"
CORE_PATH = Path(__file__).with_name("liturgie_app_core.py")


def _runtime_core_source():
    source = CORE_PATH.read_text(encoding="utf-8")

    old_version = 'APP_VERSION = "2026.09.02-persistant-supabase-v3.9.6-correctif-cycle15"'
    if old_version not in source:
        raise RuntimeError(
            "Version du cœur de l'application inattendue. La couche Monitions/P.U. doit être revalidée avant exécution."
        )
    source = source.replace(old_version, f'APP_VERSION = "{APP_VERSION_OVERRIDE}"', 1)

    state_marker = '        "whatsapp_send_log": {},\n        "audit_log": [],\n'
    if source.count(state_marker) < 2:
        raise RuntimeError("Structure d'état inattendue : impossible d'activer la persistance des brouillons liturgiques.")
    source = source.replace(
        state_marker,
        '        "whatsapp_send_log": {},\n        "liturgical_drafts": {},\n        "audit_log": [],\n',
        2,
    )

    raw_keys = (
        '    for key in ["reading_cycle_seen", "reading_pairs", "monition_pairs", "next_first_language", '
        '"history", "attendance", "attendance_ignored", "auth_security", "whatsapp_send_log", "audit_log"]:\n'
    )
    if raw_keys not in source:
        raise RuntimeError("Migration d'état inattendue : liturgical_drafts ne peut pas être conservé.")
    source = source.replace(
        raw_keys,
        '    for key in ["reading_cycle_seen", "reading_pairs", "monition_pairs", "next_first_language", '
        '"history", "attendance", "attendance_ignored", "auth_security", "whatsapp_send_log", "liturgical_drafts", "audit_log"]:\n',
        1,
    )
    return source


_original_tabs = st.tabs


def _tabs_with_private_liturgical_drafts(labels, *args, **kwargs):
    labels = list(labels)
    expected = ["🏠 Accueil", "ℹ️ Guide", "✨ Générer", "👥 Membres", "📋 Présences", "🕘 Historique"]
    is_main_tabs = labels == expected
    is_principal = st.session_state.get("auth_role") == "principal"

    if not (is_main_tabs and is_principal):
        return _original_tabs(labels, *args, **kwargs)

    extended = labels[:3] + ["📝 Monitions & P.U."] + labels[3:]
    containers = _original_tabs(extended, *args, **kwargs)

    with containers[3]:
        try:
            state = st.session_state.get("liturgie_state")
            if isinstance(state, dict):
                persist_callback = lambda show_success=False: persist_liturgical_state(
                    state,
                    show_success=show_success,
                )
                render_liturgical_drafts_tab(state, persist_callback=persist_callback)
            else:
                st.warning("L'état de l'application n'est pas encore chargé.")
        except Exception as exc:
            st.error(f"Module Monitions/P.U. indisponible : {exc}")

    # Le cœur historique attend toujours exactement six conteneurs.
    return containers[:3] + containers[4:]


def main():
    source = _runtime_core_source()
    st.tabs = _tabs_with_private_liturgical_drafts
    namespace = {
        "__name__": "__main__",
        "__file__": str(CORE_PATH),
        "__package__": None,
    }
    try:
        exec(compile(source, str(CORE_PATH), "exec"), namespace, namespace)
    finally:
        st.tabs = _original_tabs


main()

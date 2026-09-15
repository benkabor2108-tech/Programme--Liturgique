"""Entrée Streamlit du Programme liturgique.

Le cœur historique de l'application reste dans ``liturgie_app_core.py``.
Cette couche ajoute de manière isolée l'onglet privé Monitions/P.U. et la
protection non destructive de l'historique, sans reconstruire le cœur.
"""
from copy import deepcopy
from pathlib import Path

import streamlit as st

from history_protection import (
    active_history_rows,
    cancel_latest_month_non_destructive,
    cancelled_history_rows,
    latest_active_history_month,
)
from liturgical_drafts import persist_liturgical_state, render_liturgical_drafts_tab
from state_store import (
    StateConflictError, StateNotFoundError, load_state_record, save_state_if_revision,
)

APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.7-supabase-hardened"
CORE_PATH = Path(__file__).with_name("liturgie_app_core.py")


def _replace_once(source, old, new, label):
    if source.count(old) != 1:
        raise RuntimeError(
            f"Structure du cœur inattendue pour {label}. "
            "La protection historique doit être revalidée avant exécution."
        )
    return source.replace(old, new, 1)


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

    persistence_start = source.find("def load_remote_state():\n")
    persistence_end = source.find("\n\ndef as_date(value):", persistence_start)
    if persistence_start < 0 or persistence_end < 0:
        raise RuntimeError(
            "Structure du cœur inattendue : bloc de persistance Supabase introuvable."
        )
    source = source[:persistence_start] + '''def load_remote_state():
    url, api_key, state_key = supabase_config()
    if not (url and api_key):
        st.session_state.supabase_revision = None
        return None, "Secrets Supabase absents"

    try:
        raw_state, revision, _updated_at = load_state_record(
            url,
            api_key,
            state_key,
            timeout=15,
        )
        st.session_state.supabase_revision = revision
        st.session_state.supabase_conflict = False
        return normalize_state(raw_state), f"État chargé depuis Supabase · révision {revision}"
    except StateNotFoundError:
        st.session_state.supabase_revision = None
        return None, "Aucun état distant enregistré"
    except Exception as exc:
        return None, f"Lecture Supabase impossible : {exc}"


def save_remote_state(state):
    url, api_key, state_key = supabase_config()
    if not (url and api_key):
        return False, "Secrets Supabase absents"

    expected_revision = st.session_state.get("supabase_revision")
    if expected_revision is None:
        st.session_state.supabase_conflict = True
        return False, (
            "Révision Supabase inconnue. Rechargez l'état distant avant toute nouvelle sauvegarde."
        )

    try:
        new_revision = save_state_if_revision(
            url,
            api_key,
            state_key,
            state,
            expected_revision,
            timeout=20,
        )
        st.session_state.supabase_revision = new_revision
        st.session_state.supabase_conflict = False
        return True, f"Sauvegardé dans Supabase · révision {new_revision}"
    except StateConflictError:
        st.session_state.supabase_conflict = True
        return False, (
            "Conflit de sauvegarde : une autre session ou automatisation a modifié les données depuis votre dernière lecture. "
            "Aucune donnée distante n'a été écrasée. Rechargez depuis Supabase avant de reprendre vos modifications."
        )
    except Exception as exc:
        return False, f"Sauvegarde Supabase impossible : {exc}"


def ensure_loaded():
    if "liturgie_state" in st.session_state:
        return
    remote, message = load_remote_state()
    st.session_state.liturgie_state = remote if remote else initial_state()
    st.session_state.supabase_message = message
    st.session_state.last_rows = []


def persist(show_success=False):
    ok, message = save_remote_state(st.session_state.liturgie_state)
    st.session_state.supabase_message = message
    if ok:
        if show_success:
            st.success(message)
    else:
        if st.session_state.get("supabase_conflict", False):
            st.error(message)
            st.warning(
                "Utilisez « Actualiser depuis Supabase » avant toute autre modification. "
                "La sauvegarde refusée reste seulement dans cette session et n'a pas écrasé la base."
            )
        elif show_success:
            st.error(message)
    return ok
''' + source[persistence_end:]

    source = _replace_once(
        source,
        '''def latest_history_month(history):
    """Retourne (année, mois, nombre de célébrations) pour le dernier mois de l'historique."""
    dated = []
    for row in history or []:
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except Exception:
            continue
        dated.append(day)
    if not dated:
        return None
    latest = max(dated)
    count = sum(1 for d in dated if d.year == latest.year and d.month == latest.month)
    return latest.year, latest.month, count
''',
        '''def latest_history_month(history):
    """Retourne le dernier mois actif ; les versions annulées restent archivées."""
    return latest_active_history_month(history)
''',
        "dernier mois actif",
    )

    source = _replace_once(
        source,
        '''    if any(row.get("date") in month_dates for row in state["history"]):
        raise RuntimeError(
            "Ce mois figure déjà dans l'historique. Supprimez d'abord ce mois de l'historique ou choisissez un autre mois."
        )
''',
        '''    if any(row.get("date") in month_dates for row in active_history_rows(state["history"])):
        raise RuntimeError(
            "Ce mois figure déjà parmi les programmes actifs. "
            "Utilisez l'annulation non destructive dans l'onglet Historique avant de générer une nouvelle version."
        )
''',
        "contrôle des doublons mensuels",
    )

    source = _replace_once(
        source,
        '    for row in sorted((history or []), key=row_day):\n',
        '    for row in sorted(active_history_rows(history), key=row_day):\n',
        "reconstruction de rotation",
    )

    source = _replace_once(
        source,
        '''def undo_last_month(state):
    """Supprime le mois le plus récent de l'historique et reconstruit la rotation restante."""
    info = latest_history_month(state.get("history", []))
    if not info:
        return False, "Aucun mois à annuler.", state
    year, month, count = info
    remaining = []
    for row in state.get("history", []):
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except Exception:
            remaining.append(row)
            continue
        if not (day.year == year and day.month == month):
            remaining.append(row)
    rebuilt = rebuild_rotation_from_history(state, remaining)
    return True, f"{MONTHS[month - 1]} {year} annulé ({count} célébration(s)). Rotation reconstruite.", rebuilt


def full_fresh_start(state):
    """Nouveau départ : conserve membres/noms/statuts mais efface historique et rotation."""
    fresh = rotation_reset_keep_names(state)
    fresh["version"] = APP_VERSION
    return fresh
''',
        '''def undo_last_month(state, reason=""):
    """Annule le dernier mois actif sans supprimer aucune ligne historique."""
    return cancel_latest_month_non_destructive(
        state,
        rebuild_rotation_from_history,
        MONTHS,
        actor="Administrateur principal",
        reason=reason,
        timestamp=now_ouaga().isoformat(),
    )


def full_fresh_start(state):
    """Compatibilité : toute remise à zéro destructive est neutralisée."""
    protected = deepcopy(state)
    protected.setdefault("audit_log", []).append({
        "type": "destructive_history_reset_blocked",
        "timestamp": now_ouaga().isoformat(),
        "actor": "Administrateur principal",
    })
    return protected
''',
        "neutralisation des opérations destructives",
    )

    source = _replace_once(
        source,
        '    c3.metric("Célébrations validées", len(state.get("history", [])))\n',
        '    c3.metric("Célébrations validées", len(active_history_rows(state.get("history", []))))\n',
        "compteur de célébrations actives",
    )

    source = _replace_once(
        source,
        '''        history = state.get("history", [])
        latest = latest_history_month(history)
''',
        '''        history = active_history_rows(state.get("history", []))
        latest = latest_history_month(history)
''',
        "programme publié en consultation",
    )

    source = _replace_once(
        source,
        '''with history_tab:
    st.subheader("🕘 Historique")
    history = state.get("history", [])
    if history:
        show_mobile_program(history)
        with st.expander("🖥️ Tableau complet de l'historique"):
            st.dataframe(flat_rows(history), use_container_width=True, hide_index=True)
        h_xlsx, h_pdf = st.columns(2)
        with h_xlsx:
            st.download_button(
                "📊 Historique Excel",
                data=xlsx_bytes(history, state, title="Historique du programme liturgique"),
                file_name="historique_programme_liturgique.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with h_pdf:
            st.download_button(
                "🖨️ Historique PDF",
                data=pdf_bytes(history, title="Historique du programme liturgique"),
                file_name="historique_programme_liturgique.pdf",
                mime="application/pdf",
            )
    else:
        st.info("Aucune célébration enregistrée pour le moment.")

''',
        '''with history_tab:
    st.subheader("🕘 Historique")
    full_history = state.get("history", [])
    history = active_history_rows(full_history)
    cancelled_history = cancelled_history_rows(full_history)
    if history:
        show_mobile_program(history)
        with st.expander("🖥️ Tableau complet de l'historique actif"):
            st.dataframe(flat_rows(history), use_container_width=True, hide_index=True)
        h_xlsx, h_pdf = st.columns(2)
        with h_xlsx:
            st.download_button(
                "📊 Historique actif Excel",
                data=xlsx_bytes(history, state, title="Historique actif du programme liturgique"),
                file_name="historique_actif_programme_liturgique.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with h_pdf:
            st.download_button(
                "🖨️ Historique actif PDF",
                data=pdf_bytes(history, title="Historique actif du programme liturgique"),
                file_name="historique_actif_programme_liturgique.pdf",
                mime="application/pdf",
            )
    else:
        st.info("Aucune célébration active enregistrée pour le moment.")

    if cancelled_history:
        with st.expander(
            f"🗃️ Archives annulées — {len(cancelled_history)} célébration(s) conservée(s)",
            expanded=False,
        ):
            st.info(
                "Ces lignes ont été annulées pour la programmation active, mais restent conservées "
                "dans l'historique et dans les sauvegardes."
            )
            archive_rows = []
            for archived in cancelled_history:
                item = flat_row(archived)
                item["Annulé le"] = archived.get("cancelled_at", "")
                item["Motif"] = archived.get("cancel_reason", "")
                archive_rows.append(item)
            st.dataframe(archive_rows, use_container_width=True, hide_index=True)

''',
        "affichage séparé des archives annulées",
    )

    source = _replace_once(
        source,
        '''    if IS_ADMIN:
        st.divider()
        st.subheader("Maintenance")
        st.caption("Avant toute opération de maintenance, téléchargez la sauvegarde JSON située plus bas.")

        latest_info = latest_history_month(state.get("history", []))
        if latest_info:
            last_year, last_month, last_count = latest_info
            st.info(
                f"Dernier mois enregistré : {MONTHS[last_month - 1]} {last_year} "
                f"({last_count} célébration(s))."
            )
            with st.form("undo_last_month_form"):
                confirm_undo = st.checkbox(
                    f"Je confirme l'annulation de {MONTHS[last_month - 1]} {last_year}."
                )
                undo_clicked = st.form_submit_button("↩️ Annuler le dernier mois")
            if undo_clicked:
                if not confirm_undo:
                    st.error("Cochez la confirmation avant d'annuler le dernier mois.")
                else:
                    ok, message, rebuilt = undo_last_month(state)
                    if ok:
                        st.session_state.liturgie_state = rebuilt
                        st.session_state.last_rows = []
                        if persist(show_success=False):
                            st.success(message)
                            st.rerun()
                    else:
                        st.error(message)
        else:
            st.info("Aucun mois n'est actuellement enregistré dans l'historique.")

        st.divider()
        st.markdown("### 🧹 Nouveau départ complet")
        st.warning(
            "Cette opération efface TOUT l'historique des célébrations et remet tous les compteurs, "
            "dates de passage, prochaines fonctions et binômes à zéro. La liste des membres, leurs noms, "
            "leurs statuts Actif/Absent et les feuilles de présence sont conservés."
        )
        with st.form("full_reset_form"):
            confirm_full_reset = st.checkbox(
                "Je confirme vouloir effacer tout l'historique et recommencer la programmation à zéro."
            )
            full_reset_clicked = st.form_submit_button("🧹 Réinitialiser pour un nouveau départ")
        if full_reset_clicked:
            if not confirm_full_reset:
                st.error("Cochez la confirmation avant la réinitialisation complète.")
            else:
                st.session_state.liturgie_state = full_fresh_start(state)
                st.session_state.last_rows = []
                if persist(show_success=False):
                    st.success("Nouveau départ effectué : historique et rotation remis à zéro. Membres conservés.")
                    st.rerun()

        state_bytes = json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            "⬇️ Télécharger une sauvegarde JSON",
            data=state_bytes,
            file_name="etat_programme_liturgique.json",
            mime="application/json",
        )
    else:
        st.caption("Maintenance et sauvegarde technique réservées à l'administrateur.")
''',
        '''    if IS_ADMIN:
        st.divider()
        st.subheader("🛡️ Protection de l'historique")
        st.success(
            "Mode non destructif actif : aucune opération de maintenance ne supprime les programmes déjà enregistrés."
        )

        latest_info = latest_history_month(state.get("history", []))
        if latest_info:
            last_year, last_month, last_count = latest_info
            st.info(
                f"Dernier mois actif : {MONTHS[last_month - 1]} {last_year} "
                f"({last_count} célébration(s))."
            )
            with st.form("cancel_last_month_non_destructive_form"):
                cancellation_reason = st.text_input(
                    "Motif de l'annulation",
                    placeholder="Ex. programme remplacé après changement pastoral",
                )
                confirm_undo = st.checkbox(
                    f"Je confirme marquer {MONTHS[last_month - 1]} {last_year} comme annulé, sans supprimer son historique."
                )
                undo_clicked = st.form_submit_button("🗃️ Annuler sans supprimer")
            if undo_clicked:
                if not confirm_undo:
                    st.error("Cochez la confirmation avant d'annuler ce mois.")
                elif not str(cancellation_reason).strip():
                    st.error("Indiquez le motif de l'annulation.")
                else:
                    ok, message, rebuilt = undo_last_month(state, reason=cancellation_reason)
                    if ok:
                        st.session_state.liturgie_state = rebuilt
                        st.session_state.last_rows = []
                        if persist(show_success=False):
                            st.success(message)
                            st.rerun()
                    else:
                        st.error(message)
        else:
            st.info("Aucun mois actif n'est actuellement enregistré.")

        st.info(
            "La fonction « Nouveau départ complet » a été désactivée. "
            "Pour corriger un programme, annulez-le sans suppression puis générez sa nouvelle version."
        )

        state_bytes = json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            "⬇️ Télécharger une sauvegarde JSON complète",
            data=state_bytes,
            file_name="etat_programme_liturgique.json",
            mime="application/json",
        )
    else:
        st.caption("Maintenance et sauvegarde technique réservées à l'administrateur.")
''',
        "maintenance historique non destructive",
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
        "deepcopy": deepcopy,
        "active_history_rows": active_history_rows,
        "cancel_latest_month_non_destructive": cancel_latest_month_non_destructive,
        "cancelled_history_rows": cancelled_history_rows,
        "latest_active_history_month": latest_active_history_month,
        "StateConflictError": StateConflictError,
        "StateNotFoundError": StateNotFoundError,
        "load_state_record": load_state_record,
        "save_state_if_revision": save_state_if_revision,
    }
    try:
        exec(compile(source, str(CORE_PATH), "exec"), namespace, namespace)
    finally:
        st.tabs = _original_tabs


main()

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

from whatsapp_readiness import (
    display_rows as whatsapp_display_rows,
    future_readiness_rows,
    readiness_summary,
)
from whatsapp_reminder_preview import (
    display_rows as reminder_preview_display_rows,
    preview_rows as reminder_preview_rows,
    preview_summary as reminder_preview_summary,
)
from weekend_generation import (
    liturgical_reference_day,
    liturgical_reference_days,
    service_day_label,
    weekend_service_days,
)

APP_VERSION_OVERRIDE = "2026.09.16-persistant-supabase-v3.10.18-saturday-combined-ministry"
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

    # v3.10.13 : la génération mensuelle couvre désormais samedi + dimanche.
    source = _replace_once(
        source,
        '    month_dates = {d.isoformat() for d in sundays(year, month)}\n',
        '    month_dates = {d.isoformat() for d in weekend_service_days(year, month)}\n',
        "dates de génération samedi + dimanche",
    )
    source = _replace_once(
        source,
        '    month_days = sundays(year, month)\n',
        '    month_days = weekend_service_days(year, month)\n',
        "jours du mois samedi + dimanche",
    )
    source = _replace_once(
        source,
        '    for sunday in sundays(year, month):\n',
        '    for sunday in weekend_service_days(year, month):\n',
        "boucle de génération samedi + dimanche",
    )
    source = _replace_once(
        source,
        '            "date": sunday.isoformat(),\n            "Dimanche": sunday.strftime("%d/%m/%Y"),\n',
        '            "date": sunday.isoformat(),\n'
        '            "jour_service": "samedi" if sunday.weekday() == 5 else "dimanche",\n'
        '            "date_reference": liturgical_reference_day(sunday).isoformat(),\n'
        '            "Dimanche": f"{service_day_label(sunday)} {sunday.strftime(\'%d/%m/%Y\')}",\n',
        "libellé samedi ou dimanche",
    )
    source = _replace_once(
        source,
        '        month_sundays = sundays(year, month)\n',
        '        month_sundays = weekend_service_days(year, month)\n',
        "sélection des célébrations du week-end",
    )
    source = _replace_once(
        source,
        '''def fetch_month_aelf_refs(dates, zone):
    refs = {}
    errors = {}
    for day in dates:
        try:
            refs[day.isoformat()] = fetch_aelf_refs(day.isoformat(), zone)
        except Exception as exc:
            errors[day.isoformat()] = str(exc)
    return refs, errors
''',
        '''def fetch_month_aelf_refs(dates, zone):
    refs = {}
    errors = {}
    for day in dates:
        reference_day = liturgical_reference_day(day)
        try:
            item = dict(fetch_aelf_refs(reference_day.isoformat(), zone))
            item["reference_date"] = reference_day.isoformat()
            if day.weekday() == 5:
                item["source"] = f"{item.get('source', 'AELF')} · messe anticipée du dimanche"
            refs[day.isoformat()] = item
        except Exception as exc:
            errors[day.isoformat()] = str(exc)
    return refs, errors
''',
        "AELF samedi = dimanche suivant",
    )
    source = _replace_once(
        source,
        '''def parse_refs(text, dates):
    refs = {d.isoformat(): {"r1": "", "r2": "", "ev": ""} for d in dates}
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) >= 4 and parts[0] in refs:
            refs[parts[0]] = {"r1": parts[1], "r2": parts[2], "ev": parts[3], "source": "Saisie manuelle"}
    return refs
''',
        '''def parse_refs(text, dates):
    dates = list(dates)
    raw_refs = {}
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) >= 4:
            raw_refs[parts[0]] = {"r1": parts[1], "r2": parts[2], "ev": parts[3], "source": "Saisie manuelle"}

    refs = {}
    for day in dates:
        reference_day = liturgical_reference_day(day)
        item = raw_refs.get(reference_day.isoformat())
        # Compatibilité avec une ancienne saisie où le samedi avait sa propre ligne.
        if item is None:
            item = raw_refs.get(day.isoformat())
        item = dict(item or {"r1": "", "r2": "", "ev": "", "source": "Saisie manuelle"})
        item["reference_date"] = reference_day.isoformat()
        if day.weekday() == 5:
            item["source"] = "Saisie manuelle · messe anticipée du dimanche"
        refs[day.isoformat()] = item
    return refs
''',
        "saisie manuelle samedi = dimanche suivant",
    )
    source = _replace_once(
        source,
        '            st.info("📖 Les références des dimanches seront récupérées automatiquement depuis l\'API AELF au moment de la génération. Aucun copier-coller n\'est nécessaire.")\n',
        '            st.info("📖 Le samedi soir est traité comme messe anticipée : mêmes références bibliques que le dimanche qui suit, y compris si ce dimanche est dans le mois suivant. Les 3 intervenants du samedi sont tous mooréphones : 1re lecture, 2e lecture, puis une même personne pour Monition/P.U. + Annonces.")\n',
        "texte AELF week-end",
    )
    source = _replace_once(
        source,
        '                            "Dimanche": d.strftime("%d/%m/%Y"),\n',
        '                            "Célébration": f"{service_day_label(d)} {d.strftime(\'%d/%m/%Y\')}",\n'
        '                            "Références du": liturgical_reference_day(d).strftime(\'%d/%m/%Y\'),\n',
        "prévisualisation AELF week-end",
    )
    source = _replace_once(
        source,
        '    st.caption("📱 Vue téléphone : ouvrez un dimanche pour voir toutes les références et fonctions sans défilement horizontal.")\n',
        '    st.caption("📱 Vue téléphone : ouvrez une célébration pour voir toutes les références et fonctions sans défilement horizontal.")\n',
        "libellé vue téléphone",
    )
    source = _replace_once(
        source,
        '            Paragraph("Dimanche", header_style),\n',
        '            Paragraph("Célébration", header_style),\n',
        "en-tête PDF célébration",
    )
    source = _replace_once(
        source,
        """def next_published_sunday(state, reference_day=None):
    reference_day = reference_day or now_ouaga().date()
    candidates = []
    for row in state.get("history", []) or []:
        if not is_history_row_active(row):
            continue
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except Exception:
            continue
        if day >= reference_day:
            candidates.append((day, row))
    return min(candidates, key=lambda item: item[0]) if candidates else (None, None)
""",
        """def next_published_sunday(state, reference_day=None):
    reference_day = reference_day or now_ouaga().date()
    candidates = []
    for row in state.get("history", []) or []:
        if not is_history_row_active(row):
            continue
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except Exception:
            continue
        # Les rappels WhatsApp actuels sont conçus pour le dimanche.
        # Un programme du samedi ne doit donc jamais décaler le prochain dimanche.
        if day.weekday() != 6:
            continue
        if day >= reference_day:
            candidates.append((day, row))
    return min(candidates, key=lambda item: item[0]) if candidates else (None, None)
""",
        "rappels WhatsApp réservés aux dimanches",
    )

    source = _replace_once(
        source,
        '            example = "\\n".join(f"{d.isoformat()} |  |  | " for d in month_sundays)\n            refs_text = st.text_area(\n                "AAAA-MM-JJ | 1re lecture | 2e lecture | Évangile",\n                value=example,\n                height=max(160, 38 * len(month_sundays)),\n                key=f"refs_{year}_{month}",\n            )\n',
        '            reference_days = liturgical_reference_days(month_sundays)\n            example = "\\n".join(f"{d.isoformat()} |  |  | " for d in reference_days)\n            refs_text = st.text_area(\n                "Dimanche de référence (AAAA-MM-JJ) | 1re lecture | 2e lecture | Évangile",\n                value=example,\n                height=max(160, 38 * len(reference_days)),\n                key=f"refs_{year}_{month}",\n            )\n',
        "saisie manuelle par dimanche de référence",
    )

    source = _replace_once(
        source,
        '''        f_read, m_read = choose_readers(state, sunday, rng)
        first = state["next_first_language"]
        if first == "FR":
            r1_code, r1_lang, r2_code, r2_lang = f_read, "FR", m_read, "MO"
        else:
            r1_code, r1_lang, r2_code, r2_lang = m_read, "MO", f_read, "FR"

        excluded = {f_read, m_read}
        f_mon, m_mon = choose_monitions(state, sunday, excluded, rng)
        excluded.update({f_mon, m_mon})
        f_ann = choose_announcement(state, "FR", sunday, excluded, rng)
        m_ann = choose_announcement(state, "MO", sunday, excluded, rng)

        assign(state, f_read, "LECTURE", sunday)
        assign(state, m_read, "LECTURE", sunday)
        state["reading_pairs"].append([f_read, m_read])
        assign(state, f_mon, "MONITION", sunday)
        assign(state, m_mon, "MONITION", sunday)
        state["monition_pairs"].append([f_mon, m_mon])
        assign(state, f_ann, "ANNONCE", sunday)
        assign(state, m_ann, "ANNONCE", sunday)
        state["next_first_language"] = "MO" if first == "FR" else "FR"
''',
        '''        is_saturday = sunday.weekday() == 5
        if is_saturday:
            # Messe anticipée : trois intervenants distincts, tous mooréphones.
            # Le 3e assure Monition + P.U. + Annonces.
            mo_read_pool = [
                c for c in programmable_codes(state, "MO", sunday)
                if state["people"][c]["next_role"] in (None, "LECTURE")
            ]
            if len(mo_read_pool) < 2:
                raise RuntimeError(
                    "Le samedi soir exige deux lecteurs mooréphones disponibles pour les deux lectures."
                )
            seen = set(state["reading_cycle_seen"].get("MO", []))
            rng.shuffle(mo_read_pool)
            mo_read_pool.sort(
                key=lambda c: (1 if c in seen else 0, reading_rank(state, c, sunday))
            )
            r1_code, r2_code = mo_read_pool[0], mo_read_pool[1]
            r1_lang = r2_lang = "MO"

            excluded = {r1_code, r2_code}
            mo_mon_pool = monition_pool(state, "MO", excluded, sunday)
            if not mo_mon_pool:
                raise RuntimeError(
                    "Le samedi soir exige un troisième lecteur mooréphone disponible pour la monition/P.U."
                )
            rng.shuffle(mo_mon_pool)
            m_mon = min(mo_mon_pool, key=lambda c: monition_rank(state, c, sunday))
            f_mon = None
            # Messe anticipée : la même personne assure Monition + P.U. + Annonces.
            f_ann = None
            m_ann = m_mon

            assign(state, r1_code, "LECTURE", sunday)
            assign(state, r2_code, "LECTURE", sunday)
            assign(state, m_mon, "MONITION", sunday)
            assign(state, m_mon, "ANNONCE", sunday)
            # Ne pas modifier next_first_language : l'alternance FR/MO reste pilotée par les dimanches.
        else:
            f_read, m_read = choose_readers(state, sunday, rng)
            first = state["next_first_language"]
            if first == "FR":
                r1_code, r1_lang, r2_code, r2_lang = f_read, "FR", m_read, "MO"
            else:
                r1_code, r1_lang, r2_code, r2_lang = m_read, "MO", f_read, "FR"

            excluded = {f_read, m_read}
            f_mon, m_mon = choose_monitions(state, sunday, excluded, rng)
            excluded.update({f_mon, m_mon})
            f_ann = choose_announcement(state, "FR", sunday, excluded, rng)
            m_ann = choose_announcement(state, "MO", sunday, excluded, rng)

            assign(state, f_read, "LECTURE", sunday)
            assign(state, m_read, "LECTURE", sunday)
            state["reading_pairs"].append([f_read, m_read])
            assign(state, f_mon, "MONITION", sunday)
            assign(state, m_mon, "MONITION", sunday)
            state["monition_pairs"].append([f_mon, m_mon])
            assign(state, f_ann, "ANNONCE", sunday)
            assign(state, m_ann, "ANNONCE", sunday)
            state["next_first_language"] = "MO" if first == "FR" else "FR"
''',
        "samedi trois lecteurs mooréphones",
    )
    source = _replace_once(
        source,
        '            "Monition + P.U.": f"FR : {names[f_mon]}\\nMO : {names[m_mon]}",\n',
        '            "Monition + P.U.": (f"MO : {names[m_mon]}" if is_saturday else f"FR : {names[f_mon]}\\nMO : {names[m_mon]}"),\n',
        "affichage monition samedi mooré",
    )
    source = _replace_once(
        source,
        '            "Annonces": f"FR : {names[f_ann]}\\nMO : {names[m_ann]}",\n',
        '            "Annonces": (f"MO : {names[m_mon]}" if is_saturday else f"FR : {names[f_ann]}\\nMO : {names[m_ann]}"),\n',
        "affichage annonces samedi même personne",
    )
    source = _replace_once(
        source,
        '''            "codes": {
                "r1": r1_code, "r2": r2_code,
                "f_mon": f_mon, "m_mon": m_mon,
                "f_ann": f_ann, "m_ann": m_ann,
            },
''',
        '''            "codes": (
                {
                    "r1": r1_code, "r2": r2_code,
                    "m_mon": m_mon,
                    "m_ann": m_mon,
                }
                if is_saturday else
                {
                    "r1": r1_code, "r2": r2_code,
                    "f_mon": f_mon, "m_mon": m_mon,
                    "f_ann": f_ann, "m_ann": m_ann,
                }
            ),
''',
        "codes samedi sans lecteur français",
    )
    source = _replace_once(
        source,
        '''        if r1 in current and r2 in current:
            f_read = r1 if str(r1).startswith("F") else r2
            m_read = r1 if str(r1).startswith("M") else r2
            if f_read in current and m_read in current:
                fresh["reading_pairs"].append([f_read, m_read])
''',
        '''        if r1 in current and r2 in current:
            r1_is_fr = str(r1).startswith("F")
            r2_is_fr = str(r2).startswith("F")
            # Un binôme historique n'est enregistré que pour un vrai couple FR/MO du dimanche.
            if r1_is_fr != r2_is_fr:
                f_read = r1 if r1_is_fr else r2
                m_read = r2 if r1_is_fr else r1
                fresh["reading_pairs"].append([f_read, m_read])
''',
        "reconstruction binômes samedi mooré",
    )
    source = _replace_once(
        source,
        '        if r1 in current:\n            fresh["next_first_language"] = "MO" if str(r1).startswith("F") else "FR"\n',
        '        if r1 in current and sunday.weekday() == 6:\n            fresh["next_first_language"] = "MO" if str(r1).startswith("F") else "FR"\n',
        "alternance langues pilotée par le dimanche",
    )
    state_marker = '        "whatsapp_send_log": {},\n        "audit_log": [],\n'
    if source.count(state_marker) < 2:
        raise RuntimeError("Structure d'état inattendue : impossible d'activer la persistance des brouillons liturgiques.")
    source = source.replace(
        state_marker,
        '        "whatsapp_send_log": {},\n        "whatsapp_automation_authorized": False,\n        "liturgical_drafts": {},\n        "audit_log": [],\n',
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
        '"history", "attendance", "attendance_ignored", "auth_security", "whatsapp_send_log", "whatsapp_automation_authorized", "liturgical_drafts", "audit_log"]:\n',
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
    source = _replace_once(
        source,
        '        with st.expander("📱 Numéros et consentements", expanded=False):\n',
        '        st.markdown("### 🧭 Préparation à l\'automatisation WhatsApp")\n        # Readiness sécurité : samedi + dimanche, alignée avec les rappels du mercredi et du vendredi.\n        _wa_rows = future_readiness_rows(state, reference_day=_now.date())\n        _wa_summary = readiness_summary(_wa_rows)\n        if _wa_rows:\n            _wa_c1, _wa_c2, _wa_c3, _wa_c4 = st.columns(4)\n            _wa_c1.metric("Célébrations futures", _wa_summary["celebrations"])\n            _wa_c2.metric("Affectations", _wa_summary["assignments"])\n            _wa_c3.metric("Prêtes", _wa_summary["ready"])\n            _wa_c4.metric("À compléter", _wa_summary["blocked"])\n\n            _wa_blocked = [row for row in _wa_rows if not row.get("ready")]\n            if _wa_blocked:\n                _wa_names = ", ".join(_wa_summary["blocker_names"])\n                st.warning(\n                    f"Automatisation maintenue en pause : {_wa_summary[\'blocked\']} affectation(s) "\n                    f"concernent des contacts incomplets. Membres à régulariser : {_wa_names}."\n                )\n                st.dataframe(\n                    whatsapp_display_rows(_wa_blocked),\n                    use_container_width=True,\n                    hide_index=True,\n                )\n                st.caption(\n                    "Renseignez uniquement un numéro réel et cochez le consentement après accord explicite du membre. "\n                    "Aucune activation n\'est faite automatiquement."\n                )\n            else:\n                st.success(\n                    "Tous les contacts des célébrations futures du week-end sont prêts. "\n                    "La réactivation automatique reste conditionnée au readiness GitHub/Meta."\n                )\n\n            st.caption("Le contrôle de préparation et les rappels du mercredi/vendredi couvrent samedi + dimanche.")\n\n            with st.expander("Voir tous les membres programmés et leur état WhatsApp", expanded=False):\n                st.dataframe(\n                    whatsapp_display_rows(_wa_rows),\n                    use_container_width=True,\n                    hide_index=True,\n                )\n        else:\n            st.info("Aucun programme futur actif n\'est publié : aucune readiness WhatsApp à contrôler.")\n\n        st.divider()\n        st.markdown("### 🔎 Aperçu des prochains rappels WhatsApp")\n        _wa_preview_rows = reminder_preview_rows(state, reference_day=_now.date())\n        if _wa_preview_rows:\n            _wa_preview_summary = reminder_preview_summary(_wa_preview_rows)\n            _wa_weekend_label = _wa_preview_summary["weekend_label"]\n            _wa_wednesday_label = _wa_preview_summary["wednesday_label"]\n            _wa_friday_label = _wa_preview_summary["friday_label"]\n            st.info(\n                f"Prochain week-end liturgique : dimanche {_wa_weekend_label} · "\n                f"rappel mercredi {_wa_wednesday_label} · "\n                f"rappel vendredi {_wa_friday_label}."\n            )\n            _wa_p1, _wa_p2, _wa_p3, _wa_p4 = st.columns(4)\n            _wa_p1.metric("Destinataires", _wa_preview_summary["recipients"])\n            _wa_p2.metric("Prêts", _wa_preview_summary["ready"])\n            _wa_p3.metric("Bloqués", _wa_preview_summary["blocked"])\n            _wa_p4.metric(\n                "Rappels déjà envoyés",\n                _wa_preview_summary["wednesday_sent"] + _wa_preview_summary["friday_sent"],\n            )\n            st.dataframe(\n                reminder_preview_display_rows(_wa_preview_rows),\n                use_container_width=True,\n                hide_index=True,\n            )\n            st.caption(\n                "Cet aperçu n’envoie aucun message. Il reproduit uniquement le plan "\n                "du moteur Cloud API pour le prochain week-end."\n            )\n        else:\n            st.info("Aucun prochain week-end publié à prévisualiser.")\n\n        st.divider()\n        st.markdown("### \U0001f6a6 Autorisation de l\'envoi automatique")\n        _wa_authorized = bool(state.get("whatsapp_automation_authorized", False))\n        _wa_all_ready = bool(_wa_rows) and _wa_summary.get("blocked", 0) == 0\n        if _wa_authorized:\n            st.success("Autorisation principale activ\xe9e. Le gate global reste obligatoire avant chaque envoi r\xe9el.")\n        else:\n            st.info("Autorisation principale d\xe9sactiv\xe9e : aucun rappel Cloud API ne peut partir automatiquement.")\n\n        if IS_ADMIN:\n            with st.form("whatsapp_automation_authorization_form"):\n                _wa_requested = st.checkbox(\n                    "Autoriser les rappels automatiques WhatsApp Cloud API",\n                    value=_wa_authorized,\n                    help=(\n                        "Cette autorisation ne contourne jamais les contr\xf4les de readiness. "\n                        "Si un contact programm\xe9 est incomplet, le workflow restera bloqu\xe9."\n                    ),\n                )\n                _wa_save_auth = st.form_submit_button("\U0001f4be Enregistrer l\'autorisation")\n            if _wa_save_auth:\n                if _wa_requested and not _wa_all_ready:\n                    st.error(\n                        "Activation refus\xe9e : tous les contacts des célébrations futures du week-end doivent d\'abord \xeatre pr\xeats. "\n                        "Vous pourrez r\xe9essayer d\xe8s que les num\xe9ros et consentements manquants auront \xe9t\xe9 renseign\xe9s."\n                    )\n                elif bool(_wa_requested) == _wa_authorized:\n                    st.info("Aucun changement \xe0 enregistrer.")\n                else:\n                    state["whatsapp_automation_authorized"] = bool(_wa_requested)\n                    state.setdefault("audit_log", []).append({\n                        "type": "whatsapp_automation_authorization_changed",\n                        "enabled": bool(_wa_requested),\n                        "timestamp": now_ouaga().isoformat(),\n                        "actor": "Administrateur principal",\n                    })\n                    if persist(show_success=False):\n                        if _wa_requested:\n                            st.success("Autorisation WhatsApp automatique activ\xe9e. Les gates de s\xe9curit\xe9 restent obligatoires.")\n                        else:\n                            st.success("Autorisation WhatsApp automatique d\xe9sactiv\xe9e.")\n                        st.rerun()\n\n        with st.expander("\U0001f4f1 Num\xe9ros et consentements", expanded=False):\n',
        "tableau de readiness WhatsApp",
    )

    source = _replace_once(
        source,
        '    st.subheader("🤖 Automatisation future")\n    st.write(\n        "L\'application est techniquement préparée pour une automatisation complète des rappels. "\n        "Cette évolution nécessitera un accès officiel à WhatsApp Business API, des modèles "\n        "de messages approuvés et un ordonnanceur externe fiable pour déclencher les envois "\n        "aux heures prévues."\n    )\n    st.success(\n        "Sécurité actuelle : l\'automatisation complète est désactivée. "\n        "Aucun rappel WhatsApp ne peut partir automatiquement à l\'insu du responsable."\n    )\n',
        '    st.subheader("🤖 Automatisation Cloud API")\n    st.write(\n        "Le moteur WhatsApp Cloud API est piloté par GitHub Actions. Avant toute réactivation, "\n        "un contrôle de readiness vérifie le numéro expéditeur Meta, les templates approuvés "\n        "et la configuration des contacts réellement programmés."\n    )\n    st.success(\n        "Mode de sécurité actuel : l\'envoi automatique reste en pause tant que le readiness complet "\n        "n\'est pas vert. Les rappels assistés et les simulations restent disponibles."\n    )\n',
        "guide WhatsApp actuel",
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
        "future_readiness_rows": future_readiness_rows,
        "readiness_summary": readiness_summary,
        "whatsapp_display_rows": whatsapp_display_rows,
        "reminder_preview_rows": reminder_preview_rows,
        "reminder_preview_summary": reminder_preview_summary,
        "reminder_preview_display_rows": reminder_preview_display_rows,
        "weekend_service_days": weekend_service_days,
        "service_day_label": service_day_label,
        "liturgical_reference_day": liturgical_reference_day,
        "liturgical_reference_days": liturgical_reference_days,
    }
    try:
        exec(compile(source, str(CORE_PATH), "exec"), namespace, namespace)
    finally:
        st.tabs = _original_tabs


main()

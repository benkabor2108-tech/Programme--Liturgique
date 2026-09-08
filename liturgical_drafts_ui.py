import re
from datetime import datetime, timedelta

import requests
try:
    import streamlit as st
except ImportError:
    st = None

from liturgical_drafts_schedule import availability_for, is_major_event, major_celebrations, next_sunday
from liturgical_drafts_source import build_draft, fetch_liturgical_context, liturgical_season, normalize_text
from liturgical_drafts_themes import AELF_ZONES, APP_TIMEZONE
from liturgical_drafts_word import build_word_document


INTENTION_LABELS = [
    "Église et ses responsables",
    "Responsables des nations et du Burkina Faso",
    "Monde souffrant",
    "Assemblée et personnes absentes",
]


def format_refs(context):
    refs = {}
    for key in ("r1", "ps", "r2", "ev"):
        record = context.get("parts", {}).get(key)
        refs[key] = record.get("ref", "") if isinstance(record, dict) else ""
    return refs


def persist_liturgical_state(state, show_success=False):
    """Sauvegarde l'état complet dans la même ligne Supabase que l'application principale."""
    if st is None:
        return False
    try:
        cfg = st.secrets.get("supabase", {})
        url = str(cfg.get("url", "")).rstrip("/")
        api_key = str(cfg.get("api_key", ""))
        state_key = str(cfg.get("state_key", "programme-liturgique-principal"))
    except Exception:
        url = api_key = ""
        state_key = "programme-liturgique-principal"
    if not (url and api_key):
        if show_success:
            st.error("Secrets Supabase absents.")
        return False

    endpoint = f"{url}/rest/v1/liturgie_state?on_conflict=app_key"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    payload = {"app_key": state_key, "state_json": state}
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        if hasattr(st, "session_state"):
            st.session_state.supabase_message = "Sauvegardé dans Supabase"
        if show_success:
            st.success("Sauvegardé dans Supabase")
        return True
    except Exception as exc:
        if hasattr(st, "session_state"):
            st.session_state.supabase_message = f"Sauvegarde Supabase impossible : {exc}"
        if show_success:
            st.error(f"Sauvegarde Supabase impossible : {exc}")
        return False


def saved_drafts(state):
    drafts = state.setdefault("liturgical_drafts", {})
    if not isinstance(drafts, dict):
        state["liturgical_drafts"] = {}
    return state["liturgical_drafts"]


def render_liturgical_drafts_tab(state, persist_callback=None):
    if st is None:
        raise RuntimeError("Streamlit est requis pour afficher cet onglet.")
    st.header("📝 Monitions & prières universelles")
    st.success("🔐 Espace réservé à l'administrateur principal.")
    st.write(
        "Cet espace prépare une proposition de monition introductive et de prière universelle à partir des textes liturgiques "
        "AELF de la célébration choisie. La monition mentionne obligatoirement le temps liturgique et la rédaction reprend de "
        "courtes expressions bibliques du jour. Le contenu reste éditable avant l'export Word."
    )

    now = datetime.now(APP_TIMEZONE)
    today = now.date()
    upcoming_sunday = next_sunday(today)

    mode = st.radio(
        "Type de célébration",
        ["Prochain dimanche", "Grande fête / événement", "Autre date liturgique"],
        horizontal=True,
    )

    st.caption(
        "Les grandes célébrations proposées suivent des repères du calendrier romain. "
        "Si une fête est transférée localement à une autre date, utilisez « Autre date liturgique »."
    )

    kind = "dimanche"
    celebration_hint = ""
    if mode == "Prochain dimanche":
        service_date = upcoming_sunday
        if is_major_event(service_date):
            celebration_hint = major_celebrations(service_date.year)[service_date]
    elif mode == "Grande fête / événement":
        kind = "event"
        event_map = {}
        for year in (today.year, today.year + 1):
            event_map.update(major_celebrations(year))
        upcoming = [(d, title) for d, title in sorted(event_map.items()) if d >= today - timedelta(days=1)]
        options = [d for d, _ in upcoming[:24]]
        if not options:
            st.warning("Aucune grande célébration prochaine n'a été calculée.")
            return
        service_date = st.selectbox(
            "Grande fête / événement",
            options,
            format_func=lambda d: f"{d.strftime('%d/%m/%Y')} — {event_map[d]}",
        )
        celebration_hint = event_map[service_date]
    else:
        kind = "event"
        service_date = st.date_input("Date de la célébration", value=today + timedelta(days=5), min_value=today)
        celebration_hint = st.text_input("Nom de la fête / de l'événement", value="Célébration particulière")

    availability = availability_for(service_date, kind, now=now)
    unlock_at = availability["unlock_at"]
    if availability["available"]:
        st.success(
            f"✅ Rédaction disponible depuis le {unlock_at.strftime('%d/%m/%Y à %H h %M')} "
            f"({availability['rule']})."
        )
    else:
        st.warning(
            f"⏳ Cette rédaction sera disponible à partir du {unlock_at.strftime('%d/%m/%Y à %H h %M')} "
            f"({availability['rule']})."
        )

    zone_label = st.selectbox("Calendrier AELF", list(AELF_ZONES.keys()), index=0)
    zone = AELF_ZONES[zone_label]
    draft_key = f"{service_date.isoformat()}|{zone}"

    existing = saved_drafts(state).get(draft_key)
    if isinstance(existing, dict):
        st.info("💾 Un brouillon enregistré existe déjà pour cette célébration.")

    generate_clicked = st.button(
        "✨ Préparer la proposition",
        type="primary",
        disabled=not availability["available"],
        use_container_width=True,
    )

    session_key = f"liturgical_draft_session_{draft_key}"
    context_key = f"liturgical_context_session_{draft_key}"

    if generate_clicked:
        try:
            with st.spinner("Lecture des textes liturgiques AELF et préparation de la proposition..."):
                context = fetch_liturgical_context(service_date.isoformat(), zone)
                if celebration_hint and (
                    not context.get("celebration")
                    or context.get("celebration") == "Célébration liturgique"
                ):
                    context["celebration"] = celebration_hint
                context["liturgical_season"] = liturgical_season(service_date, context.get("celebration", ""))
                draft = build_draft(context)
            st.session_state[session_key] = draft
            st.session_state[context_key] = context
        except Exception as exc:
            st.error(f"Impossible de préparer la rédaction : {exc}")

    if session_key not in st.session_state and isinstance(existing, dict):
        st.session_state[session_key] = {
            "monition": existing.get("monition", ""),
            "pu_intro": existing.get("pu_intro", ""),
            "intentions": list(existing.get("intentions", []) or []),
            "pu_conclusion": existing.get("pu_conclusion", ""),
            "response": existing.get("response", "Seigneur, nous te prions."),
            "themes": list(existing.get("themes", []) or []),
            "liturgical_season": existing.get("liturgical_season", ""),
        }
        st.session_state[context_key] = {
            "date": service_date.isoformat(),
            "zone": zone,
            "celebration": existing.get("celebration", celebration_hint or "Célébration liturgique"),
            "liturgical_season": existing.get("liturgical_season", ""),
            "parts": {
                key: {"ref": value, "text": ""}
                for key, value in (existing.get("refs", {}) or {}).items()
                if value
            },
            "source_url": existing.get("source_url", ""),
        }

    if session_key not in st.session_state:
        st.caption(
            "La proposition n'est créée qu'après activation de la date et clic sur « Préparer la proposition ». "
            "Les textes liturgiques sont récupérés directement depuis l'AELF."
        )
        return

    draft = st.session_state[session_key]
    context = st.session_state.get(context_key, {})
    refs = format_refs(context)
    celebration = context.get("celebration") or celebration_hint or "Célébration liturgique"
    season = (
        context.get("liturgical_season")
        or draft.get("liturgical_season")
        or liturgical_season(service_date, celebration)
    )

    st.subheader(f"{service_date.strftime('%d/%m/%Y')} — {celebration}")
    st.caption(f"Temps liturgique : {season}")
    st.caption(
        "Références : "
        + " · ".join(
            part for part in [
                f"1re {refs.get('r1')}" if refs.get("r1") else "",
                f"Ps {refs.get('ps')}" if refs.get("ps") else "",
                f"2e {refs.get('r2')}" if refs.get("r2") else "",
                f"Év. {refs.get('ev')}" if refs.get("ev") else "",
            ]
            if part
        )
    )
    if draft.get("themes"):
        st.caption("Thèmes repérés : " + ", ".join(draft["themes"]))

    monition = st.text_area(
        "Monition introductive",
        value=draft.get("monition", ""),
        height=260,
        key=f"monition_edit_{draft_key}",
        help="Structure : accueil → temps liturgique et célébration → thème central → courte expression biblique → invitation intérieure.",
    )

    pu_intro = st.text_area(
        "Introduction de la prière universelle",
        value=draft.get("pu_intro", ""),
        height=140,
        key=f"pu_intro_edit_{draft_key}",
    )

    intentions = []
    base_intentions = list(draft.get("intentions", []) or [])
    while len(base_intentions) < 4:
        base_intentions.append("")

    # Les anciens brouillons à six intentions restent lisibles pour ne pas perdre une correction pastorale.
    intention_count = min(6, max(4, len(base_intentions)))
    with st.expander("Intentions de la prière universelle", expanded=True):
        st.caption(
            "Structure automatique : 1) Église et responsables ; 2) responsables des nations et du Burkina Faso ; "
            "3) monde souffrant ; 4) assemblée et personnes absentes."
        )
        for idx, value in enumerate(base_intentions[:intention_count], start=1):
            label = INTENTION_LABELS[idx - 1] if idx <= len(INTENTION_LABELS) else f"Intention complémentaire {idx}"
            intentions.append(
                st.text_area(
                    f"{idx}. {label}",
                    value=value,
                    height=125,
                    key=f"pu_intention_{idx}_{draft_key}",
                )
            )

    response = st.text_input(
        "Réponse de l'assemblée",
        value=draft.get("response", "Seigneur, nous te prions."),
        key=f"pu_response_{draft_key}",
    )
    pu_conclusion = st.text_area(
        "Prière de conclusion",
        value=draft.get("pu_conclusion", ""),
        height=140,
        key=f"pu_conclusion_edit_{draft_key}",
    )

    current = {
        "monition": monition,
        "pu_intro": pu_intro,
        "intentions": intentions,
        "pu_conclusion": pu_conclusion,
        "response": response,
        "themes": draft.get("themes", []),
        "liturgical_season": season,
    }
    st.session_state[session_key] = current

    col_save, col_word = st.columns(2)
    with col_save:
        if st.button("💾 Enregistrer le brouillon", use_container_width=True):
            stamp = datetime.now(APP_TIMEZONE).isoformat()
            saved_drafts(state)[draft_key] = {
                "date": service_date.isoformat(),
                "zone": zone,
                "zone_label": zone_label,
                "celebration": celebration,
                "liturgical_season": season,
                "refs": refs,
                "source_url": context.get("source_url", ""),
                "monition": monition,
                "pu_intro": pu_intro,
                "intentions": intentions,
                "pu_conclusion": pu_conclusion,
                "response": response,
                "themes": current.get("themes", []),
                "updated_at": stamp,
            }
            state.setdefault("audit_log", []).append({
                "at": stamp,
                "actor": "Administrateur principal",
                "action": "liturgical_draft_saved",
                "date": service_date.isoformat(),
                "celebration": celebration,
            })
            if callable(persist_callback):
                if persist_callback(show_success=False):
                    st.success("Brouillon enregistré dans Supabase.")
                else:
                    st.warning("Brouillon conservé dans la session, mais la sauvegarde Supabase a échoué.")
            else:
                st.success("Brouillon enregistré dans l'état de l'application.")

    with col_word:
        meta = {
            "date_label": service_date.strftime("%d/%m/%Y"),
            "celebration": celebration,
            "liturgical_season": season,
            "refs": refs,
            "zone": zone,
            "zone_label": zone_label,
        }
        word_data = build_word_document(
            meta,
            monition,
            pu_intro,
            intentions,
            pu_conclusion,
            response,
        )
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", normalize_text(celebration)).strip("_")[:45] or "celebration"
        st.download_button(
            "📄 Télécharger le Word prêt à imprimer",
            data=word_data,
            file_name=f"monition_priere_universelle_{service_date.isoformat()}_{safe_name}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

    st.caption(
        "La proposition est une aide à la préparation. L'administrateur principal reste responsable de la relecture, "
        "de l'adaptation au contexte pastoral local et de la validation avant proclamation."
    )

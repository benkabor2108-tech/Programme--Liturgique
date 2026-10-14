"""Atelier libre des textes proclamés par les lecteurs.

Stockage additif dans l'état Supabase existant : ne touche pas aux brouillons datés.
L'atelier est appelé uniquement depuis l'onglet réservé au principal.
"""
from datetime import datetime, date
from uuid import uuid4

from liturgical_drafts_themes import APP_TIMEZONE
from liturgical_drafts_word import build_word_document
from liturgical_drafts_source import fetch_liturgical_context, build_draft

ENDING = "Prions le Seigneur."
TARGETS = {
    "Les deux textes": "both",
    "Monition uniquement": "monition",
    "Prière universelle uniquement": "priere",
}
LABELS = [
    "Pour l'Église et ses responsables",
    "Pour les responsables des nations et la paix",
    "Pour les personnes qui souffrent",
    "Pour notre communauté",
]


def normalize_intention(value):
    value = str(value or "").strip()
    if not value:
        return ""
    while value.casefold().rstrip(". !").endswith("prions le seigneur"):
        value = value[:value.casefold().rfind("prions le seigneur")].rstrip(" .!\n")
    return (value + "\n" + ENDING).strip()


def _event_theme(orientation):
    """Classe une orientation sans la transformer en fait d'actualité vérifié."""
    from liturgical_drafts_source import normalize_text
    words = normalize_text(orientation)
    if any(token in words for token in ("deplace", "victime", "malade", "deuil", "insecurite", "souffrance", "catastrophe")):
        return "suffering"
    if any(token in words for token in ("paix", "nation", "pays", "burkina", "autorite", "election")):
        return "world"
    if any(token in words for token in ("paroisse", "communaute", "famille", "anniversaire", "jubile", "jeunes")):
        return "community"
    if any(token in words for token in ("eglise", "pape", "eveque", "pretre", "vocation")):
        return "church"
    return "community"


def integrate_event(draft, orientation, target):
    """Adapte les intentions à un sujet signalé, sans recopier des consignes brutes."""
    subject = " ".join(str(orientation or "").strip().split()).rstrip(".")
    result = {"monition": str(draft.get("monition", "")).strip(),
              "intentions": list(draft.get("intentions", []))[:4]}
    if not subject:
        return result
    if len(subject) > 500:
        raise ValueError("Orientation trop longue (maximum 500 caractères).")
    theme = _event_theme(subject)
    index = {"church": 0, "world": 1, "suffering": 2, "community": 3}[theme]
    if target in ("both", "monition"):
        bridge = {
            "church": "Que notre communion avec l'Église affermisse notre foi et notre disponibilité à servir.",
            "world": "Dans un monde qui aspire à la justice et à la paix, accueillons la Parole qui éclaire nos responsabilités.",
            "suffering": "Portons dans notre cœur les personnes éprouvées, afin que cette célébration nourrisse notre compassion et notre solidarité.",
            "community": "Que cette célébration fortifie les liens fraternels de notre communauté et renouvelle notre désir de servir.",
        }
        result["monition"] = (result["monition"] + " " + bridge[theme]).strip()
    if target in ("both", "priere"):
        while len(result["intentions"]) < 4:
            result["intentions"].append("")
        prayer = {
            "church": "Pour l'Église et tous ceux qui la servent : qu'ils témoignent avec fidélité de l'Évangile et grandissent dans la communion.",
            "world": "Pour les peuples et leurs responsables : que la recherche de la paix, de la justice et du bien commun guide leurs décisions.",
            "suffering": "Pour toutes les personnes qui traversent l'épreuve : qu'elles trouvent consolation, protection et soutien auprès de leurs frères et sœurs.",
            "community": "Pour notre communauté et nos familles : que le Seigneur fasse grandir entre nous la foi, la fraternité et l'attention aux plus fragiles.",
        }
        # Le sujet reste visible pour que l'intention ne devienne pas générique.
        # Une orientation saisie n'est pas pour autant une information vérifiée.
        subject_clause = {
            "church": "Nous te confions particulièrement : ",
            "world": "Nous te confions particulièrement : ",
            "suffering": "Nous te confions particulièrement : ",
            "community": "Nous te confions particulièrement : ",
        }[theme]
        result["intentions"][index] = (
            prayer[theme].rstrip(".") + ". "
            + subject_clause + subject + ". " + ENDING
        )
    result["orientation_used"] = subject
    result["orientation_theme"] = theme
    return result


def _valid_date(value):
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def propose_orientation(orientation, target):
    """Proposition éditable, sans présenter une information non vérifiée comme un fait."""
    subject = " ".join(str(orientation or "").strip().split())
    if not subject:
        return None
    if len(subject) > 500:
        raise ValueError("Limitez l'orientation à 500 caractères.")
    monition = (
        "Frères et sœurs, rassemblés pour écouter la Parole de Dieu, "
        "ouvrons nos cœurs à sa lumière. Portons également dans notre prière "
        "cette intention particulière : " + subject.rstrip(".") + ". "
        "Que cette célébration ravive notre foi, notre espérance et notre charité."
    )
    intentions = [
        "Pour l'Église et ceux qui la servent : que le Seigneur les guide dans l'annonce de l'Évangile.",
        "Pour les responsables des nations : qu'ils recherchent la justice, la paix et le bien commun.",
        "Pour les personnes éprouvées, les malades et les déplacés : qu'elles trouvent secours et consolation.",
        "Pour notre communauté : qu'elle grandisse dans l'unité, l'accueil et la fraternité.",
    ]
    if target in ("both", "priere"):
        intentions[2] = (
            "Pour toutes les personnes concernées par cette intention particulière : "
            + subject.rstrip(".") + " ; que le Seigneur les soutienne et inspire notre solidarité."
        )
    return {"monition": monition if target in ("both", "monition") else "",
            "intentions": intentions}


def new_record():
    return {
        "id": uuid4().hex, "title": "", "date": None, "orientation": "",
        "orientation_target": "both", "monition": "", "intentions": [""] * 4,
        "status": "brouillon", "updated_at": "", "versions": [],
    }


def library(state):
    value = state.setdefault("reader_liturgical_texts", {})
    if not isinstance(value, dict):
        raise ValueError("Bibliothèque de textes invalide : aucune donnée modifiée.")
    return value


def render_free_reader_workshop(state, persist_callback=None):
    import streamlit as st

    with st.expander("✍️ Atelier libre — monitions et prières universelles", expanded=True):
        st.caption("Rédaction libre, sans date obligatoire. Réservé à l'administrateur principal.")
        records = library(state)
        choices = ["➕ Nouveau document"] + [
            key for key, _ in sorted(
                records.items(), key=lambda item: item[1].get("updated_at", ""), reverse=True
            )
        ]
        selected = st.selectbox(
            "Document à préparer ou modifier", choices,
            format_func=lambda key: key if key == choices[0] else (
                records[key].get("title") or "Sans titre"
            ) + " — " + records[key].get("status", "brouillon"),
            key="reader_workshop_selected",
        )
        record = new_record() if selected == choices[0] else dict(records[selected])
        identity = "new" if selected == choices[0] else selected
        title = st.text_input("Titre du document", value=record.get("title", ""), key=f"reader_title_{identity}")
        date_text = st.text_input(
            "Date liturgique (facultative, AAAA-MM-JJ)", value=record.get("date") or "",
            key=f"reader_date_{identity}",
        ).strip()
        orientation = st.text_area(
            "Événement particulier ou orientation de la rédaction (facultatif)",
            value=record.get("orientation", ""),
            placeholder="Ex. : intention pour les personnes déplacées ; anniversaire de la paroisse.",
            key=f"reader_orientation_{identity}", height=110,
        )
        target = st.selectbox(
            "Intégrer cette orientation dans",
            list(TARGETS),
            index=list(TARGETS.values()).index(
                record.get("orientation_target", "both")
                if record.get("orientation_target", "both") in TARGETS.values() else "both"
            ),
            key=f"reader_target_{identity}",
        )
        if orientation.strip():
            st.info(
                "Orientation à prendre en compte lors de la rédaction : "
                + ("monition et prière universelle" if TARGETS[target] == "both" else target.lower())
                + ". Vérifier tout fait d'actualité avant de l'affirmer."
            )
        liturgical_day = st.date_input(
            "Choisir le jour du calendrier liturgique",
            value=date.fromisoformat(date_text) if _valid_date(date_text) else date.today(),
            key=f"reader_calendar_{identity}",
        )
        from liturgical_drafts_themes import AELF_ZONES
        zone_label = st.selectbox("Calendrier liturgique AELF", list(AELF_ZONES), key=f"reader_zone_{identity}")
        if st.button("📖 Rédiger automatiquement à partir des lectures du jour", key=f"reader_aelf_{identity}"):
            try:
                with st.spinner("Lecture des textes AELF et préparation..."):
                    context = fetch_liturgical_context(liturgical_day.isoformat(), AELF_ZONES[zone_label])
                    proposal = integrate_event(build_draft(context), orientation, TARGETS[target])
                st.session_state[f"reader_meta_{identity}"] = {
                    "celebration": context.get("celebration", ""),
                    "date_label": liturgical_day.strftime("%d/%m/%Y"),
                    "refs": {key: (context.get("parts", {}).get(key) or {}).get("ref", "") for key in ("r1", "ps", "r2", "ev")},
                    "source_url": context.get("source_url", ""),
                }
                st.session_state[f"reader_monition_{identity}"] = proposal["monition"]
                for i, intention in enumerate(proposal["intentions"]):
                    st.session_state[f"reader_intention_{identity}_{i}"] = intention
                st.success("Rédaction préparée à partir des lectures AELF. Relisez avant validation.")
            except Exception as exc:
                st.error(f"Impossible de générer le document : {exc}")
        if st.button("✨ Proposer une rédaction à partir de cette orientation", key=f"reader_propose_{identity}"):
            try:
                proposal = propose_orientation(orientation, TARGETS[target])
                if proposal is None:
                    st.warning("Indiquez d'abord une orientation.")
                else:
                    if proposal["monition"]:
                        st.session_state[f"reader_monition_{identity}"] = proposal["monition"]
                    if TARGETS[target] in ("both", "priere"):
                        for i, intention in enumerate(proposal["intentions"]):
                            st.session_state[f"reader_intention_{identity}_{i}"] = intention
                    st.info("Proposition insérée dans les champs : relisez et adaptez-la avant validation.")
            except ValueError as exc:
                st.error(str(exc))
        monition = st.text_area(
            "Monition introductive", value=record.get("monition", ""),
            key=f"reader_monition_{identity}", height=200,
        )
        prior = list(record.get("intentions", []))[:4]
        prior += [""] * (4 - len(prior))
        intentions = [
            st.text_area(label, value=prior[i], key=f"reader_intention_{identity}_{i}", height=110)
            for i, label in enumerate(LABELS)
        ]
        st.caption("Rédaction sobre, naturelle et adaptée à la proclamation. La formule « Prions le Seigneur. » termine chaque intention renseignée. Les événements saisis servent d’orientation pastorale ; ils ne sont pas vérifiés automatiquement.")
        status = st.selectbox(
            "État", ["brouillon", "validé", "archivé"],
            index=["brouillon", "validé", "archivé"].index(
                record.get("status", "brouillon") if record.get("status") in ("brouillon", "validé", "archivé") else "brouillon"
            ), key=f"reader_status_{identity}",
        )
        if st.button("💾 Enregistrer ce document", key=f"reader_save_{identity}"):
            from datetime import date
            try:
                parsed_date = date.fromisoformat(date_text).isoformat() if date_text else None
            except ValueError:
                st.error("Date invalide. Utilisez AAAA-MM-JJ ou laissez ce champ vide.")
                return
            if status == "validé" and (not monition.strip() or any(not value.strip() for value in intentions)):
                st.error("Pour valider, renseignez la monition et les quatre intentions.")
                return
            record_id = record["id"]
            timestamp = datetime.now(APP_TIMEZONE).isoformat()
            updated = {
                **record, "id": record_id, "title": title.strip(),
                "date": parsed_date or (liturgical_day.isoformat() if st.session_state.get(f"reader_meta_{identity}") else None), "orientation": orientation.strip(),
                "orientation_target": TARGETS[target], "monition": monition.strip(),
                "intentions": intentions, "status": status, "updated_at": timestamp,
                "versions": list(record.get("versions", [])),
                "liturgical_meta": st.session_state.get(f"reader_meta_{identity}", record.get("liturgical_meta", {})),
            }
            if selected != choices[0]:
                updated["versions"].append({
                    "updated_at": record.get("updated_at", ""),
                    "monition": record.get("monition", ""),
                    "intentions": record.get("intentions", []),
                    "orientation": record.get("orientation", ""),
                })
            previous = records.get(record_id)
            records[record_id] = updated
            if callable(persist_callback) and not persist_callback(show_success=False):
                if previous is None:
                    records.pop(record_id, None)
                else:
                    records[record_id] = previous
                st.error("Enregistrement distant non confirmé ; aucune version distante écrasée.")
            else:
                st.success("Document enregistré." if callable(persist_callback) else "Document enregistré dans la session.")
                st.session_state["reader_workshop_selected"] = record_id
                st.rerun()
        word_meta = dict(record.get("liturgical_meta") or {})
        word_meta.update(st.session_state.get(f"reader_meta_{identity}") or {})
        if not word_meta.get("date_label") and date_text:
            word_meta["date_label"] = date_text
        word = build_word_document(
            word_meta, monition, "",
            [normalize_intention(value) for value in intentions], "", "",
        )
        st.download_button(
            "📄 Télécharger le texte des lecteurs (Word)", data=word,
            file_name=f"lecteurs_monition_pu_{date_text or 'sans_date'}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"reader_word_{identity}",
        )

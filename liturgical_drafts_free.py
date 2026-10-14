"""Atelier libre des textes proclamés par les lecteurs.

Stockage additif dans l'état Supabase existant : ne touche pas aux brouillons datés.
L'atelier est appelé uniquement depuis l'onglet réservé au principal.
"""
from datetime import datetime
from uuid import uuid4

from liturgical_drafts_themes import APP_TIMEZONE
from liturgical_drafts_word import build_word_document

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
        return ENDING
    while value.casefold().rstrip(". !").endswith("prions le seigneur"):
        value = value[:value.casefold().rfind("prions le seigneur")].rstrip(" .!\n")
    return (value + "\n" + ENDING).strip()


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
        st.caption("La formule « Prions le Seigneur. » est ajoutée à chaque intention dans le document exporté.")
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
            record_id = record["id"]
            timestamp = datetime.now(APP_TIMEZONE).isoformat()
            updated = {
                **record, "id": record_id, "title": title.strip(),
                "date": parsed_date, "orientation": orientation.strip(),
                "orientation_target": TARGETS[target], "monition": monition.strip(),
                "intentions": intentions, "status": status, "updated_at": timestamp,
                "versions": list(record.get("versions", [])),
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
        word = build_word_document(
            {"date_label": date_text}, monition, "",
            [normalize_intention(value) for value in intentions], "", "",
        )
        st.download_button(
            "📄 Télécharger le texte des lecteurs (Word)", data=word,
            file_name=f"lecteurs_monition_pu_{date_text or 'sans_date'}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"reader_word_{identity}",
        )

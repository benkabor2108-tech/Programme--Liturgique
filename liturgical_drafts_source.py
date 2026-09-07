import re
import unicodedata
from datetime import date
from html import unescape

import requests
try:
    import streamlit as st
except ImportError:
    st = None

from liturgical_drafts_themes import AELF_API_BASE, APP_TIMEZONE, THEME_RULES

def normalize_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def clean_html(value):
    text = unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def item_text(item):
    if not isinstance(item, dict):
        return ""
    for key in ("contenu", "texte", "text", "content"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return clean_html(value)
    return ""


def item_ref(item):
    if not isinstance(item, dict):
        return ""
    for key in ("ref", "reference", "references", "citation"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def item_label(item):
    if not isinstance(item, dict):
        return ""
    parts = []
    for key in ("type", "key", "label", "titre", "title", "nom", "name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return normalize_text(" ".join(parts)).replace("œ", "oe")


def _mass_candidates(payload):
    candidates = []
    if isinstance(payload, dict):
        masses = payload.get("messes") or payload.get("masses")
        if isinstance(masses, list):
            for mass in masses:
                if not isinstance(mass, dict):
                    continue
                lectures = mass.get("lectures") or mass.get("readings")
                if not isinstance(lectures, list):
                    continue
                name = str(mass.get("nom") or mass.get("name") or mass.get("titre") or "").strip()
                normalized = normalize_text(name)
                penalty = 0
                if any(word in normalized for word in ("veille", "vigile", "nuit", "aurore")):
                    penalty += 10
                if "jour" in normalized:
                    penalty -= 2
                candidates.append((penalty, name, lectures))
    return sorted(candidates, key=lambda x: x[0])


def _recursive_lecture_lists(payload):
    result = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("lectures", "readings") and isinstance(value, list):
                    result.append((20, "", value))
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return result


def _find_celebration_name(payload):
    preferred_keys = (
        "jour_liturgique_nom", "jour_liturgique", "nom_jour", "celebration",
        "fete", "solennite", "nom", "titre", "title", "name",
    )

    found = []

    def walk(node, depth=0):
        if depth > 4:
            return
        if isinstance(node, dict):
            for key in preferred_keys:
                value = node.get(key)
                if isinstance(value, str) and 3 <= len(value.strip()) <= 160:
                    found.append((preferred_keys.index(key), depth, value.strip()))
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for value in node[:20]:
                walk(value, depth + 1)

    walk(payload)
    if not found:
        return ""
    found.sort(key=lambda x: (x[0], x[1], len(x[2])))
    return found[0][2]


def extract_liturgical_context(payload, target_date, zone):
    candidates = _mass_candidates(payload)
    if not candidates:
        candidates = _recursive_lecture_lists(payload)
    if not candidates:
        raise RuntimeError("Aucune lecture de messe n'a été trouvée dans la réponse AELF.")

    _penalty, mass_name, lectures = candidates[0]
    parts = {"r1": None, "ps": None, "r2": None, "ev": None}
    ordinary = []

    for item in lectures:
        if not isinstance(item, dict):
            continue
        label = item_label(item)
        ref = item_ref(item)
        text = item_text(item)
        record = {"label": str(item.get("titre") or item.get("label") or item.get("type") or "").strip(), "ref": ref, "text": text}

        if any(token in label for token in ("psaume", "psalm", "cantique")):
            if parts["ps"] is None:
                parts["ps"] = record
            continue
        if any(token in label for token in ("lecture_1", "premiere_lecture", "1re_lecture", "first_reading")):
            parts["r1"] = record
        elif any(token in label for token in ("lecture_2", "deuxieme_lecture", "2e_lecture", "second_reading")):
            parts["r2"] = record
        elif "evangile" in label or "gospel" in label:
            parts["ev"] = record
        ordinary.append(record)

    sequence = [r for r in ordinary if r.get("ref") or r.get("text")]
    if parts["r1"] is None and sequence:
        parts["r1"] = sequence[0]
    if parts["ev"] is None and len(sequence) >= 2:
        parts["ev"] = sequence[-1]
    if parts["r2"] is None and len(sequence) >= 3:
        parts["r2"] = sequence[-2]

    celebration = mass_name or _find_celebration_name(payload) or "Célébration liturgique"
    return {
        "date": target_date.isoformat(),
        "zone": zone,
        "celebration": celebration,
        "parts": parts,
        "source_url": f"https://www.aelf.org/{target_date.isoformat()}/{zone}/messe",
    }


def _fetch_liturgical_context(date_iso, zone):
    target_date = date.fromisoformat(date_iso)
    url = f"{AELF_API_BASE}/messes/{date_iso}/{zone}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Programme-liturgique-Streamlit/3.10",
    }
    response = requests.get(url, headers=headers, timeout=25)
    response.raise_for_status()
    return extract_liturgical_context(response.json(), target_date, zone)


if st is not None:
    fetch_liturgical_context = st.cache_data(ttl=6 * 60 * 60, show_spinner=False)(_fetch_liturgical_context)
else:
    fetch_liturgical_context = _fetch_liturgical_context


def score_themes(text):
    normalized = normalize_text(text)
    scored = []
    for name, rule in THEME_RULES.items():
        score = 0
        for keyword in rule["keywords"]:
            needle = normalize_text(keyword)
            score += normalized.count(needle)
        if score:
            scored.append((score, name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [name for _, name in scored]


def theme_for_reading(record, fallback="foi"):
    if not isinstance(record, dict):
        return fallback
    themes = score_themes(record.get("text", ""))
    return themes[0] if themes else fallback


def overall_themes(context):
    texts = []
    for key in ("r1", "ps", "r2", "ev"):
        record = context.get("parts", {}).get(key)
        if isinstance(record, dict):
            texts.append(record.get("text", ""))
    themes = score_themes("\n".join(texts))
    if not themes:
        themes = ["foi", "charité", "espérance"]
    while len(themes) < 3:
        for fallback in ("foi", "charité", "espérance"):
            if fallback not in themes:
                themes.append(fallback)
            if len(themes) >= 3:
                break
    return themes[:3]


def reading_phrase(record, theme, part_label):
    if not isinstance(record, dict):
        return ""
    ref = record.get("ref", "").strip()
    focus = THEME_RULES[theme]["focus"]
    ref_text = f" ({ref})" if ref else ""
    if part_label == "Évangile":
        return f"Dans l'Évangile{ref_text}, le Christ nous conduit vers {focus}."
    if part_label == "Deuxième lecture":
        return f"La deuxième lecture{ref_text} nous invite à approfondir {focus}."
    return f"La première lecture{ref_text} nous fait découvrir {focus}."


def build_draft(context):
    parts = context.get("parts", {})
    r1_theme = theme_for_reading(parts.get("r1"), "alliance")
    r2_theme = theme_for_reading(parts.get("r2"), "foi")
    ev_theme = theme_for_reading(parts.get("ev"), "mission")
    themes = overall_themes(context)

    reading_sentences = []
    if parts.get("r1"):
        reading_sentences.append(reading_phrase(parts.get("r1"), r1_theme, "Première lecture"))
    if parts.get("r2"):
        reading_sentences.append(reading_phrase(parts.get("r2"), r2_theme, "Deuxième lecture"))
    if parts.get("ev"):
        reading_sentences.append(reading_phrase(parts.get("ev"), ev_theme, "Évangile"))

    celebration = context.get("celebration") or "cette célébration"
    monition = (
        "Frères et sœurs, nous sommes rassemblés aujourd'hui pour écouter une Parole qui veut rejoindre notre vie "
        "et renouveler notre foi. "
        + " ".join(reading_sentences)
        + f" À travers ces textes, un même appel se dessine : vivre {THEME_RULES[themes[0]]['focus']}, "
        f"grandir dans {THEME_RULES[themes[1]]['focus']} et laisser notre existence être transformée par "
        f"{THEME_RULES[themes[2]]['focus']}. Ouvrons donc notre cœur à la Parole de Dieu et entrons dans cette "
        "célébration avec foi, disponibilité et confiance."
    )

    intro = (
        f"Frères et sœurs, éclairés par la Parole de Dieu qui nous appelle aujourd'hui à vivre "
        f"{THEME_RULES[themes[0]]['focus']}, présentons avec confiance au Père les besoins de l'Église et du monde."
    )

    intentions = [
        (
            "Pour l'Église, le pape, les évêques, les prêtres, les consacrés et tous les baptisés : "
            f"{THEME_RULES[themes[0]]['church']}. Ensemble, prions le Seigneur."
        ),
        (
            "Pour les responsables des nations et tous ceux qui exercent une autorité : "
            f"{THEME_RULES[themes[1]]['world']}. Ensemble, prions le Seigneur."
        ),
        (
            "Pour les personnes malades, isolées, éprouvées, victimes de violence, d'injustice ou de pauvreté : "
            f"{THEME_RULES[themes[2]]['suffering']}. Ensemble, prions le Seigneur."
        ),
        (
            "Pour nos familles, les jeunes, les personnes âgées, les enfants et tous ceux qui cherchent un chemin de foi : "
            f"{THEME_RULES[themes[0]]['community']}. Ensemble, prions le Seigneur."
        ),
        (
            "Pour notre communauté chrétienne et pour chacun de nous : que l'écoute de la Parole porte du fruit dans nos "
            "choix, nos relations et notre service, afin que notre vie rende témoignage à l'Évangile. Ensemble, prions le Seigneur."
        ),
        (
            "Pour nos frères et sœurs défunts, et pour toutes les familles dans le deuil : que le Seigneur les accueille dans "
            "sa paix et soutienne ceux qui pleurent. Ensemble, prions le Seigneur."
        ),
    ]

    conclusion = (
        "Dieu notre Père, toi qui connais les besoins de tes enfants avant même qu'ils ne les expriment, accueille les prières "
        "que nous te présentons avec foi. Donne-nous de mettre ta Parole en pratique et de devenir, là où nous vivons, des "
        "témoins de ton amour. Par Jésus, le Christ, notre Seigneur. Amen."
    )

    return {
        "monition": monition,
        "pu_intro": intro,
        "intentions": intentions,
        "pu_conclusion": conclusion,
        "response": "Seigneur, nous te prions.",
        "themes": themes,
    }

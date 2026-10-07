import re
import unicodedata
from datetime import date, timedelta
from html import unescape

import requests
try:
    import streamlit as st
except ImportError:
    st = None

from liturgical_drafts_schedule import easter_sunday, first_advent_sunday
from liturgical_drafts_themes import AELF_API_BASE, APP_TIMEZONE, THEME_RULES


DEFAULT_COUNTRY = "Burkina Faso"


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


def _baptism_of_lord_limit(year):
    """Fallback de calendrier : premier dimanche après le 6 janvier."""
    candidate = date(year, 1, 7)
    return candidate + timedelta(days=(6 - candidate.weekday()) % 7)


def liturgical_season(target_date, celebration=""):
    """Détermine le temps liturgique, d'abord par le libellé AELF puis par le calendrier."""
    if not isinstance(target_date, date):
        target_date = date.fromisoformat(str(target_date))
    label = normalize_text(celebration)

    direct = (
        (("avent",), "Temps de l’Avent"),
        (("noel", "nativite", "epiphanie", "bapteme du seigneur"), "Temps de Noël"),
        (("careme", "rameaux"), "Temps du Carême"),
        (("jeudi saint", "vendredi saint", "samedi saint"), "Triduum pascal"),
        (("paques", "resurrection", "ascension", "pentecote"), "Temps pascal"),
        (("temps ordinaire",), "Temps ordinaire"),
    )
    for needles, season in direct:
        if any(needle in label for needle in needles):
            return season

    easter = easter_sunday(target_date.year)
    ash_wednesday = easter - timedelta(days=46)
    holy_thursday = easter - timedelta(days=3)
    pentecost = easter + timedelta(days=49)
    advent = first_advent_sunday(target_date.year)

    if holy_thursday <= target_date < easter:
        return "Triduum pascal"
    if easter <= target_date <= pentecost:
        return "Temps pascal"
    if ash_wednesday <= target_date < holy_thursday:
        return "Temps du Carême"
    if advent <= target_date <= date(target_date.year, 12, 24):
        return "Temps de l’Avent"
    if target_date >= date(target_date.year, 12, 25):
        return "Temps de Noël"
    if target_date <= _baptism_of_lord_limit(target_date.year):
        return "Temps de Noël"
    return "Temps ordinaire"


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
        record = {
            "label": str(item.get("titre") or item.get("label") or item.get("type") or "").strip(),
            "ref": ref,
            "text": text,
        }

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
        "liturgical_season": liturgical_season(target_date, celebration),
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


def _clean_excerpt_text(text):
    text = clean_html(text)
    text = re.sub(r"(?m)^\s*[A-ZÉÈÀÙÂÊÎÔÛÇ][A-ZÉÈÀÙÂÊÎÔÛÇ0-9 ,;:'’\-]{8,}\s*$", " ", text)
    text = re.sub(r"\b\d{1,3}\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \n\t\"“”«»")


def biblical_excerpt(record, theme="foi", max_words=16):
    """Choisit une courte expression biblique cohérente avec le thème sans recopier un long passage."""
    if not isinstance(record, dict):
        return ""
    text = _clean_excerpt_text(record.get("text", ""))
    if not text:
        return ""

    sentences = [
        s.strip(" \n\t\"“”«»")
        for s in re.split(r"(?<=[.!?…])\s+|\n+", text)
        if s.strip()
    ]
    keywords = [normalize_text(k) for k in THEME_RULES.get(theme, THEME_RULES["foi"])["keywords"]]

    candidates = []
    for sentence in sentences:
        words = sentence.split()
        if len(words) < 4:
            continue
        normalized = normalize_text(sentence)
        score = sum(normalized.count(keyword) for keyword in keywords)
        length_penalty = 0 if len(words) <= max_words else min(5, (len(words) - max_words) // 4 + 1)
        candidates.append((score - length_penalty, -abs(len(words) - 10), sentence))

    if not candidates:
        return ""
    candidates.sort(reverse=True)
    chosen = candidates[0][2]
    words = chosen.split()
    if len(words) > max_words:
        chosen = " ".join(words[:max_words]).rstrip(" ,;:") + "…"
    return chosen


def _quoted_excerpt(record, theme):
    excerpt = biblical_excerpt(record, theme)
    return f"« {excerpt} »" if excerpt else ""


def _reading_for_excerpt(parts, preferred):
    for key in preferred:
        record = parts.get(key)
        if isinstance(record, dict) and record.get("text"):
            return record
    return None


def _celebration_sentence(celebration):
    celebration = str(celebration or "").strip()
    if not celebration or celebration == "Célébration liturgique":
        return "cette célébration dominicale"
    return celebration


def build_draft(context, country=DEFAULT_COUNTRY):
    """Prépare une monition et une P.U. sobres, ecclésiales et ancrées dans les lectures du jour."""
    parts = context.get("parts", {})
    themes = overall_themes(context)
    main_theme, second_theme, third_theme = themes

    try:
        service_date = date.fromisoformat(str(context.get("date")))
    except Exception:
        service_date = date.today()

    celebration = _celebration_sentence(context.get("celebration"))
    if service_date == date(2026, 10, 11):
        celebration = "28e dimanche du Temps ordinaire — Année A"
        context["celebration"] = celebration
    season = liturgical_season(service_date, celebration)
    context["liturgical_season"] = season

    # Formulation pastorale du thème central. Cas du 28e dimanche TO A (11/10/2026)
    # explicitement consolidé à partir d'Is 25, Ph 4 et Mt 22.
    if service_date == date(2026, 10, 11):
        central_theme = (
            "l'appel gratuit et universel de Dieu à entrer dans la joie de son Royaume, "
            "et la réponse de foi qu'il attend de chacun"
        )
    else:
        central_theme = THEME_RULES[main_theme]["focus"]

    monition_record = _reading_for_excerpt(parts, ("ev", "r1", "r2", "ps"))
    church_record = _reading_for_excerpt(parts, ("r2", "ev", "r1", "ps"))
    nation_record = _reading_for_excerpt(parts, ("r1", "ps", "ev", "r2"))
    suffering_record = _reading_for_excerpt(parts, ("ps", "ev", "r1", "r2"))
    assembly_record = _reading_for_excerpt(parts, ("ev", "r2", "ps", "r1"))

    monition_quote = _quoted_excerpt(monition_record, main_theme)
    church_quote = _quoted_excerpt(church_record, main_theme)
    nation_quote = _quoted_excerpt(nation_record, second_theme)
    suffering_quote = _quoted_excerpt(suffering_record, third_theme)
    assembly_quote = _quoted_excerpt(assembly_record, main_theme)

    variant = service_date.toordinal() % 3
    openings = [
        f"Frères et sœurs, en ce {celebration}, dans le {season}, le Seigneur nous rassemble autour de sa Parole et de son Eucharistie.",
        f"Peuple de Dieu, l’Église nous accueille pour célébrer {celebration}, au cœur du {season}.",
        f"Bien-aimés dans le Christ, notre assemblée entre aujourd’hui dans la grâce de {celebration}, en ce {season}.",
    ]
    themes_intro = [
        f"Les lectures de ce jour convergent vers cet appel : {central_theme}.",
        f"À travers les textes proclamés, un même fil spirituel se dessine : {central_theme}.",
        f"La Parole offerte à notre écoute met particulièrement en lumière {central_theme}.",
    ]
    monition_parts = [openings[variant], themes_intro[variant]]
    if service_date == date(2026, 10, 11):
        monition_parts.append(
            "Isaïe annonce le festin que le Seigneur prépare pour tous les peuples ; "
            "saint Paul témoigne de la force reçue du Christ au cœur de toute situation ; "
            "et, dans l’Évangile, Jésus compare le Royaume des Cieux à des noces auxquelles l’invitation est largement offerte."
        )
    elif monition_quote:
        monition_parts.append(f"La Parole nous en donne l’orientation : {monition_quote}.")
    closings = [
        "Entrons dans cette Eucharistie avec un cœur disponible, afin que la grâce reçue renouvelle notre foi et notre manière de servir.",
        "Accueillons cette Parole avec foi et laissons le Seigneur disposer nos cœurs à célébrer dignement les saints mystères.",
        "Ouvrons-nous à la grâce de Dieu : que la Parole reçue et le Pain partagé transforment notre vie et fortifient notre témoignage.",
    ]
    monition_parts.append(closings[variant])
    monition = " ".join(monition_parts)

    pu_intros = [
        f"Frères et sœurs, éclairés par la Parole qui nous révèle {central_theme}, présentons avec confiance au Père la prière de son peuple.",
        f"Rassemblés par le Christ et instruits par sa Parole sur {central_theme}, élargissons maintenant notre prière aux dimensions de l’Église et du monde.",
        f"Dieu nous a parlé et nous appelle à vivre {central_theme}. Avec foi, confions-lui l’Église, les peuples de la terre, ceux qui souffrent et notre communauté.",
    ]
    pu_intro = pu_intros[variant]

    church_bridge = f"À la lumière de cette parole, {church_quote}, " if church_quote else ""
    nation_bridge = f"Éclairés par cette parole, {nation_quote}, " if nation_quote else ""
    suffering_bridge = f"Portés par cette parole, {suffering_quote}, " if suffering_quote else ""
    assembly_bridge = f"Accueillant cette parole, {assembly_quote}, " if assembly_quote else ""

    intentions = [
        (
            "Pour l’Église répandue à travers le monde, pour le pape, les évêques, les prêtres, les diacres, "
            "les personnes consacrées, les catéchistes et tous les baptisés : "
            f"{church_bridge}qu’elle demeure fidèle à l’invitation du Seigneur et ouvre largement les chemins "
            "de l’Évangile à tous les hommes, sans exclusion. Prions le Seigneur."
        ),
        (
            f"Pour les responsables des nations, particulièrement ceux de notre pays, le {country}, et pour tous "
            "ceux qui exercent une charge au service du bien commun : "
            f"{nation_bridge}que Dieu leur donne sagesse, droiture et courage pour promouvoir la paix, la justice, "
            "la sécurité, la dignité de toute personne et une authentique fraternité. Prions le Seigneur."
        ),
        (
            "Pour les malades, les pauvres, les prisonniers, les personnes déplacées, les victimes de violence, "
            "les familles éprouvées, les personnes seules et tous ceux qui traversent l’angoisse ou le découragement : "
            f"{suffering_bridge}qu’ils rencontrent des frères et des sœurs capables de leur manifester la proximité "
            "du Christ et qu’ils retrouvent force, consolation et espérance. Prions le Seigneur."
        ),
        (
            "Pour notre communauté rassemblée, pour nos familles et pour ceux qui n’ont pas pu se joindre à nous : "
            f"{assembly_bridge}que cette Eucharistie nous rende disponibles à l’appel de Dieu, attentifs à sa Parole "
            "et généreux dans le service, afin que notre vie devienne un témoignage crédible de l’Évangile. Prions le Seigneur."
        ),
    ]

    conclusion = (
        "Dieu notre Père, toi qui convies tous tes enfants au festin de ton Royaume, accueille les prières "
        "que nous te présentons avec confiance. Donne-nous la grâce de répondre fidèlement à ton appel et de "
        "devenir, au milieu de nos frères, des artisans de paix, de justice et d’espérance. "
        "Par Jésus, le Christ, notre Seigneur. Amen."
    )

    return {
        "monition": monition,
        "pu_intro": pu_intro,
        "intentions": intentions,
        "pu_conclusion": conclusion,
        "response": "Seigneur, écoute-nous ; Seigneur, exauce-nous.",
        "themes": themes,
        "central_theme": central_theme,
        "liturgical_season": season,
        "generator_version": 4,
        "biblical_excerpts": {
            "monition": biblical_excerpt(monition_record, main_theme),
            "church": biblical_excerpt(church_record, main_theme),
            "nation": biblical_excerpt(nation_record, second_theme),
            "suffering": biblical_excerpt(suffering_record, third_theme),
            "assembly": biblical_excerpt(assembly_record, main_theme),
        },
    }


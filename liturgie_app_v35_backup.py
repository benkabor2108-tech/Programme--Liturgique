import calendar
import csv
import io
import json
import random
import re
import unicodedata
from copy import deepcopy
from datetime import date
from html import escape
from urllib.parse import quote

import requests
import streamlit as st
import xlsxwriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

APP_VERSION = "2026.08.26-persistant-supabase-v3.5-maintenance"
TABLE_NAME = "liturgie_state"
AELF_API_BASE = "https://api.aelf.org/v1"
AELF_ZONES = {
    "Calendrier romain": "romain",
    "Afrique du Nord": "afrique",
    "Belgique": "belgique",
    "Canada": "canada",
    "France": "france",
    "Luxembourg": "luxembourg",
    "Monaco": "monaco",
    "Suisse": "suisse",
}

st.set_page_config(page_title="Programme liturgique", page_icon="⛪", layout="wide")

FR = [f"F{i}" for i in range(1, 11)]
MO = [f"M{i}" for i in range(1, 9)]
GROUPS = {"FR": FR, "MO": MO}
MONTHS = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]

DEFAULT_NAMES = {
    "F1": "Mme Nacoulma",
    "F2": "Mme Sawadogo n°1",
    "F3": "M. Kabré Denis",
    "F4": "M. Bamouni",
    "F5": "Mme Kiendrebeogo",
    "F6": "M. Kaboré",
    "F7": "Mme Yaméogo",
    "F8": "Mme Traoré",
    "F9": "Mme Sawadogo n°2",
    "F10": "Mlle Zie",
    "M1": "M. Zoundi",
    "M2": "Mme Zoungrana",
    "M3": "Mlle Brigitte",
    "M4": "M. Zoungrana",
    "M5": "M. Koala",
    "M6": "M. Grégoire",
    "M7": "Mlle Gladys",
    "M8": "Mlle Jeanette",
}


def blank_person():
    return {
        "next_role": None,
        "last_reading": None,
        "last_service": None,
        "last_announcement": None,
        "reading_count": 0,
        "monition_count": 0,
        "announcement_count": 0,
    }


def code_number(code):
    match = re.fullmatch(r"([FM])(\d+)", str(code or "").strip())
    return int(match.group(2)) if match else 10**9


def member_codes(state, lang=None):
    roster = state.get("roster", {}) if isinstance(state, dict) else {}
    if lang in ("FR", "MO"):
        prefix = "F" if lang == "FR" else "M"
        values = roster.get(lang, []) if isinstance(roster, dict) else []
        return sorted(
            [c for c in values if isinstance(c, str) and c.startswith(prefix) and c[1:].isdigit()],
            key=code_number,
        )
    return member_codes(state, "FR") + member_codes(state, "MO")


def initial_state():
    return {
        "version": APP_VERSION,
        "roster": {"FR": FR[:], "MO": MO[:]},
        "next_member_number": {"FR": 11, "MO": 9},
        "names": dict(DEFAULT_NAMES),
        "active": {code: True for code in FR + MO},
        "people": {code: blank_person() for code in FR + MO},
        "reading_cycle_seen": {"FR": [], "MO": []},
        "reading_pairs": [],
        "monition_pairs": [],
        "next_first_language": "FR",
        "history": [],
    }


def normalize_state(raw):
    if not isinstance(raw, dict):
        return initial_state()

    # Migration automatique depuis les versions 3.3 et antérieures : elles n'avaient pas de roster.
    raw_roster = raw.get("roster") if isinstance(raw.get("roster"), dict) else None
    if raw_roster is None:
        roster = {"FR": FR[:], "MO": MO[:]}
        for mapping_name in ("names", "active", "people"):
            mapping = raw.get(mapping_name, {})
            if isinstance(mapping, dict):
                for code in mapping:
                    if isinstance(code, str) and re.fullmatch(r"F\d+", code) and code not in roster["FR"]:
                        roster["FR"].append(code)
                    elif isinstance(code, str) and re.fullmatch(r"M\d+", code) and code not in roster["MO"]:
                        roster["MO"].append(code)
    else:
        roster = {"FR": [], "MO": []}
        for lang, prefix in (("FR", "F"), ("MO", "M")):
            values = raw_roster.get(lang, [])
            if isinstance(values, list):
                roster[lang] = [
                    c for c in values
                    if isinstance(c, str) and re.fullmatch(fr"{prefix}\d+", c)
                ]
        # Un roster vide après migration serait dangereux : on conserve les membres historiques de base.
        if not roster["FR"] and not roster["MO"]:
            roster = {"FR": FR[:], "MO": MO[:]}

    roster["FR"] = sorted(dict.fromkeys(roster["FR"]), key=code_number)
    roster["MO"] = sorted(dict.fromkeys(roster["MO"]), key=code_number)

    state = {
        "version": APP_VERSION,
        "roster": roster,
        "next_member_number": {"FR": 1, "MO": 1},
        "names": {},
        "active": {},
        "people": {},
        "reading_cycle_seen": {"FR": [], "MO": []},
        "reading_pairs": [],
        "monition_pairs": [],
        "next_first_language": "FR",
        "history": [],
    }

    raw_names = raw.get("names", {}) if isinstance(raw.get("names"), dict) else {}
    raw_active = raw.get("active", {}) if isinstance(raw.get("active"), dict) else {}
    raw_people = raw.get("people", {}) if isinstance(raw.get("people"), dict) else {}

    for code in member_codes(state):
        state["names"][code] = str(raw_names.get(code) or DEFAULT_NAMES.get(code) or code).strip()
        state["active"][code] = bool(raw_active.get(code, True))
        state["people"][code] = blank_person()
        if isinstance(raw_people.get(code), dict):
            state["people"][code].update(raw_people[code])

    raw_next = raw.get("next_member_number", {}) if isinstance(raw.get("next_member_number"), dict) else {}
    for lang in ("FR", "MO"):
        highest = max([code_number(c) for c in member_codes(state, lang)] or [0])
        requested = raw_next.get(lang, highest + 1)
        try:
            requested = int(requested)
        except Exception:
            requested = highest + 1
        state["next_member_number"][lang] = max(highest + 1, requested)

    for key in ["reading_cycle_seen", "reading_pairs", "monition_pairs", "next_first_language", "history"]:
        if key in raw:
            state[key] = deepcopy(raw[key])

    # Nettoyer uniquement les structures de rotation des membres qui ne font plus partie du roster.
    current = set(member_codes(state))
    for lang in ("FR", "MO"):
        state["reading_cycle_seen"][lang] = [
            c for c in state.get("reading_cycle_seen", {}).get(lang, []) if c in current
        ]
    state["reading_pairs"] = [p for p in state.get("reading_pairs", []) if isinstance(p, list) and len(p) == 2 and all(c in current for c in p)]
    state["monition_pairs"] = [p for p in state.get("monition_pairs", []) if isinstance(p, list) and len(p) == 2 and all(c in current for c in p)]

    return state


def supabase_config():
    try:
        cfg = st.secrets.get("supabase", {})
        url = str(cfg.get("url", "")).rstrip("/")
        api_key = str(cfg.get("api_key", ""))
        state_key = str(cfg.get("state_key", "programme-liturgique-principal"))
        return url, api_key, state_key
    except Exception:
        return "", "", "programme-liturgique-principal"


def supabase_ready():
    url, api_key, _ = supabase_config()
    return bool(url and api_key)


def load_remote_state():
    url, api_key, state_key = supabase_config()
    if not (url and api_key):
        return None, "Secrets Supabase absents"

    endpoint = f"{url}/rest/v1/{TABLE_NAME}"
    params = {
        "select": "state_json",
        "app_key": f"eq.{state_key}",
        "limit": "1",
    }
    headers = {"apikey": api_key, "Accept": "application/json"}
    try:
        response = requests.get(endpoint, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return None, "Aucun état distant enregistré"
        return normalize_state(rows[0].get("state_json")), "État chargé depuis Supabase"
    except Exception as exc:
        return None, f"Lecture Supabase impossible : {exc}"


def save_remote_state(state):
    url, api_key, state_key = supabase_config()
    if not (url and api_key):
        return False, "Secrets Supabase absents"

    endpoint = f"{url}/rest/v1/{TABLE_NAME}?on_conflict=app_key"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    payload = {"app_key": state_key, "state_json": state}
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        return True, "Sauvegardé dans Supabase"
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
    if show_success:
        if ok:
            st.success(message)
        else:
            st.error(message)
    return ok


def as_date(value):
    return date.fromisoformat(value) if value else None


def days_since(value, today):
    return 10000 if not value else (today - as_date(value)).days


def sundays(year, month):
    cal = calendar.Calendar(firstweekday=calendar.MONDAY)
    return [
        d for d in cal.itermonthdates(year, month)
        if d.month == month and d.weekday() == 6
    ]


def active_codes(state, lang):
    return [c for c in member_codes(state, lang) if state["active"].get(c, True)]


def normalize_label(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("œ", "oe")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def aelf_ref_value(item):
    if not isinstance(item, dict):
        return ""
    for key in ("ref", "reference", "references", "citation"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def aelf_item_label(item):
    if not isinstance(item, dict):
        return ""
    parts = []
    for key in ("type", "key", "label", "titre", "title", "nom", "name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return normalize_label(" ".join(parts))


def aelf_lecture_lists(payload):
    result = []

    # Format officiel habituel : {"messes": [{"lectures": [...]}]}
    if isinstance(payload, dict):
        masses = payload.get("messes") or payload.get("masses")
        if isinstance(masses, list):
            ranked = []
            for mass in masses:
                if not isinstance(mass, dict):
                    continue
                lectures = mass.get("lectures") or mass.get("readings")
                if not isinstance(lectures, list):
                    continue
                name = normalize_label(mass.get("nom") or mass.get("name") or mass.get("titre") or "")
                penalty = 0
                if any(word in name for word in ("veille", "vigile", "nuit", "aurore")):
                    penalty += 10
                if "jour" in name:
                    penalty -= 2
                ranked.append((penalty, lectures))
            ranked.sort(key=lambda item: item[0])
            result.extend(lectures for _, lectures in ranked)

    # Repli robuste si la structure JSON évolue.
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("lectures", "readings") and isinstance(value, list):
                    if value not in result:
                        result.append(value)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return result


def extract_aelf_refs(payload):
    best = None
    best_score = -1
    for lectures in aelf_lecture_lists(payload):
        refs = {"r1": "", "r2": "", "ev": ""}
        ordinary = []
        for item in lectures:
            if not isinstance(item, dict):
                continue
            ref = aelf_ref_value(item)
            if not ref:
                continue
            label = aelf_item_label(item)
            if any(token in label for token in ("psaume", "psalm", "cantique")):
                continue

            if (
                "lecture_1" in label or "premiere_lecture" in label or
                "1re_lecture" in label or "first_reading" in label
            ):
                refs["r1"] = ref
            elif (
                "lecture_2" in label or "deuxieme_lecture" in label or
                "2e_lecture" in label or "second_reading" in label
            ):
                refs["r2"] = ref
            elif "evangile" in label or "gospel" in label:
                refs["ev"] = ref
            ordinary.append((label, ref))

        # Repli par ordre liturgique : première lecture, seconde lecture, évangile.
        sequence = []
        for label, ref in ordinary:
            if ref not in sequence and not any(token in label for token in ("psaume", "psalm", "cantique")):
                sequence.append(ref)
        if not refs["r1"] and sequence:
            refs["r1"] = sequence[0]
        if not refs["ev"] and len(sequence) >= 2:
            refs["ev"] = sequence[-1]
        if not refs["r2"] and len(sequence) >= 3:
            refs["r2"] = sequence[-2]

        score = sum(bool(refs[key]) for key in ("r1", "r2", "ev"))
        if score > best_score:
            best, best_score = refs, score
        if score == 3:
            return refs

    return best or {"r1": "", "r2": "", "ev": ""}


@st.cache_data(ttl=12 * 60 * 60, show_spinner=False)
def fetch_aelf_refs(date_iso, zone):
    url = f"{AELF_API_BASE}/messes/{date_iso}/{zone}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Programme-liturgique-Streamlit/3.3",
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    refs = extract_aelf_refs(response.json())
    if not refs.get("r1") or not refs.get("ev"):
        raise RuntimeError("Références AELF incomplètes pour cette date.")
    refs["source"] = f"AELF ({zone})"
    refs["source_url"] = f"https://www.aelf.org/{date_iso}/{zone}/messe"
    return refs


def fetch_month_aelf_refs(dates, zone):
    refs = {}
    errors = {}
    for day in dates:
        try:
            refs[day.isoformat()] = fetch_aelf_refs(day.isoformat(), zone)
        except Exception as exc:
            errors[day.isoformat()] = str(exc)
    return refs, errors


def refs_to_text(refs, dates):
    lines = []
    for day in dates:
        item = refs.get(day.isoformat(), {})
        lines.append(
            f"{day.isoformat()} | {item.get('r1', '')} | {item.get('r2', '')} | {item.get('ev', '')}"
        )
    return "\n".join(lines)


def reading_pool(state, lang, excluded):
    codes = active_codes(state, lang)
    seen = [c for c in state["reading_cycle_seen"].get(lang, []) if c in codes]
    if codes and len(set(seen)) >= len(codes):
        state["reading_cycle_seen"][lang] = []
        seen = []
    seen = set(seen)
    return [
        c for c in codes
        if c not in excluded
        and c not in seen
        and state["people"][c]["next_role"] in (None, "LECTURE")
    ]


def reading_rank(state, code, today):
    p = state["people"][code]
    return (
        p["reading_count"],
        -days_since(p["last_reading"], today),
        -days_since(p["last_service"], today),
        code,
    )


def choose_readers(state, today, rng):
    fr_pool = reading_pool(state, "FR", set())
    mo_pool = reading_pool(state, "MO", set())
    if not fr_pool or not mo_pool:
        raise RuntimeError(
            "La rotation ne permet pas de choisir les deux lecteurs sans casser une règle. "
            "Vérifiez les membres actifs ou réinitialisez uniquement la rotation."
        )
    old_pairs = {tuple(p) for p in state.get("reading_pairs", [])}
    choices = []
    for f in fr_pool:
        for m in mo_pool:
            choices.append(((
                1 if (f, m) in old_pairs else 0,
                reading_rank(state, f, today),
                reading_rank(state, m, today),
                rng.random(),
            ), f, m))
    choices.sort(key=lambda x: x[0])
    return choices[0][1], choices[0][2]


def monition_pool(state, lang, excluded):
    return [
        c for c in active_codes(state, lang)
        if c not in excluded
        and state["people"][c]["next_role"] in (None, "MONITION")
    ]


def monition_rank(state, code, today):
    p = state["people"][code]
    return (p["monition_count"], -days_since(p["last_service"], today), code)


def choose_monitions(state, today, excluded, rng):
    fr_pool = monition_pool(state, "FR", excluded)
    mo_pool = monition_pool(state, "MO", excluded)
    if not fr_pool or not mo_pool:
        raise RuntimeError(
            "Impossible d'attribuer la monition/P.U. sans casser l'alternance individuelle Lecture ↔ Monition."
        )
    old_pairs = {tuple(p) for p in state.get("monition_pairs", [])}
    choices = []
    for f in fr_pool:
        for m in mo_pool:
            choices.append(((
                1 if (f, m) in old_pairs else 0,
                monition_rank(state, f, today),
                monition_rank(state, m, today),
                rng.random(),
            ), f, m))
    choices.sort(key=lambda x: x[0])
    return choices[0][1], choices[0][2]


def announcement_rank(state, code, today):
    p = state["people"][code]
    return (p["announcement_count"], -days_since(p["last_announcement"], today), code)


def choose_announcement(state, lang, today, excluded, rng):
    pool = [c for c in active_codes(state, lang) if c not in excluded]
    if not pool:
        raise RuntimeError(f"Aucun membre {lang} disponible pour les annonces sans cumul de fonction.")
    rng.shuffle(pool)
    return min(pool, key=lambda c: announcement_rank(state, c, today))


def assign(state, code, role, today):
    p = state["people"][code]
    if role == "LECTURE":
        p["reading_count"] += 1
        p["last_reading"] = today.isoformat()
        p["last_service"] = today.isoformat()
        p["next_role"] = "MONITION"
        lang = "FR" if code.startswith("F") else "MO"
        if code not in state["reading_cycle_seen"][lang]:
            state["reading_cycle_seen"][lang].append(code)
    elif role == "MONITION":
        p["monition_count"] += 1
        p["last_service"] = today.isoformat()
        p["next_role"] = "LECTURE"
    elif role == "ANNONCE":
        p["announcement_count"] += 1
        p["last_announcement"] = today.isoformat()


def parse_refs(text, dates):
    refs = {d.isoformat(): {"r1": "", "r2": "", "ev": ""} for d in dates}
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) >= 4 and parts[0] in refs:
            refs[parts[0]] = {"r1": parts[1], "r2": parts[2], "ev": parts[3], "source": "Saisie manuelle"}
    return refs


def generate_month(state, year, month, refs, seed):
    state = normalize_state(deepcopy(state))
    rng = random.Random(seed + year * 100 + month)
    month_dates = {d.isoformat() for d in sundays(year, month)}
    if any(row.get("date") in month_dates for row in state["history"]):
        raise RuntimeError(
            "Ce mois figure déjà dans l'historique. Supprimez d'abord ce mois de l'historique ou choisissez un autre mois."
        )

    if len(active_codes(state, "FR")) < 3 or len(active_codes(state, "MO")) < 3:
        raise RuntimeError("Il faut au moins 3 membres actifs dans chaque langue pour respecter les fonctions sans cumul.")

    rows = []
    for sunday in sundays(year, month):
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

        ref = refs[sunday.isoformat()]
        names = state["names"]
        row = {
            "date": sunday.isoformat(),
            "Dimanche": sunday.strftime("%d/%m/%Y"),
            "Références": f"1re : {ref['r1']}\n2e : {ref['r2']}\nÉv. : {ref['ev']}",
            "Lecteurs": f"1re ({r1_lang}) : {names[r1_code]}\n2e ({r2_lang}) : {names[r2_code]}",
            "Monition + P.U.": f"FR : {names[f_mon]}\nMO : {names[m_mon]}",
            "Annonces": f"FR : {names[f_ann]}\nMO : {names[m_ann]}",
            "Source références": ref.get("source", ""),
            "Source URL": ref.get("source_url", ""),
            "codes": {
                "r1": r1_code, "r2": r2_code,
                "f_mon": f_mon, "m_mon": m_mon,
                "f_ann": f_ann, "m_ann": m_ann,
            },
        }
        rows.append(row)
        state["history"].append(row)

    return rows, state


def labeled_lines(text):
    result = {}
    for raw in str(text or "").splitlines():
        if ":" not in raw:
            continue
        label, value = raw.split(":", 1)
        result[label.strip()] = value.strip()
    return result


def first_value(mapping, prefix):
    for key, value in mapping.items():
        if key.startswith(prefix):
            return key, value
    return "", ""


def flat_row(row):
    refs = labeled_lines(row.get("Références", row.get("Réf.D", "")))
    readers = labeled_lines(row.get("Lecteurs", ""))
    monitions = labeled_lines(row.get("Monition + P.U.", row.get("Monition introductive + P.U.", "")))
    annonces = labeled_lines(row.get("Annonces", row.get("Chargés d’annonce", "")))

    r1_label, r1_name = first_value(readers, "1re")
    r2_label, r2_name = first_value(readers, "2e")
    r1_lang = r1_label[r1_label.find("(") + 1:r1_label.find(")")] if "(" in r1_label and ")" in r1_label else ""
    r2_lang = r2_label[r2_label.find("(") + 1:r2_label.find(")")] if "(" in r2_label and ")" in r2_label else ""

    return {
        "Dimanche": row.get("Dimanche", row.get("date", "")),
        "1re lecture": refs.get("1re", ""),
        "2e lecture": refs.get("2e", ""),
        "Évangile": refs.get("Év.", refs.get("Év", "")),
        "Lecteur 1": f"{r1_lang} — {r1_name}" if r1_lang else r1_name,
        "Lecteur 2": f"{r2_lang} — {r2_name}" if r2_lang else r2_name,
        "Monition/P.U. FR": monitions.get("FR", ""),
        "Monition/P.U. MO": monitions.get("MO", ""),
        "Annonces FR": annonces.get("FR", ""),
        "Annonces MO": annonces.get("MO", ""),
    }


def flat_rows(rows):
    return [flat_row(row) for row in rows]


def csv_bytes(rows):
    out = io.StringIO()
    fields = [
        "Dimanche", "1re lecture", "2e lecture", "Évangile",
        "Lecteur 1", "Lecteur 2", "Monition/P.U. FR", "Monition/P.U. MO",
        "Annonces FR", "Annonces MO",
    ]
    writer = csv.DictWriter(out, fieldnames=fields, delimiter=";", lineterminator="\n")
    writer.writeheader()
    for row in flat_rows(rows):
        writer.writerow({k: row.get(k, "") for k in fields})
    return out.getvalue().encode("utf-8-sig")


def rotation_rows(state):
    result = []
    for code in member_codes(state):
        p = state["people"][code]
        result.append({
            "Membre": state["names"][code],
            "Langue": "Français" if code.startswith("F") else "Mooré",
            "Statut": "Actif" if state["active"].get(code, True) else "Absent",
            "Prochaine fonction": p["next_role"] or "Libre (départ)",
            "Lectures": p["reading_count"],
            "Monitions/P.U.": p["monition_count"],
            "Annonces": p["announcement_count"],
            "Dernière lecture": p["last_reading"] or "—",
            "Dernier passage": p["last_service"] or "—",
        })
    return result


def xlsx_bytes(rows, state, title="Programme liturgique"):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_properties({"title": title, "subject": "Programme liturgique", "author": "Programme liturgique Streamlit"})

    # Feuille Programme - A4 paysage, une seule page à l'impression.
    ws = workbook.add_worksheet("Programme")
    title_fmt = workbook.add_format({
        "bold": True, "font_size": 14, "align": "center", "valign": "vcenter",
        "bg_color": "#EAF2F8", "border": 1,
    })
    header_fmt = workbook.add_format({
        "bold": True, "font_size": 8, "align": "center", "valign": "vcenter", "text_wrap": True,
        "bg_color": "#D9EAF7", "border": 1,
    })
    date_fmt = workbook.add_format({"font_size": 8, "align": "center", "valign": "top", "border": 1})
    cell_fmt = workbook.add_format({"font_size": 8, "valign": "top", "text_wrap": True, "border": 1})
    source_fmt = workbook.add_format({"font_size": 8, "italic": True, "font_color": "#666666", "align": "left"})

    fields = [
        "Dimanche", "1re lecture", "2e lecture", "Évangile",
        "Lecteur 1", "Lecteur 2", "Monition/P.U. FR", "Monition/P.U. MO",
        "Annonces FR", "Annonces MO",
    ]
    rows_flat = flat_rows(rows)
    ws.merge_range(0, 0, 0, len(fields) - 1, title, title_fmt)
    ws.set_row(0, 24)
    source_text = "Références bibliques : AELF" if any(str(r.get("Source références", "")).startswith("AELF") for r in rows) else "Références bibliques : programme enregistré"
    ws.merge_range(1, 0, 1, len(fields) - 1, source_text, source_fmt)
    ws.write_row(2, 0, fields, header_fmt)
    for idx, item in enumerate(rows_flat, start=3):
        values = [item.get(field, "") for field in fields]
        ws.write(idx, 0, values[0], date_fmt)
        for col, value in enumerate(values[1:], start=1):
            ws.write(idx, col, value, cell_fmt)
        ws.set_row(idx, 34)

    widths = [11, 14, 14, 14, 19, 19, 18, 18, 17, 17]
    for col, width in enumerate(widths):
        ws.set_column(col, col, width)
    last_row = 2 + len(rows_flat)
    if rows_flat:
        ws.autofilter(2, 0, last_row, len(fields) - 1)
    ws.freeze_panes(3, 1)
    ws.hide_gridlines(2)
    ws.set_landscape()
    ws.set_paper(9)  # A4
    ws.fit_to_pages(1, 1)
    ws.print_area(0, 0, last_row, len(fields) - 1)
    ws.set_margins(0.18, 0.18, 0.28, 0.28)
    ws.center_horizontally()
    ws.center_vertically()
    ws.repeat_rows(2)
    ws.set_footer("&CPage &P sur &N")

    # Feuille Rotation
    rot = workbook.add_worksheet("Rotation")
    rotation = rotation_rows(state)
    rot_fields = [
        "Membre", "Langue", "Statut", "Prochaine fonction", "Lectures",
        "Monitions/P.U.", "Annonces", "Dernière lecture", "Dernier passage",
    ]
    rot.merge_range(0, 0, 0, len(rot_fields) - 1, "Contrôle de la rotation", title_fmt)
    rot.write_row(2, 0, rot_fields, header_fmt)
    for idx, item in enumerate(rotation, start=3):
        for col, field in enumerate(rot_fields):
            rot.write(idx, col, item.get(field, ""), cell_fmt)
    rot_widths = [26, 12, 20, 20, 10, 15, 10, 16, 16]
    for col, width in enumerate(rot_widths):
        rot.set_column(col, col, width)
    rot.freeze_panes(3, 1)
    rot.hide_gridlines(2)
    rot.set_landscape()
    rot.set_paper(9)
    rot.fit_to_pages(1, 0)
    if rotation:
        rot.autofilter(2, 0, 2 + len(rotation), len(rot_fields) - 1)

    workbook.close()
    output.seek(0)
    return output.getvalue()


def pdf_month_title(month_rows, fallback="Programme liturgique"):
    for row in month_rows:
        value = row.get("date")
        if value:
            try:
                d = date.fromisoformat(value)
                return f"Programme liturgique - {MONTHS[d.month - 1]} {d.year}"
            except Exception:
                pass
    return fallback


def pdf_bytes(rows, title="Programme liturgique"):
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
        title=title,
        author="Programme liturgique Streamlit",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "LiturgieTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=15, leading=17, alignment=TA_CENTER, spaceAfter=4 * mm,
    )
    note_style = ParagraphStyle(
        "LiturgieNote", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7.2, leading=8.5, textColor=colors.HexColor("#555555"),
        alignment=TA_CENTER, spaceAfter=3 * mm,
    )
    header_style = ParagraphStyle(
        "LiturgieHeader", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=7.5, leading=8.5, alignment=TA_CENTER,
    )
    cell_style = ParagraphStyle(
        "LiturgieCell", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7.4, leading=9.0,
    )
    date_style = ParagraphStyle(
        "LiturgieDate", parent=cell_style, fontName="Helvetica-Bold", alignment=TA_CENTER,
    )

    # Une page paysage par mois dans l'historique.
    groups = []
    current_key = None
    current_rows = []
    for row in rows:
        value = row.get("date", "")
        key = value[:7] if len(value) >= 7 else "autre"
        if current_key is not None and key != current_key:
            groups.append(current_rows)
            current_rows = []
        current_key = key
        current_rows.append(row)
    if current_rows:
        groups.append(current_rows)
    if not groups:
        groups = [[]]

    story = []
    for group_index, month_rows in enumerate(groups):
        month_title = pdf_month_title(month_rows, title)
        story.append(Paragraph(escape(month_title), title_style))
        source_text = "Références bibliques : AELF" if any(str(r.get("Source références", "")).startswith("AELF") for r in month_rows) else "Références bibliques : programme enregistré"
        story.append(Paragraph(escape(source_text), note_style))

        data = [[
            Paragraph("Dimanche", header_style),
            Paragraph("Références bibliques", header_style),
            Paragraph("Lecteurs", header_style),
            Paragraph("Monition + P.U.", header_style),
            Paragraph("Annonces", header_style),
        ]]
        for item in flat_rows(month_rows):
            refs = (
                f"<b>1re :</b> {escape(item['1re lecture'] or '-')}<br/>"
                f"<b>2e :</b> {escape(item['2e lecture'] or '-')}<br/>"
                f"<b>Év. :</b> {escape(item['Évangile'] or '-')}"
            )
            readers = (
                f"<b>1re :</b> {escape(item['Lecteur 1'] or '-')}<br/>"
                f"<b>2e :</b> {escape(item['Lecteur 2'] or '-')}"
            )
            monitions = (
                f"<b>FR :</b> {escape(item['Monition/P.U. FR'] or '-')}<br/>"
                f"<b>MO :</b> {escape(item['Monition/P.U. MO'] or '-')}"
            )
            annonces = (
                f"<b>FR :</b> {escape(item['Annonces FR'] or '-')}<br/>"
                f"<b>MO :</b> {escape(item['Annonces MO'] or '-')}"
            )
            data.append([
                Paragraph(escape(item["Dimanche"]), date_style),
                Paragraph(refs, cell_style),
                Paragraph(readers, cell_style),
                Paragraph(monitions, cell_style),
                Paragraph(annonces, cell_style),
            ])

        table = Table(
            data,
            colWidths=[25 * mm, 61 * mm, 55 * mm, 55 * mm, 55 * mm],
            repeatRows=1,
            hAlign="CENTER",
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9EAF7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
            ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#9CA3AF")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        story.append(table)
        if group_index < len(groups) - 1:
            story.append(PageBreak())

    doc.build(story)
    output.seek(0)
    return output.getvalue()


def show_mobile_program(rows):
    st.caption("📱 Vue téléphone : ouvrez un dimanche pour voir toutes les références et fonctions sans défilement horizontal.")
    for item in flat_rows(rows):
        with st.expander(f"📅 {item['Dimanche']}"):
            st.markdown(
                f"**Références bibliques**  \n"
                f"• 1re lecture : **{item['1re lecture'] or '—'}**  \n"
                f"• 2e lecture : **{item['2e lecture'] or '—'}**  \n"
                f"• Évangile : **{item['Évangile'] or '—'}**"
            )
            st.markdown(
                f"**Lecteurs**  \n"
                f"• 1re : {item['Lecteur 1'] or '—'}  \n"
                f"• 2e : {item['Lecteur 2'] or '—'}"
            )
            st.markdown(
                f"**Monition + P.U.**  \n"
                f"• FR : {item['Monition/P.U. FR'] or '—'}  \n"
                f"• MO : {item['Monition/P.U. MO'] or '—'}"
            )
            st.markdown(
                f"**Annonces**  \n"
                f"• FR : {item['Annonces FR'] or '—'}  \n"
                f"• MO : {item['Annonces MO'] or '—'}"
            )


def rotation_reset_keep_names(state):
    fresh = initial_state()
    fresh["roster"] = deepcopy(state.get("roster", {"FR": FR[:], "MO": MO[:]}))
    fresh["next_member_number"] = deepcopy(state.get("next_member_number", {"FR": 11, "MO": 9}))
    fresh["names"] = {c: state.get("names", {}).get(c, c) for c in member_codes(state)}
    fresh["active"] = {c: bool(state.get("active", {}).get(c, True)) for c in member_codes(state)}
    fresh["people"] = {c: blank_person() for c in member_codes(state)}
    return fresh


def latest_history_month(history):
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


def rebuild_rotation_from_history(state, history):
    """
    Reconstruit les compteurs et la prochaine fonction à partir de l'historique conservé.
    Le roster, les noms et les statuts actif/absent actuels sont préservés.
    """
    fresh = rotation_reset_keep_names(state)
    clean_history = []

    def row_day(row):
        try:
            return date.fromisoformat(str(row.get("date", "")))
        except Exception:
            return date.min

    current = set(member_codes(fresh))
    for row in sorted((history or []), key=row_day):
        try:
            sunday = date.fromisoformat(str(row.get("date", "")))
        except Exception:
            continue

        # Reproduire le redémarrage d'un cycle de lecture lorsque tous les membres
        # actuellement actifs d'une langue ont déjà lu dans le cycle précédent.
        for lang in ("FR", "MO"):
            active = active_codes(fresh, lang)
            seen = [c for c in fresh["reading_cycle_seen"].get(lang, []) if c in active]
            if active and len(set(seen)) >= len(active):
                fresh["reading_cycle_seen"][lang] = []

        codes = row.get("codes", {}) if isinstance(row.get("codes"), dict) else {}
        r1 = codes.get("r1")
        r2 = codes.get("r2")
        f_mon = codes.get("f_mon")
        m_mon = codes.get("m_mon")
        f_ann = codes.get("f_ann")
        m_ann = codes.get("m_ann")

        for code in (r1, r2):
            if code in current:
                assign(fresh, code, "LECTURE", sunday)
        if r1 in current and r2 in current:
            f_read = r1 if str(r1).startswith("F") else r2
            m_read = r1 if str(r1).startswith("M") else r2
            if f_read in current and m_read in current:
                fresh["reading_pairs"].append([f_read, m_read])

        for code in (f_mon, m_mon):
            if code in current:
                assign(fresh, code, "MONITION", sunday)
        if f_mon in current and m_mon in current:
            fresh["monition_pairs"].append([f_mon, m_mon])

        for code in (f_ann, m_ann):
            if code in current:
                assign(fresh, code, "ANNONCE", sunday)

        if r1 in current:
            fresh["next_first_language"] = "MO" if str(r1).startswith("F") else "FR"

        clean_history.append(deepcopy(row))

    fresh["history"] = clean_history
    fresh["version"] = APP_VERSION
    return fresh


def undo_last_month(state):
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


def names_text(state, codes):
    return "\n".join(state["names"].get(c, c) for c in codes)


def apply_names_text(state, codes, text):
    values = [line.strip() for line in text.splitlines() if line.strip()]
    if len(values) != len(codes):
        return False, f"Il faut saisir exactement {len(codes)} noms. Vous en avez saisi {len(values)}."
    for code, value in zip(codes, values):
        state["names"][code] = value
    return True, "Noms enregistrés."


def add_member(state, lang, name):
    name = str(name or "").strip()
    if not name:
        return False, "Saisissez le nom du nouveau membre.", None
    existing = [state["names"].get(c, "").strip().casefold() for c in member_codes(state, lang)]
    if name.casefold() in existing:
        return False, "Ce nom existe déjà dans cette catégorie.", None

    prefix = "F" if lang == "FR" else "M"
    number = int(state.get("next_member_number", {}).get(lang, 1))
    used = set(member_codes(state))
    code = f"{prefix}{number}"
    while code in used:
        number += 1
        code = f"{prefix}{number}"

    state.setdefault("roster", {}).setdefault(lang, []).append(code)
    state["roster"][lang] = sorted(dict.fromkeys(state["roster"][lang]), key=code_number)
    state.setdefault("next_member_number", {})[lang] = number + 1
    state.setdefault("names", {})[code] = name
    state.setdefault("active", {})[code] = True
    state.setdefault("people", {})[code] = blank_person()
    return True, f"{name} a été ajouté et est actif.", code


def remove_member_permanently(state, code):
    if code not in member_codes(state):
        return False, "Membre introuvable."
    name = state.get("names", {}).get(code, code)
    lang = "FR" if str(code).startswith("F") else "MO"

    state["roster"][lang] = [c for c in state["roster"].get(lang, []) if c != code]
    state.get("names", {}).pop(code, None)
    state.get("active", {}).pop(code, None)
    state.get("people", {}).pop(code, None)
    state.setdefault("reading_cycle_seen", {}).setdefault(lang, [])
    state["reading_cycle_seen"][lang] = [c for c in state["reading_cycle_seen"][lang] if c != code]
    state["reading_pairs"] = [p for p in state.get("reading_pairs", []) if code not in p]
    state["monition_pairs"] = [p for p in state.get("monition_pairs", []) if code not in p]
    # L'historique des programmes déjà validés est volontairement conservé tel quel.
    return True, f"{name} a été retiré définitivement des membres futurs. L'historique passé est conservé."


ensure_loaded()
state = st.session_state.liturgie_state

st.title("⛪ Programme liturgique")
st.caption(f"Version : {APP_VERSION}")
st.write("Programmation automatique — les codes techniques restent en arrière-plan, seuls les noms sont affichés.")

home_tab, generate_tab, members_tab, history_tab = st.tabs(["🏠 Accueil", "✨ Générer", "👥 Membres", "🕘 Historique"])

with home_tab:
    c1, c2, c3 = st.columns(3)
    c1.metric("Francophones actifs", len(active_codes(state, "FR")))
    c2.metric("Mooréphones actifs", len(active_codes(state, "MO")))
    c3.metric("Célébrations validées", len(state.get("history", [])))

    if supabase_ready():
        st.success("☁️ Persistance Supabase configurée.")
    else:
        st.warning("☁️ Persistance Supabase non configurée : les données ne survivront pas à un redémarrage.")

    if st.session_state.get("supabase_message"):
        st.caption(st.session_state.supabase_message)

    st.info(
        "Règles actives : alternance FR/MO des 1re et 2e lectures ; alternance individuelle "
        "Lecture ↔ Monition/P.U. au prochain passage ; équité des intervalles ; binômes non figés ; "
        "annonces indépendantes et sans cumul de fonction le même dimanche."
    )

    if st.button("🔄 Recharger depuis Supabase"):
        remote, message = load_remote_state()
        if remote:
            st.session_state.liturgie_state = remote
            st.session_state.supabase_message = message
            st.rerun()
        st.error(message)

with members_tab:
    st.subheader("👥 Membres")
    st.info(
        "La disponibilité agit sur les prochaines générations : un membre marqué Absent est exclu automatiquement. "
        "Quand il redevient Actif, il reprend sa rotation avec ses compteurs et sa prochaine fonction conservés."
    )

    fr_codes = member_codes(state, "FR")
    mo_codes = member_codes(state, "MO")
    fr_text = st.text_area(
        f"Francophones — {len(fr_codes)} noms",
        value=names_text(state, fr_codes),
        height=max(180, min(420, 34 * max(5, len(fr_codes)))),
        key="fr_names",
    )
    mo_text = st.text_area(
        f"Mooréphones — {len(mo_codes)} noms",
        value=names_text(state, mo_codes),
        height=max(160, min(380, 34 * max(5, len(mo_codes)))),
        key="mo_names",
    )

    if st.button("💾 Enregistrer les noms", type="primary"):
        ok_fr, msg_fr = apply_names_text(state, fr_codes, fr_text)
        ok_mo, msg_mo = apply_names_text(state, mo_codes, mo_text)
        if ok_fr and ok_mo:
            st.session_state.liturgie_state = state
            if persist(show_success=True):
                st.rerun()
        else:
            if not ok_fr:
                st.error(msg_fr)
            if not ok_mo:
                st.error(msg_mo)

    st.divider()
    st.subheader("Présence / absence temporaire")
    st.caption("☑️ Actif = peut être programmé. ☐ Absent = retiré de toute nouvelle programmation, sans perdre son historique ni sa rotation.")
    with st.expander("✅ Actifs / ⛔ Absents", expanded=False):
        with st.form("availability_form"):
            availability = {}
            for lang, label in (("FR", "Francophones"), ("MO", "Mooréphones")):
                st.markdown(f"**{label}**")
                for code in member_codes(state, lang):
                    availability[code] = st.checkbox(
                        state["names"].get(code, code),
                        value=state["active"].get(code, True),
                        key=f"active_{code}",
                    )
            save_availability = st.form_submit_button("💾 Enregistrer les statuts")
        if save_availability:
            for code, is_active in availability.items():
                state["active"][code] = bool(is_active)
            st.session_state.liturgie_state = state
            if persist(show_success=True):
                st.rerun()

    st.divider()
    st.subheader("➕ Ajouter un nouveau membre")
    with st.form("add_member_form", clear_on_submit=True):
        new_lang_label = st.radio("Catégorie", ["Francophone", "Mooréphone"], horizontal=True)
        new_name = st.text_input("Nom du nouveau membre")
        add_clicked = st.form_submit_button("➕ Ajouter comme membre actif", type="primary")
    if add_clicked:
        new_lang = "FR" if new_lang_label == "Francophone" else "MO"
        ok, message, _ = add_member(state, new_lang, new_name)
        if ok:
            st.session_state.liturgie_state = state
            if persist(show_success=False):
                st.success(message)
                st.rerun()
        else:
            st.error(message)

    st.divider()
    st.subheader("🗑️ Retirer définitivement un membre")
    st.warning(
        "Le retrait définitif supprime le membre de toutes les programmations futures. "
        "Les programmes déjà enregistrés dans l'historique restent inchangés."
    )
    options = member_codes(state)
    if options:
        remove_code = st.selectbox(
            "Membre à retirer",
            options,
            format_func=lambda c: f"{state['names'].get(c, c)} — {'Français' if c.startswith('F') else 'Mooré'}",
            key="remove_member_code",
        )
        confirm_remove = st.checkbox(
            f"Je confirme le retrait définitif de {state['names'].get(remove_code, remove_code)}",
            key="confirm_remove_member",
        )
        if st.button("🗑️ Retirer définitivement", disabled=not confirm_remove):
            ok, message = remove_member_permanently(state, remove_code)
            if ok:
                st.session_state.liturgie_state = state
                if persist(show_success=False):
                    st.success(message)
                    st.rerun()
            else:
                st.error(message)

with generate_tab:
    st.subheader("1. Choisir la période")
    col1, col2 = st.columns(2)
    with col1:
        year = int(st.number_input("Année", min_value=2020, max_value=2100, value=2026, step=1))
    with col2:
        month = st.selectbox("Mois", range(1, 13), index=8, format_func=lambda m: MONTHS[m - 1])

    month_sundays = sundays(year, month)
    st.subheader("2. Références bibliques")
    ref_mode = st.radio(
        "Source des références",
        ["Automatique - AELF", "Saisie manuelle"],
        horizontal=True,
        key=f"ref_mode_{year}_{month}",
    )

    refs_text = ""
    aelf_zone = "romain"
    preview_key = None
    if ref_mode == "Automatique - AELF":
        zone_label = st.selectbox(
            "Calendrier AELF",
            list(AELF_ZONES.keys()),
            index=0,
            help="Le calendrier romain convient aux dimanches ordinaires. Choisissez une autre zone si votre calendrier local l'exige.",
        )
        aelf_zone = AELF_ZONES[zone_label]
        st.info("📖 Les références des dimanches seront récupérées automatiquement depuis l'API AELF au moment de la génération. Aucun copier-coller n'est nécessaire.")
        preview_key = f"aelf_preview_{year}_{month}_{aelf_zone}"
        if st.button("🔎 Prévisualiser les références AELF"):
            with st.spinner("Récupération des références AELF..."):
                preview_refs, preview_errors = fetch_month_aelf_refs(month_sundays, aelf_zone)
            st.session_state[preview_key] = (preview_refs, preview_errors)
        if preview_key in st.session_state:
            preview_refs, preview_errors = st.session_state[preview_key]
            st.dataframe(
                [
                    {
                        "Dimanche": d.strftime("%d/%m/%Y"),
                        "1re lecture": preview_refs.get(d.isoformat(), {}).get("r1", ""),
                        "2e lecture": preview_refs.get(d.isoformat(), {}).get("r2", ""),
                        "Évangile": preview_refs.get(d.isoformat(), {}).get("ev", ""),
                    }
                    for d in month_sundays
                ],
                use_container_width=True,
                hide_index=True,
            )
            if preview_errors:
                st.warning("Certaines références n'ont pas pu être récupérées : " + "; ".join(f"{k}: {v}" for k, v in preview_errors.items()))
    else:
        st.caption("Mode de secours : saisissez ou corrigez les références manuellement.")
        example = "\n".join(f"{d.isoformat()} |  |  | " for d in month_sundays)
        refs_text = st.text_area(
            "AAAA-MM-JJ | 1re lecture | 2e lecture | Évangile",
            value=example,
            height=max(160, 38 * len(month_sundays)),
            key=f"refs_{year}_{month}",
        )

    st.subheader("3. Paramètres de rotation")
    seed = int(st.number_input("Graine de brassage", min_value=0, max_value=999999, value=2026, step=1))
    first_lang = st.radio(
        "Langue de la prochaine 1re lecture",
        ["FR", "MO"],
        horizontal=True,
        index=0 if state.get("next_first_language", "FR") == "FR" else 1,
    )
    state["next_first_language"] = first_lang

    if st.button("✨ Générer le programme", type="primary"):
        try:
            if ref_mode == "Automatique - AELF":
                with st.spinner("Récupération automatique des références bibliques AELF..."):
                    refs, ref_errors = fetch_month_aelf_refs(month_sundays, aelf_zone)
                if ref_errors:
                    details = "; ".join(f"{day}: {message}" for day, message in ref_errors.items())
                    raise RuntimeError(
                        "Impossible de récupérer toutes les références AELF. "
                        f"{details}. Vous pouvez réessayer ou utiliser le mode Saisie manuelle."
                    )
            else:
                refs = parse_refs(refs_text, month_sundays)
            rows, new_state = generate_month(state, year, month, refs, seed)
            st.session_state.liturgie_state = new_state
            st.session_state.last_rows = rows
            persist(show_success=False)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if st.session_state.get("last_rows"):
        st.subheader("4. Programme généré")
        show_mobile_program(st.session_state.last_rows)
        display_rows = flat_rows(st.session_state.last_rows)
        with st.expander("🖥️ Tableau complet"):
            st.dataframe(display_rows, use_container_width=True, hide_index=True)

        c_csv, c_xlsx, c_pdf = st.columns(3)
        with c_csv:
            st.download_button(
                "⬇️ CSV",
                data=csv_bytes(st.session_state.last_rows),
                file_name=f"programme_liturgique_{year}_{month:02d}.csv",
                mime="text/csv",
            )
        with c_xlsx:
            st.download_button(
                "📊 Excel A4 paysage",
                data=xlsx_bytes(
                    st.session_state.last_rows,
                    state,
                    title=f"Programme liturgique - {MONTHS[month - 1]} {year}",
                ),
                file_name=f"programme_liturgique_{year}_{month:02d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with c_pdf:
            st.download_button(
                "🖨️ PDF impression",
                data=pdf_bytes(
                    st.session_state.last_rows,
                    title=f"Programme liturgique - {MONTHS[month - 1]} {year}",
                ),
                file_name=f"programme_liturgique_{year}_{month:02d}.pdf",
                mime="application/pdf",
            )

    st.subheader("5. Contrôle de la rotation")
    control = rotation_rows(state)
    st.dataframe(control, use_container_width=True, hide_index=True)

with history_tab:
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
        "dates de passage, prochaines fonctions et binômes à zéro. La liste des membres, leurs noms "
        "et leurs statuts Actif/Absent sont conservés."
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

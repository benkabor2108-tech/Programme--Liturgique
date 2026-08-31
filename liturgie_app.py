import calendar
import csv
import io
import hmac
import hashlib
import json
import random
import re
import secrets
import unicodedata
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
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

APP_VERSION = "2026.08.31-persistant-supabase-v3.9.3-partage-qr"
TABLE_NAME = "liturgie_state"
APP_PUBLIC_URL = "https://programme--liturgique-e39juey35cfq23az2qvup5.streamlit.app/"
AELF_API_BASE = "https://api.aelf.org/v1"
APP_TIMEZONE = ZoneInfo("Africa/Ouagadougou")
ATTENDANCE_OPEN_TIME = time(18, 30)
ATTENDANCE_CLOSE_TIME = time(23, 59, 59)
ATTENDANCE_MIN_COUNT = 2
ATTENDANCE_MAX_J = 2  # 3 J ou plus = non éligible le mois suivant.
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

DEFAULT_WHATSAPP_TEMPLATES = {
    "mercredi": (
        "Bonjour {nom},\n\n"
        "Premier rappel pour le dimanche {date}.\n"
        "Vous assurerez : {role}.\n\n"
        "Merci de bien vouloir confirmer la réception de ce message.\n"
        "Que Dieu vous bénisse dans ce service. 🙏"
    ),
    "vendredi": (
        "Bonjour {nom},\n\n"
        "Deuxième rappel pour ce dimanche {date}.\n"
        "Votre service prévu est : {role}.\n\n"
        "Merci de prendre les dispositions nécessaires pour être à l’heure.\n"
        "Que Dieu vous accompagne dans ce service. 🙏"
    ),
}

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
        "attendance": {},
        "attendance_ignored": [],
        "auth_security": {},
        "whatsapp_contacts": {code: {"number": "", "consent": False, "enabled": False} for code in FR + MO},
        "whatsapp_templates": deepcopy(DEFAULT_WHATSAPP_TEMPLATES),
        "whatsapp_send_log": {},
        "audit_log": [],
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
        "attendance": {},
        "attendance_ignored": [],
        "auth_security": {},
        "whatsapp_contacts": {},
        "whatsapp_templates": deepcopy(DEFAULT_WHATSAPP_TEMPLATES),
        "whatsapp_send_log": {},
        "audit_log": [],
    }

    raw_names = raw.get("names", {}) if isinstance(raw.get("names"), dict) else {}
    raw_active = raw.get("active", {}) if isinstance(raw.get("active"), dict) else {}
    raw_people = raw.get("people", {}) if isinstance(raw.get("people"), dict) else {}
    raw_whatsapp = raw.get("whatsapp_contacts", {}) if isinstance(raw.get("whatsapp_contacts"), dict) else {}
    raw_templates = raw.get("whatsapp_templates", {}) if isinstance(raw.get("whatsapp_templates"), dict) else {}
    for kind in ("mercredi", "vendredi"):
        candidate = str(raw_templates.get(kind, "")).strip()
        state["whatsapp_templates"][kind] = candidate or DEFAULT_WHATSAPP_TEMPLATES[kind]

    for code in member_codes(state):
        state["names"][code] = str(raw_names.get(code) or DEFAULT_NAMES.get(code) or code).strip()
        state["active"][code] = bool(raw_active.get(code, True))
        state["people"][code] = blank_person()
        if isinstance(raw_people.get(code), dict):
            state["people"][code].update(raw_people[code])
        contact = raw_whatsapp.get(code, {}) if isinstance(raw_whatsapp.get(code), dict) else {}
        state["whatsapp_contacts"][code] = {
            "number": str(contact.get("number", "")).strip(),
            "consent": bool(contact.get("consent", False)),
            "enabled": bool(contact.get("enabled", False)),
        }

    raw_next = raw.get("next_member_number", {}) if isinstance(raw.get("next_member_number"), dict) else {}
    for lang in ("FR", "MO"):
        highest = max([code_number(c) for c in member_codes(state, lang)] or [0])
        requested = raw_next.get(lang, highest + 1)
        try:
            requested = int(requested)
        except Exception:
            requested = highest + 1
        state["next_member_number"][lang] = max(highest + 1, requested)

    for key in ["reading_cycle_seen", "reading_pairs", "monition_pairs", "next_first_language", "history", "attendance", "attendance_ignored", "auth_security", "whatsapp_send_log", "audit_log"]:
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


def normalize_whatsapp_number(value):
    """Normalise un numéro au format international E.164 simplifié (+ puis chiffres)."""
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    cleaned = re.sub(r"[\s().-]+", "", raw)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if not cleaned.startswith("+"):
        return "", "Le numéro doit commencer par + et l'indicatif du pays, par exemple +226."
    digits = cleaned[1:]
    if not digits.isdigit() or not (8 <= len(digits) <= 15):
        return "", "Numéro WhatsApp invalide. Utilisez le format international, par exemple +226XXXXXXXX."
    return "+" + digits, ""


def whatsapp_contact(state, code):
    state.setdefault("whatsapp_contacts", {})
    contact = state["whatsapp_contacts"].setdefault(code, {"number": "", "consent": False, "enabled": False})
    contact.setdefault("number", "")
    contact.setdefault("consent", False)
    contact.setdefault("enabled", False)
    return contact


def whatsapp_role_for_code(row, code):
    codes = row.get("codes", {}) if isinstance(row.get("codes"), dict) else {}
    lang = "Français" if str(code).startswith("F") else "Mooré"
    if codes.get("r1") == code:
        return f"1re lecture — {lang}"
    if codes.get("r2") == code:
        return f"2e lecture — {lang}"
    if codes.get("f_mon") == code or codes.get("m_mon") == code:
        return f"Monition + P.U. — {lang}"
    if codes.get("f_ann") == code or codes.get("m_ann") == code:
        return f"Annonces — {lang}"
    return ""


def next_published_sunday(state, reference_day=None):
    reference_day = reference_day or now_ouaga().date()
    candidates = []
    for row in state.get("history", []) or []:
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except Exception:
            continue
        if day >= reference_day:
            candidates.append((day, row))
    return min(candidates, key=lambda item: item[0]) if candidates else (None, None)




def whatsapp_cloud_config():
    """
    Lit la configuration future de la WhatsApp Business Platform.
    Aucun secret n'est affiché dans l'interface.
    Tant que enabled=False ou que la configuration est incomplète,
    aucun envoi automatique n'est possible.
    """
    try:
        cfg = st.secrets.get("whatsapp_cloud_api", {})
    except Exception:
        cfg = {}

    return {
        "enabled": bool(cfg.get("enabled", False)),
        "graph_api_version": str(cfg.get("graph_api_version", "")).strip(),
        "phone_number_id": str(cfg.get("phone_number_id", "")).strip(),
        "access_token": str(cfg.get("access_token", "")).strip(),
        "template_wednesday": str(cfg.get("template_wednesday", "")).strip(),
        "template_friday": str(cfg.get("template_friday", "")).strip(),
        "template_language": str(cfg.get("template_language", "fr")).strip() or "fr",
    }


def whatsapp_cloud_readiness(config):
    required = {
        "Version API": bool(config.get("graph_api_version")),
        "Identifiant du numéro WhatsApp Business": bool(config.get("phone_number_id")),
        "Jeton d'accès": bool(config.get("access_token")),
        "Modèle du mercredi": bool(config.get("template_wednesday")),
        "Modèle du vendredi": bool(config.get("template_friday")),
    }
    complete = all(required.values())
    active = bool(config.get("enabled")) and complete
    return required, complete, active


def whatsapp_template_name(config, reminder_kind):
    return (
        config.get("template_friday", "")
        if reminder_kind == "vendredi"
        else config.get("template_wednesday", "")
    )


def build_whatsapp_automation_jobs(state, sunday, row):
    """
    Construit les travaux que le futur ordonnanceur devra exécuter.
    Cette fonction ne transmet aucun message.
    """
    reminder_dates = whatsapp_reminder_dates(sunday)
    codes = row.get("codes", {}) if isinstance(row.get("codes"), dict) else {}
    ordered_codes = [codes.get(k) for k in ("r1", "r2", "f_mon", "m_mon", "f_ann", "m_ann")]
    send_log = state.get("whatsapp_send_log", {}) if isinstance(state.get("whatsapp_send_log"), dict) else {}
    jobs = []

    for reminder_kind in ("mercredi", "vendredi"):
        scheduled_at = datetime.combine(
            reminder_dates[reminder_kind],
            time(18, 30),
            tzinfo=APP_TIMEZONE,
        )
        for code in ordered_codes:
            if not code:
                continue
            contact = state.get("whatsapp_contacts", {}).get(code, {})
            if not isinstance(contact, dict):
                contact = {}
            number = str(contact.get("number", "")).strip()
            consent = bool(contact.get("consent", False))
            enabled = bool(contact.get("enabled", False))
            ready = bool(number and consent and enabled)
            send_key = whatsapp_send_key(sunday, reminder_kind, code)
            jobs.append({
                "member_code": code,
                "member_name": state.get("names", {}).get(code, code),
                "role": whatsapp_role_for_code(row, code),
                "reminder_kind": reminder_kind,
                "scheduled_at": scheduled_at,
                "number": number,
                "ready": ready,
                "already_sent": send_key in send_log,
                "send_key": send_key,
            })
    return jobs


def due_whatsapp_automation_jobs(state, reference_time=None):
    """
    Retourne uniquement les travaux arrivés à échéance et encore non envoyés.
    Cette fonction ne transmet aucun message.
    """
    reference_time = reference_time or now_ouaga()
    sunday, row = next_published_sunday(state, reference_day=reference_time.date())
    if not row:
        return []
    jobs = build_whatsapp_automation_jobs(state, sunday, row)
    return [
        job for job in jobs
        if job["ready"]
        and not job["already_sent"]
        and job["scheduled_at"] <= reference_time
    ]


def whatsapp_cloud_send_template(config, number, template_name, language_code, name, sunday, role):
    """
    Adaptateur futur pour Meta Cloud API.
    IMPORTANT : cette fonction n'est jamais appelée par l'interface tant que
    l'automatisation n'est pas explicitement activée et qu'un ordonnanceur
    externe n'est pas branché.
    Le modèle futur devra accepter 3 paramètres texte : nom, date, rôle.
    """
    required, complete, active = whatsapp_cloud_readiness(config)
    if not active:
        return False, "Automatisation désactivée ou configuration incomplète."

    digits = re.sub(r"\\D", "", str(number or ""))
    if not digits:
        return False, "Numéro WhatsApp invalide."

    version = str(config["graph_api_version"]).lstrip("/")
    endpoint = (
        f"https://graph.facebook.com/{version}/"
        f"{config['phone_number_id']}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": digits,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": str(name)},
                    {"type": "text", "text": sunday.strftime("%d/%m/%Y")},
                    {"type": "text", "text": str(role)},
                ],
            }],
        },
    }
    headers = {
        "Authorization": f"Bearer {config['access_token']}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=20)
        if response.ok:
            return True, "Message accepté par la plateforme WhatsApp."
        return False, f"Erreur WhatsApp API HTTP {response.status_code}."
    except Exception as exc:
        return False, f"Connexion WhatsApp API impossible : {exc}"


def render_whatsapp_automation_ready(state):
    """
    Tableau de bord de préparation à l'automatisation complète.
    Il est volontairement en mode simulation tant que l'API et l'ordonnanceur
    ne sont pas activés.
    """
    st.subheader("🤖 Automatisation complète — préparation")
    config = whatsapp_cloud_config()
    required, complete, active = whatsapp_cloud_readiness(config)

    if active:
        st.success("API WhatsApp configurée et autorisée côté application.")
    else:
        st.info(
            "Mode sécurisé : automatisation désactivée. "
            "Aucun message WhatsApp ne peut partir automatiquement depuis cette version."
        )

    checklist_rows = [
        {"Élément": label, "État": "Prêt ✅" if ok else "À configurer"}
        for label, ok in required.items()
    ]
    checklist_rows.append({
        "Élément": "Activation explicite de l'automatisation",
        "État": "Activée ✅" if config.get("enabled") else "Désactivée 🔒",
    })
    checklist_rows.append({
        "Élément": "Ordonnanceur externe mercredi/vendredi 18 h 30",
        "État": "À brancher",
    })
    st.dataframe(checklist_rows, use_container_width=True, hide_index=True)

    sunday, row = next_published_sunday(state)
    if not row:
        st.caption("Aucun dimanche futur publié pour simuler le moteur.")
        return

    jobs = build_whatsapp_automation_jobs(state, sunday, row)
    sim_rows = []
    for job in jobs:
        sim_rows.append({
            "Quand": job["scheduled_at"].strftime("%d/%m/%Y %H:%M"),
            "Membre": job["member_name"],
            "Rôle": job["role"],
            "État": (
                "Déjà envoyé ✅"
                if job["already_sent"]
                else ("Prêt" if job["ready"] else "À configurer")
            ),
        })

    with st.expander("🧪 Simulation du futur ordonnanceur", expanded=False):
        st.caption(
            "Cette simulation montre ce que l'automatisation devra envoyer. "
            "Elle n'appelle aucune API et n'envoie aucun message."
        )
        st.dataframe(sim_rows, use_container_width=True, hide_index=True)

        ready_jobs = [j for j in jobs if j["ready"] and not j["already_sent"]]
        st.success(
            f"{len(ready_jobs)} travail(aux) prêt(s) dans la file future "
            f"pour le dimanche {sunday.strftime('%d/%m/%Y')}."
        )

        st.markdown(
            "**Pour passer à l'envoi automatique plus tard :** "
            "il restera à renseigner les identifiants API réels, faire approuver "
            "les deux modèles WhatsApp, puis brancher un ordonnanceur fiable. "
            "Aucun secret n'est nécessaire aujourd'hui."
        )


def whatsapp_click_to_chat_url(number, message):
    """Construit un lien wa.me sans exposer le numéro dans l'interface."""
    digits = re.sub(r"\\D", "", str(number or ""))
    if not digits:
        return ""
    return f"https://wa.me/{digits}?text={quote(str(message), safe='')}"


def whatsapp_reminder_message(state, name, sunday, role, reminder_kind="mercredi"):
    """Construit le message à partir du modèle officiel enregistré."""
    templates = state.get("whatsapp_templates", {}) if isinstance(state.get("whatsapp_templates"), dict) else {}
    template = str(templates.get(reminder_kind, "")).strip() or DEFAULT_WHATSAPP_TEMPLATES[reminder_kind]
    return (
        template
        .replace("{nom}", str(name))
        .replace("{date}", sunday.strftime("%d/%m/%Y"))
        .replace("{role}", str(role))
    )


def validate_whatsapp_template(template):
    required = ("{nom}", "{date}", "{role}")
    missing = [placeholder for placeholder in required if placeholder not in str(template)]
    return missing


def render_whatsapp_template_editor(state):
    st.subheader("✍️ Modèles officiels de rappel")
    st.caption(
        "Seul l'administrateur principal peut modifier ces textes. "
        "Conservez obligatoirement les variables {nom}, {date} et {role} : "
        "elles sont remplacées automatiquement lors de la préparation du message."
    )

    current = state.get("whatsapp_templates", {}) if isinstance(state.get("whatsapp_templates"), dict) else {}
    wednesday = str(current.get("mercredi", "")).strip() or DEFAULT_WHATSAPP_TEMPLATES["mercredi"]
    friday = str(current.get("vendredi", "")).strip() or DEFAULT_WHATSAPP_TEMPLATES["vendredi"]

    with st.form("whatsapp_templates_form"):
        edited_wednesday = st.text_area(
            "Mercredi — premier rappel",
            value=wednesday,
            height=220,
            key="wa_template_wednesday",
        )
        edited_friday = st.text_area(
            "Vendredi — deuxième rappel",
            value=friday,
            height=220,
            key="wa_template_friday",
        )
        save_templates = st.form_submit_button("💾 Enregistrer les modèles", type="primary")

    if save_templates:
        errors = []
        for label, candidate in (
            ("Mercredi", edited_wednesday),
            ("Vendredi", edited_friday),
        ):
            missing = validate_whatsapp_template(candidate)
            if missing:
                errors.append(f"{label} : variable(s) manquante(s) : {', '.join(missing)}")
            if not str(candidate).strip():
                errors.append(f"{label} : le message ne peut pas être vide.")

        if errors:
            for error in errors:
                st.error(error)
        else:
            state["whatsapp_templates"] = {
                "mercredi": str(edited_wednesday).strip(),
                "vendredi": str(edited_friday).strip(),
            }
            state.setdefault("audit_log", []).append({
                "type": "whatsapp_templates_updated",
                "timestamp": now_ouaga().isoformat(),
                "actor": "Administrateur principal",
            })
            st.session_state.liturgie_state = state
            if persist(show_success=False):
                st.success("Modèles WhatsApp enregistrés.")
                st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("↩️ Restaurer le modèle du mercredi", use_container_width=True):
            state.setdefault("whatsapp_templates", {})["mercredi"] = DEFAULT_WHATSAPP_TEMPLATES["mercredi"]
            st.session_state.liturgie_state = state
            if persist(show_success=False):
                st.rerun()
    with col2:
        if st.button("↩️ Restaurer le modèle du vendredi", use_container_width=True):
            state.setdefault("whatsapp_templates", {})["vendredi"] = DEFAULT_WHATSAPP_TEMPLATES["vendredi"]
            st.session_state.liturgie_state = state
            if persist(show_success=False):
                st.rerun()

    st.markdown("**Aperçu avec des exemples**")
    example_date = date(2026, 10, 4)
    st.text_area(
        "Aperçu mercredi",
        value=whatsapp_reminder_message(state, "Mme EXEMPLE", example_date, "1re lecture — Français", "mercredi"),
        height=190,
        disabled=True,
        key="wa_template_preview_wednesday",
    )
    st.text_area(
        "Aperçu vendredi",
        value=whatsapp_reminder_message(state, "Mme EXEMPLE", example_date, "1re lecture — Français", "vendredi"),
        height=190,
        disabled=True,
        key="wa_template_preview_friday",
    )


def whatsapp_reminder_dates(sunday):
    return {
        "mercredi": sunday - timedelta(days=4),
        "vendredi": sunday - timedelta(days=2),
    }


def whatsapp_send_key(sunday, reminder_kind, code):
    return f"{sunday.isoformat()}|{reminder_kind}|{code}"


def whatsapp_actor_label():
    if globals().get("IS_ADMIN", False):
        return "Administrateur principal"
    if globals().get("IS_ADJOINT", False):
        return "Administrateur adjoint"
    return "Consultation"


def mark_whatsapp_reminder_sent(state, sunday, reminder_kind, code, sent=True):
    log = state.setdefault("whatsapp_send_log", {})
    key = whatsapp_send_key(sunday, reminder_kind, code)
    if sent:
        stamp = now_ouaga().isoformat()
        log[key] = {
            "status": "sent",
            "sent_at": stamp,
            "actor": whatsapp_actor_label(),
        }
        state.setdefault("audit_log", []).append({
            "type": "whatsapp_reminder_sent",
            "date": sunday.isoformat(),
            "reminder": reminder_kind,
            "member": code,
            "timestamp": stamp,
            "actor": whatsapp_actor_label(),
        })
    else:
        previous = log.pop(key, None)
        stamp = now_ouaga().isoformat()
        state.setdefault("audit_log", []).append({
            "type": "whatsapp_reminder_unmark",
            "date": sunday.isoformat(),
            "reminder": reminder_kind,
            "member": code,
            "timestamp": stamp,
            "actor": whatsapp_actor_label(),
            "previous": previous or {},
        })


def render_whatsapp_reminder_sender(state):
    """
    Prépare les rappels du prochain dimanche publié et garde la trace des envois.
    Les numéros restent masqués : ils servent uniquement à construire le lien WhatsApp.
    """
    next_day, next_row = next_published_sunday(state)
    if not next_row:
        st.info("Aucun dimanche futur publié dans l'historique pour préparer un rappel.")
        return

    reminder_dates = whatsapp_reminder_dates(next_day)
    st.write(f"**Prochain dimanche publié : {next_day.strftime('%d/%m/%Y')}**")
    st.caption(
        "Envoi assisté sans Meta Cloud API : le message est préparé automatiquement, "
        "WhatsApp s'ouvre sur le bon destinataire, puis vous appuyez sur Envoyer. "
        "L'application conserve ensuite votre confirmation d'envoi."
    )

    reminder_kind = st.radio(
        "Rappel à préparer",
        ["mercredi", "vendredi"],
        horizontal=True,
        format_func=lambda kind: (
            f"{'Mercredi' if kind == 'mercredi' else 'Vendredi'} "
            f"{reminder_dates[kind].strftime('%d/%m/%Y')} à 18 h 30"
        ),
        key=f"wa_reminder_kind_{next_day.isoformat()}",
    )
    reminder_day = reminder_dates[reminder_kind]
    st.info(
        f"📅 Rappel sélectionné : "
        f"{'mercredi' if reminder_kind == 'mercredi' else 'vendredi'} "
        f"{reminder_day.strftime('%d/%m/%Y')} à 18 h 30."
    )

    codes = next_row.get("codes", {}) if isinstance(next_row.get("codes"), dict) else {}
    ordered_codes = [codes.get(k) for k in ("r1", "r2", "f_mon", "m_mon", "f_ann", "m_ann")]

    preview_rows = []
    ready_items = []
    log = state.get("whatsapp_send_log", {}) if isinstance(state.get("whatsapp_send_log"), dict) else {}

    for code in ordered_codes:
        if not code:
            continue
        contact = state.get("whatsapp_contacts", {}).get(code, {})
        if not isinstance(contact, dict):
            contact = {}
        number = str(contact.get("number", "")).strip()
        consent = bool(contact.get("consent", False))
        enabled = bool(contact.get("enabled", False))
        ready = bool(number and consent and enabled)
        role = whatsapp_role_for_code(next_row, code)
        name = state.get("names", {}).get(code, code)
        sent = whatsapp_send_key(next_day, reminder_kind, code) in log

        if sent:
            status = "Envoyé ✅"
        elif ready:
            status = "Prêt ✅"
        else:
            status = "À configurer"

        preview_rows.append({
            "Membre": name,
            "Rôle": role,
            "WhatsApp": status,
        })
        if ready:
            ready_items.append((code, name, role, number, sent))

    st.dataframe(preview_rows, use_container_width=True, hide_index=True)

    if not ready_items:
        st.warning(
            "Aucun membre programmé n'est encore prêt pour l'envoi. "
            "L'administrateur principal doit enregistrer le numéro, le consentement "
            "et activer les rappels WhatsApp."
        )
        return

    st.markdown("**Messages prêts à envoyer**")
    for code, name, role, number, sent in ready_items:
        message = whatsapp_reminder_message(state, name, next_day, role, reminder_kind)
        url = whatsapp_click_to_chat_url(number, message)
        send_key = whatsapp_send_key(next_day, reminder_kind, code)
        send_info = log.get(send_key, {}) if isinstance(log.get(send_key), dict) else {}

        with st.container(border=True):
            st.markdown(f"**{name}**")
            st.caption(role)

            if sent:
                sent_at = str(send_info.get("sent_at", ""))
                try:
                    sent_label = datetime.fromisoformat(sent_at).astimezone(APP_TIMEZONE).strftime("%d/%m/%Y à %H:%M")
                except Exception:
                    sent_label = "date non disponible"
                st.success(
                    f"✅ Rappel marqué comme envoyé le {sent_label} "
                    f"par {send_info.get('actor', 'administrateur')}."
                )

            st.text_area(
                "Message préparé",
                value=message,
                height=145,
                disabled=True,
                key=f"wa_message_{next_day.isoformat()}_{reminder_kind}_{code}",
            )
            st.link_button(
                f"📲 Ouvrir WhatsApp pour {name}",
                url,
                use_container_width=True,
            )

            if not sent:
                if st.button(
                    "✅ Marquer ce rappel comme envoyé",
                    key=f"wa_mark_sent_{next_day.isoformat()}_{reminder_kind}_{code}",
                    use_container_width=True,
                ):
                    mark_whatsapp_reminder_sent(state, next_day, reminder_kind, code, sent=True)
                    st.session_state.liturgie_state = state
                    if persist(show_success=False):
                        st.success("Envoi enregistré.")
                        st.rerun()
            else:
                if st.button(
                    "↩️ Annuler le marquage d'envoi",
                    key=f"wa_unmark_sent_{next_day.isoformat()}_{reminder_kind}_{code}",
                    use_container_width=True,
                ):
                    mark_whatsapp_reminder_sent(state, next_day, reminder_kind, code, sent=False)
                    st.session_state.liturgie_state = state
                    if persist(show_success=False):
                        st.rerun()

    sent_count = sum(1 for _, _, _, _, sent in ready_items if sent)
    st.success(
        f"{len(ready_items)} rappel(s) configuré(s) pour ce créneau ; "
        f"{sent_count} déjà marqué(s) comme envoyé(s). Les numéros restent masqués sur cet écran."
    )


def active_codes(state, lang):
    return [c for c in member_codes(state, lang) if state["active"].get(c, True)]


def now_ouaga():
    return datetime.now(APP_TIMEZONE)


def previous_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def latest_saturday(day):
    days_back = (day.weekday() - 5) % 7
    return day - timedelta(days=days_back)


def attendance_window(saturday):
    start = datetime.combine(saturday, ATTENDANCE_OPEN_TIME, tzinfo=APP_TIMEZONE)
    close_day = saturday + timedelta(days=1)
    end = datetime.combine(close_day, ATTENDANCE_CLOSE_TIME, tzinfo=APP_TIMEZONE)
    return start, end


def attendance_is_open(saturday, moment=None):
    moment = moment or now_ouaga()
    start, end = attendance_window(saturday)
    return start <= moment <= end


def attendance_sheet_key(saturday):
    return saturday.isoformat()


def attendance_sheets_for_month(state, year, month):
    result = []
    for key, sheet in (state.get("attendance", {}) or {}).items():
        try:
            d = date.fromisoformat(str(sheet.get("date") or key))
        except Exception:
            continue
        if d.year == year and d.month == month:
            result.append((d, sheet))
    return sorted(result, key=lambda item: item[0])


def new_attendance_sheet(state, saturday, actor="system"):
    codes = [c for c in member_codes(state) if state.get("active", {}).get(c, True)]
    stamp = now_ouaga().isoformat()
    return {
        "date": saturday.isoformat(),
        "members": codes,
        "names": {c: state.get("names", {}).get(c, c) for c in codes},
        "statuses": {c: "" for c in codes},
        "created_at": stamp,
        "created_by": actor,
        "updated_at": stamp,
        "updated_by": actor,
    }


def ensure_attendance_sheet(state, saturday, actor="system"):
    state.setdefault("attendance", {})
    key = attendance_sheet_key(saturday)
    created = False
    if key not in state["attendance"]:
        state["attendance"][key] = new_attendance_sheet(state, saturday, actor=actor)
        created = True
    sheet = state["attendance"][key]
    sheet.setdefault("members", [])
    sheet.setdefault("names", {})
    sheet.setdefault("statuses", {})
    # Pendant la fenêtre ouverte, ajouter les nouveaux membres actifs sans effacer l'historique existant.
    if attendance_is_open(saturday):
        for code in member_codes(state):
            if state.get("active", {}).get(code, True) and code not in sheet["members"]:
                sheet["members"].append(code)
                sheet["names"][code] = state.get("names", {}).get(code, code)
                sheet["statuses"][code] = ""
    return sheet, created


def attendance_actor_label(role):
    return "Administrateur principal" if role == "principal" else "Administrateur adjoint" if role == "adjoint" else "Système"


def save_attendance_sheet(state, saturday, statuses, actor_role, reason=""):
    sheet, _ = ensure_attendance_sheet(state, saturday, actor=attendance_actor_label(actor_role))
    clean = {}
    for code in sheet.get("members", []):
        value = str(statuses.get(code, "")).strip().upper()
        if value not in ("P", "J", "A"):
            return False, f"Le statut de {sheet.get('names', {}).get(code, code)} n'est pas renseigné."
        clean[code] = value

    before = dict(sheet.get("statuses", {}))
    changes = {
        code: {"avant": before.get(code, ""), "après": value}
        for code, value in clean.items()
        if before.get(code, "") != value
    }
    stamp = now_ouaga().isoformat()
    sheet["statuses"] = clean
    sheet["updated_at"] = stamp
    sheet["updated_by"] = attendance_actor_label(actor_role)
    if reason:
        sheet["last_correction_reason"] = str(reason).strip()

    state.setdefault("audit_log", []).append({
        "type": "attendance_update",
        "date": saturday.isoformat(),
        "timestamp": stamp,
        "actor": attendance_actor_label(actor_role),
        "reason": str(reason).strip(),
        "changes": changes,
    })
    return True, "Feuille de présence enregistrée."


def attendance_is_ignored(state, saturday):
    return saturday.isoformat() in set(state.get("attendance_ignored", []) or [])


def delete_attendance_sheet(state, saturday, actor_role, reason="Remise à zéro"): 
    key = attendance_sheet_key(saturday)
    removed = state.setdefault("attendance", {}).pop(key, None)
    ignored = state.setdefault("attendance_ignored", [])
    if key not in ignored:
        ignored.append(key)
    stamp = now_ouaga().isoformat()
    state.setdefault("audit_log", []).append({
        "type": "attendance_delete",
        "date": key,
        "timestamp": stamp,
        "actor": attendance_actor_label(actor_role),
        "reason": str(reason).strip() or "Remise à zéro",
        "had_sheet": bool(removed),
    })
    return True, f"Feuille du {saturday.strftime('%d/%m/%Y')} supprimée. Les présences sont remises à zéro pour cette date."


def restore_attendance_sheet(state, saturday, actor_role):
    key = attendance_sheet_key(saturday)
    state["attendance_ignored"] = [k for k in (state.get("attendance_ignored", []) or []) if k != key]
    sheet, _ = ensure_attendance_sheet(state, saturday, actor=attendance_actor_label(actor_role))
    stamp = now_ouaga().isoformat()
    state.setdefault("audit_log", []).append({
        "type": "attendance_restore",
        "date": key,
        "timestamp": stamp,
        "actor": attendance_actor_label(actor_role),
        "reason": "Réactivation manuelle de la feuille",
        "changes": {},
    })
    return sheet


def attendance_eligibility(state, target_year, target_month):
    prev_year, prev_month = previous_month(target_year, target_month)
    sheets = attendance_sheets_for_month(state, prev_year, prev_month)
    # Pour éviter de pénaliser un mois ancien ou incomplet lors de la migration,
    # la règle automatique s'active à partir de 2 feuilles de présence enregistrées.
    enforced = len(sheets) >= 2
    details = {}
    for code in member_codes(state):
        p_count = j_count = a_count = 0
        for _, sheet in sheets:
            status = str((sheet.get("statuses", {}) or {}).get(code, "")).upper()
            if status == "P":
                p_count += 1
            elif status == "J":
                j_count += 1
            elif status == "A":
                a_count += 1
        counted = p_count + j_count
        eligible = True
        reason = "Règle non activée : moins de 2 feuilles enregistrées."
        if enforced:
            if j_count >= 3:
                eligible = False
                reason = "3 absences justifiées (J) ou plus."
            elif counted < ATTENDANCE_MIN_COUNT:
                eligible = False
                reason = f"Moins de {ATTENDANCE_MIN_COUNT} présences comptabilisées (P + J)."
            else:
                reason = "Critères de présence remplis."
        details[code] = {
            "P": p_count,
            "J": j_count,
            "A": a_count,
            "P+J": counted,
            "eligible": eligible,
            "reason": reason,
        }
    return {
        "enforced": enforced,
        "previous_year": prev_year,
        "previous_month": prev_month,
        "sheet_count": len(sheets),
        "details": details,
    }


def programmable_codes(state, lang, service_date):
    base = active_codes(state, lang)
    eligibility = attendance_eligibility(state, service_date.year, service_date.month)
    if not eligibility["enforced"]:
        return base
    return [c for c in base if eligibility["details"].get(c, {}).get("eligible", True)]


def attendance_summary_rows(state, target_year, target_month):
    eligibility = attendance_eligibility(state, target_year, target_month)
    rows = []
    for code in member_codes(state):
        info = eligibility["details"].get(code, {})
        rows.append({
            "Membre": state.get("names", {}).get(code, code),
            "Langue": "FR" if code.startswith("F") else "MO",
            "P": info.get("P", 0),
            "J": info.get("J", 0),
            "A": info.get("A", 0),
            "P + J": info.get("P+J", 0),
            "Éligible": "✅ Oui" if info.get("eligible", True) else "⛔ Non",
            "Motif": info.get("reason", ""),
        })
    return eligibility, rows


def attendance_sheet_rows(sheet):
    names = sheet.get("names", {}) if isinstance(sheet, dict) else {}
    statuses = sheet.get("statuses", {}) if isinstance(sheet, dict) else {}
    members = sheet.get("members", []) if isinstance(sheet, dict) else []
    rows = []
    for code in members:
        rows.append({
            "Membre": names.get(code, code),
            "Langue": "FR" if str(code).startswith("F") else "MO",
            "Statut": statuses.get(code, "") or "—",
        })
    return rows


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


def reading_pool(state, lang, excluded, service_date):
    codes = programmable_codes(state, lang, service_date)
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
    fr_pool = reading_pool(state, "FR", set(), today)
    mo_pool = reading_pool(state, "MO", set(), today)
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


def monition_pool(state, lang, excluded, service_date):
    return [
        c for c in programmable_codes(state, lang, service_date)
        if c not in excluded
        and state["people"][c]["next_role"] in (None, "MONITION")
    ]


def monition_rank(state, code, today):
    p = state["people"][code]
    return (p["monition_count"], -days_since(p["last_service"], today), code)


def choose_monitions(state, today, excluded, rng):
    fr_pool = monition_pool(state, "FR", excluded, today)
    mo_pool = monition_pool(state, "MO", excluded, today)
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
    pool = [c for c in programmable_codes(state, lang, today) if c not in excluded]
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

    month_days = sundays(year, month)
    reference_day = month_days[0] if month_days else date(year, month, 1)
    if len(programmable_codes(state, "FR", reference_day)) < 3 or len(programmable_codes(state, "MO", reference_day)) < 3:
        raise RuntimeError(
            "Il faut au moins 3 membres éligibles dans chaque langue pour respecter les fonctions sans cumul. "
            "Vérifiez les statuts Actif/Absent et le bilan des présences du mois précédent."
        )

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
    fresh["attendance"] = deepcopy(state.get("attendance", {}))
    fresh["attendance_ignored"] = deepcopy(state.get("attendance_ignored", []))
    fresh["auth_security"] = deepcopy(state.get("auth_security", {}))
    fresh["whatsapp_contacts"] = {
        c: deepcopy(state.get("whatsapp_contacts", {}).get(c, {"number": "", "consent": False, "enabled": False}))
        for c in member_codes(fresh)
    }
    fresh["whatsapp_templates"] = deepcopy(state.get("whatsapp_templates", DEFAULT_WHATSAPP_TEMPLATES))
    fresh["whatsapp_send_log"] = deepcopy(state.get("whatsapp_send_log", {}))
    fresh["audit_log"] = deepcopy(state.get("audit_log", []))
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
    state.setdefault("whatsapp_contacts", {})[code] = {"number": "", "consent": False, "enabled": False}
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
    state.get("whatsapp_contacts", {}).pop(code, None)
    state.setdefault("reading_cycle_seen", {}).setdefault(lang, [])
    state["reading_cycle_seen"][lang] = [c for c in state["reading_cycle_seen"][lang] if c != code]
    state["reading_pairs"] = [p for p in state.get("reading_pairs", []) if code not in p]
    state["monition_pairs"] = [p for p in state.get("monition_pairs", []) if code not in p]
    # L'historique des programmes déjà validés est volontairement conservé tel quel.
    return True, f"{name} a été retiré définitivement des membres futurs. L'historique passé est conservé."


def configured_password(role):
    """Retourne le mot de passe de secours stocké dans Streamlit Secrets.

    Le mot de passe de l'adjoint peut ensuite être remplacé par un hash sécurisé
    conservé dans l'état Supabase. Le principal reste géré par Streamlit Secrets.
    """
    try:
        auth = st.secrets.get("auth", {})
        if role == "principal":
            if "ADMIN_PASSWORD" in st.secrets and str(st.secrets["ADMIN_PASSWORD"]).strip():
                return str(st.secrets["ADMIN_PASSWORD"]).strip()
            value = str(auth.get("admin_password", "")).strip()
            if value:
                return value
        if role == "adjoint":
            value = str(auth.get("adjoint_password", "")).strip()
            if value:
                return value
            if "ADJOINT_PASSWORD" in st.secrets and str(st.secrets["ADJOINT_PASSWORD"]).strip():
                return str(st.secrets["ADJOINT_PASSWORD"]).strip()
    except Exception:
        pass
    return ""


PASSWORD_ITERATIONS = 260_000


def hash_password(password):
    """PBKDF2-SHA256 salé. Aucun mot de passe en clair n'est stocké dans Supabase."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password_hash(password, stored):
    try:
        scheme, iterations, salt_hex, digest_hex = str(stored).split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(password).encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def auth_security(state):
    value = state.setdefault("auth_security", {})
    if not isinstance(value, dict):
        state["auth_security"] = {}
    return state["auth_security"]


def adjoint_password_hash(state):
    return str(auth_security(state).get("adjoint_password_hash", "")).strip()


def adjoint_auth_version(state):
    try:
        return int(auth_security(state).get("adjoint_auth_version", 0))
    except Exception:
        return 0


def adjoint_must_change_password(state):
    return bool(auth_security(state).get("adjoint_must_change_password", False))


def verify_role_password(role, password, state):
    """Vérifie le mot de passe sans jamais exposer le hash ni le secret."""
    if role == "adjoint":
        stored = adjoint_password_hash(state)
        if stored:
            return verify_password_hash(password, stored)
    expected = configured_password(role)
    return bool(expected) and hmac.compare_digest(str(password), expected)


def set_adjoint_password(state, new_password, actor, must_change=False):
    security = auth_security(state)
    security["adjoint_password_hash"] = hash_password(new_password)
    security["adjoint_must_change_password"] = bool(must_change)
    security["adjoint_password_updated_at"] = now_ouaga().isoformat()
    security["adjoint_password_updated_by"] = str(actor)
    security["adjoint_auth_version"] = adjoint_auth_version(state) + 1
    state.setdefault("audit_log", []).append({
        "at": now_ouaga().isoformat(),
        "actor": str(actor),
        "action": "adjoint_password_reset" if must_change else "adjoint_password_change",
    })
    return int(security["adjoint_auth_version"])


def provisional_password(length=10):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def current_role():
    role = st.session_state.get("auth_role", "")
    if role in ("principal", "adjoint"):
        return role
    if st.session_state.get("admin_authenticated", False):
        return "principal"
    return "consultation"


def principal_mode():
    return current_role() == "principal"


def adjoint_mode():
    return current_role() == "adjoint"


def staff_mode():
    return current_role() in ("principal", "adjoint")


def admin_mode():
    """Alias historique : admin = administrateur principal."""
    return principal_mode()


def render_adjoint_self_service(state):
    must_change = adjoint_must_change_password(state)
    if must_change:
        st.warning("🔑 Mot de passe provisoire : choisissez maintenant votre nouveau mot de passe.")
    with st.expander("🔑 Changer mon mot de passe", expanded=must_change):
        with st.form("adjoint_change_password_form", clear_on_submit=True):
            if not must_change:
                current = st.text_input("Mot de passe actuel", type="password", key="adjoint_current_password")
            else:
                current = ""
            new1 = st.text_input("Nouveau mot de passe", type="password", key="adjoint_new_password")
            new2 = st.text_input("Confirmer le nouveau mot de passe", type="password", key="adjoint_confirm_password")
            clicked = st.form_submit_button("💾 Enregistrer mon nouveau mot de passe")
        if clicked:
            if not must_change and not verify_role_password("adjoint", current, state):
                st.error("Le mot de passe actuel est incorrect.")
            elif len(str(new1)) < 8:
                st.error("Le nouveau mot de passe doit contenir au moins 8 caractères.")
            elif new1 != new2:
                st.error("Les deux nouveaux mots de passe ne correspondent pas.")
            elif not must_change and str(new1) == str(current):
                st.error("Choisissez un mot de passe différent de l'ancien.")
            else:
                version = set_adjoint_password(
                    state,
                    str(new1),
                    actor="Administrateur adjoint",
                    must_change=False,
                )
                st.session_state.adjoint_auth_version = version
                st.session_state.liturgie_state = state
                if persist(show_success=False):
                    st.session_state.password_change_notice = "Mot de passe adjoint modifié avec succès."
                    st.rerun()


def render_principal_adjoint_password_tools(state):
    with st.expander("🔑 Réinitialiser le mot de passe de l'adjoint"):
        st.caption(
            "À utiliser seulement si l'adjoint a oublié son mot de passe. "
            "Un code provisoire sera créé ; à sa prochaine connexion, il devra choisir lui-même un nouveau mot de passe."
        )
        with st.form("principal_reset_adjoint_password_form"):
            confirm = st.checkbox("Je confirme la réinitialisation du mot de passe de l'adjoint.")
            clicked = st.form_submit_button("🔄 Créer un mot de passe provisoire")
        if clicked:
            if not confirm:
                st.error("Cochez la confirmation avant la réinitialisation.")
            else:
                temporary = provisional_password()
                set_adjoint_password(
                    state,
                    temporary,
                    actor="Administrateur principal",
                    must_change=True,
                )
                st.session_state.liturgie_state = state
                if persist(show_success=False):
                    st.session_state.adjoint_temp_password = temporary
                    st.rerun()
        temporary = st.session_state.get("adjoint_temp_password", "")
        if temporary:
            st.success("Mot de passe provisoire créé. Communiquez-le uniquement à l'administrateur adjoint.")
            st.code(temporary, language=None)
            st.caption("Ce code est affiché uniquement dans votre session d'administrateur principal.")
            if st.button("🙈 Masquer le code provisoire", key="hide_adjoint_temp_password"):
                st.session_state.pop("adjoint_temp_password", None)
                st.rerun()


def render_admin_login(state):
    """Authentification par session avec deux niveaux de droits et autonomie de l'adjoint."""
    with st.sidebar:
        st.markdown("### 🔐 Accès administrateur")
        role = current_role()

        # Une réinitialisation par le principal invalide les anciennes sessions adjointes.
        if role == "adjoint":
            session_version = st.session_state.get("adjoint_auth_version", adjoint_auth_version(state))
            if int(session_version) != adjoint_auth_version(state):
                st.session_state.auth_role = "consultation"
                st.session_state.admin_authenticated = False
                st.session_state.pop("adjoint_auth_version", None)
                st.warning("Votre mot de passe a été réinitialisé. Reconnectez-vous avec le nouveau code provisoire.")
                role = "consultation"

        if role in ("principal", "adjoint"):
            if role == "principal":
                st.success("Mode administrateur principal actif")
                render_principal_adjoint_password_tools(state)
            else:
                st.success("Mode administrateur adjoint actif")
                st.caption("Droits limités : saisie de la feuille de présence en cours. Les anciennes feuilles restent en lecture seule.")
                if st.session_state.pop("password_change_notice", None):
                    st.success("Mot de passe modifié avec succès.")
                render_adjoint_self_service(state)
            if st.button("🚪 Se déconnecter", key="admin_logout"):
                st.session_state.auth_role = "consultation"
                st.session_state.admin_authenticated = False
                st.session_state.pop("admin_password_input", None)
                st.session_state.pop("adjoint_auth_version", None)
                st.rerun()
        else:
            st.caption("Mode consultation. Connectez-vous uniquement si vous êtes autorisé à modifier des données.")
            profile = st.radio(
                "Profil",
                ["Administrateur principal", "Administrateur adjoint"],
                horizontal=False,
                key="admin_profile_choice",
            )
            password = st.text_input(
                "Mot de passe",
                type="password",
                key="admin_password_input",
            )
            if st.button("🔓 Se connecter", key="admin_login"):
                wanted_role = "principal" if profile == "Administrateur principal" else "adjoint"
                # Distinguer « non configuré » d'un mot de passe incorrect.
                has_adjoint = bool(adjoint_password_hash(state) or configured_password("adjoint"))
                has_principal = bool(configured_password("principal"))
                configured = has_principal if wanted_role == "principal" else has_adjoint
                if not configured:
                    if wanted_role == "adjoint":
                        st.error("Le mot de passe de l'administrateur adjoint n'est pas encore configuré.")
                    else:
                        st.error("Le mot de passe administrateur principal n'est pas encore configuré dans Streamlit Secrets.")
                elif verify_role_password(wanted_role, password, state):
                    st.session_state.auth_role = wanted_role
                    st.session_state.admin_authenticated = wanted_role == "principal"
                    if wanted_role == "adjoint":
                        st.session_state.adjoint_auth_version = adjoint_auth_version(state)
                    st.session_state.pop("admin_password_input", None)
                    st.rerun()
                else:
                    st.error("Mot de passe incorrect.")


ensure_loaded()
state = st.session_state.liturgie_state
render_admin_login(state)
IS_ADMIN = principal_mode()
IS_ADJOINT = adjoint_mode()
CAN_EDIT_ATTENDANCE = staff_mode()

# Création automatique de la feuille pendant la fenêtre samedi 18 h 30 → dimanche 23 h 59.
_now = now_ouaga()
_current_saturday = latest_saturday(_now.date())
_current_attendance_open = attendance_is_open(_current_saturday, _now)
if CAN_EDIT_ATTENDANCE and _current_attendance_open and not attendance_is_ignored(state, _current_saturday):
    _sheet, _created = ensure_attendance_sheet(state, _current_saturday, actor=attendance_actor_label(current_role()))
    if _created:
        st.session_state.liturgie_state = state
        persist(show_success=False)

st.title("⛪ Programme liturgique")
st.caption(f"Version : {APP_VERSION}")
if IS_ADMIN:
    st.success("🔐 Administrateur principal — modifications complètes autorisées")
elif IS_ADJOINT:
    st.success("🔐 Administrateur adjoint — droits limités aux présences en cours")
else:
    st.info("👁️ Consultation uniquement — aucune modification n'est autorisée sur cet appareil.")
st.write("Programmation automatique — les codes techniques restent en arrière-plan, seuls les noms sont affichés.")

if CAN_EDIT_ATTENDANCE and _current_attendance_open and not attendance_is_ignored(state, _current_saturday):
    _notice_key = f"attendance_notice_{_current_saturday.isoformat()}"
    if not st.session_state.get(_notice_key, False):
        @st.dialog("📋 Feuille de présence ouverte")
        def _attendance_notice():
            st.success(f"Feuille du samedi {_current_saturday.strftime('%d/%m/%Y')} ouverte.")
            st.write("Renseignez P, J ou A dans l'onglet **📋 Présences**. La feuille sera verrouillée dimanche à 23 h 59.")
            st.caption("P = présent · J = absence justifiée comptée comme présence · A = absence non justifiée.")
        _attendance_notice()
        st.session_state[_notice_key] = True

home_tab, guide_tab, generate_tab, members_tab, attendance_tab, history_tab = st.tabs(
    ["🏠 Accueil", "ℹ️ Guide", "✨ Générer", "👥 Membres", "📋 Présences", "🕘 Historique"]
)

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
        "annonces indépendantes et sans cumul de fonction le même dimanche. "
        "Présences : P et J comptent ; P + J ≥ 2 pour le mois suivant ; 3 J ou plus = non éligible."
    )

    if st.button("🔄 Actualiser depuis Supabase"):
        remote, message = load_remote_state()
        if remote:
            st.session_state.liturgie_state = remote
            st.session_state.supabase_message = message
            st.session_state.last_rows = []
            st.rerun()
        st.error(message)


with guide_tab:
    st.header("ℹ️ Guide d'utilisation")
    st.write(
        "Cette application facilite l'organisation, la programmation et le suivi du service "
        "liturgique des lecteurs francophones et mooréphones."
    )

    st.subheader("🔗 Lien officiel à conserver et à transmettre")
    st.code(APP_PUBLIC_URL, language=None)
    st.link_button("Ouvrir le lien officiel", APP_PUBLIC_URL, use_container_width=True)

    share_text = (
        "Bonjour 🙏\n\n"
        "Voici le lien officiel de l'application Programme liturgique :\n"
        f"{APP_PUBLIC_URL}\n\n"
        "Vous pouvez conserver ce lien dans vos favoris pour consulter les programmations."
    )
    whatsapp_share_url = f"https://wa.me/?text={quote(share_text)}"
    st.link_button(
        "📤 Partager l'application sur WhatsApp",
        whatsapp_share_url,
        use_container_width=True,
    )

    st.caption(
        "Le même lien reste valable après les mises à jour de l'application. "
        "Il peut être enregistré dans les favoris du téléphone. "
        "L'icône de copie à droite du lien permet également de le copier rapidement."
    )

    with st.expander("📷 QR code de l'application", expanded=False):
        st.write(
            "Un membre peut scanner ce QR code avec l'appareil photo de son téléphone "
            "pour ouvrir directement l'application."
        )
        qr_url = (
            "https://api.qrserver.com/v1/create-qr-code/"
            f"?size=320x320&data={quote(APP_PUBLIC_URL, safe='')}"
        )
        st.image(qr_url, caption="QR code — Programme liturgique", width=320)
        st.caption(
            "Le QR code contient uniquement le lien public de l'application. "
            "Il ne contient aucun mot de passe ni aucune donnée confidentielle."
        )

    st.subheader("👁️ Consultation et droits d'accès")
    st.write(
        "L'application s'ouvre par défaut en mode « Consultation uniquement ». "
        "Les membres peuvent consulter les programmes sans modifier les données. "
        "Les fonctions de gestion restent réservées aux administrateurs autorisés."
    )

    st.subheader("📖 Programmation liturgique")
    st.write(
        "La programmation prend en compte les membres francophones et mooréphones, "
        "les disponibilités, les présences aux répétitions et les règles de rotation. "
        "Elle répartit notamment la 1re lecture, la 2e lecture, la Monition/Prière universelle "
        "et les Annonces."
    )
    st.info(
        "L'historique est conservé afin de favoriser une rotation équitable. "
        "Une absence temporaire n'efface pas le parcours du membre : lorsqu'il redevient actif, "
        "il reprend sa rotation."
    )

    st.subheader("📱 Rappels WhatsApp")
    st.markdown(
        """
**Mercredi à 18 h 30 — Premier rappel**  
Le message indique au membre la date de la célébration et le service qui lui est confié,
avec une demande de confirmation de réception.

**Vendredi à 18 h 30 — Deuxième rappel**  
Un second message rappelle le service prévu afin que le membre puisse prendre les dispositions
nécessaires et être ponctuel.
"""
    )
    st.warning(
        "Mode actuel : l'application prépare le message et ouvre WhatsApp, mais l'envoi final "
        "reste manuel. Le responsable doit encore appuyer sur « Envoyer » dans WhatsApp."
    )

    st.subheader("🤖 Automatisation future")
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

    st.subheader("🙏 Pourquoi cette application est importante")
    st.write(
        "Elle aide à réduire les oublis, améliorer la communication, conserver un historique fiable, "
        "répartir plus équitablement les services et donner à chaque lecteur le temps nécessaire "
        "pour préparer son service de la Parole de Dieu."
    )

    st.subheader("🔐 Bonne pratique de sécurité")
    st.write(
        "Le lien public de consultation peut être communiqué aux membres concernés. "
        "En revanche, les mots de passe administrateurs, les clés techniques, les jetons d'accès "
        "et autres informations confidentielles ne doivent jamais être partagés."
    )

with members_tab:
    st.subheader("👥 Membres")
    fr_codes = member_codes(state, "FR")
    mo_codes = member_codes(state, "MO")

    if not IS_ADMIN:
        st.caption("Liste en lecture seule. Les changements de noms, statuts, ajouts et retraits sont réservés à l'administrateur.")
        member_view = []
        for lang, label in (("FR", "Francophone"), ("MO", "Mooréphone")):
            for code in member_codes(state, lang):
                member_view.append({
                    "Membre": state.get("names", {}).get(code, code),
                    "Catégorie": label,
                    "Statut": "Actif" if state.get("active", {}).get(code, True) else "Absent",
                })
        st.dataframe(member_view, use_container_width=True, hide_index=True)
    else:
        st.info(
            "La disponibilité agit sur les prochaines générations : un membre marqué Absent est exclu automatiquement. "
            "Quand il redevient Actif, il reprend sa rotation avec ses compteurs et sa prochaine fonction conservés."
        )

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
        st.subheader("📱 WhatsApp des membres")
        st.caption(
            "Ces numéros sont visibles uniquement par l'administrateur principal. "
            "Enregistrez le numéro au format international (ex. +226...) et activez les rappels uniquement avec l'accord du membre."
        )
        with st.expander("📱 Numéros et consentements", expanded=False):
            wa_codes = member_codes(state)
            with st.form("whatsapp_contacts_form"):
                wa_inputs = {}
                for lang, label in (("FR", "Francophones"), ("MO", "Mooréphones")):
                    st.markdown(f"**{label}**")
                    for code in member_codes(state, lang):
                        contact = whatsapp_contact(state, code)
                        st.markdown(f"**{state['names'].get(code, code)}**")
                        number = st.text_input(
                            "Numéro WhatsApp",
                            value=contact.get("number", ""),
                            placeholder="+226XXXXXXXX",
                            key=f"wa_number_{code}",
                            label_visibility="collapsed",
                        )
                        consent = st.checkbox(
                            "Consentement reçu",
                            value=bool(contact.get("consent", False)),
                            key=f"wa_consent_{code}",
                        )
                        enabled = st.checkbox(
                            "Rappels WhatsApp activés",
                            value=bool(contact.get("enabled", False)),
                            key=f"wa_enabled_{code}",
                        )
                        wa_inputs[code] = (number, consent, enabled)
                    st.write("")
                save_whatsapp = st.form_submit_button("💾 Enregistrer les numéros WhatsApp", type="primary")

            if save_whatsapp:
                errors = []
                normalized = {}
                for code, (number, consent, enabled) in wa_inputs.items():
                    clean, err = normalize_whatsapp_number(number) if str(number).strip() else ("", "")
                    if err:
                        errors.append(f"{state['names'].get(code, code)} : {err}")
                    if enabled and not clean:
                        errors.append(f"{state['names'].get(code, code)} : ajoutez un numéro avant d'activer les rappels.")
                    if enabled and not consent:
                        errors.append(f"{state['names'].get(code, code)} : le consentement est requis pour activer les rappels.")
                    normalized[code] = (clean, bool(consent), bool(enabled))

                if errors:
                    for err in errors:
                        st.error(err)
                else:
                    for code, (clean, consent, enabled) in normalized.items():
                        state.setdefault("whatsapp_contacts", {})[code] = {
                            "number": clean,
                            "consent": consent,
                            "enabled": enabled,
                        }
                    st.session_state.liturgie_state = state
                    if persist(show_success=False):
                        st.success("Numéros WhatsApp et consentements enregistrés.")
                        st.rerun()

        with st.expander("✍️ Modèles officiels des rappels", expanded=False):
            render_whatsapp_template_editor(state)

        with st.expander("📲 Préparer les rappels WhatsApp", expanded=False):
            render_whatsapp_reminder_sender(state)

        with st.expander("🤖 Automatisation WhatsApp — prête mais désactivée", expanded=False):
            render_whatsapp_automation_ready(state)

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


    if IS_ADJOINT:
        st.divider()
        st.subheader("📲 Rappels WhatsApp")
        st.caption(
            "L'administrateur adjoint peut préparer et ouvrir les rappels des membres programmés. "
            "Les numéros de téléphone restent masqués et ne sont pas modifiables ici."
        )
        render_whatsapp_reminder_sender(state)


with attendance_tab:
    st.subheader("📋 Présences aux répétitions")
    st.caption(
        "P = Présent · J = absence justifiée (comptée comme présence) · "
        "A = absence non justifiée. Pour être éligible le mois suivant : P + J ≥ 2 et moins de 3 J."
    )

    attendance_key = attendance_sheet_key(_current_saturday)
    current_sheet = state.get("attendance", {}).get(attendance_key)
    current_ignored = attendance_is_ignored(state, _current_saturday)
    open_start, open_end = attendance_window(_current_saturday)

    if current_ignored:
        st.info(
            f"0️⃣ Présences remises à zéro pour le samedi {_current_saturday.strftime('%d/%m/%Y')}. "
            "Cette feuille ne compte plus dans le bilan du mois."
        )
        if IS_ADMIN and _current_attendance_open:
            if st.button("↩️ Réactiver cette feuille", key=f"restore_attendance_{attendance_key}"):
                restore_attendance_sheet(state, _current_saturday, "principal")
                st.session_state.liturgie_state = state
                if persist(show_success=False):
                    st.success("Feuille réactivée.")
                    st.rerun()
    elif _current_attendance_open:
        st.success(
            f"🟢 Feuille du samedi {_current_saturday.strftime('%d/%m/%Y')} ouverte "
            "jusqu'au dimanche 23 h 59."
        )
        if current_sheet:
            if CAN_EDIT_ATTENDANCE:
                st.info(
                    "Vous pouvez renseigner ou corriger cette feuille tant que la fenêtre est ouverte. "
                    "Après dimanche 23 h 59, seul l'administrateur principal pourra la corriger."
                )
                with st.form(f"attendance_current_{attendance_key}"):
                    current_statuses = {}
                    last_lang = None
                    for code in current_sheet.get("members", []):
                        lang = "FR" if str(code).startswith("F") else "MO"
                        if lang != last_lang:
                            st.markdown("**Francophones**" if lang == "FR" else "**Mooréphones**")
                            last_lang = lang
                        old_status = str(current_sheet.get("statuses", {}).get(code, "")).upper()
                        options = ["—", "P", "J", "A"]
                        default_index = options.index(old_status) if old_status in options else 0
                        current_statuses[code] = st.radio(
                            current_sheet.get("names", {}).get(code, code),
                            options,
                            index=default_index,
                            horizontal=True,
                            key=f"att_current_{attendance_key}_{code}",
                        )
                    save_current = st.form_submit_button("💾 Enregistrer la feuille", type="primary")
                if save_current:
                    clean_statuses = {
                        code: ("" if value == "—" else value)
                        for code, value in current_statuses.items()
                    }
                    ok, message = save_attendance_sheet(
                        state,
                        _current_saturday,
                        clean_statuses,
                        current_role(),
                    )
                    if ok:
                        st.session_state.liturgie_state = state
                        if persist(show_success=False):
                            st.success(message)
                            st.rerun()
                    else:
                        st.error(message)
            else:
                st.info("La feuille est visible en consultation. Seuls les administrateurs peuvent la renseigner.")
                st.dataframe(attendance_sheet_rows(current_sheet), use_container_width=True, hide_index=True)
        elif not CAN_EDIT_ATTENDANCE:
            st.info("La feuille sera créée automatiquement lorsqu'un administrateur ouvrira l'application pendant la fenêtre de saisie.")
    else:
        if _now < open_start and _now.date() == _current_saturday:
            st.info(
                f"⏳ La feuille du samedi {_current_saturday.strftime('%d/%m/%Y')} "
                "s'ouvrira automatiquement à 18 h 30."
            )
        else:
            st.info(
                f"🔒 La dernière fenêtre de saisie ({_current_saturday.strftime('%d/%m/%Y')}) est fermée. "
                "Seul l'administrateur principal peut corriger une ancienne feuille."
            )
        if current_sheet:
            st.dataframe(attendance_sheet_rows(current_sheet), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 📊 Bilan du mois et éligibilité")
    target_year, target_month = next_month(_current_saturday.year, _current_saturday.month)
    eligibility, eligibility_rows = attendance_summary_rows(state, target_year, target_month)
    prev_label = f"{MONTHS[eligibility['previous_month'] - 1]} {eligibility['previous_year']}"
    target_label = f"{MONTHS[target_month - 1]} {target_year}"
    if eligibility["enforced"]:
        eligible_count = sum(
            1 for code, info in eligibility["details"].items()
            if info.get("eligible", True) and state.get("active", {}).get(code, True)
        )
        ineligible_count = sum(
            1 for code, info in eligibility["details"].items()
            if not info.get("eligible", True) and state.get("active", {}).get(code, True)
        )
        st.success(
            f"Règle active pour la programmation de {target_label} : "
            f"{eligible_count} éligible(s), {ineligible_count} non éligible(s), "
            f"sur {eligibility['sheet_count']} feuille(s) de {prev_label}."
        )
    else:
        st.warning(
            f"Règle d'éligibilité non encore appliquée pour {target_label} : "
            f"{eligibility['sheet_count']} feuille(s) enregistrée(s) en {prev_label}. "
            "Il faut au moins 2 feuilles enregistrées pour activer automatiquement le filtre."
        )
    with st.expander("Voir le détail P / J / A"):
        st.dataframe(eligibility_rows, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 🗂️ Anciennes feuilles")
    attendance_items = []
    for key, sheet in (state.get("attendance", {}) or {}).items():
        try:
            sheet_day = date.fromisoformat(str(sheet.get("date") or key))
        except Exception:
            continue
        attendance_items.append((sheet_day, key, sheet))
    attendance_items.sort(key=lambda item: item[0], reverse=True)

    if not attendance_items:
        st.caption("Aucune feuille de présence enregistrée pour le moment.")
    else:
        attendance_keys = [item[1] for item in attendance_items]
        selected_key = st.selectbox(
            "Choisir une feuille",
            attendance_keys,
            format_func=lambda k: date.fromisoformat(k).strftime("%d/%m/%Y"),
            key="attendance_history_select",
        )
        selected_sheet = state.get("attendance", {}).get(selected_key, {})
        selected_day = date.fromisoformat(selected_key)
        st.dataframe(attendance_sheet_rows(selected_sheet), use_container_width=True, hide_index=True)
        if selected_sheet.get("updated_at"):
            st.caption(
                f"Dernière modification : {selected_sheet.get('updated_by', '—')} · "
                f"{selected_sheet.get('updated_at', '')}"
            )

        if IS_ADMIN:
            with st.expander("🗑️ Supprimer / remettre cette feuille à zéro", expanded=False):
                st.warning(
                    "Cette action est réservée à l'administrateur principal. La feuille sera retirée du bilan "
                    "et ne comptera plus pour l'éligibilité. Les programmes, membres et rotations ne sont pas touchés."
                )
                confirm_delete_attendance = st.checkbox(
                    f"Je confirme la remise à zéro de la feuille du {selected_day.strftime('%d/%m/%Y')}",
                    key=f"confirm_delete_attendance_{selected_key}",
                )
                if st.button("🗑️ Supprimer cette feuille de présence", key=f"delete_attendance_{selected_key}"):
                    if not confirm_delete_attendance:
                        st.error("Cochez la confirmation avant de supprimer la feuille.")
                    else:
                        ok, message = delete_attendance_sheet(state, selected_day, "principal")
                        if ok:
                            st.session_state.liturgie_state = state
                            if persist(show_success=False):
                                st.success(message)
                                st.rerun()

        if IS_ADMIN and not attendance_is_open(selected_day, _now):
            with st.expander("✏️ Corriger cette ancienne feuille", expanded=False):
                st.warning(
                    "Cette correction est réservée à l'administrateur principal et sera inscrite dans le journal."
                )
                with st.form(f"attendance_history_edit_{selected_key}"):
                    corrected_statuses = {}
                    last_lang = None
                    for code in selected_sheet.get("members", []):
                        lang = "FR" if str(code).startswith("F") else "MO"
                        if lang != last_lang:
                            st.markdown("**Francophones**" if lang == "FR" else "**Mooréphones**")
                            last_lang = lang
                        old_status = str(selected_sheet.get("statuses", {}).get(code, "")).upper()
                        options = ["—", "P", "J", "A"]
                        default_index = options.index(old_status) if old_status in options else 0
                        corrected_statuses[code] = st.radio(
                            selected_sheet.get("names", {}).get(code, code),
                            options,
                            index=default_index,
                            horizontal=True,
                            key=f"att_history_{selected_key}_{code}",
                        )
                    correction_reason = st.text_input(
                        "Motif de la correction",
                        placeholder="Ex. justificatif reçu après la répétition",
                    )
                    confirm_correction = st.checkbox(
                        "Je confirme la correction de cette ancienne feuille."
                    )
                    save_correction = st.form_submit_button("💾 Enregistrer la correction")
                if save_correction:
                    if not confirm_correction:
                        st.error("Cochez la confirmation avant d'enregistrer la correction.")
                    elif not str(correction_reason).strip():
                        st.error("Indiquez le motif de la correction.")
                    else:
                        clean_statuses = {
                            code: ("" if value == "—" else value)
                            for code, value in corrected_statuses.items()
                        }
                        ok, message = save_attendance_sheet(
                            state,
                            selected_day,
                            clean_statuses,
                            "principal",
                            reason=correction_reason,
                        )
                        if ok:
                            st.session_state.liturgie_state = state
                            if persist(show_success=False):
                                st.success(message)
                                st.rerun()
                        else:
                            st.error(message)
        elif IS_ADJOINT and not attendance_is_open(selected_day, _now):
            st.caption("🔒 Ancienne feuille en lecture seule pour l'administrateur adjoint.")


with generate_tab:
    if not IS_ADMIN:
        st.subheader("✨ Générer")
        st.info("La génération et la validation d'un nouveau programme sont réservées à l'administrateur principal.")
        history = state.get("history", [])
        latest = latest_history_month(history)
        if latest:
            latest_year, latest_month, _ = latest
            latest_rows = [
                row for row in history
                if str(row.get("date", "")).startswith(f"{latest_year:04d}-{latest_month:02d}-")
            ]
            if latest_rows:
                st.markdown(f"### Programme publié — {MONTHS[latest_month - 1]} {latest_year}")
                show_mobile_program(latest_rows)
        else:
            st.caption("Aucun programme n'est encore publié.")
    else:
        st.subheader("1. Choisir la période")
        col1, col2 = st.columns(2)
        with col1:
            year = int(st.number_input("Année", min_value=2020, max_value=2100, value=2026, step=1))
        with col2:
            month = st.selectbox("Mois", range(1, 13), index=8, format_func=lambda m: MONTHS[m - 1])

        month_sundays = sundays(year, month)

        attendance_check, attendance_check_rows = attendance_summary_rows(state, year, month)
        prev_att_label = f"{MONTHS[attendance_check['previous_month'] - 1]} {attendance_check['previous_year']}"
        if attendance_check["enforced"]:
            blocked = [
                state.get("names", {}).get(code, code)
                for code, info in attendance_check["details"].items()
                if not info.get("eligible", True) and state.get("active", {}).get(code, True)
            ]
            st.info(
                f"📋 Éligibilité calculée à partir des présences de {prev_att_label}. "
                f"{len(blocked)} membre(s) actif(s) seront automatiquement exclus de la programmation "
                "si leurs critères de présence ne sont pas remplis."
            )
            if blocked:
                with st.expander("Voir les lecteurs non éligibles"):
                    st.dataframe(
                        [row for row in attendance_check_rows if row["Éligible"] == "⛔ Non"],
                        use_container_width=True,
                        hide_index=True,
                    )
        elif attendance_check["sheet_count"] > 0:
            st.warning(
                f"📋 Seulement {attendance_check['sheet_count']} feuille(s) de présence enregistrée(s) en {prev_att_label}. "
                "Le filtre automatique d'éligibilité n'est pas encore activé (minimum : 2 feuilles)."
            )
        else:
            st.caption(
                f"📋 Aucune feuille de présence enregistrée en {prev_att_label} : "
                "la programmation utilise les statuts Actif/Absent habituels."
            )

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

    if IS_ADMIN:
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

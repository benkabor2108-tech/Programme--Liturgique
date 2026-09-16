#!/usr/bin/env python3
"""Rappels WhatsApp Cloud API planifiés pour Programme liturgique.

Le script lit le programme publié et les préférences WhatsApp dans Supabase,
envoie des modèles Meta approuvés, puis journalise chaque succès dans Supabase
pour éviter les doublons. Aucun secret ni numéro n'est affiché dans les logs.

Depuis v3.10.16, le cycle de rappel couvre le week-end liturgique complet :
- messe anticipée du samedi soir ;
- messe du dimanche.
Les rappels restent envoyés le mercredi et le vendredi précédents. Si une même
personne est programmée les deux jours, un seul message regroupe ses services.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from copy import deepcopy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from history_protection import is_history_row_active
from state_store import StateConflictError, load_state_record, save_state_if_revision

APP_TIMEZONE = ZoneInfo("Africa/Ouagadougou")
TABLE_NAME = "liturgie_state"
ROLE_KEYS = ("r1", "r2", "f_mon", "m_mon", "f_ann", "m_ann")
REMINDER_OFFSETS = {"mercredi": 4, "vendredi": 2}


class ConfigError(RuntimeError):
    pass


def env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip()


def as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> dict:
    cfg = {
        "supabase_url": env("SUPABASE_URL").rstrip("/"),
        "supabase_api_key": env("SUPABASE_API_KEY"),
        "supabase_state_key": env("SUPABASE_STATE_KEY", "programme-liturgique-principal"),
        "graph_api_version": env("WHATSAPP_GRAPH_API_VERSION").lstrip("/"),
        "phone_number_id": env("WHATSAPP_PHONE_NUMBER_ID"),
        "access_token": env("WHATSAPP_ACCESS_TOKEN"),
        "template_wednesday": env("WHATSAPP_TEMPLATE_WEDNESDAY"),
        "template_friday": env("WHATSAPP_TEMPLATE_FRIDAY"),
        "template_language": env("WHATSAPP_TEMPLATE_LANGUAGE", "fr") or "fr",
        "enabled": as_bool(env("WHATSAPP_AUTOMATION_ENABLED", "false")),
        "dry_run": as_bool(env("WHATSAPP_DRY_RUN", "false")),
    }
    missing = [k for k in ("supabase_url", "supabase_api_key") if not cfg[k]]
    if missing:
        raise ConfigError("Configuration Supabase incomplète: " + ", ".join(missing))
    return cfg


def whatsapp_config_missing(cfg: dict) -> list[str]:
    required = {
        "WHATSAPP_GRAPH_API_VERSION": cfg["graph_api_version"],
        "WHATSAPP_PHONE_NUMBER_ID": cfg["phone_number_id"],
        "WHATSAPP_ACCESS_TOKEN": cfg["access_token"],
        "WHATSAPP_TEMPLATE_WEDNESDAY": cfg["template_wednesday"],
        "WHATSAPP_TEMPLATE_FRIDAY": cfg["template_friday"],
    }
    return [name for name, value in required.items() if not value]


def supabase_headers(cfg: dict) -> dict:
    return {
        "apikey": cfg["supabase_api_key"],
        "Authorization": f"Bearer {cfg['supabase_api_key']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def load_state_with_revision(cfg: dict):
    return load_state_record(
        cfg["supabase_url"],
        cfg["supabase_api_key"],
        cfg["supabase_state_key"],
        timeout=20,
    )


def load_state(cfg: dict) -> dict:
    state, _revision, _updated_at = load_state_with_revision(cfg)
    return state


def automation_authorized(state: dict) -> bool:
    """Autorisation métier persistée par l'administrateur principal."""
    return bool(state.get("whatsapp_automation_authorized", False)) if isinstance(state, dict) else False


def weekend_anchor(day: date) -> date:
    """Retourne le dimanche qui sert d'ancre au week-end liturgique."""
    if day.weekday() == 5:  # samedi
        return day + timedelta(days=1)
    return day


def next_published_weekend(state: dict, reference_day: date):
    """Retourne (dimanche_ancre, [(date_service, ligne), ...]) pour le prochain week-end actif.

    Les lignes du samedi et du dimanche sont regroupées sous le dimanche qui suit.
    Une ligne déjà passée par rapport à ``reference_day`` est ignorée, ce qui évite
    qu'un lancement manuel le dimanche tente de rappeler la messe anticipée déjà passée.
    """
    grouped: dict[date, list[tuple[date, dict]]] = {}
    for row in state.get("history", []) or []:
        if not isinstance(row, dict) or not is_history_row_active(row):
            continue
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except ValueError:
            continue
        if day.weekday() not in (5, 6):
            continue
        if day < reference_day:
            continue
        anchor = weekend_anchor(day)
        grouped.setdefault(anchor, []).append((day, row))

    if not grouped:
        return None, []
    anchor = min(grouped)
    services = sorted(grouped[anchor], key=lambda item: item[0])
    return anchor, services


def next_published_sunday(state: dict, reference_day: date):
    """Compatibilité historique : retourne uniquement la ligne du prochain dimanche."""
    anchor, services = next_published_weekend(state, reference_day)
    if not anchor:
        return None, None
    for day, row in services:
        if day.weekday() == 6:
            return day, row
    return None, None


def reminder_date(sunday: date, kind: str) -> date:
    return sunday - timedelta(days=REMINDER_OFFSETS[kind])


def send_key(sunday: date, kind: str, code: str) -> str:
    """Une clé par membre et week-end : évite un doublon samedi + dimanche."""
    return f"{sunday.isoformat()}|{kind}|{code}"


def normalize_number(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not (8 <= len(digits) <= 15):
        return ""
    return digits


def contact_readiness(contact: dict) -> tuple[str, bool, list[str]]:
    """Évalue un contact sans exposer son numéro dans les diagnostics."""
    contact = contact if isinstance(contact, dict) else {}
    number = normalize_number(contact.get("number", ""))
    reasons = []
    if not number:
        reasons.append("numéro absent ou invalide")
    if not bool(contact.get("consent")):
        reasons.append("consentement absent")
    if not bool(contact.get("enabled")):
        reasons.append("rappels désactivés")
    return number, not reasons, reasons


def role_for_code(row: dict, code: str) -> str:
    codes = row.get("codes", {}) if isinstance(row.get("codes"), dict) else {}
    lang = "Français" if str(code).startswith("F") else "Mooré"
    roles = []
    if codes.get("r1") == code:
        roles.append(f"1re lecture — {lang}")
    if codes.get("r2") == code:
        roles.append(f"2e lecture — {lang}")
    if codes.get("f_mon") == code or codes.get("m_mon") == code:
        roles.append(f"Monition + P.U. — {lang}")
    if codes.get("f_ann") == code or codes.get("m_ann") == code:
        roles.append(f"Annonces — {lang}")
    return " + ".join(roles)


def scheduled_codes(row: dict) -> list[str]:
    codes = row.get("codes", {}) if isinstance(row.get("codes"), dict) else {}
    result, seen = [], set()
    for key in ROLE_KEYS:
        code = str(codes.get(key) or "").strip()
        if code and code not in seen:
            result.append(code)
            seen.add(code)
    return result


def service_day_name(day: date) -> str:
    return "Samedi" if day.weekday() == 5 else "Dimanche"


def _service_assignment_label(day: date, role: str) -> str:
    return f"{service_day_name(day)} {day:%d/%m/%Y} : {role}"


def build_weekend_jobs(
    state: dict,
    sunday: date,
    services: list[tuple[date, dict]],
    kind: str,
) -> list[dict]:
    """Construit un seul job par membre pour l'ensemble samedi + dimanche."""
    contacts = state.get("whatsapp_contacts", {}) if isinstance(state.get("whatsapp_contacts"), dict) else {}
    names = state.get("names", {}) if isinstance(state.get("names"), dict) else {}
    log = state.get("whatsapp_send_log", {}) if isinstance(state.get("whatsapp_send_log"), dict) else {}

    assignments: dict[str, list[dict]] = {}
    order: list[str] = []
    for service_day, row in sorted(services, key=lambda item: item[0]):
        for code in scheduled_codes(row):
            if code not in assignments:
                assignments[code] = []
                order.append(code)
            assignments[code].append({
                "date": service_day.isoformat(),
                "date_label": service_day.strftime("%d/%m/%Y"),
                "day_name": service_day_name(service_day),
                "role": role_for_code(row, code),
            })

    jobs = []
    for code in order:
        contact = contacts.get(code, {})
        if not isinstance(contact, dict):
            contact = {}
        number, ready, not_ready_reasons = contact_readiness(contact)
        member_assignments = assignments[code]
        role_text = " ; ".join(
            _service_assignment_label(date.fromisoformat(item["date"]), item["role"])
            for item in member_assignments
        )
        service_label = " et ".join(
            f"{item['day_name']} {item['date_label']}" for item in member_assignments
        )
        key = send_key(sunday, kind, code)
        jobs.append({
            "code": code,
            "name": str(names.get(code, code)),
            "role": role_text,
            "service_label": service_label,
            "assignments": member_assignments,
            "number": number,
            "ready": ready,
            "not_ready_reasons": not_ready_reasons,
            "already_sent": key in log,
            "send_key": key,
        })
    return jobs


def build_jobs(state: dict, service_day: date, row: dict, kind: str) -> list[dict]:
    """Compatibilité pour les tests/appels unitaires sur une seule célébration."""
    return build_weekend_jobs(
        state,
        weekend_anchor(service_day),
        [(service_day, row)],
        kind,
    )


def template_name(cfg: dict, kind: str) -> str:
    return cfg["template_friday"] if kind == "vendredi" else cfg["template_wednesday"]


def send_template(cfg: dict, job: dict, sunday: date, kind: str):
    endpoint = f"https://graph.facebook.com/{cfg['graph_api_version']}/{cfg['phone_number_id']}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": job["number"],
        "type": "template",
        "template": {
            "name": template_name(cfg, kind),
            "language": {"code": cfg["template_language"]},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": job["name"]},
                    {"type": "text", "text": job.get("service_label") or sunday.strftime("%d/%m/%Y")},
                    {"type": "text", "text": job["role"]},
                ],
            }],
        },
    }
    headers = {"Authorization": f"Bearer {cfg['access_token']}", "Content-Type": "application/json"}
    response = requests.post(endpoint, headers=headers, json=payload, timeout=25)
    try:
        body = response.json()
    except Exception:
        body = {}
    if response.ok:
        message_id = ""
        messages = body.get("messages") if isinstance(body, dict) else None
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            message_id = str(messages[0].get("id", ""))
        return True, message_id
    error_message = ""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        error_message = str(body["error"].get("message", ""))
    safe_error = f"HTTP {response.status_code}"
    if error_message:
        safe_error += f": {error_message[:240]}"
    return False, safe_error


def record_success(cfg: dict, sunday: date, kind: str, job: dict, message_id: str) -> None:
    """Journalise un succès en réessayant si une autre écriture intervient simultanément."""
    for attempt in range(1, 7):
        latest, revision, _updated_at = load_state_with_revision(cfg)
        latest = deepcopy(latest)
        log = latest.setdefault("whatsapp_send_log", {})
        if not isinstance(log, dict):
            log = {}
            latest["whatsapp_send_log"] = log
        if job["send_key"] in log:
            return

        stamp = datetime.now(APP_TIMEZONE).isoformat()
        log[job["send_key"]] = {
            "status": "sent",
            "sent_at": stamp,
            "actor": "GitHub Actions — WhatsApp Cloud API",
            "message_id": message_id,
            "weekend_sunday": sunday.isoformat(),
            "assignments": deepcopy(job.get("assignments", [])),
        }
        audit = latest.setdefault("audit_log", [])
        if not isinstance(audit, list):
            audit = []
            latest["audit_log"] = audit
        audit.append({
            "type": "whatsapp_reminder_sent",
            "date": sunday.isoformat(),
            "weekend_sunday": sunday.isoformat(),
            "reminder": kind,
            "member": job["code"],
            "assignments": deepcopy(job.get("assignments", [])),
            "timestamp": stamp,
            "actor": "GitHub Actions — WhatsApp Cloud API",
            "message_id": message_id,
        })
        try:
            save_state_if_revision(
                cfg["supabase_url"],
                cfg["supabase_api_key"],
                cfg["supabase_state_key"],
                latest,
                revision,
                timeout=20,
            )
            return
        except StateConflictError:
            if attempt >= 6:
                raise
            print(f"[concurrency] journal WhatsApp modifié simultanément ; nouvelle tentative {attempt + 1}/6.")


def resolve_kind(value: str, now: datetime) -> str:
    if value in REMINDER_OFFSETS:
        return value
    if now.weekday() == 2:
        return "mercredi"
    if now.weekday() == 4:
        return "vendredi"
    raise ConfigError("Aujourd'hui n'est ni mercredi ni vendredi; utilisez --kind pour un test manuel.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["auto", "mercredi", "vendredi"], default=env("WHATSAPP_REMINDER_KIND", "auto"))
    parser.add_argument("--reference-date", help="Date YYYY-MM-DD pour un test reproductible.")
    parser.add_argument(
        "--readiness-only",
        action="store_true",
        help="Contrôle le prochain week-end samedi + dimanche sans envoyer ni journaliser.",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        default=as_bool(env("WHATSAPP_REQUIRE_COMPLETE", "false")),
        help="Échoue en mode readiness si un contact ou un paramètre WhatsApp manque.",
    )
    args = parser.parse_args()

    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"[preflight] {exc}")
        return 0

    now = datetime.now(APP_TIMEZONE)
    reference_day = date.fromisoformat(args.reference_date) if args.reference_date else now.date()
    effective_now = now if not args.reference_date else datetime.combine(reference_day, now.time(), tzinfo=APP_TIMEZONE)

    try:
        kind = resolve_kind(args.kind, effective_now)
    except ConfigError as exc:
        print(f"[preflight] {exc}")
        return 0

    state = load_state(cfg)
    sunday, services = next_published_weekend(state, reference_day)
    if not sunday or not services:
        print("[info] Aucun week-end liturgique futur publié; aucun rappel à envoyer.")
        return 0

    jobs = build_weekend_jobs(state, sunday, services, kind)
    ready_jobs = [job for job in jobs if job["ready"]]
    not_ready = [job for job in jobs if not job["ready"]]

    if args.readiness_only:
        missing_config = whatsapp_config_missing(cfg)
        print(
            f"[readiness] week-end={sunday:%d/%m/%Y} "
            f"célébrations={len(services)} prêts={len(ready_jobs)} non_configurés={len(not_ready)}"
        )
        for job in not_ready:
            reasons = ", ".join(job.get("not_ready_reasons", [])) or "configuration incomplète"
            print(f"[warning] {job['code']} — {job['name']} — {reasons}")
        if missing_config:
            print("[warning] paramètres WhatsApp manquants: " + ", ".join(missing_config))
        if args.require_complete and (not_ready or missing_config):
            print("[readiness] INCOMPLET")
            return 2
        print("[readiness] COMPLET")
        return 0

    expected_day = reminder_date(sunday, kind)
    if reference_day != expected_day:
        print(f"[info] Aucun envoi aujourd'hui: rappel {kind} prévu le {expected_day:%d/%m/%Y}.")
        return 0

    pending = [j for j in jobs if j["ready"] and not j["already_sent"]]
    already_sent = [j for j in jobs if j["already_sent"]]
    print(
        f"[plan] week-end={sunday:%d/%m/%Y} célébrations={len(services)} rappel={kind} "
        f"prêts={len(pending)} déjà_envoyés={len(already_sent)} non_configurés={len(not_ready)}"
    )
    for job in not_ready:
        reasons = ", ".join(job.get("not_ready_reasons", [])) or "configuration incomplète"
        print(f"[warning] {job['code']} — {job['name']} — {reasons}")

    if cfg["dry_run"]:
        for job in pending:
            print(f"[dry-run] {job['code']} — {job['name']} — {job['role']}")
        return 0

    # Défense en profondeur : même hors workflow GitHub, aucun envoi partiel
    # si le prochain week-end contient un contact non prêt.
    if not_ready:
        print("[preflight] Week-end incomplet; aucun message envoyé.")
        return 2

    if not automation_authorized(state):
        print("[preflight] Autorisation principale WhatsApp désactivée; aucun message envoyé.")
        return 0

    missing = whatsapp_config_missing(cfg)
    if missing:
        print("[preflight] Configuration WhatsApp incomplète: " + ", ".join(missing))
        return 0
    if not cfg["enabled"]:
        print("[preflight] WHATSAPP_AUTOMATION_ENABLED n'est pas activé; aucun message envoyé.")
        return 0

    failures = 0
    for job in pending:
        ok, detail = send_template(cfg, job, sunday, kind)
        if ok:
            record_success(cfg, sunday, kind, job, detail)
            print(f"[sent] {job['code']} — {job['name']}")
        else:
            failures += 1
            print(f"[error] {job['code']} — {detail}", file=sys.stderr)

    if failures:
        print(f"[result] {failures} envoi(s) en erreur.", file=sys.stderr)
        return 1
    print(f"[result] {len(pending)} rappel(s) envoyé(s) avec succès.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Rappels WhatsApp Cloud API planifiés pour Programme liturgique.

Le script lit le programme publié et les préférences WhatsApp dans Supabase,
envoie des modèles Meta approuvés, puis journalise chaque succès dans Supabase
pour éviter les doublons. Aucun secret ni numéro n'est affiché dans les logs.
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


def load_state(cfg: dict) -> dict:
    endpoint = f"{cfg['supabase_url']}/rest/v1/{TABLE_NAME}"
    params = {
        "select": "state_json",
        "app_key": f"eq.{cfg['supabase_state_key']}",
        "limit": "1",
    }
    response = requests.get(endpoint, headers=supabase_headers(cfg), params=params, timeout=20)
    response.raise_for_status()
    rows = response.json()
    if not rows:
        raise RuntimeError("Aucun état Programme liturgique trouvé dans Supabase.")
    state = rows[0].get("state_json")
    if not isinstance(state, dict):
        raise RuntimeError("Le state_json Supabase est invalide.")
    return state


def save_state(cfg: dict, state: dict) -> None:
    endpoint = f"{cfg['supabase_url']}/rest/v1/{TABLE_NAME}?on_conflict=app_key"
    headers = supabase_headers(cfg)
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    payload = {"app_key": cfg["supabase_state_key"], "state_json": state}
    response = requests.post(endpoint, headers=headers, json=payload, timeout=20)
    response.raise_for_status()


def next_published_sunday(state: dict, reference_day: date):
    candidates = []
    for row in state.get("history", []) or []:
        if not isinstance(row, dict):
            continue
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except ValueError:
            continue
        if day >= reference_day:
            candidates.append((day, row))
    return min(candidates, key=lambda item: item[0]) if candidates else (None, None)


def reminder_date(sunday: date, kind: str) -> date:
    return sunday - timedelta(days=REMINDER_OFFSETS[kind])


def send_key(sunday: date, kind: str, code: str) -> str:
    return f"{sunday.isoformat()}|{kind}|{code}"


def normalize_number(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not (8 <= len(digits) <= 15):
        return ""
    return digits


def role_for_code(row: dict, code: str) -> str:
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


def scheduled_codes(row: dict) -> list[str]:
    codes = row.get("codes", {}) if isinstance(row.get("codes"), dict) else {}
    result, seen = [], set()
    for key in ROLE_KEYS:
        code = str(codes.get(key) or "").strip()
        if code and code not in seen:
            result.append(code)
            seen.add(code)
    return result


def build_jobs(state: dict, sunday: date, row: dict, kind: str) -> list[dict]:
    contacts = state.get("whatsapp_contacts", {}) if isinstance(state.get("whatsapp_contacts"), dict) else {}
    names = state.get("names", {}) if isinstance(state.get("names"), dict) else {}
    log = state.get("whatsapp_send_log", {}) if isinstance(state.get("whatsapp_send_log"), dict) else {}
    jobs = []
    for code in scheduled_codes(row):
        contact = contacts.get(code, {})
        if not isinstance(contact, dict):
            contact = {}
        number = normalize_number(contact.get("number", ""))
        ready = bool(number and contact.get("consent") and contact.get("enabled"))
        key = send_key(sunday, kind, code)
        jobs.append({
            "code": code,
            "name": str(names.get(code, code)),
            "role": role_for_code(row, code),
            "number": number,
            "ready": ready,
            "already_sent": key in log,
            "send_key": key,
        })
    return jobs


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
                    {"type": "text", "text": sunday.strftime("%d/%m/%Y")},
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
    # Recharger juste avant l'écriture pour préserver les éventuelles modifications Streamlit.
    latest = deepcopy(load_state(cfg))
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
    }
    audit = latest.setdefault("audit_log", [])
    if not isinstance(audit, list):
        audit = []
        latest["audit_log"] = audit
    audit.append({
        "type": "whatsapp_reminder_sent",
        "date": sunday.isoformat(),
        "reminder": kind,
        "member": job["code"],
        "timestamp": stamp,
        "actor": "GitHub Actions — WhatsApp Cloud API",
        "message_id": message_id,
    })
    save_state(cfg, latest)


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
    sunday, row = next_published_sunday(state, reference_day)
    if not sunday or not row:
        print("[info] Aucun dimanche futur publié; aucun rappel à envoyer.")
        return 0

    expected_day = reminder_date(sunday, kind)
    if reference_day != expected_day:
        print(f"[info] Aucun envoi aujourd'hui: rappel {kind} prévu le {expected_day:%d/%m/%Y}.")
        return 0

    jobs = build_jobs(state, sunday, row, kind)
    pending = [j for j in jobs if j["ready"] and not j["already_sent"]]
    not_ready = [j for j in jobs if not j["ready"]]
    already_sent = [j for j in jobs if j["already_sent"]]
    print(f"[plan] dimanche={sunday:%d/%m/%Y} rappel={kind} prêts={len(pending)} déjà_envoyés={len(already_sent)} non_configurés={len(not_ready)}")

    if cfg["dry_run"]:
        for job in pending:
            print(f"[dry-run] {job['code']} — {job['name']} — {job['role']}")
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

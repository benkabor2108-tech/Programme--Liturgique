#!/usr/bin/env python3
"""Préparation automatique des monitions et prières universelles.

Le moteur est prévu pour être lancé par GitHub Actions à partir de 18 h 00
(heure de Ouagadougou). Il prépare :
- chaque mardi, le prochain dimanche ;
- chaque jour, les grandes célébrations connues qui auront lieu dans 5 jours.

Le brouillon est construit à partir des textes AELF puis enregistré dans le
même état Supabase que l'application. Un brouillon déjà présent n'est jamais
écrasé : les corrections pastorales de l'administrateur principal sont donc
préservées.
"""
from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, time, timedelta

import requests

from liturgical_drafts_schedule import major_celebrations, next_sunday
from liturgical_drafts_source import build_draft, fetch_liturgical_context
from liturgical_drafts_themes import APP_TIMEZONE

TABLE_NAME = "liturgie_state"
DEFAULT_ZONE = "romain"
DEFAULT_ZONE_LABEL = "Calendrier romain"
AUTO_ACTOR = "GitHub Actions — préparation liturgique automatique"


class ConfigError(RuntimeError):
    pass


def env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip()


def load_config() -> dict:
    cfg = {
        "supabase_url": env("SUPABASE_URL").rstrip("/"),
        "supabase_api_key": env("SUPABASE_API_KEY"),
        "supabase_state_key": env("SUPABASE_STATE_KEY", "programme-liturgique-principal"),
    }
    missing = [name for name in ("supabase_url", "supabase_api_key") if not cfg[name]]
    if missing:
        raise ConfigError("Configuration Supabase incomplète: " + ", ".join(missing))
    return cfg


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


def draft_key(service_date, zone: str = DEFAULT_ZONE) -> str:
    return f"{service_date.isoformat()}|{zone}"


def format_refs(context: dict) -> dict:
    refs = {}
    parts = context.get("parts", {}) if isinstance(context.get("parts"), dict) else {}
    for key in ("r1", "ps", "r2", "ev"):
        record = parts.get(key)
        refs[key] = str(record.get("ref", "")).strip() if isinstance(record, dict) else ""
    return refs


def targets_for(now: datetime) -> list[dict]:
    """Retourne les célébrations qui doivent être préparées à cet instant."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=APP_TIMEZONE)
    else:
        now = now.astimezone(APP_TIMEZONE)

    if now.timetz().replace(tzinfo=None) < time(18, 0):
        return []

    today = now.date()
    targets = {}

    # Le mardi à partir de 18 h : préparer le dimanche suivant.
    if today.weekday() == 1:
        service_date = next_sunday(today)
        title = major_celebrations(service_date.year).get(service_date, "")
        targets[service_date] = {
            "date": service_date,
            "kind": "dimanche",
            "celebration_hint": title,
            "rule": "mardi à 18 h 00",
        }

    # Tous les jours à partir de 18 h : préparer une grande célébration à J-5.
    service_date = today + timedelta(days=5)
    title = major_celebrations(service_date.year).get(service_date)
    if title:
        targets[service_date] = {
            "date": service_date,
            "kind": "event",
            "celebration_hint": title,
            "rule": "5 jours avant à 18 h 00",
        }

    return [targets[key] for key in sorted(targets)]


def prepare_record(target: dict, now: datetime) -> dict:
    service_date = target["date"]
    context = fetch_liturgical_context(service_date.isoformat(), DEFAULT_ZONE)
    hint = str(target.get("celebration_hint") or "").strip()
    if hint and (not context.get("celebration") or context.get("celebration") == "Célébration liturgique"):
        context["celebration"] = hint

    draft = build_draft(context)
    stamp = now.astimezone(APP_TIMEZONE).isoformat()
    return {
        "date": service_date.isoformat(),
        "zone": DEFAULT_ZONE,
        "zone_label": DEFAULT_ZONE_LABEL,
        "celebration": context.get("celebration") or hint or "Célébration liturgique",
        "refs": format_refs(context),
        "source_url": context.get("source_url", ""),
        "monition": draft.get("monition", ""),
        "pu_intro": draft.get("pu_intro", ""),
        "intentions": list(draft.get("intentions", []) or []),
        "pu_conclusion": draft.get("pu_conclusion", ""),
        "response": draft.get("response", "Seigneur, nous te prions."),
        "themes": list(draft.get("themes", []) or []),
        "updated_at": stamp,
        "auto_generated_at": stamp,
        "generated_by": AUTO_ACTOR,
        "availability_rule": target.get("rule", ""),
    }


def persist_if_missing(cfg: dict, target: dict, record: dict, now: datetime) -> bool:
    """Ajoute le brouillon sans écraser un brouillon créé ou corrigé entre-temps."""
    latest = deepcopy(load_state(cfg))
    drafts = latest.setdefault("liturgical_drafts", {})
    if not isinstance(drafts, dict):
        drafts = {}
        latest["liturgical_drafts"] = drafts

    key = draft_key(target["date"])
    if isinstance(drafts.get(key), dict):
        print(f"Brouillon déjà présent pour {target['date'].isoformat()} : aucun écrasement.")
        return False

    drafts[key] = record
    audit = latest.setdefault("audit_log", [])
    if not isinstance(audit, list):
        audit = []
        latest["audit_log"] = audit
    audit.append({
        "at": now.astimezone(APP_TIMEZONE).isoformat(),
        "actor": AUTO_ACTOR,
        "action": "liturgical_draft_auto_generated",
        "date": target["date"].isoformat(),
        "celebration": record.get("celebration", ""),
        "rule": target.get("rule", ""),
    })
    save_state(cfg, latest)
    return True


def run(now: datetime | None = None) -> int:
    now = now or datetime.now(APP_TIMEZONE)
    cfg = load_config()
    targets = targets_for(now)
    if not targets:
        print("Aucune rédaction liturgique à préparer maintenant.")
        return 0

    created = 0
    for target in targets:
        key = draft_key(target["date"])
        state = load_state(cfg)
        drafts = state.get("liturgical_drafts", {}) if isinstance(state.get("liturgical_drafts"), dict) else {}
        if isinstance(drafts.get(key), dict):
            print(f"Brouillon déjà disponible pour {target['date'].isoformat()}.")
            continue

        print(f"Préparation automatique pour {target['date'].isoformat()} ({target['rule']}).")
        record = prepare_record(target, now)
        if persist_if_missing(cfg, target, record, now):
            created += 1
            print(f"Brouillon enregistré pour {target['date'].isoformat()}.")

    print(f"Préparation terminée : {created} nouveau(x) brouillon(s).")
    return created


if __name__ == "__main__":
    run()

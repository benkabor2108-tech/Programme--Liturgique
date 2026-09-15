#!/usr/bin/env python3
"""Verrou global de readiness avant tout envoi WhatsApp de production.

Ce script lit l'état Supabase, contrôle toutes les affectations futures actives
et échoue si un seul membre programmé n'a pas de numéro valide, de consentement
ou d'activation des rappels. Aucun numéro n'est affiché dans les logs.
"""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from state_store import load_state_record
from whatsapp_readiness import future_readiness_rows, readiness_summary

APP_TIMEZONE = ZoneInfo("Africa/Ouagadougou")
REQUIRED_RUNTIME_ENV = (
    "WHATSAPP_GRAPH_API_VERSION",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_TEMPLATE_WEDNESDAY",
    "WHATSAPP_TEMPLATE_FRIDAY",
)


def env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip().strip("\"'")


def evaluate_state(state: dict, reference_day: date) -> tuple[dict, list[dict]]:
    rows = future_readiness_rows(state, reference_day)
    summary = readiness_summary(rows)
    blocked = [row for row in rows if not bool(row.get("ready"))]
    return summary, blocked


def missing_runtime_config(values: dict[str, str] | None = None) -> list[str]:
    values = values or {name: env(name) for name in REQUIRED_RUNTIME_ENV}
    return [name for name in REQUIRED_RUNTIME_ENV if not str(values.get(name, "")).strip()]


def blocker_lines(blocked: list[dict]) -> list[str]:
    """Produit des diagnostics sans numéro et dédupliqués par membre/date."""
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in blocked:
        code = str(row.get("code", "")).strip() or "?"
        day = str(row.get("date_label", row.get("date", ""))).strip()
        key = (day, code)
        if key in seen:
            continue
        seen.add(key)
        reasons = ", ".join(str(item) for item in (row.get("reasons") or [])) or "configuration incomplète"
        lines.append(f"{day} — {code} — {reasons}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-date", help="Date YYYY-MM-DD pour un contrôle reproductible.")
    args = parser.parse_args()

    supabase_url = env("SUPABASE_URL").rstrip("/")
    supabase_api_key = env("SUPABASE_API_KEY")
    state_key = env("SUPABASE_STATE_KEY", "programme-liturgique-principal")
    if not supabase_url or not supabase_api_key:
        print("[global-readiness] BLOQUÉ — configuration Supabase incomplète")
        return 2

    missing = missing_runtime_config()
    if missing:
        print("[global-readiness] BLOQUÉ — paramètres WhatsApp manquants: " + ", ".join(missing))
        return 2

    reference_day = (
        date.fromisoformat(args.reference_date)
        if args.reference_date
        else datetime.now(APP_TIMEZONE).date()
    )
    state, _revision, _updated_at = load_state_record(
        supabase_url,
        supabase_api_key,
        state_key,
        timeout=20,
    )
    summary, blocked = evaluate_state(state, reference_day)

    if not summary["assignments"]:
        print("[global-readiness] Aucun programme futur actif — aucun envoi possible.")
        return 0

    print(
        "[global-readiness] "
        f"dimanches={summary['sundays']} affectations={summary['assignments']} "
        f"prêtes={summary['ready']} bloquées={summary['blocked']}"
    )
    if blocked:
        for line in blocker_lines(blocked):
            print(f"[global-readiness][warning] {line}")
        print("[global-readiness] INCOMPLET — envoi de production interdit")
        return 2

    print("[global-readiness] COMPLET — tous les programmes futurs actifs sont prêts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Vérifie le statut des modèles WhatsApp Meta sans afficher de secret.

Variables attendues :
- WHATSAPP_BUSINESS_ACCOUNT_ID
- WHATSAPP_ACCESS_TOKEN
- WHATSAPP_GRAPH_API_VERSION (optionnel, défaut v25.0)
- WHATSAPP_TEMPLATE_WEDNESDAY (optionnel)
- WHATSAPP_TEMPLATE_FRIDAY (optionnel)
"""
from __future__ import annotations

import os
import sys

import requests


def env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip()


def fetch_template(base_url: str, token: str, waba_id: str, name: str) -> dict:
    endpoint = f"{base_url}/{waba_id}/message_templates"
    response = requests.get(
        endpoint,
        headers={"Authorization": f"Bearer {token}"},
        params={
            "name": name,
            "fields": "name,status,category,language,rejected_reason",
            "limit": "10",
        },
        timeout=25,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {}

    if not response.ok:
        message = ""
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            message = str(payload["error"].get("message", ""))
        safe = f"HTTP {response.status_code}"
        if message:
            safe += f": {message[:240]}"
        raise RuntimeError(safe)

    rows = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        if isinstance(row, dict) and str(row.get("name", "")) == name:
            return row
    return {}


def main() -> int:
    waba_id = env("WHATSAPP_BUSINESS_ACCOUNT_ID")
    token = env("WHATSAPP_ACCESS_TOKEN")
    version = env("WHATSAPP_GRAPH_API_VERSION", "v25.0").lstrip("/")
    names = [
        env("WHATSAPP_TEMPLATE_WEDNESDAY", "rappel_liturgie_mercredi"),
        env("WHATSAPP_TEMPLATE_FRIDAY", "rappel_liturgie_vendredi"),
    ]

    if not waba_id:
        print("[preflight] Secret WHATSAPP_BUSINESS_ACCOUNT_ID absent.")
        return 0
    if not token:
        print("[preflight] Secret WHATSAPP_ACCESS_TOKEN absent.")
        return 0

    base_url = f"https://graph.facebook.com/{version}"
    failures = 0
    for name in names:
        try:
            row = fetch_template(base_url, token, waba_id, name)
        except Exception as exc:
            print(f"[error] {name}: {exc}", file=sys.stderr)
            failures += 1
            continue

        if not row:
            print(f"[template] {name}: INTROUVABLE")
            continue

        status = str(row.get("status", "UNKNOWN"))
        category = str(row.get("category", ""))
        language = str(row.get("language", ""))
        reason = str(row.get("rejected_reason", "")).strip()
        line = f"[template] {name}: statut={status} catégorie={category} langue={language}"
        if reason:
            line += f" motif={reason[:180]}"
        print(line)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

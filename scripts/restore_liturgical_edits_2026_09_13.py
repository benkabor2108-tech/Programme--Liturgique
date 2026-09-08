#!/usr/bin/env python3
"""Restaure les corrections pastorales du 13/09/2026 depuis les captures fournies par l'administrateur.

Ce script est volontairement ponctuel : il ne modifie que le brouillon
2026-09-13|romain dans le state_json Supabase courant et conserve tout le
reste de l'état de l'application.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

TABLE_NAME = "liturgie_state"
DRAFT_KEY = "2026-09-13|romain"

MONITION = """Frères et sœurs, bénis sont Dieu qui nous rassemble aujourd’hui, en ce 24ème dimanche du temps ordinaire, autour du Christ pour célébrer le mystère de l’Eucharistie.
La Parole de Dieu nous invite à vivre la miséricorde de Dieu qui pardonne, relève et ouvre un avenir.
Elle fait résonner pour nous cette parole : « je t’avais remis toute cette dette parce que tu m’avais supplié. ». Accueillons cette Parole dans la foi, laissons-la éclairer notre vie et ouvrons nos cœurs à la grâce que le Seigneur veut nous donner au cours de cette Eucharistie.
Fructueuse célébration à toutes et à tous. Amen"""

PU_INTRO = """Frères et sœurs, éclairés par la Parole de Dieu qui nous appelle aujourd’hui à vivre la miséricorde de Dieu qui pardonne, relève et ouvre un avenir, présentons avec confiance au Père les besoins de l’Église et du monde."""

INTENTIONS = [
    "Pour l’Église Universelle et ses pasteurs : le pape, les évêques, les prêtres, les diacres, les personnes consacrées, les catéchistes et tous ceux qui servent l’Évangile, afin qu'éclairé par l'Esprit Saint, ils soient des hommes de foi et de charité pour conduire le peuple de Dieu dans la miséricorde.Prions le Seigneur.",
    "Pour les responsables des nations, et particulièrement pour ceux de notre pays, le Burkina Faso, afin qu'ils soient des hommes et des femmes de bonne volonté qui recherchent avec courage la paix, la justice, la sécurité et le bien commun. Prions le Seigneur.",
    "Pour le monde souffrant, les malades, les prisonniers, les pauvres, les personnes déplacées, les personnes isolées, les veuves, les veufs, les orphelins et toutes les victimes de violence ou d’injustice, afin qu'ils soient entourés d'une charité concrète, fidèle et respectueuse. Prions le Seigneur.",
    "Pour notre assemblée en prière, nos familles, notre communauté chrétienne et tous ceux qui n’ont pas pu venir, afin que la Parole entendue aujourd’hui porte du fruit dans notre vie quotidienne. Prions le Seigneur.",
]

RESPONSE = "Seigneur, nous te prions."


def clean_secret(value: str) -> str:
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value


def load_config() -> dict:
    url = clean_secret(os.getenv("SUPABASE_URL", "")).rstrip("/")
    if url and not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    api_key = clean_secret(os.getenv("SUPABASE_API_KEY", ""))
    state_key = clean_secret(os.getenv("SUPABASE_STATE_KEY", "programme-liturgique-principal"))
    if not url or not api_key:
        raise RuntimeError("Configuration Supabase incomplète.")
    return {"url": url, "api_key": api_key, "state_key": state_key}


def headers(cfg: dict) -> dict:
    return {
        "apikey": cfg["api_key"],
        "Authorization": f"Bearer {cfg['api_key']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def load_state(cfg: dict) -> dict:
    endpoint = f"{cfg['url']}/rest/v1/{TABLE_NAME}"
    params = {
        "select": "state_json",
        "app_key": f"eq.{cfg['state_key']}",
        "limit": "1",
    }
    response = requests.get(endpoint, headers=headers(cfg), params=params, timeout=20)
    response.raise_for_status()
    rows = response.json()
    if not rows or not isinstance(rows[0].get("state_json"), dict):
        raise RuntimeError("État Programme liturgique introuvable ou invalide.")
    return rows[0]["state_json"]


def save_state(cfg: dict, state: dict) -> None:
    endpoint = f"{cfg['url']}/rest/v1/{TABLE_NAME}?on_conflict=app_key"
    h = headers(cfg)
    h["Prefer"] = "resolution=merge-duplicates,return=minimal"
    payload = {"app_key": cfg["state_key"], "state_json": state}
    response = requests.post(endpoint, headers=h, json=payload, timeout=20)
    response.raise_for_status()


def main() -> None:
    cfg = load_config()
    state = load_state(cfg)
    drafts = state.get("liturgical_drafts")
    if not isinstance(drafts, dict):
        raise RuntimeError("La collection liturgical_drafts est absente ou invalide.")
    record = drafts.get(DRAFT_KEY)
    if not isinstance(record, dict):
        raise RuntimeError(f"Brouillon {DRAFT_KEY} introuvable : aucune restauration effectuée.")

    stamp = datetime.now(timezone.utc).isoformat()
    record["monition"] = MONITION
    record["pu_intro"] = PU_INTRO
    record["intentions"] = list(INTENTIONS)
    record["response"] = RESPONSE
    record["updated_at"] = stamp

    # Marquer ce brouillon comme correction humaine afin qu'une future
    # régénération automatique ne l'écrase pas.
    record.pop("generated_by", None)
    record.pop("generator_version", None)
    record.pop("auto_generated_at", None)

    audit = state.setdefault("audit_log", [])
    if isinstance(audit, list):
        audit.append({
            "at": stamp,
            "actor": "Administrateur principal — restauration depuis captures",
            "action": "liturgical_draft_saved",
            "date": "2026-09-13",
            "celebration": record.get("celebration", ""),
        })

    save_state(cfg, state)
    print("Restauration réussie : brouillon du 13/09/2026 enregistré avec 4 intentions.")


if __name__ == "__main__":
    main()

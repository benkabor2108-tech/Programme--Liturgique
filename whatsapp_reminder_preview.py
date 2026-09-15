"""Aperçu sans envoi des rappels WhatsApp du prochain week-end liturgique.

Ce module réutilise exactement la logique du moteur d'envoi pour déterminer
le prochain week-end, regrouper samedi + dimanche et éviter les doublons.
Il n'effectue aucun appel Meta et n'écrit aucune donnée.
"""
from __future__ import annotations

from datetime import date

from scripts.whatsapp_automation import (
    build_weekend_jobs,
    next_published_weekend,
    reminder_date,
)


def _sent_label(sent: bool, ready: bool) -> str:
    if sent:
        return "✅ Envoyé"
    if not ready:
        return "⛔ Bloqué"
    return "⏳ À envoyer"


def preview_rows(state: dict | None, reference_day: date | None = None) -> list[dict]:
    """Retourne un aperçu unique par membre pour le prochain week-end actif."""
    state = state if isinstance(state, dict) else {}
    reference_day = reference_day or date.today()
    sunday, services = next_published_weekend(state, reference_day)
    if not sunday or not services:
        return []

    wed_jobs = build_weekend_jobs(state, sunday, services, "mercredi")
    fri_jobs = build_weekend_jobs(state, sunday, services, "vendredi")
    fri_by_code = {job["code"]: job for job in fri_jobs}

    rows: list[dict] = []
    for wed_job in wed_jobs:
        code = wed_job["code"]
        fri_job = fri_by_code.get(code, wed_job)
        ready = bool(wed_job.get("ready"))
        assignments = list(wed_job.get("assignments") or [])
        services_text = " ; ".join(
            f"{item.get('day_name', '')} {item.get('date_label', '')} — {item.get('role', '')}".strip()
            for item in assignments
        )
        rows.append({
            "code": code,
            "name": str(wed_job.get("name", code)),
            "ready": ready,
            "reasons": list(wed_job.get("not_ready_reasons") or []),
            "services": services_text,
            "weekend_sunday": sunday.isoformat(),
            "weekend_label": sunday.strftime("%d/%m/%Y"),
            "wednesday_date": reminder_date(sunday, "mercredi").isoformat(),
            "wednesday_label": reminder_date(sunday, "mercredi").strftime("%d/%m/%Y"),
            "friday_date": reminder_date(sunday, "vendredi").isoformat(),
            "friday_label": reminder_date(sunday, "vendredi").strftime("%d/%m/%Y"),
            "wednesday_sent": bool(wed_job.get("already_sent")),
            "friday_sent": bool(fri_job.get("already_sent")),
            "wednesday_status": _sent_label(bool(wed_job.get("already_sent")), ready),
            "friday_status": _sent_label(bool(fri_job.get("already_sent")), ready),
        })
    return rows


def preview_summary(rows: list[dict] | None) -> dict:
    rows = [row for row in (rows or []) if isinstance(row, dict)]
    if not rows:
        return {
            "recipients": 0,
            "ready": 0,
            "blocked": 0,
            "wednesday_sent": 0,
            "friday_sent": 0,
            "weekend_sunday": "",
            "weekend_label": "",
            "wednesday_date": "",
            "wednesday_label": "",
            "friday_date": "",
            "friday_label": "",
        }
    first = rows[0]
    return {
        "recipients": len(rows),
        "ready": sum(1 for row in rows if row.get("ready")),
        "blocked": sum(1 for row in rows if not row.get("ready")),
        "wednesday_sent": sum(1 for row in rows if row.get("wednesday_sent")),
        "friday_sent": sum(1 for row in rows if row.get("friday_sent")),
        "weekend_sunday": first.get("weekend_sunday", ""),
        "weekend_label": first.get("weekend_label", ""),
        "wednesday_date": first.get("wednesday_date", ""),
        "wednesday_label": first.get("wednesday_label", ""),
        "friday_date": first.get("friday_date", ""),
        "friday_label": first.get("friday_label", ""),
    }


def display_rows(rows: list[dict] | None) -> list[dict]:
    """Projection Streamlit sans numéro de téléphone."""
    return [
        {
            "Membre": row.get("name", row.get("code", "")),
            "Services du week-end": row.get("services", ""),
            "Mercredi": row.get("wednesday_status", ""),
            "Vendredi": row.get("friday_status", ""),
            "État contact": "✅ Prêt" if row.get("ready") else "⛔ À compléter",
            "À corriger": " — " if row.get("ready") else ", ".join(row.get("reasons") or []),
        }
        for row in (rows or [])
        if isinstance(row, dict)
    ]

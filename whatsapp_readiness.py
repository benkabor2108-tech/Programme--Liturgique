"""Calcul pur de la readiness WhatsApp des programmes liturgiques publiés.

Ce module ne lit ni n'écrit Supabase et ne contacte pas Meta. Il évalue
uniquement les dimanches futurs actifs et la configuration locale des contacts
(numéro, consentement, activation) afin d'alimenter l'interface et les tests.
"""
from __future__ import annotations

from datetime import date
import re

ROLE_FIELDS = (
    ("r1", "1re lecture"),
    ("r2", "2e lecture"),
    ("f_mon", "Monition + P.U. — Français"),
    ("m_mon", "Monition + P.U. — Mooré"),
    ("f_ann", "Annonces — Français"),
    ("m_ann", "Annonces — Mooré"),
)


def _active_history_row(row: dict | None) -> bool:
    if not isinstance(row, dict):
        return False
    status = str(row.get("history_status", "active")).strip().lower() or "active"
    return status != "cancelled"


def normalize_number(value: object) -> str:
    """Retourne uniquement les chiffres d'un numéro plausible, sinon une chaîne vide."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if 8 <= len(digits) <= 15 else ""


def contact_readiness(contact: dict | None) -> tuple[bool, list[str]]:
    """Évalue un contact sans exposer son numéro."""
    contact = contact if isinstance(contact, dict) else {}
    reasons: list[str] = []
    if not normalize_number(contact.get("number", "")):
        reasons.append("numéro absent ou invalide")
    if not bool(contact.get("consent")):
        reasons.append("consentement absent")
    if not bool(contact.get("enabled")):
        reasons.append("rappels désactivés")
    return not reasons, reasons


def scheduled_assignments(row: dict) -> list[tuple[str, str]]:
    """Retourne une affectation unique par membre, même en cas de données incohérentes."""
    codes = row.get("codes", {}) if isinstance(row.get("codes"), dict) else {}
    roles_by_code: dict[str, list[str]] = {}
    order: list[str] = []
    for field, label in ROLE_FIELDS:
        code = str(codes.get(field) or "").strip()
        if not code:
            continue
        if code not in roles_by_code:
            roles_by_code[code] = []
            order.append(code)
        if label not in roles_by_code[code]:
            roles_by_code[code].append(label)
    return [(code, " / ".join(roles_by_code[code])) for code in order]


def future_readiness_rows(state: dict | None, reference_day: date | None = None) -> list[dict]:
    """Construit la readiness des affectations des dimanches futurs encore actifs."""
    state = state if isinstance(state, dict) else {}
    reference_day = reference_day or date.today()
    names = state.get("names", {}) if isinstance(state.get("names"), dict) else {}
    contacts = state.get("whatsapp_contacts", {}) if isinstance(state.get("whatsapp_contacts"), dict) else {}

    dated_rows: list[tuple[date, dict]] = []
    for row in state.get("history", []) or []:
        if not _active_history_row(row):
            continue
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except (TypeError, ValueError):
            continue
        if day.weekday() != 6:
            continue
        if day >= reference_day:
            dated_rows.append((day, row))

    output: list[dict] = []
    for day, row in sorted(dated_rows, key=lambda item: item[0]):
        for code, role in scheduled_assignments(row):
            ready, reasons = contact_readiness(contacts.get(code, {}))
            output.append({
                "date": day.isoformat(),
                "date_label": day.strftime("%d/%m/%Y"),
                "code": code,
                "name": str(names.get(code, code)),
                "role": role,
                "ready": ready,
                "reasons": reasons,
                "status": "✅ Prêt" if ready else "⛔ À compléter",
                "reason_label": " — " if ready else ", ".join(reasons),
            })
    return output


def readiness_summary(rows: list[dict] | None) -> dict:
    rows = [row for row in (rows or []) if isinstance(row, dict)]
    ready = [row for row in rows if bool(row.get("ready"))]
    blocked = [row for row in rows if not bool(row.get("ready"))]
    blocker_map: dict[str, str] = {}
    for row in blocked:
        code = str(row.get("code", "")).strip()
        if code:
            blocker_map[code] = str(row.get("name", code))
    sundays = sorted({str(row.get("date", "")) for row in rows if row.get("date")})
    return {
        "assignments": len(rows),
        "ready": len(ready),
        "blocked": len(blocked),
        "sundays": len(sundays),
        "blocker_codes": sorted(blocker_map),
        "blocker_names": [blocker_map[code] for code in sorted(blocker_map)],
    }


def display_rows(rows: list[dict] | None) -> list[dict]:
    """Projection sans numéro, adaptée à l'affichage Streamlit."""
    return [
        {
            "Dimanche": row.get("date_label", ""),
            "Membre": row.get("name", row.get("code", "")),
            "Service": row.get("role", ""),
            "État WhatsApp": row.get("status", ""),
            "À corriger": row.get("reason_label", ""),
        }
        for row in (rows or [])
        if isinstance(row, dict)
    ]

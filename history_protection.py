"""Protection non destructive de l'historique du Programme liturgique.

Ce module isole les règles qui garantissent qu'une annulation de programme
n'efface jamais les lignes historiques déjà publiées. Une annulation ajoute un
statut aux lignes concernées et reconstruit uniquement l'état courant des
rotations à partir des lignes encore actives.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone

CANCELLED_STATUS = "cancelled"
ROTATION_KEYS = (
    "people",
    "reading_cycle_seen",
    "reading_pairs",
    "monition_pairs",
    "next_first_language",
)


def history_status(row: dict | None) -> str:
    """Retourne le statut historique normalisé d'une ligne de programme."""
    if not isinstance(row, dict):
        return ""
    value = str(row.get("history_status", "active")).strip().lower()
    return value or "active"


def is_history_row_active(row: dict | None) -> bool:
    """Les anciennes lignes sans statut restent actives par compatibilité."""
    return isinstance(row, dict) and history_status(row) != CANCELLED_STATUS


def active_history_rows(history) -> list[dict]:
    """Retourne les lignes actives sans modifier l'historique source."""
    return [row for row in (history or []) if is_history_row_active(row)]


def cancelled_history_rows(history) -> list[dict]:
    """Retourne uniquement les lignes conservées mais marquées comme annulées."""
    return [
        row for row in (history or [])
        if isinstance(row, dict) and history_status(row) == CANCELLED_STATUS
    ]


def latest_active_history_month(history):
    """Retourne (année, mois, nombre) pour le dernier mois encore actif."""
    dated = []
    for row in active_history_rows(history):
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except Exception:
            continue
        dated.append(day)
    if not dated:
        return None
    latest = max(dated)
    count = sum(1 for day in dated if day.year == latest.year and day.month == latest.month)
    return latest.year, latest.month, count


def cancel_latest_month_non_destructive(
    state,
    rebuild_rotation,
    month_labels=None,
    *,
    actor="Administrateur principal",
    reason="",
    timestamp=None,
):
    """Annule le dernier mois actif sans retirer aucune ligne de ``history``.

    ``rebuild_rotation`` est fourni par le cœur historique. Seules les clés de
    rotation sont reprises de son résultat ; toutes les autres données
    persistantes (présences, comptes, WhatsApp, brouillons, audit, futures clés)
    sont conservées telles quelles.
    """
    if not isinstance(state, dict):
        return False, "État invalide : aucune annulation effectuée.", state

    result = deepcopy(state)
    history = result.get("history", [])
    if not isinstance(history, list):
        return False, "Historique invalide : aucune annulation effectuée.", state

    info = latest_active_history_month(history)
    if not info:
        return False, "Aucun mois actif à annuler.", result

    year, month, _ = info
    stamp = str(timestamp or datetime.now(timezone.utc).isoformat())
    clean_reason = " ".join(str(reason or "").split()).strip()
    marked = 0

    for row in history:
        if not is_history_row_active(row):
            continue
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except Exception:
            continue
        if day.year == year and day.month == month:
            row["history_status"] = CANCELLED_STATUS
            row["cancelled_at"] = stamp
            row["cancelled_by"] = str(actor)
            if clean_reason:
                row["cancel_reason"] = clean_reason
            marked += 1

    if not marked:
        return False, "Aucune célébration active n'a été trouvée pour ce mois.", result

    rebuilt = rebuild_rotation(result, active_history_rows(history))
    if isinstance(rebuilt, dict):
        for key in ROTATION_KEYS:
            if key in rebuilt:
                result[key] = deepcopy(rebuilt[key])

    audit = result.setdefault("audit_log", [])
    if not isinstance(audit, list):
        audit = []
        result["audit_log"] = audit
    audit.append({
        "type": "history_month_cancelled",
        "action": "history_month_cancelled",
        "timestamp": stamp,
        "actor": str(actor),
        "year": year,
        "month": month,
        "celebration_count": marked,
        "reason": clean_reason,
        "preserved": True,
    })

    label = f"{month:02d}/{year}"
    if month_labels and 1 <= month <= len(month_labels):
        label = f"{month_labels[month - 1]} {year}"
    return (
        True,
        f"{label} annulé sans suppression ({marked} célébration(s) conservée(s) dans l'historique).",
        result,
    )

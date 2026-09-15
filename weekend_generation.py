"""Helpers purs pour les célébrations liturgiques du week-end.

La génération mensuelle utilise samedi + dimanche, tandis que les rappels
WhatsApp automatiques restent volontairement limités aux dimanches tant qu'un
workflow spécifique au samedi n'a pas été validé.
"""
from __future__ import annotations

import calendar
from datetime import date


def weekend_service_days(year: int, month: int) -> list[date]:
    """Retourne tous les samedis et dimanches du mois, par ordre chronologique."""
    cal = calendar.Calendar(firstweekday=calendar.MONDAY)
    return [
        day
        for day in cal.itermonthdates(int(year), int(month))
        if day.month == int(month) and day.weekday() in (5, 6)
    ]


def service_day_label(day: date) -> str:
    """Libellé français strict pour une célébration du week-end."""
    if day.weekday() == 5:
        return "Samedi"
    if day.weekday() == 6:
        return "Dimanche"
    raise ValueError("La date n'est ni un samedi ni un dimanche.")

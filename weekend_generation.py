"""Helpers purs pour les célébrations liturgiques du week-end.

La génération mensuelle utilise samedi + dimanche, tandis que les rappels
WhatsApp automatiques restent volontairement limités aux dimanches tant qu'un
workflow spécifique au samedi n'a pas été validé.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta


def weekend_service_days(year: int, month: int) -> list[date]:
    """Retourne les week-ends du mois et le samedi précédant son premier dimanche."""
    cal = calendar.Calendar(firstweekday=calendar.MONDAY)
    days = [
        day for day in cal.itermonthdates(int(year), int(month))
        if day.month == int(month) and day.weekday() in (5, 6)
    ]
    first_sunday = next((day for day in days if day.weekday() == 6), None)
    if first_sunday is not None:
        preceding_saturday = first_sunday - timedelta(days=1)
        if preceding_saturday not in days:
            days.insert(0, preceding_saturday)
    return days


def liturgical_reference_day(day: date) -> date:
    """Date liturgique dont les lectures doivent être utilisées pour ce service.

    Le samedi soir est une messe anticipée du dimanche : il reprend donc
    exactement les références bibliques du dimanche qui suit.
    """
    if day.weekday() == 5:
        return day + timedelta(days=1)
    if day.weekday() == 6:
        return day
    raise ValueError("La date n'est ni un samedi ni un dimanche.")


def liturgical_reference_days(days: list[date]) -> list[date]:
    """Retourne les dimanches de référence uniques, dans l'ordre des services."""
    result: list[date] = []
    seen: set[date] = set()
    for day in days:
        reference_day = liturgical_reference_day(day)
        if reference_day not in seen:
            result.append(reference_day)
            seen.add(reference_day)
    return result


def service_day_label(day: date) -> str:
    """Libellé français strict pour une célébration du week-end."""
    if day.weekday() == 5:
        return "Samedi"
    if day.weekday() == 6:
        return "Dimanche"
    raise ValueError("La date n'est ni un samedi ni un dimanche.")

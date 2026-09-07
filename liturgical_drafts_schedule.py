from datetime import date, datetime, time, timedelta

from liturgical_drafts_themes import APP_TIMEZONE

def easter_sunday(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def first_advent_sunday(year):
    for day in range(27, 34):
        candidate = date(year, 11, day) if day <= 30 else date(year, 12, day - 30)
        if candidate.weekday() == 6:
            return candidate
    raise RuntimeError("Impossible de calculer le premier dimanche de l'Avent.")


def major_celebrations(year):
    easter = easter_sunday(year)
    advent1 = first_advent_sunday(year)
    events = {
        date(year, 1, 1): "Sainte Marie, Mère de Dieu",
        date(year, 1, 6): "Épiphanie du Seigneur",
        date(year, 3, 19): "Saint Joseph, époux de la Vierge Marie",
        date(year, 3, 25): "Annonciation du Seigneur",
        easter - timedelta(days=7): "Dimanche des Rameaux et de la Passion",
        easter - timedelta(days=3): "Jeudi saint — Cène du Seigneur",
        easter - timedelta(days=2): "Vendredi saint — Passion du Seigneur",
        easter: "Dimanche de Pâques — Résurrection du Seigneur",
        easter + timedelta(days=39): "Ascension du Seigneur",
        easter + timedelta(days=49): "Pentecôte",
        easter + timedelta(days=56): "Sainte Trinité",
        easter + timedelta(days=60): "Saint-Sacrement du Corps et du Sang du Christ",
        easter + timedelta(days=68): "Sacré-Cœur de Jésus",
        date(year, 6, 29): "Saints Pierre et Paul, apôtres",
        date(year, 8, 15): "Assomption de la Vierge Marie",
        date(year, 11, 1): "Tous les Saints",
        advent1 - timedelta(days=7): "Notre Seigneur Jésus Christ, Roi de l'Univers",
        date(year, 12, 8): "Immaculée Conception de la Vierge Marie",
        date(year, 12, 25): "Nativité du Seigneur — Noël",
    }
    return events


def next_sunday(day):
    days = (6 - day.weekday()) % 7
    if days == 0:
        days = 7
    return day + timedelta(days=days)


def unlock_for_sunday(service_date):
    return datetime.combine(service_date - timedelta(days=5), time(18, 0), tzinfo=APP_TIMEZONE)


def unlock_for_event(service_date):
    return datetime.combine(service_date - timedelta(days=5), time(18, 0), tzinfo=APP_TIMEZONE)


def is_major_event(service_date):
    return service_date in major_celebrations(service_date.year)


def availability_for(service_date, kind, now=None):
    now = now or datetime.now(APP_TIMEZONE)
    if kind == "dimanche" and not is_major_event(service_date):
        unlock = unlock_for_sunday(service_date)
        rule = "mardi à 18 h 00"
    else:
        unlock = unlock_for_event(service_date)
        rule = "5 jours avant à 18 h 00"
    return {
        "available": now >= unlock,
        "unlock_at": unlock,
        "rule": rule,
    }

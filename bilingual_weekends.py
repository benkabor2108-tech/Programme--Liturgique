"""Programmation bilingue du samedi soir et du dimanche, sans cumul sur un week-end."""
from copy import deepcopy
from datetime import timedelta
import random


def weekend_dates(sundays, year, month):
    dates = []
    for sunday in sundays(year, month):
        dates.extend([sunday - timedelta(days=1), sunday])
    return dates


def generate_bilingual_weekends(state, year, month, refs, seed, sundays,
                                normalize_state, programmable_codes, assign):
    """Retourne (lignes, état simulé). Ne sauvegarde ni ne publie rien."""
    working = normalize_state(deepcopy(state))
    dates = weekend_dates(sundays, year, month)
    existing = {row.get("date") for row in working.get("history", [])}
    if existing.intersection(d.isoformat() for d in dates):
        raise ValueError("Une célébration de cette période est déjà publiée.")
    rng = random.Random(seed + year * 100 + month)
    rows = []
    for sunday in sundays(year, month):
        used_weekend = set()
        reference = refs.get(sunday.isoformat(), {})
        if not reference.get("r1") or not reference.get("ev"):
            raise ValueError(f"Références bibliques incomplètes pour {sunday.isoformat()}.")
        for service_day, label in ((sunday - timedelta(days=1), "Samedi soir"),
                                   (sunday, "Dimanche")):
            available = {}
            for lang in ("FR", "MO"):
                available[lang] = [
                    c for c in programmable_codes(working, lang, sunday)
                    if c not in used_weekend
                ]
                if len(available[lang]) < 2:
                    raise ValueError(
                        f"Effectif insuffisant pour {label} du {service_day.isoformat()} "
                        f"({lang}). Éviter un doublon exige au moins quatre personnes "
                        "par langue sur le week-end."
                    )
            chosen = {}
            for lang in ("FR", "MO"):
                readers = [c for c in available[lang]
                           if working["people"][c].get("next_role") in (None, "LECTURE")]
                if not readers:
                    raise ValueError(f"Aucun lecteur {lang} compatible avec l'alternance.")
                readers.sort(key=lambda c: (
                    working["people"][c].get("reading_count", 0),
                    working["people"][c].get("last_service") or "", rng.random()))
                chosen[lang + "_read"] = readers[0]
                available[lang].remove(readers[0])
                monitions = [c for c in available[lang]
                             if working["people"][c].get("next_role") in (None, "MONITION")]
                if not monitions:
                    raise ValueError(f"Aucune monition {lang} compatible avec l'alternance.")
                monitions.sort(key=lambda c: (
                    working["people"][c].get("monition_count", 0),
                    working["people"][c].get("last_service") or "", rng.random()))
                chosen[lang + "_mon"] = monitions[0]
                available[lang].remove(monitions[0])
            first = working.get("next_first_language", "FR")
            r1, r2 = (chosen["FR_read"], chosen["MO_read"]) if first == "FR" else (
                chosen["MO_read"], chosen["FR_read"])
            codes = {
                "r1": r1, "r2": r2, "f_mon": chosen["FR_mon"],
                "m_mon": chosen["MO_mon"],
            }
            names = working["names"]
            row = {
                "date": service_day.isoformat(),
                "Dimanche": service_day.strftime("%d/%m/%Y"),
                "celebration": label,
                "liturgical_date": sunday.isoformat(),
                "Références": f"1re : {reference['r1']}\\n2e : {reference.get('r2', '')}\\nÉv. : {reference['ev']}",
                "Lecteurs": f"1re ({first}) : {names[r1]}\\n2e ({'MO' if first == 'FR' else 'FR'}) : {names[r2]}",
                "Monition + P.U.": f"FR : {names[codes['f_mon']]}\\nMO : {names[codes['m_mon']]}",

                "Source références": reference.get("source", ""),
                "Source URL": reference.get("source_url", ""),
                "codes": codes,
            }
            rows.append(row)
            used_weekend.update(codes.values())
            for role in ("r1", "r2"):
                assign(working, codes[role], "LECTURE", service_day)
            for role in ("f_mon", "m_mon"):
                assign(working, codes[role], "MONITION", service_day)
            working["reading_pairs"].append([chosen["FR_read"], chosen["MO_read"]])
            working["monition_pairs"].append([codes["f_mon"], codes["m_mon"]])
            working["next_first_language"] = "MO" if first == "FR" else "FR"
    working["history"].extend(deepcopy(rows))
    return rows, working

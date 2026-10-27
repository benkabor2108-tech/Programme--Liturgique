"""Projets de programmation : aucun impact sur les rotations avant validation principale."""
from copy import deepcopy
from datetime import date


ROLES = ("r1", "r2", "f_mon", "m_mon", "f_ann", "m_ann")


def draft_key(year, month):
    return f"{int(year):04d}-{int(month):02d}"


def store_draft(state, year, month, rows, actor):
    key = draft_key(year, month)
    state.setdefault("program_drafts", {})[key] = {
        "year": int(year), "month": int(month),
        "rows": deepcopy(rows), "updated_by": actor, "status": "à valider",
    }
    return key


def validate_draft(state, draft, sundays, programmable_codes):
    year, month = int(draft["year"]), int(draft["month"])
    rows = draft.get("rows", [])
    expected = [day.isoformat() for sunday in sundays(year, month) for day in (sunday - __import__("datetime").timedelta(days=1), sunday)] if any(row.get("celebration") == "Samedi soir" for row in rows) else [d.isoformat() for d in sundays(year, month)]
    if [row.get("date") for row in rows] != expected:
        raise ValueError("Les dimanches du projet ne correspondent pas au mois choisi.")
    if any(row.get("date") in set(expected) for row in state.get("history", [])):
        raise ValueError("Ce mois est déjà publié. Aucune modification n'a été enregistrée.")
    weekend_codes = {}
    for row in rows:
        sunday_key = row.get("liturgical_date", row["date"])
        weekend_codes.setdefault(sunday_key, []).extend(row.get("codes", {}).values())
        codes = row.get("codes", {})
        if set(codes) != set(ROLES) or len(set(codes.values())) != len(ROLES):
            raise ValueError("Chaque dimanche doit avoir six intervenants distincts.")
        d = date.fromisoformat(row.get("liturgical_date", row["date"]))
        allowed_fr = set(programmable_codes(state, "FR", d))
        allowed_mo = set(programmable_codes(state, "MO", d))
        for role in ("f_mon", "f_ann"):
            if codes[role] not in allowed_fr:
                raise ValueError(f"Intervenant francophone non éligible le {row['date']}.")
        for role in ("m_mon", "m_ann"):
            if codes[role] not in allowed_mo:
                raise ValueError(f"Intervenant mooréphone non éligible le {row['date']}.")
        if {codes["r1"], codes["r2"]}.intersection(allowed_fr) == set() or {codes["r1"], codes["r2"]}.intersection(allowed_mo) == set():
            raise ValueError(f"Les deux langues doivent être représentées le {row['date']}.")
        if not ((codes["r1"] in allowed_fr and codes["r2"] in allowed_mo) or
                (codes["r1"] in allowed_mo and codes["r2"] in allowed_fr)):
            raise ValueError(f"Les lecteurs ne respectent pas les langues le {row['date']}.")
    for key, assigned in weekend_codes.items():
        if len(assigned) != len(set(assigned)):
            raise ValueError(f"Un lecteur est affecté deux fois le même week-end ({key}).")
    return True


def publish_draft(state, key, sundays, programmable_codes, assign, normalize_state):
    draft = state.get("program_drafts", {}).get(key)
    if not draft:
        raise ValueError("Projet introuvable.")
    validate_draft(state, draft, sundays, programmable_codes)
    updated = normalize_state(deepcopy(state))
    for row in draft["rows"]:
        d = date.fromisoformat(row["date"])
        codes = row["codes"]
        for role in ("r1", "r2"):
            assign(updated, codes[role], "LECTURE", d)
        for role in ("f_mon", "m_mon"):
            assign(updated, codes[role], "MONITION", d)
        for role in ("f_ann", "m_ann"):
            assign(updated, codes[role], "ANNONCE", d)
        updated.setdefault("reading_pairs", []).append([codes["r1"], codes["r2"]])
        updated.setdefault("monition_pairs", []).append([codes["f_mon"], codes["m_mon"]])
        first_lang = "FR" if codes["r1"].startswith("F") else "MO"
        updated["next_first_language"] = "MO" if first_lang == "FR" else "FR"
        updated["history"].append(deepcopy(row))
    updated["program_drafts"].pop(key, None)
    return updated

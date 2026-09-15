from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: attendu 1 occurrence, trouvé {count}")
    return text.replace(old, new, 1)


# --- weekend_generation.py -------------------------------------------------
path = ROOT / "weekend_generation.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from datetime import date\n",
    "from datetime import date, timedelta\n",
    "import timedelta",
)
marker = "def service_day_label(day: date) -> str:\n"
insert = '''def liturgical_reference_day(day: date) -> date:
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


'''
text = replace_once(text, marker, insert + marker, "helpers références anticipées")
path.write_text(text, encoding="utf-8")


# --- liturgie_app.py -------------------------------------------------------
path = ROOT / "liturgie_app.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from weekend_generation import service_day_label, weekend_service_days\n",
    "from weekend_generation import (\n"
    "    liturgical_reference_day,\n"
    "    liturgical_reference_days,\n"
    "    service_day_label,\n"
    "    weekend_service_days,\n"
    ")\n",
    "imports weekend_generation",
)
text = replace_once(
    text,
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.13-weekend-generation"',
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.14-anticipated-mass-references"',
    "version v3.10.14",
)

text = replace_once(
    text,
    "        '            \"date\": sunday.isoformat(),\\n'\n"
    "        '            \"jour_service\": \"samedi\" if sunday.weekday() == 5 else \"dimanche\",\\n'\n"
    "        '            \"Dimanche\": f\"{service_day_label(sunday)} {sunday.strftime(\\\'%d/%m/%Y\\\')}\",\\n',\n",
    "        '            \"date\": sunday.isoformat(),\\n'\n"
    "        '            \"jour_service\": \"samedi\" if sunday.weekday() == 5 else \"dimanche\",\\n'\n"
    "        '            \"date_reference\": liturgical_reference_day(sunday).isoformat(),\\n'\n"
    "        '            \"Dimanche\": f\"{service_day_label(sunday)} {sunday.strftime(\\\'%d/%m/%Y\\\')}\",\\n',\n",
    "métadonnée dimanche de référence",
)

anchor = """    source = _replace_once(
        source,
        '        month_sundays = sundays(year, month)\\n',
        '        month_sundays = weekend_service_days(year, month)\\n',
        "sélection des célébrations du week-end",
    )
"""
new_block = anchor + """    source = _replace_once(
        source,
        '''def fetch_month_aelf_refs(dates, zone):
    refs = {}
    errors = {}
    for day in dates:
        try:
            refs[day.isoformat()] = fetch_aelf_refs(day.isoformat(), zone)
        except Exception as exc:
            errors[day.isoformat()] = str(exc)
    return refs, errors
''',
        '''def fetch_month_aelf_refs(dates, zone):
    refs = {}
    errors = {}
    for day in dates:
        reference_day = liturgical_reference_day(day)
        try:
            item = dict(fetch_aelf_refs(reference_day.isoformat(), zone))
            item["reference_date"] = reference_day.isoformat()
            if day.weekday() == 5:
                item["source"] = f"{item.get('source', 'AELF')} · messe anticipée du dimanche"
            refs[day.isoformat()] = item
        except Exception as exc:
            errors[day.isoformat()] = str(exc)
    return refs, errors
''',
        "AELF samedi = dimanche suivant",
    )
    source = _replace_once(
        source,
        '''def parse_refs(text, dates):
    refs = {d.isoformat(): {"r1": "", "r2": "", "ev": ""} for d in dates}
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) >= 4 and parts[0] in refs:
            refs[parts[0]] = {"r1": parts[1], "r2": parts[2], "ev": parts[3], "source": "Saisie manuelle"}
    return refs
''',
        '''def parse_refs(text, dates):
    dates = list(dates)
    raw_refs = {}
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) >= 4:
            raw_refs[parts[0]] = {"r1": parts[1], "r2": parts[2], "ev": parts[3], "source": "Saisie manuelle"}

    refs = {}
    for day in dates:
        reference_day = liturgical_reference_day(day)
        item = raw_refs.get(reference_day.isoformat())
        # Compatibilité avec une ancienne saisie où le samedi avait sa propre ligne.
        if item is None:
            item = raw_refs.get(day.isoformat())
        item = dict(item or {"r1": "", "r2": "", "ev": "", "source": "Saisie manuelle"})
        item["reference_date"] = reference_day.isoformat()
        if day.weekday() == 5:
            item["source"] = "Saisie manuelle · messe anticipée du dimanche"
        refs[day.isoformat()] = item
    return refs
''',
        "saisie manuelle samedi = dimanche suivant",
    )
"""
text = replace_once(text, anchor, new_block, "insertion règles références anticipées")

text = replace_once(
    text,
    "        '            st.info(\"📖 Les références des samedis et dimanches seront récupérées automatiquement depuis l\\'API AELF au moment de la génération. Aucun copier-coller n\\'est nécessaire.\")\\n',\n",
    "        '            st.info(\"📖 Le samedi soir est traité comme messe anticipée : il reprend automatiquement les mêmes références bibliques que le dimanche qui suit, y compris si ce dimanche est dans le mois suivant.\")\\n',\n",
    "texte explicatif AELF",
)
text = replace_once(
    text,
    "        '                            \"Célébration\": f\"{service_day_label(d)} {d.strftime(\\\'%d/%m/%Y\\\')}\",\\n',\n",
    "        '                            \"Célébration\": f\"{service_day_label(d)} {d.strftime(\\\'%d/%m/%Y\\\')}\",\\n'\n"
    "        '                            \"Références du\": liturgical_reference_day(d).strftime(\\\'%d/%m/%Y\\\'),\\n',\n",
    "colonne dimanche de référence",
)

manual_anchor = """    source = _replace_once(
        source,
        '    st.caption("📱 Vue téléphone : ouvrez un dimanche pour voir toutes les références et fonctions sans défilement horizontal.")\\n',
"""
manual_insert = """    source = _replace_once(
        source,
        '            example = "\\n".join(f"{d.isoformat()} |  |  | " for d in month_sundays)\\n',
        '            reference_days = liturgical_reference_days(month_sundays)\\n            example = "\\n".join(f"{d.isoformat()} |  |  | " for d in reference_days)\\n',
        "saisie manuelle par dimanche de référence",
    )
    source = _replace_once(
        source,
        '                "AAAA-MM-JJ | 1re lecture | 2e lecture | Évangile",\\n',
        '                "Dimanche de référence (AAAA-MM-JJ) | 1re lecture | 2e lecture | Évangile",\\n',
        "libellé saisie manuelle dimanche",
    )
"""
text = replace_once(text, manual_anchor, manual_insert + manual_anchor, "UI saisie manuelle")

text = replace_once(
    text,
    '        "weekend_service_days": weekend_service_days,\n        "service_day_label": service_day_label,\n',
    '        "weekend_service_days": weekend_service_days,\n        "service_day_label": service_day_label,\n        "liturgical_reference_day": liturgical_reference_day,\n        "liturgical_reference_days": liturgical_reference_days,\n',
    "namespace helpers références",
)
path.write_text(text, encoding="utf-8")


# --- tests/test_weekend_generation.py -------------------------------------
path = ROOT / "tests" / "test_weekend_generation.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from weekend_generation import service_day_label, weekend_service_days\n",
    "from weekend_generation import (\n"
    "    liturgical_reference_day,\n"
    "    liturgical_reference_days,\n"
    "    service_day_label,\n"
    "    weekend_service_days,\n"
    ")\n",
    "imports tests références",
)
insert_before = "    def test_wrapper_targets_weekend_generation_without_rewriting_core(self):\n"
new_tests = '''    def test_saturday_uses_following_sunday_references(self):
        self.assertEqual(
            liturgical_reference_day(date(2026, 10, 3)),
            date(2026, 10, 4),
        )
        self.assertEqual(
            liturgical_reference_day(date(2026, 10, 4)),
            date(2026, 10, 4),
        )
        # Cas important : samedi en fin de mois, dimanche dans le mois suivant.
        self.assertEqual(
            liturgical_reference_day(date(2026, 10, 31)),
            date(2026, 11, 1),
        )

    def test_reference_days_are_unique_sundays_including_next_month(self):
        refs = liturgical_reference_days(weekend_service_days(2026, 10))
        self.assertEqual(
            [day.isoformat() for day in refs],
            ["2026-10-04", "2026-10-11", "2026-10-18", "2026-10-25", "2026-11-01"],
        )

'''
text = replace_once(text, insert_before, new_tests + insert_before, "tests règle messe anticipée")
text = replace_once(
    text,
    '        self.assertIn("jour_service", wrapper)\n',
    '        self.assertIn("jour_service", wrapper)\n'
    '        self.assertIn("date_reference", wrapper)\n'
    '        self.assertIn("liturgical_reference_day", wrapper)\n'
    '        self.assertIn("AELF samedi = dimanche suivant", wrapper)\n'
    '        self.assertIn("saisie manuelle samedi = dimanche suivant", wrapper)\n',
    "assertions wrapper référence dimanche",
)
path.write_text(text, encoding="utf-8")

print("v3.10.14 anticipated-mass references patch applied")

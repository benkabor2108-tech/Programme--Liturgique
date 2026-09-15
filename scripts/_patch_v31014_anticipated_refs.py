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
marker = '''def service_day_label(day: date) -> str:\n'''
insert = '''def liturgical_reference_day(day: date) -> date:\n    \"\"\"Date liturgique dont les lectures doivent être utilisées pour ce service.\n\n    Le samedi soir est une messe anticipée du dimanche : il reprend donc\n    exactement les références bibliques du dimanche qui suit.\n    \"\"\"\n    if day.weekday() == 5:\n        return day + timedelta(days=1)\n    if day.weekday() == 6:\n        return day\n    raise ValueError(\"La date n'est ni un samedi ni un dimanche.\")\n\n\ndef liturgical_reference_days(days: list[date]) -> list[date]:\n    \"\"\"Retourne les dimanches de référence uniques, dans l'ordre des services.\"\"\"\n    result: list[date] = []\n    seen: set[date] = set()\n    for day in days:\n        reference_day = liturgical_reference_day(day)\n        if reference_day not in seen:\n            result.append(reference_day)\n            seen.add(reference_day)\n    return result\n\n\n'''
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

# Le programme du samedi garde sa propre date/service, mais mémorise le dimanche de référence.
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

# Les appels AELF du samedi sont redirigés vers le dimanche suivant, y compris hors mois.
anchor = '''    source = _replace_once(\n        source,\n        '        month_sundays = sundays(year, month)\\n',\n        '        month_sundays = weekend_service_days(year, month)\\n',\n        \"sélection des célébrations du week-end\",\n    )\n'''
new_block = anchor + '''    source = _replace_once(\n        source,\n        '''def fetch_month_aelf_refs(dates, zone):\n    refs = {}\n    errors = {}\n    for day in dates:\n        try:\n            refs[day.isoformat()] = fetch_aelf_refs(day.isoformat(), zone)\n        except Exception as exc:\n            errors[day.isoformat()] = str(exc)\n    return refs, errors\n''',\n        '''def fetch_month_aelf_refs(dates, zone):\n    refs = {}\n    errors = {}\n    for day in dates:\n        reference_day = liturgical_reference_day(day)\n        try:\n            item = dict(fetch_aelf_refs(reference_day.isoformat(), zone))\n            item[\"reference_date\"] = reference_day.isoformat()\n            if day.weekday() == 5:\n                item[\"source\"] = f\"{item.get('source', 'AELF')} · messe anticipée du dimanche\"\n            refs[day.isoformat()] = item\n        except Exception as exc:\n            errors[day.isoformat()] = str(exc)\n    return refs, errors\n''',\n        \"AELF samedi = dimanche suivant\",\n    )\n    source = _replace_once(\n        source,\n        '''def parse_refs(text, dates):\n    refs = {d.isoformat(): {\"r1\": \"\", \"r2\": \"\", \"ev\": \"\"} for d in dates}\n    for raw in text.splitlines():\n        raw = raw.strip()\n        if not raw:\n            continue\n        parts = [p.strip() for p in raw.split(\"|\")]\n        if len(parts) >= 4 and parts[0] in refs:\n            refs[parts[0]] = {\"r1\": parts[1], \"r2\": parts[2], \"ev\": parts[3], \"source\": \"Saisie manuelle\"}\n    return refs\n''',\n        '''def parse_refs(text, dates):\n    dates = list(dates)\n    raw_refs = {}\n    for raw in text.splitlines():\n        raw = raw.strip()\n        if not raw:\n            continue\n        parts = [p.strip() for p in raw.split(\"|\")]\n        if len(parts) >= 4:\n            raw_refs[parts[0]] = {\"r1\": parts[1], \"r2\": parts[2], \"ev\": parts[3], \"source\": \"Saisie manuelle\"}\n\n    refs = {}\n    for day in dates:\n        reference_day = liturgical_reference_day(day)\n        item = raw_refs.get(reference_day.isoformat())\n        # Compatibilité avec une ancienne saisie où le samedi avait sa propre ligne.\n        if item is None:\n            item = raw_refs.get(day.isoformat())\n        item = dict(item or {\"r1\": \"\", \"r2\": \"\", \"ev\": \"\", \"source\": \"Saisie manuelle\"})\n        item[\"reference_date\"] = reference_day.isoformat()\n        if day.weekday() == 5:\n            item[\"source\"] = \"Saisie manuelle · messe anticipée du dimanche\"\n        refs[day.isoformat()] = item\n    return refs\n''',\n        \"saisie manuelle samedi = dimanche suivant\",\n    )\n'''
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

# En saisie manuelle, on demande une ligne par dimanche de référence et non par service.
manual_anchor = '''    source = _replace_once(\n        source,\n        '    st.caption(\"📱 Vue téléphone : ouvrez un dimanche pour voir toutes les références et fonctions sans défilement horizontal.\")\\n',\n'''
manual_insert = '''    source = _replace_once(\n        source,\n        '            example = \"\\n\".join(f\"{d.isoformat()} |  |  | \" for d in month_sundays)\\n',\n        '            reference_days = liturgical_reference_days(month_sundays)\\n            example = \"\\n\".join(f\"{d.isoformat()} |  |  | \" for d in reference_days)\\n',\n        \"saisie manuelle par dimanche de référence\",\n    )\n    source = _replace_once(\n        source,\n        '                \"AAAA-MM-JJ | 1re lecture | 2e lecture | Évangile\",\\n',\n        '                \"Dimanche de référence (AAAA-MM-JJ) | 1re lecture | 2e lecture | Évangile\",\\n',\n        \"libellé saisie manuelle dimanche\",\n    )\n'''
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
insert_before = '''    def test_wrapper_targets_weekend_generation_without_rewriting_core(self):\n'''
new_tests = '''    def test_saturday_uses_following_sunday_references(self):\n        self.assertEqual(\n            liturgical_reference_day(date(2026, 10, 3)),\n            date(2026, 10, 4),\n        )\n        self.assertEqual(\n            liturgical_reference_day(date(2026, 10, 4)),\n            date(2026, 10, 4),\n        )\n        # Cas important : samedi en fin de mois, dimanche dans le mois suivant.\n        self.assertEqual(\n            liturgical_reference_day(date(2026, 10, 31)),\n            date(2026, 11, 1),\n        )\n\n    def test_reference_days_are_unique_sundays_including_next_month(self):\n        refs = liturgical_reference_days(weekend_service_days(2026, 10))\n        self.assertEqual(\n            [day.isoformat() for day in refs],\n            [\"2026-10-04\", \"2026-10-11\", \"2026-10-18\", \"2026-10-25\", \"2026-11-01\"],\n        )\n\n'''
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

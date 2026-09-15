from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / 'liturgie_app.py').exists() is False:
    ROOT = Path.cwd()


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 occurrence, found {count}")
    return text.replace(old, new, 1)


path = ROOT / "liturgie_app.py"
text = path.read_text(encoding="utf-8")
text = replace_once(text, 'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.12-whatsapp-admin-activation"', 'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.13-weekend-generation"', "version")
text = replace_once(text, 'from whatsapp_readiness import (\n    display_rows as whatsapp_display_rows,\n    future_readiness_rows,\n    readiness_summary,\n)\n', 'from whatsapp_readiness import (\n    display_rows as whatsapp_display_rows,\n    future_readiness_rows,\n    readiness_summary,\n)\nfrom weekend_generation import service_day_label, weekend_service_days\n', "weekend helper import")
anchor = '    source = source.replace(old_version, f\'APP_VERSION = "{APP_VERSION_OVERRIDE}"\', 1)\n\n'
weekend_block = '''    source = source.replace(old_version, f'APP_VERSION = "{APP_VERSION_OVERRIDE}"', 1)

    # v3.10.13 : la génération mensuelle couvre désormais samedi + dimanche.
    source = _replace_once(
        source,
        '    month_dates = {d.isoformat() for d in sundays(year, month)}\\n',
        '    month_dates = {d.isoformat() for d in weekend_service_days(year, month)}\\n',
        "dates de génération samedi + dimanche",
    )
    source = _replace_once(
        source,
        '    month_days = sundays(year, month)\\n',
        '    month_days = weekend_service_days(year, month)\\n',
        "jours du mois samedi + dimanche",
    )
    source = _replace_once(
        source,
        '    for sunday in sundays(year, month):\\n',
        '    for sunday in weekend_service_days(year, month):\\n',
        "boucle de génération samedi + dimanche",
    )
    source = _replace_once(
        source,
        '            "date": sunday.isoformat(),\\n            "Dimanche": sunday.strftime("%d/%m/%Y"),\\n',
        '            "date": sunday.isoformat(),\\n'
        '            "jour_service": "samedi" if sunday.weekday() == 5 else "dimanche",\\n'
        '            "Dimanche": f"{service_day_label(sunday)} {sunday.strftime(\\\'%d/%m/%Y\\\')}",\\n',
        "libellé samedi ou dimanche",
    )
    source = _replace_once(
        source,
        '        month_sundays = sundays(year, month)\\n',
        '        month_sundays = weekend_service_days(year, month)\\n',
        "sélection des célébrations du week-end",
    )
    source = _replace_once(
        source,
        '            st.info("📖 Les références des dimanches seront récupérées automatiquement depuis l\\\'API AELF au moment de la génération. Aucun copier-coller n\\\'est nécessaire.")\\n',
        '            st.info("📖 Les références des samedis et dimanches seront récupérées automatiquement depuis l\\\'API AELF au moment de la génération. Aucun copier-coller n\\\'est nécessaire.")\\n',
        "texte AELF week-end",
    )
    source = _replace_once(
        source,
        '                            "Dimanche": d.strftime("%d/%m/%Y"),\\n',
        '                            "Célébration": f"{service_day_label(d)} {d.strftime(\\\'%d/%m/%Y\\\')}",\\n',
        "prévisualisation AELF week-end",
    )
    source = _replace_once(
        source,
        '    st.caption("📱 Vue téléphone : ouvrez un dimanche pour voir toutes les références et fonctions sans défilement horizontal.")\\n',
        '    st.caption("📱 Vue téléphone : ouvrez une célébration pour voir toutes les références et fonctions sans défilement horizontal.")\\n',
        "libellé vue téléphone",
    )
    source = _replace_once(
        source,
        '            Paragraph("Dimanche", header_style),\\n',
        '            Paragraph("Célébration", header_style),\\n',
        "en-tête PDF célébration",
    )
    source = _replace_once(
        source,
        """def next_published_sunday(state, reference_day=None):
    reference_day = reference_day or now_ouaga().date()
    candidates = []
    for row in state.get("history", []) or []:
        if not is_history_row_active(row):
            continue
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except Exception:
            continue
        if day >= reference_day:
            candidates.append((day, row))
    return min(candidates, key=lambda item: item[0]) if candidates else (None, None)
""",
        """def next_published_sunday(state, reference_day=None):
    reference_day = reference_day or now_ouaga().date()
    candidates = []
    for row in state.get("history", []) or []:
        if not is_history_row_active(row):
            continue
        try:
            day = date.fromisoformat(str(row.get("date", "")))
        except Exception:
            continue
        # Les rappels WhatsApp actuels sont conçus pour le dimanche.
        # Un programme du samedi ne doit donc jamais décaler le prochain dimanche.
        if day.weekday() != 6:
            continue
        if day >= reference_day:
            candidates.append((day, row))
    return min(candidates, key=lambda item: item[0]) if candidates else (None, None)
""",
        "rappels WhatsApp réservés aux dimanches",
    )

'''
text = replace_once(text, anchor, weekend_block, "weekend transform insertion")
text = replace_once(text, '        "whatsapp_display_rows": whatsapp_display_rows,\n', '        "whatsapp_display_rows": whatsapp_display_rows,\n        "weekend_service_days": weekend_service_days,\n        "service_day_label": service_day_label,\n', "runtime helper namespace")
path.write_text(text, encoding="utf-8")

path = ROOT / "scripts" / "whatsapp_automation.py"
text = path.read_text(encoding="utf-8")
text = replace_once(text, '        if day >= reference_day:\n            candidates.append((day, row))\n', '        if day.weekday() != 6:\n            continue\n        if day >= reference_day:\n            candidates.append((day, row))\n', "automation Sunday filter")
path.write_text(text, encoding="utf-8")

path = ROOT / "whatsapp_readiness.py"
text = path.read_text(encoding="utf-8")
text = replace_once(text, 'uniquement les programmes futurs actifs et la configuration locale des contacts\n', 'uniquement les dimanches futurs actifs et la configuration locale des contacts\n', "readiness module doc")
text = replace_once(text, '    """Construit la readiness de toutes les affectations futures encore actives."""\n', '    """Construit la readiness des affectations des dimanches futurs encore actifs."""\n', "readiness function doc")
text = replace_once(text, '        if day >= reference_day:\n            dated_rows.append((day, row))\n', '        if day.weekday() != 6:\n            continue\n        if day >= reference_day:\n            dated_rows.append((day, row))\n', "readiness Sunday filter")
path.write_text(text, encoding="utf-8")

path = ROOT / "scripts" / "whatsapp_global_readiness.py"
text = path.read_text(encoding="utf-8")
text = replace_once(text, "Ce script lit l'état Supabase, contrôle toutes les affectations futures actives\n", "Ce script lit l'état Supabase, contrôle toutes les affectations des dimanches futurs actifs\n", "global readiness doc")
path.write_text(text, encoding="utf-8")

path = ROOT / "tests" / "test_whatsapp_ui_guards.py"
text = path.read_text(encoding="utf-8")
text = replace_once(text, 'self.assertIn("v3.10.12-whatsapp-admin-activation", WRAPPER)', 'self.assertIn("v3.10.13-weekend-generation", WRAPPER)', "ui checkpoint version")
path.write_text(text, encoding="utf-8")

path = ROOT / "tests" / "test_whatsapp_automation.py"
text = path.read_text(encoding="utf-8")
insert_after = '''    def test_next_published_sunday_ignores_cancelled_history(self):
        state = {
            "history": [
                {
                    "date": "2026-10-04",
                    "history_status": "cancelled",
                    "codes": {"r1": "F1"},
                },
                {
                    "date": "2026-10-11",
                    "codes": {"r1": "F2"},
                },
            ]
        }
        sunday, row = wa.next_published_sunday(state, date(2026, 9, 30))
        self.assertEqual(sunday, date(2026, 10, 11))
        self.assertEqual(row["codes"]["r1"], "F2")

'''
addition = insert_after + '''    def test_next_published_sunday_ignores_saturday_program(self):
        state = {
            "history": [
                {"date": "2026-10-03", "codes": {"r1": "F1"}},
                {"date": "2026-10-04", "codes": {"r1": "F2"}},
            ]
        }
        sunday, row = wa.next_published_sunday(state, date(2026, 10, 1))
        self.assertEqual(sunday, date(2026, 10, 4))
        self.assertEqual(row["codes"]["r1"], "F2")

'''
text = replace_once(text, insert_after, addition, "automation Saturday test")
path.write_text(text, encoding="utf-8")

path = ROOT / "tests" / "test_whatsapp_contact_readiness.py"
text = path.read_text(encoding="utf-8")
needle = '        self.assertFalse(next(row for row in rows if row["code"] == "M1")["ready"])\n\n'
addition = needle + '''    def test_future_rows_ignore_saturday_programs(self):
        state = {
            "names": {"F1": "Samedi", "F2": "Dimanche"},
            "whatsapp_contacts": {
                "F1": {"number": "+22670000000", "consent": True, "enabled": True},
                "F2": {"number": "+22671000000", "consent": True, "enabled": True},
            },
            "history": [
                {"date": "2026-10-03", "codes": {"r1": "F1"}},
                {"date": "2026-10-04", "codes": {"r1": "F2"}},
            ],
        }
        rows = future_readiness_rows(state, reference_day=date(2026, 10, 1))
        self.assertEqual([row["code"] for row in rows], ["F2"])

'''
text = replace_once(text, needle, addition, "readiness Saturday test")
path.write_text(text, encoding="utf-8")

path = ROOT / ".github" / "workflows" / "ci.yml"
text = path.read_text(encoding="utf-8")
text = replace_once(text, '          python -m py_compile whatsapp_readiness.py\n', '          python -m py_compile whatsapp_readiness.py\n          python -m py_compile weekend_generation.py\n', "compile weekend helper")
text = replace_once(text, '          python -m py_compile tests/test_whatsapp_ui_guards.py\n', '          python -m py_compile tests/test_whatsapp_ui_guards.py\n          python -m py_compile tests/test_weekend_generation.py\n', "compile weekend tests")
text = replace_once(text, '          python -m unittest tests/test_whatsapp_ui_guards.py -v\n', '          python -m unittest tests/test_whatsapp_ui_guards.py -v\n          python -m unittest tests/test_weekend_generation.py -v\n', "run weekend tests")
path.write_text(text, encoding="utf-8")

print("v3.10.13 weekend-generation patch applied")

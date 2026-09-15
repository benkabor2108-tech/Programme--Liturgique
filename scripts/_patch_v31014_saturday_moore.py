from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: attendu 1 occurrence, trouvé {count}")
    return text.replace(old, new, 1)


# --- liturgie_app.py -------------------------------------------------------
path = ROOT / "liturgie_app.py"
text = path.read_text(encoding="utf-8")

marker = "    state_marker = '        \"whatsapp_send_log\": {},\\n        \"audit_log\": [],\\n'\n"
insert = r'''    source = _replace_once(
        source,
        '''        f_read, m_read = choose_readers(state, sunday, rng)
        first = state["next_first_language"]
        if first == "FR":
            r1_code, r1_lang, r2_code, r2_lang = f_read, "FR", m_read, "MO"
        else:
            r1_code, r1_lang, r2_code, r2_lang = m_read, "MO", f_read, "FR"

        excluded = {f_read, m_read}
        f_mon, m_mon = choose_monitions(state, sunday, excluded, rng)
        excluded.update({f_mon, m_mon})
        f_ann = choose_announcement(state, "FR", sunday, excluded, rng)
        m_ann = choose_announcement(state, "MO", sunday, excluded, rng)

        assign(state, f_read, "LECTURE", sunday)
        assign(state, m_read, "LECTURE", sunday)
        state["reading_pairs"].append([f_read, m_read])
        assign(state, f_mon, "MONITION", sunday)
        assign(state, m_mon, "MONITION", sunday)
        state["monition_pairs"].append([f_mon, m_mon])
        assign(state, f_ann, "ANNONCE", sunday)
        assign(state, m_ann, "ANNONCE", sunday)
        state["next_first_language"] = "MO" if first == "FR" else "FR"
''',
        '''        is_saturday = sunday.weekday() == 5
        if is_saturday:
            # Messe anticipée : trois lecteurs distincts, tous mooréphones.
            # Les annonces restent une fonction indépendante, comme le dimanche.
            mo_read_pool = [
                c for c in programmable_codes(state, "MO", sunday)
                if state["people"][c]["next_role"] in (None, "LECTURE")
            ]
            if len(mo_read_pool) < 2:
                raise RuntimeError(
                    "Le samedi soir exige deux lecteurs mooréphones disponibles pour les deux lectures."
                )
            seen = set(state["reading_cycle_seen"].get("MO", []))
            rng.shuffle(mo_read_pool)
            mo_read_pool.sort(
                key=lambda c: (1 if c in seen else 0, reading_rank(state, c, sunday))
            )
            r1_code, r2_code = mo_read_pool[0], mo_read_pool[1]
            r1_lang = r2_lang = "MO"

            excluded = {r1_code, r2_code}
            mo_mon_pool = monition_pool(state, "MO", excluded, sunday)
            if not mo_mon_pool:
                raise RuntimeError(
                    "Le samedi soir exige un troisième lecteur mooréphone disponible pour la monition/P.U."
                )
            rng.shuffle(mo_mon_pool)
            m_mon = min(mo_mon_pool, key=lambda c: monition_rank(state, c, sunday))
            f_mon = None
            excluded.add(m_mon)

            # Les annonces restent indépendantes et sans cumul avec les trois lecteurs.
            f_ann = choose_announcement(state, "FR", sunday, excluded, rng)
            m_ann = choose_announcement(state, "MO", sunday, excluded, rng)

            assign(state, r1_code, "LECTURE", sunday)
            assign(state, r2_code, "LECTURE", sunday)
            assign(state, m_mon, "MONITION", sunday)
            assign(state, f_ann, "ANNONCE", sunday)
            assign(state, m_ann, "ANNONCE", sunday)
            # Ne pas modifier next_first_language : l'alternance FR/MO reste pilotée par les dimanches.
        else:
            f_read, m_read = choose_readers(state, sunday, rng)
            first = state["next_first_language"]
            if first == "FR":
                r1_code, r1_lang, r2_code, r2_lang = f_read, "FR", m_read, "MO"
            else:
                r1_code, r1_lang, r2_code, r2_lang = m_read, "MO", f_read, "FR"

            excluded = {f_read, m_read}
            f_mon, m_mon = choose_monitions(state, sunday, excluded, rng)
            excluded.update({f_mon, m_mon})
            f_ann = choose_announcement(state, "FR", sunday, excluded, rng)
            m_ann = choose_announcement(state, "MO", sunday, excluded, rng)

            assign(state, f_read, "LECTURE", sunday)
            assign(state, m_read, "LECTURE", sunday)
            state["reading_pairs"].append([f_read, m_read])
            assign(state, f_mon, "MONITION", sunday)
            assign(state, m_mon, "MONITION", sunday)
            state["monition_pairs"].append([f_mon, m_mon])
            assign(state, f_ann, "ANNONCE", sunday)
            assign(state, m_ann, "ANNONCE", sunday)
            state["next_first_language"] = "MO" if first == "FR" else "FR"
''',
        "samedi trois lecteurs mooréphones",
    )
    source = _replace_once(
        source,
        '            "Monition + P.U.": f"FR : {names[f_mon]}\\nMO : {names[m_mon]}",\n',
        '            "Monition + P.U.": (f"MO : {names[m_mon]}" if is_saturday else f"FR : {names[f_mon]}\\nMO : {names[m_mon]}"),\n',
        "affichage monition samedi mooré",
    )
    source = _replace_once(
        source,
        '''            "codes": {
                "r1": r1_code, "r2": r2_code,
                "f_mon": f_mon, "m_mon": m_mon,
                "f_ann": f_ann, "m_ann": m_ann,
            },
''',
        '''            "codes": (
                {
                    "r1": r1_code, "r2": r2_code,
                    "m_mon": m_mon,
                    "f_ann": f_ann, "m_ann": m_ann,
                }
                if is_saturday else
                {
                    "r1": r1_code, "r2": r2_code,
                    "f_mon": f_mon, "m_mon": m_mon,
                    "f_ann": f_ann, "m_ann": m_ann,
                }
            ),
''',
        "codes samedi sans lecteur français",
    )
    source = _replace_once(
        source,
        '''        if r1 in current and r2 in current:
            f_read = r1 if str(r1).startswith("F") else r2
            m_read = r1 if str(r1).startswith("M") else r2
            if f_read in current and m_read in current:
                fresh["reading_pairs"].append([f_read, m_read])
''',
        '''        if r1 in current and r2 in current:
            r1_is_fr = str(r1).startswith("F")
            r2_is_fr = str(r2).startswith("F")
            # Un binôme historique n'est enregistré que pour un vrai couple FR/MO du dimanche.
            if r1_is_fr != r2_is_fr:
                f_read = r1 if r1_is_fr else r2
                m_read = r2 if r1_is_fr else r1
                fresh["reading_pairs"].append([f_read, m_read])
''',
        "reconstruction binômes samedi mooré",
    )
    source = _replace_once(
        source,
        '        if r1 in current:\n            fresh["next_first_language"] = "MO" if str(r1).startswith("F") else "FR"\n',
        '        if r1 in current and sunday.weekday() == 6:\n            fresh["next_first_language"] = "MO" if str(r1).startswith("F") else "FR"\n',
        "alternance langues pilotée par le dimanche",
    )
'''
text = replace_once(text, marker, insert + marker, "insertion règle lecteurs samedi")

old_info = 'Le samedi soir est traité comme messe anticipée : il reprend automatiquement les mêmes références bibliques que le dimanche qui suit, y compris si ce dimanche est dans le mois suivant.'
new_info = 'Le samedi soir est traité comme messe anticipée : mêmes références bibliques que le dimanche qui suit, y compris si ce dimanche est dans le mois suivant. Les 3 lecteurs du samedi (1re lecture, 2e lecture, Monition/P.U.) sont tous mooréphones.'
text = replace_once(text, old_info, new_info, "message règle samedi")
path.write_text(text, encoding="utf-8")


# --- tests/test_weekend_generation.py -------------------------------------
path = ROOT / "tests" / "test_weekend_generation.py"
text = path.read_text(encoding="utf-8")
needle = '        self.assertIn("reference_days = liturgical_reference_days(month_sundays)", wrapper)\n'
addition = needle + (
    '        self.assertIn("samedi trois lecteurs mooréphones", wrapper)\n'
    '        self.assertIn("is_saturday = sunday.weekday() == 5", wrapper)\n'
    '        self.assertIn("r1_lang = r2_lang = \\"MO\\"", wrapper)\n'
    '        self.assertIn("troisième lecteur mooréphone", wrapper)\n'
    '        self.assertIn("codes samedi sans lecteur français", wrapper)\n'
    '        self.assertIn("sunday.weekday() == 6", wrapper)\n'
    '        self.assertIn("Les 3 lecteurs du samedi", wrapper)\n'
)
text = replace_once(text, needle, addition, "tests règle lecteurs samedi")
path.write_text(text, encoding="utf-8")

print("v3.10.14 Saturday Mooré reader rule patched")

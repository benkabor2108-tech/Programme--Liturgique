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

text = replace_once(
    text,
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.17-whatsapp-reminder-preview"',
    'APP_VERSION_OVERRIDE = "2026.09.16-persistant-supabase-v3.10.18-saturday-combined-ministry"',
    "version v3.10.18",
)

text = replace_once(
    text,
    '            # Messe anticipée : trois lecteurs distincts, tous mooréphones.\n            # Les annonces restent une fonction indépendante, comme le dimanche.\n',
    '            # Messe anticipée : trois intervenants distincts, tous mooréphones.\n            # Le 3e assure Monition + P.U. + Annonces.\n',
    "commentaire ministère samedi",
)

text = replace_once(
    text,
    '''            f_mon = None
            excluded.add(m_mon)

            # Les annonces restent indépendantes et sans cumul avec les trois lecteurs.
            f_ann = choose_announcement(state, "FR", sunday, excluded, rng)
            m_ann = choose_announcement(state, "MO", sunday, excluded, rng)

            assign(state, r1_code, "LECTURE", sunday)
            assign(state, r2_code, "LECTURE", sunday)
            assign(state, m_mon, "MONITION", sunday)
            assign(state, f_ann, "ANNONCE", sunday)
            assign(state, m_ann, "ANNONCE", sunday)
''',
    '''            f_mon = None
            # Messe anticipée : la même personne assure Monition + P.U. + Annonces.
            f_ann = None
            m_ann = m_mon

            assign(state, r1_code, "LECTURE", sunday)
            assign(state, r2_code, "LECTURE", sunday)
            assign(state, m_mon, "MONITION", sunday)
            assign(state, m_mon, "ANNONCE", sunday)
''',
    "samedi monition pu annonces même personne",
)

text = replace_once(
    text,
    '        "affichage monition samedi mooré",\n    )\n',
    '''        "affichage monition samedi mooré",
    )
    source = _replace_once(
        source,
        '            "Annonces": f"FR : {names[f_ann]}\\nMO : {names[m_ann]}",\\n',
        '            "Annonces": (f"MO : {names[m_mon]}" if is_saturday else f"FR : {names[f_ann]}\\nMO : {names[m_ann]}"),\\n',
        "affichage annonces samedi même personne",
    )
''',
    "injection affichage annonces samedi",
)

text = replace_once(
    text,
    '''                {
                    "r1": r1_code, "r2": r2_code,
                    "m_mon": m_mon,
                    "f_ann": f_ann, "m_ann": m_ann,
                }
''',
    '''                {
                    "r1": r1_code, "r2": r2_code,
                    "m_mon": m_mon,
                    "m_ann": m_mon,
                }
''',
    "codes samedi ministère combiné",
)

text = replace_once(
    text,
    'Les 3 lecteurs du samedi (1re lecture, 2e lecture, Monition/P.U.) sont tous mooréphones.',
    'Les 3 intervenants du samedi sont tous mooréphones : 1re lecture, 2e lecture, puis une même personne pour Monition/P.U. + Annonces.',
    "texte explicatif samedi",
)

path.write_text(text, encoding="utf-8")


# --- scripts/whatsapp_automation.py ---------------------------------------
path = ROOT / "scripts" / "whatsapp_automation.py"
text = path.read_text(encoding="utf-8")
old = '''def role_for_code(row: dict, code: str) -> str:
    codes = row.get("codes", {}) if isinstance(row.get("codes"), dict) else {}
    lang = "Français" if str(code).startswith("F") else "Mooré"
    if codes.get("r1") == code:
        return f"1re lecture — {lang}"
    if codes.get("r2") == code:
        return f"2e lecture — {lang}"
    if codes.get("f_mon") == code or codes.get("m_mon") == code:
        return f"Monition + P.U. — {lang}"
    if codes.get("f_ann") == code or codes.get("m_ann") == code:
        return f"Annonces — {lang}"
    return ""
'''
new = '''def role_for_code(row: dict, code: str) -> str:
    codes = row.get("codes", {}) if isinstance(row.get("codes"), dict) else {}
    lang = "Français" if str(code).startswith("F") else "Mooré"
    roles = []
    if codes.get("r1") == code:
        roles.append(f"1re lecture — {lang}")
    if codes.get("r2") == code:
        roles.append(f"2e lecture — {lang}")
    if codes.get("f_mon") == code or codes.get("m_mon") == code:
        roles.append(f"Monition + P.U. — {lang}")
    if codes.get("f_ann") == code or codes.get("m_ann") == code:
        roles.append(f"Annonces — {lang}")
    return " + ".join(roles)
'''
text = replace_once(text, old, new, "rôle WhatsApp combiné")
path.write_text(text, encoding="utf-8")


# --- tests/test_weekend_generation.py -------------------------------------
path = ROOT / "tests" / "test_weekend_generation.py"
text = path.read_text(encoding="utf-8")
needle = '        self.assertIn("Les 3 lecteurs du samedi", wrapper)\n'
replacement = '''        self.assertIn("Les 3 intervenants du samedi", wrapper)
        self.assertIn("la même personne assure Monition + P.U. + Annonces", wrapper)
        self.assertIn("f_ann = None", wrapper)
        self.assertIn("m_ann = m_mon", wrapper)
        self.assertIn('"m_ann": m_mon', wrapper)
'''
text = replace_once(text, needle, replacement, "tests ministère combiné samedi")
path.write_text(text, encoding="utf-8")


# --- tests/test_whatsapp_automation.py ------------------------------------
path = ROOT / "tests" / "test_whatsapp_automation.py"
text = path.read_text(encoding="utf-8")
insert_marker = 'class WhatsAppAutomationTests(unittest.TestCase):\n'
addition = '''class WhatsAppAutomationTests(unittest.TestCase):
    def test_role_for_code_combines_monition_and_announcements(self):
        row = {"codes": {"m_mon": "M3", "m_ann": "M3"}}
        role = automation.role_for_code(row, "M3")
        self.assertIn("Monition + P.U. — Mooré", role)
        self.assertIn("Annonces — Mooré", role)

'''
text = replace_once(text, insert_marker, addition, "test rôle WhatsApp combiné")
path.write_text(text, encoding="utf-8")

print("v3.10.18 Saturday combined ministry patch applied")

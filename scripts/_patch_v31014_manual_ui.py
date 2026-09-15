from pathlib import Path

root = Path(__file__).resolve().parents[1]
wrapper_path = root / "liturgie_app.py"
test_path = root / "tests" / "test_weekend_generation.py"

wrapper = wrapper_path.read_text(encoding="utf-8")
marker = '    state_marker = \'        "whatsapp_send_log": {},\\n        "audit_log": [],\\n\'\n'
if wrapper.count(marker) != 1:
    raise RuntimeError(f"state marker count={wrapper.count(marker)}")

old_core = '''            example = "\\n".join(f"{d.isoformat()} |  |  | " for d in month_sundays)
            refs_text = st.text_area(
                "AAAA-MM-JJ | 1re lecture | 2e lecture | Évangile",
                value=example,
                height=max(160, 38 * len(month_sundays)),
                key=f"refs_{year}_{month}",
            )
'''
new_core = '''            reference_days = liturgical_reference_days(month_sundays)
            example = "\\n".join(f"{d.isoformat()} |  |  | " for d in reference_days)
            refs_text = st.text_area(
                "Dimanche de référence (AAAA-MM-JJ) | 1re lecture | 2e lecture | Évangile",
                value=example,
                height=max(160, 38 * len(reference_days)),
                key=f"refs_{year}_{month}",
            )
'''
transform = (
    "    source = _replace_once(\n"
    "        source,\n"
    f"        {old_core!r},\n"
    f"        {new_core!r},\n"
    "        \"saisie manuelle par dimanche de référence\",\n"
    "    )\n\n"
)
wrapper = wrapper.replace(marker, transform + marker, 1)
wrapper_path.write_text(wrapper, encoding="utf-8")

tests = test_path.read_text(encoding="utf-8")
needle = '        self.assertIn("saisie manuelle samedi = dimanche suivant", wrapper)\n'
addition = needle + '        self.assertIn("saisie manuelle par dimanche de référence", wrapper)\n        self.assertIn("reference_days = liturgical_reference_days(month_sundays)", wrapper)\n'
if tests.count(needle) != 1:
    raise RuntimeError(f"test marker count={tests.count(needle)}")
test_path.write_text(tests.replace(needle, addition, 1), encoding="utf-8")

print("v3.10.14 manual-reference UI patch applied")

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

path = ROOT / "tests" / "test_whatsapp_ui_guards.py"
text = path.read_text(encoding="utf-8")
old = '        self.assertIn("v3.10.17-whatsapp-reminder-preview", WRAPPER)\n'
new = '        self.assertIn("v3.10.18-saturday-combined-ministry", WRAPPER)\n'
if text.count(old) != 1:
    raise RuntimeError(f"version guard: attendu 1 occurrence, trouvé {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Le test ajouté par le patch principal doit utiliser l'alias existant `wa`.
path = ROOT / "tests" / "test_whatsapp_automation.py"
text = path.read_text(encoding="utf-8")
old = '        role = automation.role_for_code(row, "M3")\n'
new = '        role = wa.role_for_code(row, "M3")\n'
if text.count(old) != 1:
    raise RuntimeError(f"WhatsApp alias guard: attendu 1 occurrence, trouvé {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

print("v3.10.18 UI/test guards patched")

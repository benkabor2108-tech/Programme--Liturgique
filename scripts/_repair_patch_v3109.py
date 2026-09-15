from pathlib import Path

path = Path("scripts/_patch_v3109.py")
text = path.read_text(encoding="utf-8")
old = '''ready_marker = '            ready = bool(number and consent and enabled)\\n'\nif core.count(ready_marker) != 2:\n    raise SystemExit(f"number readiness: expected 2 matches, found {core.count(ready_marker)}")\ncore = core.replace(\n    ready_marker,\n    '            normalized_number, _number_error = normalize_whatsapp_number(number)\\n'\n    '            ready = bool(normalized_number and consent and enabled)\\n',\n    2,\n)\n'''
new = '''core = replace_once(\n    core,\n    '            ready = bool(number and consent and enabled)\\n',\n    '            normalized_number, _number_error = normalize_whatsapp_number(number)\\n'\n    '            ready = bool(normalized_number and consent and enabled)\\n',\n    "automation job number readiness",\n)\ncore = replace_once(\n    core,\n    '        ready = bool(number and consent and enabled)\\n',\n    '        normalized_number, _number_error = normalize_whatsapp_number(number)\\n'\n    '        ready = bool(normalized_number and consent and enabled)\\n',\n    "manual sender number readiness",\n)\n'''
if text.count(old) != 1:
    raise SystemExit(f"repair target count={text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patcher repaired")

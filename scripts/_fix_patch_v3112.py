from pathlib import Path

path = Path("scripts/_patch_v3112.py")
text = path.read_text(encoding="utf-8")
old = 'text = replace_once(text, anchor, activation, "activation UI")'
new = '''_anchor_pos = text.rfind(anchor)\nif _anchor_pos < 0:\n    raise SystemExit("activation UI: anchor not found")\ntext = text[:_anchor_pos] + activation + text[_anchor_pos + len(anchor):]'''
if text.count(old) != 1:
    raise SystemExit(f"fix target expected once, got {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patcher precision fix applied")

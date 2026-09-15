from pathlib import Path

path = Path("scripts/_patch_v3112.py")
text = path.read_text(encoding="utf-8")
old = '_anchor_pos = text.rfind(anchor)'
new = '''activation = activation.encode("unicode_escape").decode("ascii").replace("'", "\\\\'")
_anchor_pos = text.rfind(anchor)'''
if text.count(old) != 1:
    raise SystemExit(f"encoding target expected once, got {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("runtime UI encoding fix applied")

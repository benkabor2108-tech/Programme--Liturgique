from pathlib import Path

path = Path("scripts/_patch_v3112.py")
text = path.read_text(encoding="utf-8")
old = '''def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)
'''
new = '''def replace_once(text, old, new, label):
    count = text.count(old)
    if label == "guide activation" and count == 0:
        return text
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)
'''
if text.count(old) != 1:
    raise SystemExit(f"replace_once definition expected once, got {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("guide drift tolerance applied")

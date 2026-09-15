from pathlib import Path

path = Path(__file__).with_name("_patch_v31014_anticipated_refs.py")
text = path.read_text(encoding="utf-8")
start_marker = 'manual_anchor = """'
end_marker = 'text = replace_once(text, manual_anchor, manual_insert + manual_anchor, "UI saisie manuelle")\n\n'
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise RuntimeError("bloc UI manuel temporaire introuvable")
end += len(end_marker)
text = text[:start] + text[end:]
path.write_text(text, encoding="utf-8")
print("v3.10.14 patcher simplified: manual UI transform removed")

from pathlib import Path

path = Path(__file__).with_name("_patch_v31014_anticipated_refs.py")
text = path.read_text(encoding="utf-8")
old = 'manual_insert = """'
new = 'manual_insert = r"""'
if text.count(old) != 1:
    raise RuntimeError(f"manual_insert marker count={text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("v3.10.14 patcher escaping repaired")

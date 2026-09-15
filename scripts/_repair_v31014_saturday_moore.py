from pathlib import Path

path = Path(__file__).with_name("_patch_v31014_saturday_moore.py")
text = path.read_text(encoding="utf-8")
start = "insert = r'''"
end = "\n'''\ntext = replace_once(text, marker, insert + marker"
if text.count(start) != 1:
    raise RuntimeError(f"start marker count={text.count(start)}")
if text.count(end) != 1:
    raise RuntimeError(f"end marker count={text.count(end)}")
text = text.replace(start, 'insert = r"""', 1)
text = text.replace(end, '\n"""\ntext = replace_once(text, marker, insert + marker', 1)
path.write_text(text, encoding="utf-8")
print("Saturday Mooré patcher quoting repaired")

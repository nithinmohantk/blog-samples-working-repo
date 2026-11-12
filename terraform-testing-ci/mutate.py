"""Apply one deliberate defect to a copy of the module: python mutate.py <module copy> <mutation name>"""
import json
import pathlib
import sys

root, name = pathlib.Path(sys.argv[1]), sys.argv[2]
mutation = next(m for m in json.loads(pathlib.Path(__file__).with_name("mutations.json").read_text()) if m["name"] == name)
target = root / mutation["file"]
text = target.read_text(encoding="utf-8")
if text.count(mutation["find"]) != 1:
    sys.exit(f"{name}: expected the text to appear once in {mutation['file']}, found {text.count(mutation['find'])}")
target.write_text(text.replace(mutation["find"], mutation["replace"]), encoding="utf-8")

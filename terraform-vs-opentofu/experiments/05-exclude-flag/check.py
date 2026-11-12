import json, pathlib, sys
names = sorted(r["name"] for r in json.loads(pathlib.Path("terraform.tfstate").read_text())["resources"])
print("resources in state:", names)
sys.exit(0 if names == ["kept"] else 1)

import json, pathlib, sys
resources = json.loads(pathlib.Path("terraform.tfstate").read_text())["resources"]
print("resources in state:", len(resources))
sys.exit(0 if not resources else 1)

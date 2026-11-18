"""Count what each module asks you to decide: python measure.py modules/aca modules/aks"""
import pathlib
import re
import sys

for module in sys.argv[1:]:
    text = (pathlib.Path(module) / "main.tf").read_text(encoding="utf-8")
    code = [line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    resources = re.findall(r'^resource "([^"]+)"', text, flags=re.M)
    arguments = [line for line in code if re.match(r"^\s+[a-z_]+\s+=", line)]
    print(f"{module}: {len(resources)} resources ({', '.join(resources)}), {len(arguments)} arguments set, {len(code)} lines of HCL")

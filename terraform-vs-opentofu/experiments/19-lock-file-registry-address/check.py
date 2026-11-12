import pathlib, re
print("lock file records:", ", ".join(re.findall(r'provider "([^"]+)"', pathlib.Path(".terraform.lock.hcl").read_text())))

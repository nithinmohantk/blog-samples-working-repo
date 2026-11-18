import pathlib, sys
leaked = "not-a-real-token" in pathlib.Path("terraform.tfstate").read_text()
print("token written to state:", leaked)
sys.exit(1 if leaked else 0)

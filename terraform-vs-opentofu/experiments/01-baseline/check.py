import pathlib
print("state holds the value in clear text:", "patient-index-shard-7" in pathlib.Path("terraform.tfstate").read_text())

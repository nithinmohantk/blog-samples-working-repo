import pathlib, sys
text = pathlib.Path("terraform.tfstate").read_text()
clear = "patient-index-shard-7" in text
print("state holds the value in clear text:", clear, "| encrypted_data present:", "encrypted_data" in text)
sys.exit(1 if clear else 0)

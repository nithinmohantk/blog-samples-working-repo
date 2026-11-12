import subprocess, sys
print("loaded_from =", subprocess.run([sys.argv[1], "output", "-raw", "loaded_from"], capture_output=True, text=True).stdout.strip())

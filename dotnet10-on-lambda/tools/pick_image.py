"""Prints the newest dated tag of an AWS Lambda base image published on or before a given day.

    python pick_image.py lambda/dotnet 10 2026-04-11        ->  10.2026.04.07.13
    python pick_image.py lambda/provided al2023 2026-04-11  ->  al2023.2026.04.07.13

The plain tags (dotnet:10, provided:al2023) move every time AWS patches the image. A dated tag pins the runtime
the function is tested against. Standard library only; reads the public registry at public.ecr.aws.
"""
import json
import re
import sys
import urllib.request

repository, prefix, cutoff = sys.argv[1], sys.argv[2], sys.argv[3].replace("-", ".")
token = json.load(urllib.request.urlopen("https://public.ecr.aws/token/", timeout=30))["token"]
pattern = re.compile(rf"^{re.escape(prefix)}\.(\d{{4}}\.\d{{2}}\.\d{{2}})\.(\d+)$")
found: list[tuple[str, int, str]] = []
url = f"https://public.ecr.aws/v2/{repository}/tags/list?n=1000"
while url:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        for tag in json.load(response).get("tags", []):
            match = pattern.match(tag)
            if match and match.group(1) <= cutoff:
                found.append((match.group(1), int(match.group(2)), tag))
        link = response.headers.get("Link", "")
    following = re.search(r"<([^>]+)>;\s*rel=\"next\"", link)
    url = ("https://public.ecr.aws" + following.group(1)) if following else None
if not found:
    sys.exit(f"no dated tag of {repository} with prefix {prefix} on or before {cutoff}")
print(max(found)[2])

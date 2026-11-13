"""Prints the SQL Server 2025 container tag that was built most recently on or before a given day.

    python pick_tag.py 2026-04-25        ->  2025-CU3-ubuntu-22.04  2026-03-12T...

Tags such as 2025-latest move with every cumulative update, so a pipeline that uses them changes without a
commit. Tag names carry no date, so this reads each image's build time from its configuration in the registry.
Standard library only.
"""
import json
import re
import sys
import urllib.request

REGISTRY, REPOSITORY = "https://mcr.microsoft.com", "mssql/server"
ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json",
])


def get(path: str) -> dict:
    request = urllib.request.Request(f"{REGISTRY}/v2/{REPOSITORY}/{path}", headers={"Accept": ACCEPT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def built(tag: str) -> str:
    manifest = get(f"manifests/{tag}")
    if "manifests" in manifest:  # a multi-architecture index: take the x64 Linux image
        entry = next(m for m in manifest["manifests"] if m["platform"]["architecture"] == "amd64" and m["platform"]["os"] == "linux")
        manifest = get(f"manifests/{entry['digest']}")
    return get(f"blobs/{manifest['config']['digest']}")["created"]


cutoff = sys.argv[1]
candidates = []
for tag in get("tags/list")["tags"]:
    if re.fullmatch(r"2025-(RTM|CU\d+)(-GDR\d*)?-ubuntu-22\.04", tag):
        created = built(tag)
        print(f"{tag:34} {created}", file=sys.stderr)
        if created[:10] <= cutoff:
            candidates.append((created, tag))
if not candidates:
    sys.exit(f"no SQL Server 2025 tag built on or before {cutoff}")
created, tag = max(candidates)
print(tag, created)

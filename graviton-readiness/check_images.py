"""Check whether container images in Amazon ECR can run on arm64 (Graviton).

An image runs on Graviton only if its manifest list (OCI image index) includes
a linux/arm64 entry. A single-platform manifest is checked through its config
blob's architecture. Pass repository:tag pairs; the report says which images
need a multi-architecture build before nodes can move.

Usage:
    python check_images.py orders-api:1.42.0 billing-worker:2026.03.1
"""
from __future__ import annotations

import json
import sys

import boto3
from botocore.exceptions import ClientError

INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
ACCEPT = sorted(INDEX_TYPES | {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
})


def platforms_of(ecr, repository: str, tag: str) -> set[str]:
    """Return the os/arch platforms an image tag provides, e.g. {'linux/amd64'}."""
    resp = ecr.batch_get_image(
        repositoryName=repository,
        imageIds=[{"imageTag": tag}],
        acceptedMediaTypes=ACCEPT,
    )
    if resp.get("failures"):
        f = resp["failures"][0]
        raise LookupError(f"{repository}:{tag}: {f['failureCode']} {f.get('failureReason', '')}".strip())
    image = resp["images"][0]
    manifest = json.loads(image["imageManifest"])
    media_type = image.get("imageManifestMediaType") or manifest.get("mediaType")

    if media_type in INDEX_TYPES:
        found = set()
        for m in manifest.get("manifests", []):
            p = m.get("platform") or {}
            # Attestation manifests (provenance, SBOM) are listed as unknown/unknown
            if p.get("os") and p.get("architecture") and p["architecture"] != "unknown":
                variant = f"/{p['variant']}" if p.get("variant") else ""
                found.add(f"{p['os']}/{p['architecture']}{variant}")
        return found

    # Single-platform image: the architecture is in the config blob
    digest = manifest["config"]["digest"]
    layer = ecr.get_download_url_for_layer(repositoryName=repository, layerDigest=digest)
    config = _fetch_json(layer["downloadUrl"])
    return {f"{config.get('os', 'linux')}/{config['architecture']}"}


def _fetch_json(url: str) -> dict:
    import urllib.request
    with urllib.request.urlopen(url, timeout=30) as resp:  # presigned S3 URL from ECR
        return json.loads(resp.read())


def arm64_ready(platforms: set[str]) -> bool:
    return any(p.startswith("linux/arm64") for p in platforms)


def report(ecr, refs: list[str]) -> list[dict]:
    rows = []
    for ref in refs:
        repository, _, tag = ref.rpartition(":")
        if not repository:
            raise ValueError(f"{ref}: expected repository:tag")
        try:
            plats = platforms_of(ecr, repository, tag)
            rows.append({"image": ref, "platforms": sorted(plats), "arm64": arm64_ready(plats)})
        except (LookupError, ClientError) as exc:
            rows.append({"image": ref, "platforms": [], "arm64": False, "error": str(exc)})
    return rows


def main(argv: list[str]) -> int:
    ecr = boto3.client("ecr")
    rows = report(ecr, argv)
    for r in rows:
        status = "ok" if r["arm64"] else ("ERROR " + r["error"] if "error" in r else "needs arm64 build")
        print(f"{r['image']:<45} {','.join(r['platforms']) or '-':<30} {status}")
    return 0 if all(r["arm64"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rvcheck.licence import classify, classify_image_tag  # noqa: E402


@pytest.mark.parametrize("info, product, licence", [
    ({"redis_version": "7.2.4"}, "Redis", "BSD-3-Clause"),
    ({"redis_version": "6.2.14"}, "Redis", "BSD-3-Clause"),
    ({"redis_version": "7.4.0"}, "Redis", "RSALv2 or SSPLv1"),
    ({"redis_version": "8.0.0"}, "Redis", "RSALv2 or SSPLv1"),
    ({"redis_version": "255.255.255"}, "Redis-compatible development build", "unknown"),
    ({"redis_version": "7.2.4", "server_name": "valkey", "valkey_version": "7.2.5"}, "Valkey", "BSD-3-Clause"),
    ({"redis_version": "7.2.4", "redict_version": "7.3.0"}, "Redict", "LGPL-3.0-only (changes); BSD-3-Clause (inherited code)"),
])
def test_classify_from_info(info, product, licence):
    got = classify(info)
    assert (got.product, got.licence) == (product, licence)


@pytest.mark.parametrize("image, licence", [
    ("redis:7.2.4", "BSD-3-Clause"), ("redis:7.2.4-alpine", "BSD-3-Clause"),
    ("public.ecr.aws/docker/library/redis:7.0.15", "BSD-3-Clause"),
    ("redis:latest", "unknown"), ("redis:alpine", "unknown"), ("redis", "unknown"),
    ("redis:7.4.0", "RSALv2 or SSPLv1"), ("valkey/valkey:7.2.5", "BSD-3-Clause"),
    ("bitnami/redis:7.2.4", "BSD-3-Clause"), ("postgres:16", "n/a"),
])
def test_classify_image_tag(image, licence):
    assert classify_image_tag(image).licence == licence


def test_floating_tags_get_a_warning():
    assert "pin a version" in classify_image_tag("redis:latest").note

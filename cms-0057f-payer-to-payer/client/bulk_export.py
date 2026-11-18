"""FHIR Bulk Data (v1.0.0) export client for a payer-to-payer request.

Kick-off, status polling and download, following the Bulk Data Access IG STU 1:
  * kick-off with `Prefer: respond-async`, expect 202 and a Content-Location
  * poll that URL; 202 means in progress (honour Retry-After), 200 carries the manifest
  * download each `output[].url` as NDJSON

Standard library only, so it can run inside a locked-down integration host.
"""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterator


class ExportError(RuntimeError):
    pass


@dataclass
class ExportResult:
    manifest: dict
    resources: dict[str, list[dict]] = field(default_factory=dict)
    polls: int = 0

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in sorted(self.resources.items())}


@dataclass
class BulkClient:
    base_url: str
    token_provider: Callable[[], str] | None = None   # SMART Backend Services in production
    max_wait_seconds: float = 600
    max_poll_interval: float = 30
    sleep: Callable[[float], None] = time.sleep

    def _request(self, url: str, accept: str, extra: dict | None = None) -> tuple[int, dict, bytes]:
        headers = {"Accept": accept, **(extra or {})}
        if self.token_provider:
            headers["Authorization"] = f"Bearer {self.token_provider()}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read()

    def kick_off(self, group_id: str, types: list[str], since: str | None = None,
                 type_filters: list[str] | None = None) -> str:
        params = [("_outputFormat", "application/fhir+ndjson"), ("_type", ",".join(types))]
        if since:
            params.append(("_since", since))
        for f in type_filters or []:
            params.append(("_typeFilter", f))
        url = f"{self.base_url}/Group/{group_id}/$export?{urllib.parse.urlencode(params)}"
        status, headers, body = self._request(url, "application/fhir+json", {"Prefer": "respond-async"})
        if status != 202:
            raise ExportError(f"kick-off returned {status}: {body[:300]!r}")
        location = headers.get("Content-Location") or headers.get("content-location")
        if not location:
            raise ExportError("kick-off returned 202 without Content-Location")
        return location

    def wait(self, status_url: str) -> tuple[dict, int]:
        started, polls, delay = time.monotonic(), 0, 1.0
        while True:
            status, headers, body = self._request(status_url, "application/json")
            polls += 1
            if status == 200:
                return json.loads(body), polls
            if status == 202:
                retry_after = headers.get("Retry-After") or headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    delay = float(retry_after)
                else:
                    delay = min(self.max_poll_interval, delay * 2)
            elif status in (429, 503):
                delay = min(self.max_poll_interval, delay * 2)
            else:
                raise ExportError(f"status request returned {status}: {body[:300]!r}")
            if time.monotonic() - started + delay > self.max_wait_seconds:
                raise ExportError(f"export not complete after {self.max_wait_seconds:.0f} s")
            self.sleep(delay + random.uniform(0, delay * 0.1))

    def download(self, manifest: dict) -> Iterator[tuple[str, dict]]:
        if manifest.get("error"):
            raise ExportError(f"export reported errors: {manifest['error']}")
        for item in manifest.get("output", []):
            status, _, body = self._request(item["url"], "application/fhir+ndjson")
            if status != 200:
                raise ExportError(f"download of {item['type']} returned {status}")
            for line in body.decode("utf-8").splitlines():
                if line.strip():
                    yield item["type"], json.loads(line)

    def export(self, group_id: str, types: list[str], **kwargs) -> ExportResult:
        manifest, polls = self.wait(self.kick_off(group_id, types, **kwargs))
        result = ExportResult(manifest=manifest, polls=polls)
        for resource_type, resource in self.download(manifest):
            result.resources.setdefault(resource_type, []).append(resource)
        return result

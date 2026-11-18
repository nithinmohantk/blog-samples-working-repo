"""A small FHIR R4 REST client on the standard library, with retries for a busy server."""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request


class FhirError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status


class FhirClient:
    def __init__(self, base: str, *, timeout: float = 60, attempts: int = 4):
        self.base, self.timeout, self.attempts = base.rstrip("/"), timeout, attempts

    def _call(self, method: str, url: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/fhir+json", "Content-Type": "application/fhir+json"}
        for attempt in range(self.attempts):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code not in (429, 502, 503, 504) or attempt == self.attempts - 1:
                    raise FhirError(e.code, e.read().decode(errors="replace")) from None
            except urllib.error.URLError:
                if attempt == self.attempts - 1:
                    raise
            time.sleep(min(8, 0.5 * 2 ** attempt) * random.uniform(0.5, 1.0))   # backoff with jitter
        raise AssertionError("unreachable")

    def create(self, resource: dict) -> dict:
        return self._call("POST", f"{self.base}/{resource['resourceType']}", resource)

    def transaction(self, bundle: dict) -> dict:
        return self._call("POST", self.base, bundle)

    def search_page(self, rtype: str, params: dict) -> dict:
        return self._call("GET", f"{self.base}/{rtype}?{urllib.parse.urlencode(params, doseq=True)}")

    def search_all(self, rtype: str, params: dict) -> tuple[list[dict], int | None]:
        """Every match across pages, plus the server's own total for the first page."""
        bundle = self.search_page(rtype, params)
        total, found = bundle.get("total"), []
        while True:
            found += [e["resource"] for e in bundle.get("entry", []) if e.get("search", {}).get("mode", "match") == "match"]
            nxt = next((l["url"] for l in bundle.get("link", []) if l["relation"] == "next"), None)
            if not nxt:
                return found, total
            bundle = self._call("GET", nxt)

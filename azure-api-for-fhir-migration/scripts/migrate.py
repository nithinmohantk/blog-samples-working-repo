"""Lift-and-shift from Azure API for FHIR to the Azure Health Data Services FHIR service.

    1. $export on the source, into a container of the storage account configured for export.
    2. Turn the export manifest into an $import request for the target.
    3. $import on the target and report what was loaded and what was rejected.

    python migrate.py --source https://old.azurehealthcareapis.com \
                      --target https://ws-fhir.fhir.azurehealthcareapis.com \
                      --container migration-2026-08 --till 2026-08-22T22:00:00Z --history --deleted

Run it again with --since set to the previous --till to copy what changed in between.
Nothing is deleted or modified on the source. Hard deletes on the source are not carried across by any
export: track them separately and apply them to the target by hand.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from typing import Callable

import requests

log = logging.getLogger("migrate")
TokenProvider = Callable[[str], str]


class MigrationError(RuntimeError):
    """The operation stopped. The message is safe to log: it never contains a response body."""


def azure_token_provider() -> TokenProvider:
    """Tokens from the signed-in identity (az login, managed identity, workload identity)."""
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    return lambda base_url: credential.get_token(base_url.rstrip("/") + "/.default").token


class FhirOperations:
    """The two asynchronous operations a lift-and-shift needs, with polling."""

    def __init__(self, base_url: str, token_provider: TokenProvider, *, poll_seconds: float = 30,
                 timeout_seconds: float = 24 * 3600, session: requests.Session | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token_provider
        self._poll = poll_seconds
        self._timeout = timeout_seconds
        self._http = session or requests.Session()

    def _headers(self, **extra: str) -> dict[str, str]:
        # A fresh token for every request: a large export or import outlives one token.
        return {"Authorization": f"Bearer {self._token(self.base_url)}", **extra}

    def start_export(self, container: str, *, since: str | None = None, till: str | None = None,
                     types: list[str] | None = None, history: bool = False, deleted: bool = False) -> str:
        params: dict[str, str] = {"_container": container}
        if since:
            params["_since"] = since
        if till:
            params["_till"] = till          # system-level export only; gives a snapshot as of that time
        if types:
            params["_type"] = ",".join(types)
        associated = [name for name, wanted in (("_history", history), ("_deleted", deleted)) if wanted]
        if associated:
            params["includeAssociatedData"] = ",".join(associated)
        response = self._http.get(f"{self.base_url}/$export", params=params, timeout=120,
                                  headers=self._headers(Accept="application/fhir+json", Prefer="respond-async"))
        return self._status_url(response, "$export")

    def start_import(self, parameters: dict) -> str:
        response = self._http.post(f"{self.base_url}/$import", json=parameters, timeout=120,
                                   headers=self._headers(Prefer="respond-async", **{"Content-Type": "application/fhir+json"}))
        return self._status_url(response, "$import")

    def wait(self, status_url: str, what: str) -> dict:
        """Poll until the operation finishes. 202 means still running, 200 carries the result."""
        deadline = time.monotonic() + self._timeout
        while True:
            response = self._http.get(status_url, headers=self._headers(), timeout=120)
            if response.status_code == 200:
                return response.json()
            if response.status_code not in (202, 429, 503):
                raise MigrationError(f"{what} failed with HTTP {response.status_code}. "
                                     "Resources already imported are not rolled back.")
            if time.monotonic() > deadline:
                raise MigrationError(f"{what} did not finish within {self._timeout:.0f} seconds; it is still running")
            retry_after = response.headers.get("Retry-After", "")
            time.sleep(min(float(retry_after), 300) if retry_after.isdigit() else self._poll)

    @staticmethod
    def _status_url(response: requests.Response, what: str) -> str:
        location = response.headers.get("Content-Location")
        if response.status_code != 202 or not location:
            raise MigrationError(f"{what} was not accepted: HTTP {response.status_code}")
        return location


def build_import_parameters(export_manifest: dict, mode: str = "IncrementalLoad", *,
                            max_files: int = 10_000) -> dict:
    """Turn an export manifest into the Parameters resource $import expects.

    IncrementalLoad keeps each resource's lastUpdated and versionId and accepts history and soft deletes.
    InitialLoad is free of charge but blocks writes on the target and keeps only the latest version.
    """
    if mode not in ("IncrementalLoad", "InitialLoad"):
        raise ValueError("mode must be IncrementalLoad or InitialLoad")
    if export_manifest.get("error"):
        raise MigrationError(f"The export reported {len(export_manifest['error'])} error file(s); resolve them before importing")
    files = export_manifest.get("output") or []
    if not files:
        raise MigrationError("The export produced no files")
    if len(files) > max_files:
        raise MigrationError(f"{len(files)} files exceed the {max_files} files one import accepts; split the export")
    # SearchParameter resources cannot be imported. They are recreated on the target and reindexed.
    skipped = [f["url"] for f in files if f.get("type") == "SearchParameter"]
    if skipped:
        log.warning("Leaving out %d SearchParameter file(s); recreate custom search parameters on the target", len(skipped))
    parameter: list[dict] = [
        {"name": "inputFormat", "valueString": "application/fhir+ndjson"},
        {"name": "mode", "valueString": mode},
    ]
    for item in files:
        if item.get("type") == "SearchParameter":
            continue
        parameter.append({"name": "input", "part": [
            {"name": "type", "valueString": item["type"]},
            {"name": "url", "valueUri": item["url"]},
        ]})
    return {"resourceType": "Parameters", "parameter": parameter}


def summarise_import(result: dict) -> dict:
    """Counts per resource type, and where the error files are. No resource content."""
    loaded: dict[str, int] = {}
    for item in result.get("output") or []:
        loaded[item.get("type") or "unknown"] = loaded.get(item.get("type") or "unknown", 0) + int(item.get("count", 0))
    failed = [{"type": e.get("type"), "count": int(e.get("count", 0)), "inputUrl": e.get("inputUrl"), "errorFile": e.get("url")}
              for e in result.get("error") or []]
    return {"loaded": loaded, "loadedTotal": sum(loaded.values()),
            "failedTotal": sum(f["count"] for f in failed), "failed": failed}


def main(argv: list[str] | None = None, token_provider: TokenProvider | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="Azure API for FHIR base URL")
    parser.add_argument("--target", required=True, help="Azure Health Data Services FHIR service base URL")
    parser.add_argument("--container", required=True, help="container in the export storage account")
    parser.add_argument("--since", help="only resources changed at or after this instant")
    parser.add_argument("--till", help="only resources changed up to this instant")
    parser.add_argument("--types", help="comma-separated resource types; default is everything")
    parser.add_argument("--history", action="store_true", help="include earlier versions")
    parser.add_argument("--deleted", action="store_true", help="include soft-deleted resources")
    parser.add_argument("--mode", default="IncrementalLoad", choices=["IncrementalLoad", "InitialLoad"])
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--export-only", action="store_true", help="stop after the export and print the import request")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.mode == "InitialLoad" and (args.history or args.deleted):
        parser.error("InitialLoad keeps only the latest version: use IncrementalLoad with --history or --deleted")

    tokens = token_provider or azure_token_provider()
    source = FhirOperations(args.source, tokens, poll_seconds=args.poll_seconds)
    target = FhirOperations(args.target, tokens, poll_seconds=args.poll_seconds)
    try:
        status = source.start_export(args.container, since=args.since, till=args.till, history=args.history,
                                     deleted=args.deleted, types=args.types.split(",") if args.types else None)
        log.info("Export accepted")
        manifest = source.wait(status, "$export")
        log.info("Export finished: %d file(s)", len(manifest.get("output") or []))
        parameters = build_import_parameters(manifest, args.mode)
        if args.export_only:
            print(json.dumps(parameters, indent=2))
            return 0
        status = target.start_import(parameters)
        log.info("Import accepted in %s mode", args.mode)
        summary = summarise_import(target.wait(status, "$import"))
    except (MigrationError, requests.RequestException) as error:
        log.error("%s", error if isinstance(error, MigrationError) else type(error).__name__)
        return 2
    print(json.dumps(summary, indent=2))
    return 1 if summary["failedTotal"] else 0


if __name__ == "__main__":
    sys.exit(main())

"""The few FHIR calls the tools make. This server's own connection: the caller's token is never forwarded."""
from __future__ import annotations

import httpx

PAGE = 50


class Fhir:
    def __init__(self, base: str) -> None:
        self.client = httpx.AsyncClient(base_url=base.rstrip("/") + "/", timeout=30.0, headers={"Accept": "application/fhir+json"})

    async def read(self, resource: str, identifier: str) -> dict | None:
        response = await self.client.get(f"{resource}/{identifier}")
        if response.status_code in (404, 410):
            return None
        response.raise_for_status()
        return response.json()

    async def search(self, resource: str, parameters: dict[str, str]) -> list[dict]:
        """One page of matches. Only resources of the type asked for are returned, whatever the server adds."""
        response = await self.client.get(resource, params={**parameters, "_count": str(PAGE)})
        response.raise_for_status()
        entries = response.json().get("entry", [])
        return [entry["resource"] for entry in entries if entry.get("resource", {}).get("resourceType") == resource]

    async def create(self, resource: dict) -> dict:
        response = await self.client.post(resource["resourceType"], json=resource, headers={"Content-Type": "application/fhir+json"})
        response.raise_for_status()
        return response.json()

    async def raw(self, path: str) -> dict:
        """An arbitrary GET, used only by the generic tools in the lab."""
        response = await self.client.get(path)
        if response.status_code >= 400:
            return {"resourceType": "OperationOutcome", "status": response.status_code}
        return response.json()

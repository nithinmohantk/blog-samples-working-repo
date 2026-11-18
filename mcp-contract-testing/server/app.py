"""Stockroom: a small MCP server used as the subject of the contract tests.

Synthetic data, held in memory. The interesting part of this file is not what the tools do
but what they declare: every type hint, default, constraint and docstring below ends up in
the tool listing that agents read, which makes it the server's public contract.
"""
from __future__ import annotations

import itertools
from typing import Annotated, Literal

from pydantic import BaseModel, Field

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer
except ImportError:  # MCP Python SDK 1.x, where the same class was called FastMCP
    from mcp.server.fastmcp import FastMCP as MCPServer
from mcp.types import ToolAnnotations

SERVER_NAME = "stockroom"
SERVER_VERSION = "1.4.0"

Category = Literal["fasteners", "fittings", "sealants", "tools"]
Sku = Annotated[str, Field(pattern=r"^[A-Z]{3}-\d{4}$", description="Stock keeping unit, for example FAS-0012.")]


class Product(BaseModel):
    sku: str
    name: str
    category: Category
    unit_price_cents: int = Field(ge=0)


class StockLevel(BaseModel):
    sku: str
    on_hand: int = Field(ge=0, description="Units physically in the warehouses.")
    reserved: int = Field(ge=0, description="Units held by open reservations.")
    available: int = Field(ge=0, description="on_hand minus reserved.")


class Reservation(BaseModel):
    reservation_id: str
    sku: str
    quantity: int
    status: Literal["held", "rejected"]
    reason: str | None = None


class CancelResult(BaseModel):
    reservation_id: str
    cancelled: bool


class Warehouse(BaseModel):
    code: str
    city: str


PRODUCTS = [
    Product(sku="FAS-0012", name="M6 hex bolt, zinc, box of 100", category="fasteners", unit_price_cents=1250),
    Product(sku="FAS-0044", name="M8 washer, stainless, box of 200", category="fasteners", unit_price_cents=980),
    Product(sku="FIT-0101", name="15 mm compression elbow", category="fittings", unit_price_cents=340),
    Product(sku="SEA-0007", name="Silicone sealant, clear, 310 ml", category="sealants", unit_price_cents=615),
    Product(sku="TOO-0300", name="Torque wrench, 20 to 100 Nm", category="tools", unit_price_cents=8900),
]
WAREHOUSES = [Warehouse(code="GWY", city="Galway"), Warehouse(code="LMK", city="Limerick")]


class Store:
    """In-memory state. One instance per server process."""

    def __init__(self) -> None:
        self.on_hand = {"FAS-0012": 40, "FAS-0044": 12, "FIT-0101": 0, "SEA-0007": 75, "TOO-0300": 3}
        self.reservations: dict[str, Reservation] = {}
        self._ids = itertools.count(1)

    def reserved(self, sku: str) -> int:
        return sum(r.quantity for r in self.reservations.values() if r.sku == sku and r.status == "held")

    def level(self, sku: str) -> StockLevel:
        if sku not in self.on_hand:
            raise ValueError(f"unknown sku {sku}")
        held = self.reserved(sku)
        return StockLevel(sku=sku, on_hand=self.on_hand[sku], reserved=held, available=self.on_hand[sku] - held)

    def reserve(self, sku: str, quantity: int) -> Reservation:
        level = self.level(sku)
        rid = f"R-{next(self._ids):05d}"
        if quantity > level.available:
            result = Reservation(reservation_id=rid, sku=sku, quantity=quantity, status="rejected",
                                 reason=f"only {level.available} available")
        else:
            result = Reservation(reservation_id=rid, sku=sku, quantity=quantity, status="held")
        self.reservations[rid] = result
        return result


READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def new_server(instructions: str | None = None) -> MCPServer:
    text = instructions or "Stock levels and reservations for a small parts warehouse. Synthetic data."
    try:
        return MCPServer(SERVER_NAME, instructions=text, version=SERVER_VERSION)
    except TypeError:  # SDK 1.x takes no version argument; set it on the low-level server
        server = MCPServer(SERVER_NAME, instructions=text)
        server._mcp_server.version = SERVER_VERSION  # noqa: SLF001
        return server


def build() -> MCPServer:
    server, store = new_server(), Store()
    server.store = store  # type: ignore[attr-defined]  # the lab's variants reach the same state

    @server.tool(annotations=READ_ONLY)
    def search_products(
        query: Annotated[str, Field(min_length=2, max_length=80, description="Words to look for in the product name.")],
        category: Annotated[Category | None, Field(description="Restrict the search to one category.")] = None,
        limit: Annotated[int, Field(ge=1, le=50, description="Maximum number of products to return.")] = 10,
    ) -> list[Product]:
        """Search the product catalogue by name."""
        words = query.lower().split()
        hits = [p for p in PRODUCTS if all(w in p.name.lower() for w in words) and category in (None, p.category)]
        return hits[:limit]

    @server.tool(annotations=READ_ONLY)
    def get_stock(sku: Sku) -> StockLevel:
        """Return on-hand, reserved and available units for one product."""
        return store.level(sku)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def reserve_stock(
        sku: Sku,
        quantity: Annotated[int, Field(ge=1, le=100, description="Units to hold.")],
        order_ref: Annotated[str, Field(min_length=3, max_length=40, description="The caller's order reference.")],
    ) -> Reservation:
        """Hold stock for an order. Returns status 'rejected' when there is not enough available."""
        return store.reserve(sku, quantity)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
    def cancel_reservation(
        reservation_id: Annotated[str, Field(pattern=r"^R-\d{5}$", description="Identifier returned by reserve_stock.")],
    ) -> CancelResult:
        """Release a reservation. Cancelling twice is not an error."""
        found = store.reservations.pop(reservation_id, None)
        return CancelResult(reservation_id=reservation_id, cancelled=found is not None)

    @server.tool(annotations=READ_ONLY)
    def list_warehouses() -> list[Warehouse]:
        """List the warehouses that hold stock."""
        return WAREHOUSES

    @server.resource("stockroom://policy/reservations", mime_type="text/plain")
    def reservation_policy() -> str:
        """How long a reservation is held."""
        return "Reservations are held for 48 hours and then released."

    @server.resource("stockroom://warehouses/{code}", mime_type="application/json")
    def warehouse(code: str) -> str:
        """One warehouse by its three-letter code."""
        match = next((w for w in WAREHOUSES if w.code == code), None)
        if match is None:
            raise ValueError(f"unknown warehouse {code}")
        return match.model_dump_json()

    @server.prompt()
    def restock_report(warehouse_code: str) -> str:
        """Ask for a restocking report for one warehouse."""
        return f"List every product in warehouse {warehouse_code} with fewer than 10 units available, lowest first."

    return server


if __name__ == "__main__":
    import sys

    app = build()
    if len(sys.argv) > 1 and sys.argv[1] == "http":
        app.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    else:
        app.run("stdio")

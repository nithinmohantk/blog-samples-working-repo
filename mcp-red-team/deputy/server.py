"""Four tools, each written twice: the way it is usually written, and the way it has to be.

A confused deputy is a program that uses its own authority on behalf of whoever asks. An MCP server is
one by construction: it holds file access, network position and database credentials, and it acts on
arguments chosen by a model that may have been steered by anything it has read. The naive tools below
trust those arguments. The hardened ones take their authority from the server's own configuration.

Configuration comes from the environment, set by whoever starts the server, never by a tool argument:
DEPUTY_ROOT (directory holding reports/), DEPUTY_TENANT, DEPUTY_ALLOWED_ORIGINS (comma separated).
Synthetic data throughout.
"""
from __future__ import annotations

import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from mcp.server.fastmcp import FastMCP

ROOT = Path(os.environ.get("DEPUTY_ROOT", ".")).resolve()
REPORTS = ROOT / "reports"
TENANT = os.environ.get("DEPUTY_TENANT", "acme")
ALLOWED_ORIGINS = {origin for origin in os.environ.get("DEPUTY_ALLOWED_ORIGINS", "").split(",") if origin}
MAX_BYTES = 64_000

server = FastMCP("deputy", instructions="Reports, partner rates and invoices. Synthetic data.")

db = sqlite3.connect(":memory:", check_same_thread=False)
db.executescript("""
    CREATE TABLE invoices (id TEXT PRIMARY KEY, tenant TEXT NOT NULL, status TEXT NOT NULL, total_cents INTEGER NOT NULL);
    INSERT INTO invoices VALUES ('INV-1001', 'acme', 'open', 125000), ('INV-1002', 'acme', 'paid', 98000),
                                ('INV-2001', 'globex', 'open', 4100000), ('INV-2002', 'globex', 'paid', 730000);
""")


# ---- files -----------------------------------------------------------------------------------------

@server.tool()
def read_report_naive(name: str) -> str:
    """Read a report by file name."""
    return (REPORTS / name).read_text(encoding="utf-8")


@server.tool()
def read_report(name: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}\.txt$", description="Report file name, for example q1.txt.")]) -> str:
    """Read a report by file name."""
    path = (REPORTS / name).resolve()  # resolve() follows symlinks, so a link that points outside is caught below
    if not path.is_relative_to(REPORTS) or not path.is_file():
        raise ValueError("no such report")
    return path.read_text(encoding="utf-8")[:MAX_BYTES]


# ---- outbound requests -----------------------------------------------------------------------------

@server.tool()
def fetch_rates_naive(url: str) -> str:
    """Fetch partner rates from a URL."""
    with urllib.request.urlopen(url, timeout=5) as response:  # follows redirects, to anywhere
        return response.read().decode("utf-8", "replace")


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # noqa: ANN001, D102
        raise urllib.error.HTTPError(request.full_url, code, "redirect refused", headers, fp)


OPENER = urllib.request.build_opener(NoRedirects, urllib.request.ProxyHandler({}))


@server.tool()
def fetch_rates(url: Annotated[str, Field(max_length=300, description="URL on an approved partner host.")]) -> str:
    """Fetch partner rates from an approved partner host."""
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if parts.username or parts.password or origin not in ALLOWED_ORIGINS:
        raise ValueError("host is not an approved partner")
    try:
        with OPENER.open(url, timeout=5) as response:
            return response.read(MAX_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        raise ValueError(f"partner request failed: {error.code} {error.reason}") from None


# ---- data that belongs to a tenant -----------------------------------------------------------------

@server.tool()
def get_invoice_naive(invoice_id: str, tenant_id: str) -> dict:
    """Return one invoice for a tenant."""
    row = db.execute("SELECT id, tenant, status, total_cents FROM invoices WHERE id = ? AND tenant = ?", (invoice_id, tenant_id)).fetchone()
    if row is None:
        raise ValueError("no such invoice")
    return dict(zip(("id", "tenant", "status", "total_cents"), row))


@server.tool()
def get_invoice(invoice_id: Annotated[str, Field(pattern=r"^INV-\d{4}$")]) -> dict:
    """Return one invoice."""
    row = db.execute("SELECT id, tenant, status, total_cents FROM invoices WHERE id = ? AND tenant = ?", (invoice_id, TENANT)).fetchone()
    if row is None:  # another tenant's invoice and a missing invoice must look the same
        raise ValueError("no such invoice")
    return dict(zip(("id", "tenant", "status", "total_cents"), row))


@server.tool()
def find_invoices_naive(status: str) -> list[dict]:
    """List this tenant's invoices with a given status."""
    query = f"SELECT id, tenant, status, total_cents FROM invoices WHERE tenant = '{TENANT}' AND status = '{status}'"
    return [dict(zip(("id", "tenant", "status", "total_cents"), row)) for row in db.execute(query)]


@server.tool()
def find_invoices(status: Literal["open", "paid"]) -> list[dict]:
    """List this tenant's invoices with a given status."""
    rows = db.execute("SELECT id, tenant, status, total_cents FROM invoices WHERE tenant = ? AND status = ?", (TENANT, status))
    return [dict(zip(("id", "tenant", "status", "total_cents"), row)) for row in rows]


if __name__ == "__main__":
    server.run("stdio")

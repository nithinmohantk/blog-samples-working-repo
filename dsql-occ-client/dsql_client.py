"""Connection and transaction helpers for Amazon Aurora DSQL with psycopg 3.

Aurora DSQL differs from PostgreSQL in three ways that application code has to
handle:

1. Authentication uses short-lived IAM tokens instead of passwords. The token
   is generated locally with SigV4 by boto3; no network call is made.
2. Concurrency control is optimistic. Conflicts are detected at COMMIT and
   returned as SQLSTATE 40001 (OC000 for data, OC001 for schema). The service
   does not retry for you, so the client must retry the whole transaction.
3. A transaction may modify at most 3,000 rows and 10 MiB, may run for at most
   5 minutes, and a connection lasts at most 60 minutes.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, TypeVar

import boto3
import psycopg

log = logging.getLogger("dsql")
T = TypeVar("T")

MAX_ROWS_PER_TRANSACTION = 3000
SERIALIZATION_FAILURE = "40001"


class TokenProvider:
    """Generates and caches IAM authentication tokens for one cluster endpoint."""

    def __init__(self, endpoint: str, region: str, *, admin: bool = False, ttl_seconds: int = 900,
                 refresh_margin_seconds: int = 60, session: boto3.session.Session | None = None,
                 clock: Callable[[], float] = time.monotonic):
        if ttl_seconds <= refresh_margin_seconds:
            raise ValueError("ttl_seconds must be larger than refresh_margin_seconds")
        self.endpoint, self.region, self.admin = endpoint, region, admin
        self.ttl, self.margin, self.clock = ttl_seconds, refresh_margin_seconds, clock
        self._client = (session or boto3.session.Session()).client("dsql", region_name=region)
        self._token: str | None = None
        self._expires_at = 0.0

    def token(self) -> str:
        now = self.clock()
        if self._token is None or now >= self._expires_at - self.margin:
            generate = (self._client.generate_db_connect_admin_auth_token if self.admin
                        else self._client.generate_db_connect_auth_token)
            self._token = generate(self.endpoint, self.region, self.ttl)
            self._expires_at = now + self.ttl
        return self._token


def connect(provider: TokenProvider, user: str | None = None, *, connect_timeout: int = 5) -> psycopg.Connection:
    """Open a TLS connection to the cluster's single database, 'postgres'."""
    return psycopg.connect(
        host=provider.endpoint,
        port=5432,
        dbname="postgres",
        user=user or ("admin" if provider.admin else "app_user"),
        password=provider.token(),
        sslmode="require",
        connect_timeout=connect_timeout,
        application_name="dsql-occ-client",
    )


def _is_retryable(exc: BaseException) -> bool:
    return getattr(exc, "sqlstate", None) == SERIALIZATION_FAILURE


class Session:
    """Holds one connection, reopening it when it has closed (DSQL ends connections after 60 minutes)."""

    def __init__(self, connect_fn: Callable[[], Any]):
        self._connect_fn = connect_fn
        self._conn: Any = None

    @property
    def conn(self) -> Any:
        if self._conn is None or self._conn.closed:
            self._conn = self._connect_fn()
        return self._conn

    def discard(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    def run(self, work: Callable[[Any], T], *, max_attempts: int = 6, base_delay: float = 0.02,
            max_delay: float = 1.0, sleep: Callable[[float], None] = time.sleep,
            rand: Callable[[], float] = random.random) -> T:
        """Run work(cursor) in one transaction, retrying the whole transaction on OCC conflicts.

        work must be safe to run more than once: it is re-executed from the start
        after a conflict. Delays use full jitter: rand() * min(max_delay, base * 2**attempt).
        """
        for attempt in range(1, max_attempts + 1):
            try:
                with self.conn.transaction():
                    with self.conn.cursor() as cur:
                        return work(cur)
            except psycopg.OperationalError as exc:
                if _is_retryable(exc) and attempt < max_attempts:
                    delay = rand() * min(max_delay, base_delay * 2 ** attempt)
                    log.warning("OCC conflict, attempt %d of %d, retrying in %.3fs: %s",
                                attempt, max_attempts, delay, str(exc).strip())
                    sleep(delay)
                    continue
                if getattr(self._conn, "closed", False) and attempt < max_attempts:
                    log.warning("connection closed, reconnecting: %s", str(exc).strip())
                    self.discard()
                    continue
                raise
        raise AssertionError("unreachable")


def chunked(rows: Iterable[Sequence[Any]], size: int) -> Iterator[list[Sequence[Any]]]:
    if not 1 <= size <= MAX_ROWS_PER_TRANSACTION:
        raise ValueError(f"size must be between 1 and {MAX_ROWS_PER_TRANSACTION}")
    batch: list[Sequence[Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def write_in_batches(session: Session, sql: str, rows: Iterable[Sequence[Any]], *, batch_size: int = 500,
                     **run_kwargs: Any) -> int:
    """Insert or upsert rows in transactions of at most batch_size rows each.

    Each batch commits on its own, so a failure part-way leaves earlier batches
    committed. Make sql idempotent (for example INSERT ... ON CONFLICT DO NOTHING)
    so the whole load can be re-run.
    """
    written = 0
    for batch in chunked(rows, batch_size):
        session.run(lambda cur, b=batch: cur.executemany(sql, b), **run_kwargs)
        written += len(batch)
    return written

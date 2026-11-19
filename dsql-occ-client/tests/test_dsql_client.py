import contextlib
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import boto3
import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dsql_client as dc  # noqa: E402

ENDPOINT = "abcdefghijklmnopqrst.dsql.eu-west-1.on.aws"


def occ_error(code="OC000"):
    return psycopg.errors.SerializationFailure(
        f"change conflicts with another transaction, please retry: ({code})")


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def executemany(self, sql, rows):
        self.conn.executed.append(list(rows))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    """Stands in for psycopg.Connection: commit happens when transaction() exits cleanly."""

    def __init__(self, failures=()):
        self.failures = list(failures)
        self.closed = False
        self.executed, self.commits, self.rollbacks = [], 0, 0

    @contextlib.contextmanager
    def transaction(self):
        try:
            yield
        except BaseException:
            self.rollbacks += 1
            raise
        if self.failures:
            err = self.failures.pop(0)
            if isinstance(err, psycopg.OperationalError) and "closed" in str(err):
                self.closed = True
            self.rollbacks += 1
            raise err
        self.commits += 1

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


def session_for(*conns):
    it = iter(conns)
    return dc.Session(lambda: next(it))


def no_sleep():
    delays = []
    return delays, delays.append


def boto_session():
    return boto3.session.Session(aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
                                 aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")


def test_admin_token_is_a_presigned_dsql_request():
    p = dc.TokenProvider(ENDPOINT, "eu-west-1", admin=True, session=boto_session())
    token = p.token()
    q = parse_qs(urlsplit("https://" + token).query)
    assert token.startswith(ENDPOINT + "/?")
    assert q["Action"] == ["DbConnectAdmin"]
    assert q["X-Amz-Expires"] == ["900"]
    assert "/eu-west-1/dsql/aws4_request" in q["X-Amz-Credential"][0]


def test_non_admin_token_and_refresh_before_expiry():
    now = [1000.0]
    p = dc.TokenProvider(ENDPOINT, "eu-west-1", session=boto_session(), ttl_seconds=900,
                         refresh_margin_seconds=60, clock=lambda: now[0])
    first = p.token()
    assert parse_qs(urlsplit("https://" + first).query)["Action"] == ["DbConnect"]
    now[0] += 800
    assert p.token() is first          # still inside the validity window
    now[0] += 50                      # 850 s: within 60 s of expiry
    assert p.token() is not first


def test_ttl_must_exceed_margin():
    with pytest.raises(ValueError):
        dc.TokenProvider(ENDPOINT, "eu-west-1", session=boto_session(), ttl_seconds=60, refresh_margin_seconds=60)


def test_occ_conflicts_are_retried_with_jittered_backoff():
    conn = FakeConn(failures=[occ_error("OC000"), occ_error("OC001")])
    delays, sleep = no_sleep()
    calls = []
    result = session_for(conn).run(lambda cur: calls.append(1) or "ok", sleep=sleep, rand=lambda: 0.5)
    assert result == "ok"
    assert len(calls) == 3 and conn.commits == 1 and conn.rollbacks == 2
    assert delays == [0.5 * 0.04, 0.5 * 0.08]


def test_gives_up_after_max_attempts():
    conn = FakeConn(failures=[occ_error()] * 3)
    _, sleep = no_sleep()
    with pytest.raises(psycopg.errors.SerializationFailure):
        session_for(conn).run(lambda cur: None, max_attempts=3, sleep=sleep)
    assert conn.commits == 0


def test_other_errors_are_not_retried():
    conn = FakeConn()
    _, sleep = no_sleep()

    def work(cur):
        raise psycopg.errors.UniqueViolation("duplicate key")

    with pytest.raises(psycopg.errors.UniqueViolation):
        session_for(conn).run(work, sleep=sleep)
    assert conn.rollbacks == 1


def test_closed_connection_is_reopened():
    old = FakeConn(failures=[psycopg.OperationalError("the connection is closed")])
    new = FakeConn()
    _, sleep = no_sleep()
    s = session_for(old, new)
    assert s.run(lambda cur: 42, sleep=sleep) == 42
    assert new.commits == 1


def test_chunked_respects_the_row_limit():
    assert [len(b) for b in dc.chunked(range(7), 3)] == [3, 3, 1]
    with pytest.raises(ValueError):
        list(dc.chunked(range(10), 3001))


def test_write_in_batches_commits_each_batch():
    conn = FakeConn(failures=[None] * 0)
    rows = [(i, f"name-{i}") for i in range(1250)]
    _, sleep = no_sleep()
    n = dc.write_in_batches(session_for(conn), "INSERT INTO t VALUES (%s, %s) ON CONFLICT DO NOTHING",
                            rows, batch_size=500, sleep=sleep)
    assert n == 1250
    assert [len(b) for b in conn.executed] == [500, 500, 250]
    assert conn.commits == 3


def test_connect_passes_token_and_tls(monkeypatch):
    seen = {}
    monkeypatch.setattr(dc.psycopg, "connect", lambda **kw: seen.update(kw) or "conn")
    p = dc.TokenProvider(ENDPOINT, "eu-west-1", admin=True, session=boto_session())
    assert dc.connect(p) == "conn"
    assert seen["user"] == "admin" and seen["dbname"] == "postgres" and seen["sslmode"] == "require"
    assert seen["password"].startswith(ENDPOINT + "/?Action=DbConnectAdmin")

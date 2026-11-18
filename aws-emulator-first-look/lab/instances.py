"""Two emulators at once, and what survives a restart. Called by ci.sh, which starts and stops the processes.

    python instances.py isolation 9297 9298
    python instances.py count 9297
"""
import sys

from common import session_for


def buckets(port: str) -> list[str]:
    session, kw = session_for(f"emulator:{port}")
    return sorted(b["Name"] for b in session.client("s3", **kw).list_buckets().get("Buckets", []))


def key_tail(port: str) -> str:
    session, _ = session_for(f"emulator:{port}")
    return "..." + session.get_credentials().access_key[-4:]


if sys.argv[1] == "isolation":
    a, b = sys.argv[2], sys.argv[3]
    session, kw = session_for(f"emulator:{a}")
    session.client("s3", **kw).create_bucket(Bucket="only-in-the-first")
    print(f"port {a}: buckets {buckets(a)}, access key {key_tail(a)}")
    print(f"port {b}: buckets {buckets(b)}, access key {key_tail(b)}")
else:
    port = sys.argv[2]
    print(f"port {port}: {len(buckets(port))} bucket(s) {buckets(port)}, access key {key_tail(port)}")

#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>   (needs gcc, make, git, Python 3.12 with pytest and redis)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
work="${RUNNER_TEMP:-/tmp}/rv-work"
mkdir -p "$work"
status=0

REDIS_TAG=7.2.4                                            # 9 January 2024, the last BSD-3-Clause release
VALKEY_SHA=1950acd1e2b8c2282d51e528377f6e564eb447cd       # valkey unstable, 29 March 2024; no release existed yet

build() {  # build <name> <repo url> <ref>
  local dir="$work/$1"
  rm -rf "$dir" && mkdir -p "$dir" && cd "$dir"
  git init -q && git remote add origin "$2" && git fetch -q --depth 1 origin "$3" && git checkout -q FETCH_HEAD
  make -j"$(nproc)" BUILD_TLS=no > "$work/$1-build.log" 2>&1 || { tail -30 "$work/$1-build.log"; return 1; }
  cd - > /dev/null
}

echo "== unit tests"
python -m pytest -q 2>&1 | tee "$out/unit-tests.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== build"
build redis https://github.com/redis/redis.git "refs/tags/$REDIS_TAG" || exit 2
build valkey https://github.com/valkey-io/valkey.git "$VALKEY_SHA" || exit 2
valkey_bin="$(ls "$work"/valkey/src/valkey-server 2>/dev/null || ls "$work"/valkey/src/redis-server)"
{ echo "redis $REDIS_TAG: $(git -C "$work/redis" rev-parse HEAD)"
  echo "valkey: $(git -C "$work/valkey" rev-parse HEAD) $(git -C "$work/valkey" log -1 --format='%cd' --date=iso)"
  echo "valkey server binary: $(basename "$valkey_bin")"
  echo "valkey LICENSE first line: $(head -1 "$work/valkey/COPYING" 2>/dev/null || head -1 "$work/valkey/LICENSE.txt" 2>/dev/null)"
  echo "redis LICENSE first line: $(head -1 "$work/redis/COPYING" 2>/dev/null)"
  gcc --version | head -1; python --version; python -c 'import redis; print("redis-py", redis.__version__)'
} > "$out/versions.txt"
cat "$out/versions.txt"

echo "== checks"
python -u tools/run_checks.py "$work/redis/src/redis-server" "$valkey_bin" "$work/run" "$out" 2>&1 | tee "$out/run-log.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || status=1
exit $status

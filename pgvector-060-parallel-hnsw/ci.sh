#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
# Needs Docker and Python 3.12 with psycopg, numpy, h5py and pytest.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
pw=bench-only
dsn="postgresql://postgres:${pw}@localhost:5432/postgres"

{
  echo "runner: $(nproc) vCPU, $(free -g | awk '/Mem:/ {print $2}') GiB RAM"
  docker --version
  python --version
  python -c 'import importlib.metadata as m; [print(p, m.version(p)) for p in ("psycopg", "numpy", "h5py", "pytest")]'
} > "$out/environment.txt" 2>&1

echo "== build pgvector 0.5.1 and 0.6.0 on postgres:16.1-bookworm"
for tag in v0.5.1 v0.6.0; do
  docker build -q --build-arg PGVECTOR_TAG=$tag -t "bench-pgvector:${tag#v}" docker >> "$out/docker-build.txt" 2>&1 || status=1
done

echo "== unit tests"
python -m pytest -q tests 2>&1 | tee "$out/unit-tests.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

start() {  # start <image> <name> [docker args...]
  local image=$1 name=$2; shift 2
  docker rm -f "$name" >/dev/null 2>&1
  docker run -d --name "$name" "$@" -e POSTGRES_PASSWORD=$pw -p 5432:5432 "$image" >/dev/null
  for _ in $(seq 1 60); do docker exec "$name" pg_isready -U postgres -q && sleep 2 && return 0; sleep 1; done
  return 1
}

stop() {  # stop <name>: keep the server log, then remove
  docker exec "$1" sh -c 'df -h /dev/shm | tail -1' > "$out/$1-shm.txt" 2>&1
  docker logs "$1" > "$out/$1-server.log" 2>&1
  docker rm -f "$1" >/dev/null
}

run() {  # run <label> <experiments...>
  local label=$1; shift
  python bench/run.py --dsn "$dsn" --label "$label" --experiments "$@" --out "$out/results.json" \
    2>&1 | tee -a "$out/runs.jsonl"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
}

echo "== 0.5.1, /dev/shm 2 GB"
start bench-pgvector:0.5.1 pg051 --shm-size=2g || status=1
run "0.5.1 shm-2g" default-mem serial-1gb parallel-1gb
stop pg051

echo "== 0.6.0, /dev/shm 2 GB"
start bench-pgvector:0.6.0 pg060 --shm-size=2g || status=1
PGVECTOR_DSN="$dsn" python -m pytest -q tests -k round_trips 2>&1 | tee "$out/copy-round-trip.txt"
run "0.6.0 shm-2g" default-mem serial-1gb parallel-1gb parallel-1gb serial-1gb parallel-1gb-unlogged
stop pg060

echo "== 0.6.0, Docker's default /dev/shm (64 MB)"
start bench-pgvector:0.6.0 pg060-default-shm || status=1
run "0.6.0 shm-64m" parallel-1gb serial-1gb
stop pg060-default-shm

python bench/report.py "$out/results.json" | tee "$out/table.txt" || status=1
exit $status

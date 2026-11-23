#!/usr/bin/env bash
# Starts PostgreSQL 19 (a primary and a streaming standby) and PostgreSQL 18, then runs the lab.
# Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
password=lab-only   # a throwaway password for containers that live for one run

cleanup() { docker rm -f pg19 pg19s pg18 > /dev/null 2>&1; docker volume rm -f pg19s-data > /dev/null 2>&1; docker network rm pglab > /dev/null 2>&1; }
ready() { for _ in $(seq 1 60); do docker exec "$1" pg_isready -q -U postgres -h 127.0.0.1 && return 0; sleep 1; done; echo "$1 did not start"; docker logs "$1" | tail -n 20; return 1; }

{
  cleanup
  docker network create pglab > /dev/null
  docker run -d --name pg19 --network pglab -p 127.0.0.1:5419:5432 --shm-size=1g -e POSTGRES_PASSWORD=$password postgres:19 > /dev/null
  docker run -d --name pg18 --network pglab -p 127.0.0.1:5418:5432 --shm-size=1g -e POSTGRES_PASSWORD=$password postgres:18 > /dev/null
  sleep 8; ready pg19 && ready pg18 || exit 1

  # The image allows password logins but not replication connections. Add that line, then copy the primary.
  docker exec pg19 bash -c 'echo "host replication all all scram-sha-256" >> "$PGDATA/pg_hba.conf"'
  docker exec pg19 psql -U postgres -qAtc "select pg_reload_conf()" > /dev/null
  docker run --rm --network pglab --user postgres -v pg19s-data:/var/lib/postgresql -e PGPASSWORD=$password postgres:19 \
    bash -c 'pg_basebackup -h pg19 -U postgres -D "$PGDATA" -R -X stream && chmod 700 "$PGDATA"' || exit 1
  docker run -d --name pg19s --network pglab -p 127.0.0.1:5420:5432 --shm-size=1g -v pg19s-data:/var/lib/postgresql postgres:19 > /dev/null
  sleep 4; ready pg19s || exit 1
  echo "primary sees: $(docker exec pg19 psql -U postgres -Atc "select application_name || ' ' || state from pg_stat_replication")"
} 2>&1 | tee "$out/00-setup.txt"

python -m pip install -q "psycopg[binary]==3.2.*" 2>&1 | tail -n 2
python lab/run.py "$out" 2>&1 | tee "$out/01-console.txt"
status=${PIPESTATUS[0]}
failed=$(grep -c "^FAILED" "$out/results.txt" 2>/dev/null || echo 0)
echo "experiments that failed: $failed" | tee -a "$out/00-setup.txt"
docker logs pg19 2>&1 | grep -E "ERROR|FATAL|PANIC" | tail -n 40 > "$out/02-pg19-errors.txt"
cleanup
[ "$status" = 0 ] && [ "$failed" = 0 ]

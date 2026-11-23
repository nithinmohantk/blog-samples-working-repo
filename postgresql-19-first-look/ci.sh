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
  docker pull -q postgres:19 > /dev/null; docker pull -q postgres:18 > /dev/null
  docker run -d --name pg19 --network pglab -p 127.0.0.1:5419:5432 --shm-size=1g -e POSTGRES_PASSWORD=$password postgres:19 > /dev/null
  docker run -d --name pg18 --network pglab -p 127.0.0.1:5418:5432 --shm-size=1g -e POSTGRES_PASSWORD=$password postgres:18 > /dev/null
  sleep 8; ready pg19 && ready pg18 || exit 1

  # The image allows password logins but not replication connections. Add that line, then copy the primary.
  # The standby gets a replication slot, so the primary keeps the WAL the standby has not had yet.
  docker exec pg19 bash -c 'echo "host replication all all scram-sha-256" >> "$PGDATA/pg_hba.conf"'
  docker exec pg19 psql -U postgres -qAtc "select pg_reload_conf()" > /dev/null
  docker run --rm --network pglab --user postgres -v pg19s-data:/var/lib/postgresql -e PGPASSWORD=$password postgres:19 \
    bash -c 'pg_basebackup -h pg19 -U postgres -D "$PGDATA" -R -X stream -C -S standby1 && chmod 700 "$PGDATA"' || exit 1
  docker run -d --name pg19s --network pglab -p 127.0.0.1:5420:5432 --shm-size=1g -v pg19s-data:/var/lib/postgresql postgres:19 > /dev/null
  sleep 4; ready pg19s || exit 1
  echo "primary sees: $(docker exec pg19 psql -U postgres -Atc "select application_name || ' ' || state from pg_stat_replication")"
} 2>&1 | tee "$out/00-setup.txt"

python -m pip install -q "psycopg[binary]==3.2.*" 2>&1 | tail -n 2
python lab/run.py "$out" 2>&1 | tee "$out/01-console.txt"
status=${PIPESTATUS[0]}
failed=$(grep -c "^FAILED" "$out/results.txt" 2>/dev/null); failed=${failed:-0}
echo "experiments that failed: $failed" | tee -a "$out/00-setup.txt"
# The tour: plain SQL on 19, each statement echoed with its answer.
docker exec -i pg19 psql -U postgres -a -f - < sql/tour.sql > "$out/03-tour.txt" 2>&1

# The upgrade checks, on 18, after planting one of everything they look for.
# The RADIUS line uses a made-up secret and an address that nothing connects from.
docker exec pg18 bash -c 'echo "host all legacy_app 10.9.9.9/32 radius radiusservers=127.0.0.1 radiussecrets=fake-lab-only" >> "$PGDATA/pg_hba.conf"'
docker exec -i pg18 psql -U postgres -q -f - < sql/upgrade-plant.sql > "$out/04-upgrade-plant.txt" 2>&1
sleep 1
docker exec -i pg18 psql -U postgres -f - < sql/upgrade-checks.sql > "$out/04-upgrade-checks.txt" 2>&1
grep -n "ERROR" "$out/03-tour.txt" "$out/04-upgrade-plant.txt" "$out/04-upgrade-checks.txt" | tee -a "$out/00-setup.txt"
docker logs pg19 2>&1 | grep -E "ERROR|FATAL|PANIC" | tail -n 40 > "$out/02-pg19-errors.txt"
cleanup
[ "$status" = 0 ] && [ "$failed" = 0 ]

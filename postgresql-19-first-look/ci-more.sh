#!/usr/bin/env bash
# Second part: starts PostgreSQL 19 and 18, runs lab/more.py, then tries the two login warnings.
# Usage: ./ci-more.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
password=lab-only   # a throwaway password for containers that live for one run

cleanup() { docker rm -f pg19 pg18 > /dev/null 2>&1; docker network rm pglab > /dev/null 2>&1; }
ready() { for _ in $(seq 1 60); do docker exec "$1" pg_isready -q -U postgres -h 127.0.0.1 && return 0; sleep 1; done; echo "$1 did not start"; return 1; }

cleanup
docker network create pglab > /dev/null
docker pull -q postgres:19 > /dev/null; docker pull -q postgres:18 > /dev/null
docker run -d --name pg19 --network pglab -p 127.0.0.1:5419:5432 -e POSTGRES_PASSWORD=$password postgres:19 > /dev/null
docker run -d --name pg18 --network pglab -p 127.0.0.1:5418:5432 -e POSTGRES_PASSWORD=$password postgres:18 > /dev/null
sleep 8; ready pg19 && ready pg18 || exit 1

python -m pip install -q "psycopg[binary]==3.2.*" 2>&1 | tail -n 2
python lab/more.py "$out" 2>&1 | tee "$out/05-more-console.txt"
status=${PIPESTATUS[0]}

# Login warnings. Two roles on each server: one whose password expires in three days, one with an MD5
# password. The image trusts connections from 127.0.0.1, so the logins go to the container's own
# network name, which asks for the password. The MD5 role gets its own pg_hba.conf line, placed first.
expires="$(date -u -d '+3 days' '+%Y-%m-%d %H:%M:%S+00')"
{
  for v in 19 18; do
    echo "=== PostgreSQL $v: creating the roles"
    docker exec pg$v psql -U postgres -c "create role expiring_user login password 'fake-lab-only' valid until '$expires'" \
      -c "set password_encryption = 'md5'" -c "create role md5_user login password 'fake-lab-only'" 2>&1
    docker exec pg$v bash -c 'sed -i "1i host all md5_user all md5" "$PGDATA/pg_hba.conf"'
    docker exec pg$v psql -U postgres -qAtc "select pg_reload_conf()" > /dev/null
    sleep 1
    for role in expiring_user md5_user; do
      echo "=== PostgreSQL $v: login as $role"
      docker exec -e PGPASSWORD=fake-lab-only pg$v psql -h pg$v -U $role -d postgres -Atc "select 'logged in as ' || current_user" 2>&1
    done
  done
} > "$out/06-logins.txt"

failed=$(grep -c "^FAILED" "$out/more-results.txt" 2>/dev/null); failed=${failed:-0}
echo "experiments that failed: $failed" | tee "$out/05-setup.txt"
cleanup
[ "$status" = 0 ] && [ "$failed" = 0 ]

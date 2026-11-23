#!/usr/bin/env bash
# Probe: what does the PostgreSQL 19 image contain. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
{
  for v in 19 18; do
    docker pull -q postgres:$v 2>&1 | tail -n 1
    docker rm -f pg$v > /dev/null 2>&1
    docker run -d --name pg$v -e POSTGRES_PASSWORD=lab-only postgres:$v > /dev/null
  done
  sleep 12
  for v in 19 18; do
    echo "=== postgres:$v"
    docker exec pg$v psql -U postgres -Atc "select version()"
    docker exec pg$v psql -U postgres -Atc "select name||'='||setting from pg_settings where name in ('jit','default_toast_compression','io_method','io_workers','io_min_workers','io_max_workers','wal_level','effective_wal_level','max_locks_per_transaction','max_repack_replication_slots','autovacuum_max_parallel_workers','md5_password_warnings','password_expiration_warning_threshold','enable_eager_aggregate','max_replication_slots') order by 1"
    docker exec pg$v psql -U postgres -Atc "select name||' '||default_version from pg_available_extensions where name ~ 'advice|plan|stat_statements|fdw' order by 1"
    docker exec pg$v psql -U postgres -Atc "select string_agg(viewname, ', ' order by viewname) from pg_views where viewname in ('pg_stat_lock','pg_stat_recovery','pg_stat_autovacuum_scores','pg_stat_progress_repack')"
  done
  for h in "WAIT FOR" "REPACK" "INSERT" "COPY" "CREATE PUBLICATION" "CREATE SUBSCRIPTION" "EXPLAIN"; do
    echo "=== \\h $h"
    docker exec pg19 psql -U postgres -c "\\h $h"
  done
  echo "=== pg_stash_advice objects"
  docker exec pg19 psql -U postgres -c "create extension if not exists pg_stash_advice" -c "\\dx+ pg_stash_advice"
  docker exec pg19 psql -U postgres -Atc "select name||'='||setting||' ('||short_desc||')' from pg_settings where name ~ 'advice' order by 1"
  docker exec pg19 psql -U postgres -c "load 'pg_plan_advice'" -c "select name||'='||setting||' ('||short_desc||')' from pg_settings where name ~ 'advice' order by 1" -c "\\df *advice*"
  docker exec pg19 psql -U postgres -c "\\d pg_stat_lock" -c "\\d pg_stat_recovery" -c "\\d pg_stat_autovacuum_scores" -c "\\df random"
  docker rm -f pg19 pg18 > /dev/null
} 2>&1 | tee "$out/00-probe.txt"

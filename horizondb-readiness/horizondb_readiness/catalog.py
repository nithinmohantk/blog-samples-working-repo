"""What Azure HorizonDB offered at GA, as published on Microsoft Learn.

Sources (read 19 Nov 2026):
  * Extensions: "List of the PostgreSQL extensions and modules in Azure HorizonDB",
    last updated 2026-07-06.
  * Versions: "Azure HorizonDB version policy" (PostgreSQL 17, PostgreSQL 18 in preview).
  * Limitations: "What is Azure HorizonDB?", last updated 2026-11-17.

Re-check these lists before a real migration: they change with the service.
"""

# Extension name -> version offered by HorizonDB.
HORIZONDB_EXTENSIONS: dict[str, str] = {
    "address_standardizer": "3.5.2",
    "address_standardizer_data_us": "3.5.2",
    "age": "1.6.0",
    "amcheck": "1.4",
    "auto_explain": "",
    "azure_ai": "2.2.1",
    "azure_storage": "1.9",
    "bloom": "1.0",
    "btree_gin": "1.3",
    "btree_gist": "1.7",
    "citext": "1.6",
    "cube": "1.5",
    "dblink": "1.2",
    "dict_int": "1.0",
    "dict_xsyn": "1.0",
    "earthdistance": "1.2",
    "fuzzystrmatch": "1.2",
    "hstore": "1.8",
    "hypopg": "1.4.1",
    "intagg": "1.1",
    "intarray": "1.5",
    "isn": "1.2",
    "lo": "1.1",
    "ltree": "1.3",
    "orafce": "4.9",
    "pageinspect": "1.12",
    "pgaudit": "16.0",
    "pg_buffercache": "1.5",
    "pg_cron": "1.6",
    "pgcrypto": "1.3",
    "pg_diskann": "0.7.1",
    "pg_freespacemap": "1.2",
    "pglogical": "2.4.5",
    "pg_partman": "5.0.1",
    "pg_partman_bgw": "5.0.1",
    "pg_prewarm": "1.2",
    "pg_repack": "1.5.1",
    "pgrowlocks": "1.2",
    "pg_stat_statements": "1.11",
    "pgstattuple": "1.5",
    "pg_trgm": "1.6",
    "pg_visibility": "1.2",
    "postgis": "3.5.2",
    "postgis_raster": "3.5.2",
    "postgis_sfcgal": "3.5.2",
    "postgis_tiger_geocoder": "3.5.2",
    "postgis_topology": "3.5.2",
    "postgres_fdw": "1.1",
    "sslinfo": "1.2",
    "tablefunc": "1.0",
    "tsm_system_time": "1.0",
    "unaccent": "1.1",
    "uuid-ossp": "1.1",
    "vector": "0.8.0",
    "wal2json": "2.6",
}

# Listed on the extensions page as not supported.
HORIZONDB_UNSUPPORTED_EXTENSIONS = frozenset({"pg_failover_slots"})

# Always present; never part of a migration decision.
BUILTIN_EXTENSIONS = frozenset({"plpgsql"})

# Major version -> support status.
HORIZONDB_MAJOR_VERSIONS: dict[int, str] = {17: "ga", 18: "preview"}

# Capabilities the overview lists as not available at GA, with what to do instead.
NOT_AVAILABLE_AT_GA: dict[str, str] = {
    "connection_pooling": "No built-in PgBouncer: run a pooler in your own compute or rely on client-side pools.",
    "cross_region_readers": "No cross-region readers: disaster recovery is geo-redundant backup and restore.",
    "vnet_injection": "No VNet injection: use Private Link (private endpoints).",
    "long_term_retention": "No long-term backup retention: retention is 1 to 35 days.",
    "in_place_major_upgrade": "No in-place major version upgrade: plan upgrades as migrations.",
    "custom_maintenance_window": "System-managed maintenance window only: no custom window, deferral or notifications.",
    "cmk_with_geo_backup": "Customer-managed keys and geo-redundant backup cannot be combined: choose one at creation.",
}

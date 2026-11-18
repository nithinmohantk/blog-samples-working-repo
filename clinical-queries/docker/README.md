# Local openEHR and FHIR test stack

Runs EHRbase and HAPI FHIR on this machine so the AQL and FHIR search examples from the dataa.dev
articles can be executed for real.

    docker compose up -d
    docker compose ps

| Service | URL | Check |
| --- | --- | --- |
| EHRbase (openEHR) | http://localhost:8080/ehrbase/rest/openehr/v1/ | http://localhost:8080/ehrbase/rest/status |
| HAPI FHIR (R4) | http://localhost:8090/fhir/ | http://localhost:8090/fhir/metadata |

Stop and discard everything with `docker compose down`.

Notes

* Synthetic data only. Authentication is off and ports are bound to 127.0.0.1.
* The compose file is adapted from the EHRbase project's own `docker-compose.yml` (Keycloak removed,
  `SECURITY_AUTHTYPE: NONE` added). It was started on Docker Desktop on 12 November 2026 and gave
  EHRbase 2.39.0-SNAPSHOT and HAPI FHIR 8.6.0. If a container fails, `docker compose logs ehrbase` shows why.
* The database passwords in the compose file are throwaway values for a local, loopback-only stack. Do not reuse them.
* HAPI's `$lastn` operation needs Elasticsearch, which this stack does not include.

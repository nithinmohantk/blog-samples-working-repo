# cosmos-rust-ga

Sample code for the dataa.dev article *Azure Cosmos DB SDK for Rust Is GA: What Changes for Developers, DevOps and Architects* (19 Nov 2026).

An order service's storage layer on Azure Cosmos DB for NoSQL with `azure_data_cosmos` 1.0.0, the generally available Rust SDK.

| File | What it shows |
| :--- | :--- |
| `src/config.rs` | Settings from the environment, validated before a client is built: https endpoint, app region, managed identity or developer login, one operation time budget |
| `src/client.rs` | One `CosmosClient` per process with Entra ID (managed identity in Azure, `DeveloperToolsCredential` locally) and `RoutingStrategy::ProximityTo`; the 1.0 defaults (Gateway v2, binary encoding, per-partition failover handling, circuit breaker, point-read hedging) are left on |
| `src/model.rs` | The `Order` document with `tenantId` as partition key, money in minor units, unknown fields preserved on replace, allowed status transitions |
| `src/errors.rs` | What to do with an error after the SDK's own retries: not found, conflict, ETag mismatch, still throttled, unavailable, rejected |
| `src/repo.rs` | Create with conflict handling for client retries, point read with ETag, status change with `If-Match` and a bounded retry, single-partition parameterised query, an end-to-end latency budget on every operation |
| `ci/github-actions.yml` | fmt, clippy, tests on Rust 1.88 (the SDK's MSRV) and stable, plus `cargo audit` |

## Run the tests

```bash
cargo test
cargo clippy --all-targets -- -D warnings
```

The 8 unit tests need no Azure account. The repository code compiles against the 1.0.0 API; running `cargo run` needs an account:

```bash
export COSMOS_ENDPOINT=https://<account>.documents.azure.com/
export APP_REGION="West Europe"
export COSMOS_DATABASE=commerce COSMOS_CONTAINER=orders   # container partitioned on /tenantId
export COSMOS_CREDENTIAL=developer                         # after `az login`; omit in Azure to use managed identity
cargo run
```

The identity needs a Cosmos DB data-plane role assignment (for example *Cosmos DB Built-in Data Contributor*) on the account. Database and container creation is a control-plane task for your infrastructure code: in 1.0.0 the SDK's control-plane APIs sit behind the non-default `control_plane` feature and require key authentication.

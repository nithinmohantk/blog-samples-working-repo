//! Order storage on Azure Cosmos DB for NoSQL with the Rust SDK 1.0.
//!
//! Partition key values built from `&str` must be `'static` in 1.0.0; values
//! known only at run time are passed as `String` (or `&String`).

use std::time::Duration;

use azure_data_cosmos::{
    clients::ContainerClient,
    feed::FeedScope,
    options::{
        EndToEndOperationLatencyPolicy, ItemReadOptions, ItemWriteOptions, OperationOptions,
        Precondition, QueryOptions,
    },
    Query,
};
use futures::TryStreamExt;
use tracing::{debug, warn};

use crate::errors::StoreError;
use crate::model::{Order, OrderStatus};

/// An order together with the ETag it was read at, for optimistic concurrency.
#[derive(Debug, Clone)]
pub struct Versioned<T> {
    pub value: T,
    pub etag: String,
}

pub struct OrderRepository {
    container: ContainerClient,
    timeout: Duration,
}

impl OrderRepository {
    pub fn new(container: ContainerClient, timeout: Duration) -> Self {
        Self { container, timeout }
    }

    /// One budget for the whole operation: retries, failover and hedging
    /// included. Without it a request can keep retrying long after the caller
    /// has given up.
    fn operation(&self) -> OperationOptions {
        let mut op = OperationOptions::default();
        op.end_to_end_latency_policy = Some(EndToEndOperationLatencyPolicy::new(self.timeout));
        op
    }

    fn write_options(&self) -> ItemWriteOptions {
        ItemWriteOptions::default().with_operation_options(self.operation())
    }

    /// Creates an order. A 409 means the id already exists in this tenant, which
    /// is what a client retry after a lost response looks like, so the caller
    /// gets the stored order back instead of an error when it matches.
    pub async fn place(&self, order: &Order) -> Result<Versioned<Order>, StoreError> {
        match self
            .container
            .create_item(
                &order.tenant_id,
                &order.id,
                order,
                Some(self.write_options()),
            )
            .await
        {
            Ok(resp) => {
                let charge = resp.headers().request_charge().map(|c| c.to_string());
                debug!(order_id = %order.id, ru = ?charge, "order created");
                let etag = resp
                    .headers()
                    .etag()
                    .map(|e| e.to_string())
                    .unwrap_or_default();
                Ok(Versioned {
                    value: order.clone(),
                    etag,
                })
            }
            Err(e) => match StoreError::from(e) {
                StoreError::Conflict => {
                    let existing = self.get(&order.tenant_id, &order.id).await?;
                    if existing.value.lines == order.lines
                        && existing.value.currency == order.currency
                    {
                        Ok(existing)
                    } else {
                        Err(StoreError::Conflict)
                    }
                }
                other => Err(other),
            },
        }
    }

    pub async fn get(&self, tenant_id: &str, id: &str) -> Result<Versioned<Order>, StoreError> {
        let options = ItemReadOptions::default().with_operation_options(self.operation());
        let resp = self
            .container
            .read_item(tenant_id.to_owned(), id, Some(options))
            .await?;
        let etag = resp
            .headers()
            .etag()
            .map(|e| e.to_string())
            .unwrap_or_default();
        Ok(Versioned {
            value: resp.into_model::<Order>()?,
            etag,
        })
    }

    /// Moves an order to a new status with an If-Match precondition, retrying a
    /// small number of times when another writer got there first.
    pub async fn transition(
        &self,
        tenant_id: &str,
        id: &str,
        next: OrderStatus,
    ) -> Result<Order, StoreError> {
        for attempt in 1..=3 {
            let current = self.get(tenant_id, id).await?;
            if current.value.status == next {
                return Ok(current.value); // already applied: idempotent
            }
            if !current.value.status.can_move_to(next) {
                return Err(StoreError::InvalidTransition);
            }
            let mut updated = current.value.clone();
            updated.status = next;
            let mut options = self.write_options();
            options.precondition = Some(Precondition::IfMatch(current.etag.clone().into()));
            match self
                .container
                .replace_item(tenant_id.to_owned(), id, &updated, Some(options))
                .await
            {
                Ok(_) => return Ok(updated),
                Err(e) => match StoreError::from(e) {
                    StoreError::Concurrency => {
                        warn!(order_id = id, attempt, "etag mismatch, re-reading");
                        continue;
                    }
                    other => return Err(other),
                },
            }
        }
        Err(StoreError::Concurrency)
    }

    /// Lists a tenant's orders in one status. Scoped to one partition key, so it
    /// is a single-partition query: no fan-out across physical partitions.
    pub async fn by_status(
        &self,
        tenant_id: &str,
        status: OrderStatus,
        limit: u32,
    ) -> Result<Vec<Order>, StoreError> {
        let query =
            Query::from("SELECT TOP @limit * FROM c WHERE c.status = @status ORDER BY c._ts DESC")
                .with_parameter("@limit", limit)
                .and_then(|q| q.with_parameter("@status", status))
                .map_err(StoreError::from)?;
        let options = QueryOptions::default().with_operation_options(self.operation());
        let mut items = self
            .container
            .query_items::<Order>(
                query,
                FeedScope::partition(tenant_id.to_owned()),
                Some(options),
            )
            .await?;
        let mut out = Vec::new();
        while let Some(order) = items.try_next().await? {
            out.push(order);
        }
        Ok(out)
    }
}

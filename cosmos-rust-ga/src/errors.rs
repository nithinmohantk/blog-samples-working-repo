//! Maps SDK errors to what the application does next.
//!
//! The SDK has already retried what is safe to retry (throttling, 449 RetryWith,
//! regional failover, per-partition circuit breaking) by the time an error
//! reaches this code. What is left needs an application decision.

use azure_data_cosmos::error::CosmosError;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum StoreError {
    #[error("not found")]
    NotFound,
    #[error("already exists")]
    Conflict,
    /// The item changed since it was read (ETag mismatch). Re-read and re-apply.
    #[error("item was modified concurrently")]
    Concurrency,
    /// Still throttled after the SDK's own retries: shed load or raise throughput.
    #[error("throttled after retries")]
    Throttled,
    /// Timed out or unavailable after retries and failover: safe for the caller
    /// to retry later only if the operation is idempotent.
    #[error("temporarily unavailable ({status})")]
    Unavailable {
        status: u16,
        sub_status: Option<u32>,
    },
    /// Bad request, auth or permission problems: a bug or a configuration
    /// error, never retried.
    #[error("request rejected ({status})")]
    Rejected {
        status: u16,
        sub_status: Option<u32>,
    },
    #[error("invalid state transition")]
    InvalidTransition,
}

impl StoreError {
    /// HTTP status an API in front of the store would return.
    pub fn http_status(&self) -> u16 {
        match self {
            StoreError::NotFound => 404,
            StoreError::Conflict | StoreError::Concurrency | StoreError::InvalidTransition => 409,
            StoreError::Throttled => 429,
            StoreError::Unavailable { .. } => 503,
            StoreError::Rejected { .. } => 500,
        }
    }
}

impl From<CosmosError> for StoreError {
    fn from(e: CosmosError) -> Self {
        let s = e.status();
        let status = u16::from(s.status_code());
        let sub_status = s.sub_status().map(|x| u32::from(x.value()));
        if s.is_not_found() {
            StoreError::NotFound
        } else if s.is_conflict() {
            StoreError::Conflict
        } else if s.is_precondition_failed() {
            StoreError::Concurrency
        } else if s.is_throttled() {
            StoreError::Throttled
        } else if s.is_transient() {
            StoreError::Unavailable { status, sub_status }
        } else {
            StoreError::Rejected { status, sub_status }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use azure_core::http::StatusCode;
    use azure_data_cosmos::error::CosmosStatus;

    fn err(code: u16, sub: Option<u16>) -> CosmosError {
        let mut st = CosmosStatus::new(StatusCode::from(code));
        if let Some(sub) = sub {
            st = st.with_sub_status(sub);
        }
        CosmosError::builder()
            .with_status(st)
            .with_message("test")
            .build()
    }

    #[test]
    fn maps_statuses_to_actions() {
        assert!(matches!(
            StoreError::from(err(404, None)),
            StoreError::NotFound
        ));
        assert!(matches!(
            StoreError::from(err(409, None)),
            StoreError::Conflict
        ));
        assert!(matches!(
            StoreError::from(err(412, None)),
            StoreError::Concurrency
        ));
        assert!(matches!(
            StoreError::from(err(429, Some(3200))),
            StoreError::Throttled
        ));
        assert!(matches!(
            StoreError::from(err(503, None)),
            StoreError::Unavailable { status: 503, .. }
        ));
        // 408 with sub-status 20008 is the SDK's own end-to-end timeout.
        assert!(matches!(
            StoreError::from(err(408, Some(20008))),
            StoreError::Unavailable {
                status: 408,
                sub_status: Some(20008)
            }
        ));
        assert!(matches!(
            StoreError::from(err(403, None)),
            StoreError::Rejected { status: 403, .. }
        ));
        assert!(matches!(
            StoreError::from(err(400, None)),
            StoreError::Rejected { status: 400, .. }
        ));
    }

    #[test]
    fn http_mapping() {
        assert_eq!(StoreError::Concurrency.http_status(), 409);
        assert_eq!(StoreError::Throttled.http_status(), 429);
        assert_eq!(StoreError::from(err(403, None)).http_status(), 500);
    }
}

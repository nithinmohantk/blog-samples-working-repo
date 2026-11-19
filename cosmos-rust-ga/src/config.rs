//! Settings read from the environment and validated before any client is built.

use std::time::Duration;

use thiserror::Error;

/// How the process authenticates to Microsoft Entra ID.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CredentialSource {
    /// Azure CLI or Azure Developer CLI login on a developer machine.
    DeveloperTools,
    /// A managed identity: system-assigned when `client_id` is `None`.
    ManagedIdentity { client_id: Option<String> },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Settings {
    pub endpoint: String,
    /// The Azure region this process runs in, e.g. "West Europe". The SDK orders
    /// the account's regions by proximity to it.
    pub app_region: String,
    pub database: String,
    pub container: String,
    pub credential: CredentialSource,
    /// Upper bound for one logical operation, including retries, failover and hedging.
    pub operation_timeout: Duration,
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ConfigError {
    #[error("missing environment variable {0}")]
    Missing(&'static str),
    #[error("COSMOS_ENDPOINT must be an https://<account>.documents.azure.com/ URL, got {0}")]
    BadEndpoint(String),
    #[error("COSMOS_OPERATION_TIMEOUT_MS must be between 100 and 60000, got {0}")]
    BadTimeout(String),
    #[error("COSMOS_CREDENTIAL must be 'developer' or 'managed-identity', got {0}")]
    BadCredential(String),
}

impl Settings {
    /// Reads settings through `get`, so tests can supply values without touching
    /// the process environment.
    pub fn from_lookup(get: impl Fn(&str) -> Option<String>) -> Result<Self, ConfigError> {
        let need = |k: &'static str| {
            get(k)
                .filter(|v| !v.trim().is_empty())
                .ok_or(ConfigError::Missing(k))
        };

        let endpoint = need("COSMOS_ENDPOINT")?;
        let host_ok = endpoint
            .strip_prefix("https://")
            .map(|rest| rest.trim_end_matches('/'))
            .is_some_and(|host| host.ends_with(".documents.azure.com") && !host.contains('/'));
        if !host_ok {
            return Err(ConfigError::BadEndpoint(endpoint));
        }

        let operation_timeout = match get("COSMOS_OPERATION_TIMEOUT_MS") {
            None => Duration::from_secs(5),
            Some(raw) => match raw.parse::<u64>() {
                Ok(ms) if (100..=60_000).contains(&ms) => Duration::from_millis(ms),
                _ => return Err(ConfigError::BadTimeout(raw)),
            },
        };

        let credential = match get("COSMOS_CREDENTIAL").as_deref() {
            None | Some("managed-identity") => CredentialSource::ManagedIdentity {
                client_id: get("AZURE_CLIENT_ID").filter(|v| !v.is_empty()),
            },
            Some("developer") => CredentialSource::DeveloperTools,
            Some(other) => return Err(ConfigError::BadCredential(other.to_owned())),
        };

        Ok(Settings {
            endpoint,
            app_region: need("APP_REGION")?,
            database: need("COSMOS_DATABASE")?,
            container: need("COSMOS_CONTAINER")?,
            credential,
            operation_timeout,
        })
    }

    pub fn from_env() -> Result<Self, ConfigError> {
        Self::from_lookup(|k| std::env::var(k).ok())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn env(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let map: HashMap<String, String> = pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        move |k| map.get(k).cloned()
    }

    const BASE: &[(&str, &str)] = &[
        (
            "COSMOS_ENDPOINT",
            "https://orders-prod.documents.azure.com/",
        ),
        ("APP_REGION", "West Europe"),
        ("COSMOS_DATABASE", "commerce"),
        ("COSMOS_CONTAINER", "orders"),
    ];

    #[test]
    fn defaults_to_managed_identity_and_five_second_budget() {
        let s = Settings::from_lookup(env(BASE)).unwrap();
        assert_eq!(
            s.credential,
            CredentialSource::ManagedIdentity { client_id: None }
        );
        assert_eq!(s.operation_timeout, Duration::from_secs(5));
    }

    #[test]
    fn user_assigned_identity_and_developer_login() {
        let mut v = BASE.to_vec();
        v.push(("AZURE_CLIENT_ID", "1b2c"));
        let s = Settings::from_lookup(env(&v)).unwrap();
        assert_eq!(
            s.credential,
            CredentialSource::ManagedIdentity {
                client_id: Some("1b2c".into())
            }
        );
        let mut v = BASE.to_vec();
        v.push(("COSMOS_CREDENTIAL", "developer"));
        assert_eq!(
            Settings::from_lookup(env(&v)).unwrap().credential,
            CredentialSource::DeveloperTools
        );
    }

    #[test]
    fn rejects_plain_http_wrong_host_and_bad_values() {
        for bad in [
            "http://orders-prod.documents.azure.com/",
            "https://example.com/",
            "https://x.documents.azure.com/dbs",
        ] {
            let mut v = BASE.to_vec();
            v[0] = ("COSMOS_ENDPOINT", bad);
            assert!(
                matches!(
                    Settings::from_lookup(env(&v)),
                    Err(ConfigError::BadEndpoint(_))
                ),
                "{bad}"
            );
        }
        let mut v = BASE.to_vec();
        v.push(("COSMOS_OPERATION_TIMEOUT_MS", "0"));
        assert!(matches!(
            Settings::from_lookup(env(&v)),
            Err(ConfigError::BadTimeout(_))
        ));
        let mut v = BASE.to_vec();
        v.push(("COSMOS_CREDENTIAL", "account-key"));
        assert!(matches!(
            Settings::from_lookup(env(&v)),
            Err(ConfigError::BadCredential(_))
        ));
        assert_eq!(
            Settings::from_lookup(env(&BASE[..3])),
            Err(ConfigError::Missing("COSMOS_CONTAINER"))
        );
    }
}

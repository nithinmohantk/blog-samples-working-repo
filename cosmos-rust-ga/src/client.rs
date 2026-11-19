//! Builds one long-lived `CosmosClient` per process.

use std::sync::Arc;

use azure_core::credentials::TokenCredential;
use azure_data_cosmos::{
    clients::ContainerClient, options::RoutingStrategy, AccountEndpoint, AccountReference,
    CosmosClient,
};
use azure_identity::{
    DeveloperToolsCredential, ManagedIdentityCredential, ManagedIdentityCredentialOptions,
    UserAssignedId,
};

use crate::config::{CredentialSource, Settings};

pub fn credential(source: &CredentialSource) -> azure_core::Result<Arc<dyn TokenCredential>> {
    Ok(match source {
        CredentialSource::DeveloperTools => DeveloperToolsCredential::new(None)?,
        CredentialSource::ManagedIdentity { client_id: None } => {
            ManagedIdentityCredential::new(None)?
        }
        CredentialSource::ManagedIdentity {
            client_id: Some(id),
        } => ManagedIdentityCredential::new(Some(ManagedIdentityCredentialOptions {
            user_assigned_id: Some(UserAssignedId::ClientId(id.clone())),
            ..Default::default()
        }))?,
    })
}

/// Gateway v2, binary encoding, per-partition failover handling, the
/// per-partition circuit breaker and point-read hedging are all defaults in
/// 1.0.0, so nothing here switches them on. The routing strategy is the one
/// required decision: it orders the account's regions by proximity to where
/// this process runs.
pub async fn connect(
    settings: &Settings,
) -> Result<(CosmosClient, ContainerClient), Box<dyn std::error::Error + Send + Sync>> {
    let endpoint: AccountEndpoint = settings.endpoint.parse()?;
    let account = AccountReference::with_credential(endpoint, credential(&settings.credential)?);
    let client = CosmosClient::builder()
        .build(
            account,
            RoutingStrategy::ProximityTo(settings.app_region.clone().into()),
        )
        .await?;
    // Resolving the container loads the partition topology eagerly (the 1.0
    // default), so a misconfigured name or missing permission fails at start-up
    // rather than on the first customer request.
    let container = client
        .database_client(settings.database.as_str())
        .container_client(settings.container.as_str(), None)
        .await?;
    Ok((client, container))
}

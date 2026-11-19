use cosmos_orders::{
    client::connect,
    config::Settings,
    model::{Order, OrderLine, OrderStatus},
    repo::OrderRepository,
};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let settings = Settings::from_env()?;
    let (_client, container) = connect(&settings).await?;
    let orders = OrderRepository::new(container, settings.operation_timeout);

    let order = Order::new(
        "tenant-0042",
        "ord-2026-11-19-0001",
        "EUR",
        vec![OrderLine {
            sku: "SKU-RED-M".into(),
            quantity: 2,
            unit_price_minor: 2_499,
        }],
    );
    let placed = orders.place(&order).await?;
    tracing::info!(id = %placed.value.id, etag = %placed.etag, "placed");

    let paid = orders
        .transition("tenant-0042", &order.id, OrderStatus::Paid)
        .await?;
    tracing::info!(id = %paid.id, status = ?paid.status, "paid");

    let open = orders
        .by_status("tenant-0042", OrderStatus::Paid, 20)
        .await?;
    tracing::info!(count = open.len(), "paid orders for tenant");
    Ok(())
}

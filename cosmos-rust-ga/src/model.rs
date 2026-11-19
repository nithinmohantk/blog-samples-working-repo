//! The order document. `tenantId` is the partition key: every query the API
//! serves is scoped to one tenant, so reads and queries stay in one partition.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum OrderStatus {
    Placed,
    Paid,
    Shipped,
    Cancelled,
}

impl OrderStatus {
    /// Allowed transitions; anything else is rejected before a write is attempted.
    pub fn can_move_to(self, next: OrderStatus) -> bool {
        use OrderStatus::*;
        matches!(
            (self, next),
            (Placed, Paid) | (Placed, Cancelled) | (Paid, Shipped) | (Paid, Cancelled)
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OrderLine {
    pub sku: String,
    pub quantity: u32,
    /// Minor units (cents) avoid floating-point money.
    pub unit_price_minor: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Order {
    pub id: String,
    pub tenant_id: String,
    pub status: OrderStatus,
    pub currency: String,
    pub lines: Vec<OrderLine>,
    pub total_minor: u64,
    /// Fields this version of the service does not model (including system
    /// properties such as `_ts`) are kept and written back unchanged, so an
    /// older deployment cannot strip data a newer one added.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

impl Order {
    pub fn new(tenant_id: &str, id: &str, currency: &str, lines: Vec<OrderLine>) -> Self {
        let total_minor = lines
            .iter()
            .map(|l| l.unit_price_minor * u64::from(l.quantity))
            .sum();
        Order {
            id: id.to_owned(),
            tenant_id: tenant_id.to_owned(),
            status: OrderStatus::Placed,
            currency: currency.to_owned(),
            lines,
            total_minor,
            extra: Map::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn serializes_with_camel_case_partition_key_and_total() {
        let o = Order::new(
            "t-42",
            "o-1",
            "EUR",
            vec![OrderLine {
                sku: "A".into(),
                quantity: 3,
                unit_price_minor: 1250,
            }],
        );
        let v = serde_json::to_value(&o).unwrap();
        assert_eq!(v["tenantId"], "t-42");
        assert_eq!(v["status"], "placed");
        assert_eq!(v["totalMinor"], 3750);
    }

    #[test]
    fn unknown_fields_round_trip() {
        let raw = r#"{"id":"o-1","tenantId":"t-42","status":"paid","currency":"EUR","lines":[],
                      "totalMinor":0,"loyaltyPoints":12,"_ts":1763571000}"#;
        let o: Order = serde_json::from_str(raw).unwrap();
        let back = serde_json::to_value(&o).unwrap();
        assert_eq!(back["loyaltyPoints"], 12);
        assert_eq!(back["_ts"], 1763571000);
    }

    #[test]
    fn status_transitions() {
        use OrderStatus::*;
        assert!(Placed.can_move_to(Paid) && Paid.can_move_to(Shipped));
        assert!(
            !Shipped.can_move_to(Placed)
                && !Cancelled.can_move_to(Paid)
                && !Placed.can_move_to(Shipped)
        );
    }
}

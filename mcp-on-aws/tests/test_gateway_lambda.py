from types import SimpleNamespace

from conftest import expected_total
from gateway_lambda.handler import lambda_handler


def ctx(tool, target="sales-target"):
    custom = {"bedrockAgentCoreToolName": f"{target}___{tool}"}
    return SimpleNamespace(client_context=SimpleNamespace(custom=custom), aws_request_id="req-1")


def test_summary_matches_independent_sum(orders_table):
    out = lambda_handler({"customer_id": "C-000001"}, ctx("get_customer_summary"))
    assert out["order_count"] == 30
    assert out["total_spend"] == expected_total("C-000001")


def test_pagination_walks_every_order_once(orders_table):
    seen, token = [], None
    while True:
        args = {"customer_id": "C-000001", "limit": 25}
        if token:
            args["next_token"] = token
        page = lambda_handler(args, ctx("list_customer_orders"))
        seen += [o["order_id"] for o in page["orders"]]
        token = page["next_token"]
        if not token:
            break
    assert len(seen) == 30 and len(set(seen)) == 30
    assert seen[0] == "O-0029"  # newest first


def test_limit_is_clamped(orders_table):
    page = lambda_handler({"customer_id": "C-000001", "limit": 500}, ctx("list_customer_orders"))
    assert len(page["orders"]) == 25


def test_token_cannot_cross_customers(orders_table):
    first = lambda_handler({"customer_id": "C-000001", "limit": 5}, ctx("list_customer_orders"))
    out = lambda_handler(
        {"customer_id": "C-000002", "next_token": first["next_token"]}, ctx("list_customer_orders")
    )
    assert out["error"] == "INVALID_INPUT"


def test_invalid_customer_id_and_unknown_tool(orders_table):
    assert lambda_handler({"customer_id": "1 OR 1=1"}, ctx("get_customer_summary"))["error"] == "INVALID_INPUT"
    assert lambda_handler({}, ctx("drop_table"))["error"] == "UNKNOWN_TOOL"

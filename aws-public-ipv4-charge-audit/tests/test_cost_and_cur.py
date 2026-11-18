import csv
import gzip
from decimal import Decimal

from ipv4_audit.audit import PublicIp
from ipv4_audit.cost import hours_in_month, month_cost, summarise
from ipv4_audit.cur_summary import summarise_cur


def test_february_2024_is_a_leap_month():
    assert hours_in_month(2024, 2) == 696
    assert month_cost(1, 2024, 2) == Decimal("3.48")
    assert month_cost(1, 2024, 3) == Decimal("3.72")


def test_free_tier_covers_one_address_for_a_whole_month():
    assert month_cost(1, 2024, 3, free_tier=True) == Decimal("0.00")
    assert month_cost(2, 2024, 3, free_tier=True) == Decimal("3.69")  # 1488 - 750 = 738 hours


def test_summary_separates_the_new_charge():
    addresses = [
        PublicIp("eu-west-1", "203.0.113.1", "ec2-auto", "ec2 i-1", None, "RunInstances", True),
        PublicIp("eu-west-1", "203.0.113.2", "eip-idle", "none (idle)", None, "AllocateAddressVPC", False),
    ]
    s = summarise(addresses, 2024, 2)
    assert (s["addresses"], s["newly_charged"], s["cost_all"], s["cost_new_from_feb_2024"]) == (2, 1, "6.96", "3.48")


HEADER = ["lineItem/UsageStartDate", "lineItem/UsageType", "lineItem/Operation",
          "lineItem/ResourceId", "lineItem/UsageAmount", "lineItem/UnblendedCost"]


def _write_cur(path, rows, gz=False):
    opener = gzip.open(path, "wt", newline="") if gz else open(path, "w", newline="")
    with opener as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)


def test_cur_summary_counts_only_public_ipv4_lines(tmp_path):
    rows = [
        ["2024-01-10T00:00:00Z", "EU-PublicIPv4:InUseAddress", "RunInstances", "eipalloc-x", "24", "0"],
        ["2024-01-10T00:00:00Z", "EU-PublicIPv4:InUseAddress", "DescribeNetworkInterfaces", "eni-1", "48", "0"],
        ["2024-01-10T00:00:00Z", "EU-PublicIPv4:IdleAddress", "AllocateAddressVPC", "eipalloc-y", "24", "0"],
        ["2024-01-10T00:00:00Z", "EU-BoxUsage:t3.micro", "RunInstances", "i-1", "24", "0.2736"],
    ]
    path = tmp_path / "cur.csv.gz"
    _write_cur(path, rows, gz=True)
    s = summarise_cur(path)
    assert s["address_hours"] == "96"
    assert s["cost_at_feb_2024_rate"] == "0.48"
    assert s["by_usage_type"] == {"PublicIPv4:IdleAddress": "24", "PublicIPv4:InUseAddress": "72"}
    assert s["by_operation"]["DescribeNetworkInterfaces"] == "48"
    assert s["top_resources"][0] == ["eni-1", "48"]

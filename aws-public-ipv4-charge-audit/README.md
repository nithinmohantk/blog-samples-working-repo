# Public IPv4 audit for the 1 February 2024 charge

Sample code for the dataa.dev article *The AWS Public IPv4 Charge: Audit Every Address Before 1 February 2024*.

From 1 February 2024 AWS charges $0.005 per hour for every public IPv4 address, whether it is
attached to something or not. Before that date only idle Elastic IPs and second and later Elastic
IPs on a running instance were charged. This code finds every public IPv4 address in an account,
names what holds it, marks the ones that become chargeable on 1 February, and prices them.

It is read-only. It calls `describe_*` operations and changes nothing.

## What is here

| Path | What it does |
| --- | --- |
| `ipv4_audit/audit.py` | `audit_region` and `audit_account`: every address from instances, Elastic IPs, NAT gateways and ENIs, counted once each. `auto_assign_subnets` lists subnets with `MapPublicIpOnLaunch` on. |
| `ipv4_audit/cost.py` | Monthly cost at $0.005 per address-hour, with the EC2 Free Tier's 750 hours and the real hours in each month. |
| `ipv4_audit/cur_summary.py` | Reads a Cost and Usage Report CSV (or `.csv.gz`) and totals the `PublicIPv4:InUseAddress` and `PublicIPv4:IdleAddress` lines by operation and resource. |
| `tools/audit_account.py` | Command line: audit your account, write a CSV, print a summary. |
| `tools/cur_report.py` | Command line: price a downloaded CUR file at the February 2024 rate. |
| `tools/demo_account.py` | Builds a made-up account in moto and audits it. |
| `tools/scenarios.py` | Prices a clean-up of the demo account step by step. |
| `tools/api_options.py` | Prints the IPv4-related options in the installed botocore model. |
| `tests/` | 16 tests: moto for instances, Elastic IPs, NAT gateways and subnets; botocore Stubber for load balancer, ECS and typed ENIs; CSV fixtures for the CUR reader. |
| `ci.sh` | What CI runs. |

## Run it against your account

```bash
python -m venv .venv && . .venv/bin/activate
pip install boto3
python tools/audit_account.py --out ipv4.csv                       # every enabled Region
python tools/audit_account.py --regions eu-west-1 --month 2024-03  # one Region, priced for March
```

IAM permissions needed: `ec2:DescribeRegions`, `ec2:DescribeAddresses`, `ec2:DescribeInstances`,
`ec2:DescribeNetworkInterfaces`, `ec2:DescribeNatGateways`, `ec2:DescribeSubnets`.

## Run the tests

```bash
pip install uv
uv pip install --exclude-newer 2024-01-26 boto3 "moto[ec2]" pytest
./ci.sh out
```

## What was verified

In GitHub Actions with Python 3.12 and the packages available on 26 January 2024
(boto3 and botocore 1.34.29, moto 4.2.13, pytest 7.4.4):

- All 16 tests pass.
- The demo account (two subnets with auto-assign on, four web instances, a bastion with an
  Elastic IP, two NAT gateways, two idle Elastic IPs, one forgotten instance in us-east-1) holds
  10 public IPv4 addresses. Eight were free before 1 February 2024. February 2024 has 696 hours,
  so the account's bill for these addresses goes from $6.96 to $34.80 that month.
- botocore 1.34.29 lists `natGateway` in the `NetworkInterfaceType` enum, while the EC2 API
  reference lists `nat_gateway`. The audit accepts both.
- moto 4.2.13 leaves the ENI `Association` empty for auto-assigned instance addresses, and leaves
  `InstanceId` empty on an Elastic IP associated through its ENI. The audit reads instances
  directly and maps ENIs back to instances, so it does not depend on either field.

## What was not verified

- No real AWS account was used. Load balancer, ECS and typed ENIs are tested with synthetic
  responses that botocore's Stubber checks against the service model, not with live resources.
- Site-to-Site VPN tunnel addresses and Global Accelerator addresses are charged too but are not
  counted. Use VPC IPAM Public IP Insights or the CUR for those.
- Owner names for load balancers rely on the `ELB app/`, `ELB net/` and `ELB ` description
  prefixes. AWS documents the description field's purpose but not its exact format.
- The CUR reader was tested on a synthetic file with the CUR CSV column names, not on a real report.

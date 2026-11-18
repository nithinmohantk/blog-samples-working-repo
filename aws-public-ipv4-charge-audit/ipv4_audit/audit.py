"""Find every public IPv4 address in one AWS account and Region, and say who owns it.

From 1 February 2024 AWS charges $0.005 per hour for every public IPv4 address,
in use or idle. Before that date, only idle Elastic IPs and second and later
Elastic IPs on a running instance were charged. This module lists the
addresses, names the resource that holds each one, and marks which addresses
the February change makes chargeable for the first time.

Read-only. It calls describe_* operations only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict

log = logging.getLogger("ipv4_audit")

# The botocore model (1.34.29) lists "natGateway" in the NetworkInterfaceType enum,
# while the EC2 API reference lists "nat_gateway" as the value. Accept both.
NAT_INTERFACE_TYPES = {"nat_gateway", "natGateway"}

# Billing operations from the CUR, per the AWS Networking blog of 28 July 2023.
OP_EC2 = "RunInstances"
OP_EIP_IN_USE = "AssociateAddressVPC"
OP_EIP_IDLE = "AllocateAddressVPC"
OP_SERVICE = "DescribeNetworkInterfaces"


@dataclass(frozen=True)
class PublicIp:
    region: str
    ip: str
    kind: str            # ec2-auto | eip-in-use | eip-idle | service-managed
    owner: str           # what holds the address, e.g. "ec2 i-0abc", "nat nat-0abc", "elb app/web/123"
    eni: str | None
    billing_operation: str
    newly_charged: bool  # True if this address was free before 1 February 2024

    def as_row(self) -> dict:
        return asdict(self)


def _pages(client, operation: str, key: str, **kwargs):
    for page in client.get_paginator(operation).paginate(**kwargs):
        yield from page.get(key, [])


def describe_owner(eni: dict, nat_by_eni: dict[str, str]) -> str:
    """Name the resource that holds an ENI. Uses only documented fields."""
    eni_id = eni["NetworkInterfaceId"]
    instance_id = (eni.get("Attachment") or {}).get("InstanceId")
    if instance_id:
        return f"ec2 {instance_id}"
    if eni_id in nat_by_eni:
        return f"nat {nat_by_eni[eni_id]}"
    description = eni.get("Description") or ""
    if description.startswith(("ELB app/", "ELB net/")):
        return "elb " + description[len("ELB "):]
    if description.startswith("ELB "):
        return "elb classic " + description[len("ELB "):]
    interface_type = eni.get("InterfaceType") or "interface"
    if interface_type in NAT_INTERFACE_TYPES:
        return f"nat (from interface type) {eni_id}"
    if interface_type != "interface":
        return f"{interface_type} {eni_id}"
    if eni.get("RequesterManaged"):
        return f"requester-managed '{description}' {eni_id}"
    return f"unknown {eni_id}"


def audit_region(ec2, region: str) -> list[PublicIp]:
    """Return one PublicIp per address. ec2 is a boto3 EC2 client for that Region."""
    found: dict[str, PublicIp] = {}

    nat_by_eni = {
        address["NetworkInterfaceId"]: nat["NatGatewayId"]
        for nat in _pages(ec2, "describe_nat_gateways", "NatGateways")
        if nat.get("State") in ("pending", "available")
        for address in nat.get("NatGatewayAddresses", [])
        if address.get("NetworkInterfaceId")
    }

    # 1. Instances. Auto-assigned addresses live here (and on the ENI).
    instance_by_eni: dict[str, str] = {}
    auto_assigned: list[PublicIp] = []
    for reservation in _pages(ec2, "describe_instances", "Reservations"):
        for instance in reservation["Instances"]:
            owner = f"ec2 {instance['InstanceId']}"
            seen = set()
            for eni in instance.get("NetworkInterfaces", []):
                instance_by_eni[eni["NetworkInterfaceId"]] = instance["InstanceId"]
                for private in eni.get("PrivateIpAddresses", []):
                    association = private.get("Association") or {}
                    if association.get("PublicIp") and not association.get("AllocationId"):
                        seen.add(association["PublicIp"])
                        auto_assigned.append(PublicIp(region, association["PublicIp"], "ec2-auto", owner,
                                                      eni["NetworkInterfaceId"], OP_EC2, True))
            ip = instance.get("PublicIpAddress")
            if ip and ip not in seen:
                auto_assigned.append(PublicIp(region, ip, "ec2-auto", owner, None, OP_EC2, True))

    # 2. Elastic IPs. The only source for idle ones. They win over step 1 for the same address.
    eips_per_instance: dict[str, int] = {}
    for address in ec2.describe_addresses()["Addresses"]:
        ip = address["PublicIp"]
        if not address.get("AssociationId"):
            found[ip] = PublicIp(region, ip, "eip-idle", "none (idle)", None, OP_EIP_IDLE, False)
            continue
        eni_id = address.get("NetworkInterfaceId") or None
        # InstanceId can be empty when the EIP was associated through the ENI; map it back.
        instance_id = address.get("InstanceId") or instance_by_eni.get(eni_id or "", "")
        if instance_id:
            owner = f"ec2 {instance_id}"
            eips_per_instance[instance_id] = eips_per_instance.get(instance_id, 0) + 1
            # Before February 2024 the first EIP on a running instance was free.
            newly = eips_per_instance[instance_id] == 1
        else:
            owner = f"nat {nat_by_eni[eni_id]}" if eni_id in nat_by_eni else f"eni {eni_id}"
            newly = True
        found[ip] = PublicIp(region, ip, "eip-in-use", owner, eni_id, OP_EIP_IN_USE, newly)
    for item in auto_assigned:
        found.setdefault(item.ip, item)

    # 3. Every other ENI with a public address: load balancers, ECS tasks, and the rest.
    for eni in _pages(ec2, "describe_network_interfaces", "NetworkInterfaces"):
        for private in eni.get("PrivateIpAddresses", []) or [eni]:
            association = private.get("Association") or {}
            ip = association.get("PublicIp")
            if not ip or ip in found:
                continue
            kind, op = ("eip-in-use", OP_EIP_IN_USE) if association.get("AllocationId") else ("service-managed", OP_SERVICE)
            found[ip] = PublicIp(region, ip, kind, describe_owner(eni, nat_by_eni),
                                 eni["NetworkInterfaceId"], op, True)

    log.info("region=%s public_ipv4=%d", region, len(found))
    return sorted(found.values(), key=lambda p: (p.kind, p.owner, p.ip))


def enabled_regions(ec2) -> list[str]:
    regions = ec2.describe_regions(AllRegions=False)["Regions"]
    return sorted(r["RegionName"] for r in regions)


def audit_account(session, regions: list[str] | None = None) -> list[PublicIp]:
    """Audit every enabled Region. Errors in one Region are logged and skipped, not fatal."""
    home = session.client("ec2", region_name=session.region_name or "us-east-1")
    results: list[PublicIp] = []
    for region in regions or enabled_regions(home):
        try:
            results.extend(audit_region(session.client("ec2", region_name=region), region))
        except Exception as err:  # one Region's denial or throttling must not lose the rest
            log.warning("region=%s skipped: %s", region, err)
    return results


def auto_assign_subnets(ec2) -> list[dict]:
    """Subnets that hand a public IPv4 address to everything launched in them.

    Default VPC subnets have this on. Turning it off changes only new launches.
    Existing instances made their choice at launch: they get a new address
    every time they start, so they have to be replaced to lose it.
    """
    return [
        {"subnet": s["SubnetId"], "vpc": s["VpcId"], "az": s["AvailabilityZone"],
         "default_for_az": s.get("DefaultForAz", False)}
        for s in _pages(ec2, "describe_subnets", "Subnets")
        if s.get("MapPublicIpOnLaunch")
    ]

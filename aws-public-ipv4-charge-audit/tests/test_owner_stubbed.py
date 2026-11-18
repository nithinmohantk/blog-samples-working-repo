"""ENI shapes moto 4.2.13 does not produce: load balancers, ECS tasks, typed managed ENIs.

The responses are synthetic but botocore's Stubber validates them against the
EC2 service model of botocore 1.34.29, so every field name and type is real.
"""
import boto3
import pytest
from botocore.stub import Stubber

from ipv4_audit.audit import audit_region, describe_owner

REGION = "eu-west-1"


def eni(eni_id, ip, *, description="", interface_type="interface", requester_managed=True,
        allocation_id=None, instance_id=None, ip_owner="amazon"):
    association = {"PublicIp": ip, "IpOwnerId": ip_owner}
    if allocation_id:
        association["AllocationId"] = allocation_id
    item = {
        "NetworkInterfaceId": eni_id,
        "Description": description,
        "InterfaceType": interface_type,
        "RequesterManaged": requester_managed,
        "Association": association,
        "PrivateIpAddresses": [{"PrivateIpAddress": "10.0.1.10", "Primary": True, "Association": association}],
    }
    if instance_id:
        item["Attachment"] = {"InstanceId": instance_id}
    return item


ENIS = [
    eni("eni-0alb0000000000001", "203.0.113.11", description="ELB app/web/50dc6c495c0c9188"),
    eni("eni-0alb0000000000002", "203.0.113.12", description="ELB app/web/50dc6c495c0c9188"),
    eni("eni-0nlb0000000000001", "203.0.113.21", description="ELB net/api/7f6e5d4c3b2a1908",
        interface_type="network_load_balancer", allocation_id="eipalloc-0nlb000000000001", ip_owner="111122223333"),
    eni("eni-0clb0000000000001", "203.0.113.31", description="ELB legacy-portal"),
    eni("eni-0ecs0000000000001", "203.0.113.41",
        description="arn:aws:ecs:eu-west-1:111122223333:attachment/1b2c3d4e-0000-4000-8000-000000000001"),
    eni("eni-0nat0000000000001", "203.0.113.51", description="Interface for NAT Gateway nat-0abc",
        interface_type="nat_gateway", allocation_id="eipalloc-0nat000000000001", ip_owner="111122223333"),
    eni("eni-0own0000000000001", "203.0.113.61", requester_managed=False),
]


@pytest.fixture
def stubbed():
    client = boto3.client("ec2", region_name=REGION, aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(client) as stub:
        stub.add_response("describe_nat_gateways", {"NatGateways": []})
        stub.add_response("describe_instances", {"Reservations": []})
        stub.add_response("describe_addresses", {"Addresses": []})
        stub.add_response("describe_network_interfaces", {"NetworkInterfaces": ENIS})
        yield client
        stub.assert_no_pending_responses()


def test_every_eni_address_gets_an_owner(stubbed):
    owners = {f.ip: (f.kind, f.owner, f.billing_operation) for f in audit_region(stubbed, REGION)}
    assert owners == {
        "203.0.113.11": ("service-managed", "elb app/web/50dc6c495c0c9188", "DescribeNetworkInterfaces"),
        "203.0.113.12": ("service-managed", "elb app/web/50dc6c495c0c9188", "DescribeNetworkInterfaces"),
        "203.0.113.21": ("eip-in-use", "elb net/api/7f6e5d4c3b2a1908", "AssociateAddressVPC"),
        "203.0.113.31": ("service-managed", "elb classic legacy-portal", "DescribeNetworkInterfaces"),
        "203.0.113.41": ("service-managed",
                         "requester-managed 'arn:aws:ecs:eu-west-1:111122223333:attachment/"
                         "1b2c3d4e-0000-4000-8000-000000000001' eni-0ecs0000000000001",
                         "DescribeNetworkInterfaces"),
        "203.0.113.51": ("eip-in-use", "nat (from interface type) eni-0nat0000000000001", "AssociateAddressVPC"),
        "203.0.113.61": ("service-managed", "unknown eni-0own0000000000001", "DescribeNetworkInterfaces"),
    }


@pytest.mark.parametrize("interface_type", ["nat_gateway", "natGateway"])
def test_nat_type_is_recognised_in_either_spelling(interface_type):
    item = eni("eni-0n", "198.51.100.1", interface_type=interface_type)
    assert describe_owner(item, {}).startswith("nat ")


def test_nat_join_beats_the_description():
    item = eni("eni-0n", "198.51.100.1", description="anything")
    assert describe_owner(item, {"eni-0n": "nat-0123"}) == "nat nat-0123"


def test_auto_assigned_address_seen_twice_is_counted_once_as_ec2():
    """Real AWS puts an auto-assigned address on the instance and on its ENI. Count it once."""
    client = boto3.client("ec2", region_name=REGION, aws_access_key_id="x", aws_secret_access_key="x")
    shared = eni("eni-0web000000000001", "198.51.100.7", requester_managed=False, instance_id="i-0web0000000000001")
    instance = {"InstanceId": "i-0web0000000000001", "PublicIpAddress": "198.51.100.7",
                "NetworkInterfaces": [{"NetworkInterfaceId": shared["NetworkInterfaceId"],
                                       "PrivateIpAddresses": shared["PrivateIpAddresses"]}]}
    with Stubber(client) as stub:
        stub.add_response("describe_nat_gateways", {"NatGateways": []})
        stub.add_response("describe_instances", {"Reservations": [{"Instances": [instance]}]})
        stub.add_response("describe_addresses", {"Addresses": []})
        stub.add_response("describe_network_interfaces", {"NetworkInterfaces": [shared]})
        found = audit_region(client, REGION)
    assert [(f.ip, f.kind, f.owner, f.eni) for f in found] == [
        ("198.51.100.7", "ec2-auto", "ec2 i-0web0000000000001", "eni-0web000000000001")
    ]

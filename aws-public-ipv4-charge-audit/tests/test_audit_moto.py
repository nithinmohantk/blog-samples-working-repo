"""Instances, Elastic IPs and NAT gateways, against moto 4.2.13 (January 2024)."""
import boto3
import pytest
from moto import mock_ec2

from ipv4_audit.audit import audit_region

REGION = "eu-west-1"
AMI = "ami-12c6146b"  # an image moto ships with


@pytest.fixture
def ec2():
    with mock_ec2():
        yield boto3.client("ec2", region_name=REGION)


def _public_subnet(ec2, cidr="10.0.1.0/24", az="eu-west-1a"):
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock=cidr, AvailabilityZone=az)["Subnet"]["SubnetId"]
    ec2.modify_subnet_attribute(SubnetId=subnet, MapPublicIpOnLaunch={"Value": True})
    return subnet


def _by_kind(found):
    out = {}
    for item in found:
        out.setdefault(item.kind, []).append(item)
    return out


def test_auto_assigned_instance_address_is_found_and_newly_charged(ec2):
    subnet = _public_subnet(ec2)
    instance = ec2.run_instances(ImageId=AMI, MinCount=1, MaxCount=1, SubnetId=subnet)["Instances"][0]
    found = audit_region(ec2, REGION)
    assert [(f.kind, f.owner, f.billing_operation, f.newly_charged) for f in found] == [
        ("ec2-auto", f"ec2 {instance['InstanceId']}", "RunInstances", True)
    ]


def test_idle_elastic_ip_was_already_charged(ec2):
    ec2.allocate_address(Domain="vpc")
    (found,) = audit_region(ec2, REGION)
    assert (found.kind, found.billing_operation, found.newly_charged) == ("eip-idle", "AllocateAddressVPC", False)


def test_first_eip_on_an_instance_is_new_the_second_is_not(ec2):
    subnet = _public_subnet(ec2)
    instance = ec2.run_instances(
        ImageId=AMI, MinCount=1, MaxCount=1,
        NetworkInterfaces=[{"DeviceIndex": 0, "SubnetId": subnet, "AssociatePublicIpAddress": False}],
    )["Instances"][0]
    second = ec2.create_network_interface(SubnetId=subnet)["NetworkInterface"]["NetworkInterfaceId"]
    ec2.attach_network_interface(NetworkInterfaceId=second, InstanceId=instance["InstanceId"], DeviceIndex=1)
    for eni_id in (instance["NetworkInterfaces"][0]["NetworkInterfaceId"], second):
        allocation = ec2.allocate_address(Domain="vpc")["AllocationId"]
        ec2.associate_address(AllocationId=allocation, NetworkInterfaceId=eni_id)
    found = [f for f in audit_region(ec2, REGION) if f.kind == "eip-in-use"]
    assert {f.owner for f in found} == {f"ec2 {instance['InstanceId']}"}
    assert sorted(f.newly_charged for f in found) == [False, True]


def test_nat_gateway_eip_is_attributed_to_the_gateway(ec2):
    subnet = _public_subnet(ec2)
    allocation = ec2.allocate_address(Domain="vpc")["AllocationId"]
    nat = ec2.create_nat_gateway(SubnetId=subnet, AllocationId=allocation)["NatGateway"]["NatGatewayId"]
    (found,) = audit_region(ec2, REGION)
    assert (found.kind, found.owner, found.newly_charged) == ("eip-in-use", f"nat {nat}", True)


def test_stopped_instance_loses_its_auto_assigned_address(ec2):
    subnet = _public_subnet(ec2)
    instance = ec2.run_instances(ImageId=AMI, MinCount=1, MaxCount=1, SubnetId=subnet)["Instances"][0]
    ec2.stop_instances(InstanceIds=[instance["InstanceId"]])
    assert audit_region(ec2, REGION) == []


def test_each_address_is_counted_once(ec2):
    subnet = _public_subnet(ec2)
    ec2.run_instances(ImageId=AMI, MinCount=3, MaxCount=3, SubnetId=subnet)
    nat_eip = ec2.allocate_address(Domain="vpc")["AllocationId"]
    ec2.create_nat_gateway(SubnetId=subnet, AllocationId=nat_eip)
    ec2.allocate_address(Domain="vpc")
    found = audit_region(ec2, REGION)
    assert len({f.ip for f in found}) == len(found) == 5
    assert {k: len(v) for k, v in _by_kind(found).items()} == {"ec2-auto": 3, "eip-in-use": 1, "eip-idle": 1}


def test_auto_assign_subnets_are_listed_and_the_switch_works(ec2):
    from ipv4_audit.audit import auto_assign_subnets
    subnet = _public_subnet(ec2)
    flagged = {s["subnet"] for s in auto_assign_subnets(ec2)}
    assert subnet in flagged
    ec2.modify_subnet_attribute(SubnetId=subnet, MapPublicIpOnLaunch={"Value": False})
    assert subnet not in {s["subnet"] for s in auto_assign_subnets(ec2)}
    instance = ec2.run_instances(ImageId=AMI, MinCount=1, MaxCount=1, SubnetId=subnet)["Instances"][0]
    assert "PublicIpAddress" not in instance

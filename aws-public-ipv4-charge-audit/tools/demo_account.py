"""Build a small, made-up production estate in moto and run the audit over it.

The estate is the kind of account the February 2024 change hits hardest: a VPC
built from the wizard defaults, with public subnets that auto-assign addresses.

    eu-west-1: 2 public subnets (auto-assign on), 4 web instances,
               1 bastion with an Elastic IP, 2 NAT gateways (one per AZ),
               2 Elastic IPs left over from an old migration
    us-east-1: 1 instance in the default VPC that someone forgot

Writes demo-addresses.csv and prints the summary for February 2024.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3  # noqa: E402
from moto import mock_ec2  # noqa: E402

AMI = "ami-12c6146b"


def build_estate(session) -> None:
    ec2 = session.client("ec2", region_name="eu-west-1")
    vpc = ec2.create_vpc(CidrBlock="10.20.0.0/16")["Vpc"]["VpcId"]
    subnets = []
    for cidr, az in (("10.20.0.0/24", "eu-west-1a"), ("10.20.1.0/24", "eu-west-1b")):
        subnet = ec2.create_subnet(VpcId=vpc, CidrBlock=cidr, AvailabilityZone=az)["Subnet"]["SubnetId"]
        ec2.modify_subnet_attribute(SubnetId=subnet, MapPublicIpOnLaunch={"Value": True})
        subnets.append(subnet)
        nat_eip = ec2.allocate_address(Domain="vpc")["AllocationId"]
        ec2.create_nat_gateway(SubnetId=subnet, AllocationId=nat_eip)
    for subnet in subnets:
        ec2.run_instances(ImageId=AMI, MinCount=2, MaxCount=2, SubnetId=subnet, InstanceType="t3.small")
    bastion = ec2.run_instances(
        ImageId=AMI, MinCount=1, MaxCount=1, InstanceType="t3.micro",
        NetworkInterfaces=[{"DeviceIndex": 0, "SubnetId": subnets[0], "AssociatePublicIpAddress": False}],
    )["Instances"][0]["InstanceId"]
    ec2.associate_address(AllocationId=ec2.allocate_address(Domain="vpc")["AllocationId"], InstanceId=bastion)
    for _ in range(2):
        ec2.allocate_address(Domain="vpc")  # left behind, idle

    session.client("ec2", region_name="us-east-1").run_instances(ImageId=AMI, MinCount=1, MaxCount=1)


def main(out_dir: Path) -> dict:
    from tools.audit_account import main as audit_main

    with mock_ec2():
        session = boto3.Session(region_name="eu-west-1", aws_access_key_id="testing",
                                aws_secret_access_key="testing")
        build_estate(session)
        return audit_main(["--regions", "eu-west-1", "us-east-1", "--month", "2024-02",
                           "--out", str(out_dir / "demo-addresses.csv")], session=session)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("."))

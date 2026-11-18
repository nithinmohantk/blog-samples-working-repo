"""Print the IPv4-related options the installed botocore model offers.

Run with the January 2024 packages to see what existed on that date.
"""
import json

import botocore
import botocore.session

session = botocore.session.get_session()
ec2 = session.get_service_model("ec2")
print(json.dumps({
    "botocore": botocore.__version__,
    "elbv2 IpAddressType": session.get_service_model("elbv2").shape_for("IpAddressType").enum,
    "ec2 NetworkInterfaceType has nat_gateway": "nat_gateway" in ec2.shape_for("NetworkInterfaceType").enum,
    "ec2 NetworkInterfaceType has natGateway": "natGateway" in ec2.shape_for("NetworkInterfaceType").enum,
    "ec2 ModifySubnetAttribute has EnableDns64":
        "EnableDns64" in ec2.operation_model("ModifySubnetAttribute").input_shape.members,
    "lambda VpcConfig has Ipv6AllowedForDualStack":
        "Ipv6AllowedForDualStack" in session.get_service_model("lambda").shape_for("VpcConfig").members,
    "ecs AssignPublicIp": session.get_service_model("ecs").shape_for("AssignPublicIp").enum,
}, indent=2))

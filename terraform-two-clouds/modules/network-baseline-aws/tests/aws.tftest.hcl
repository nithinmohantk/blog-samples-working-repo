# What only the AWS implementation can be asked: the cloud-specific controls.

# --- mock block, kept in step with the contract by contract/render.py ---
# The AWS provider validates the format of some values even when it is mocked: a flow log
# destination has to look like an ARN. Give the mock a well-formed one.
mock_provider "aws" {
  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::netlogs-mock"
    }
  }
}
# --- mock block, kept in step with the contract by contract/render.py ---

variables {
  name          = "records"
  environment   = "dev"
  region        = "eu-west-1"
  address_space = "10.40.0.0/20"
}

run "subnets_never_assign_public_addresses" {
  command = plan

  assert {
    condition     = alltrue([for subnet in aws_subnet.private : subnet.map_public_ip_on_launch == false])
    error_message = "Private subnets must not assign public IP addresses."
  }
}

run "resources_are_named_for_the_workload" {
  command = plan

  assert {
    condition     = aws_vpc.this.tags["Name"] == "vpc-records-dev" && aws_subnet.private["private-1"].tags["Name"] == "snet-records-dev-private-1"
    error_message = "The VPC and subnets must carry Name tags built from the workload and environment."
  }
}

run "flow_logs_capture_all_traffic_to_s3" {
  command = plan

  assert {
    condition     = aws_flow_log.vpc.traffic_type == "ALL" && aws_flow_log.vpc.log_destination_type == "s3"
    error_message = "Flow logs must capture accepted and rejected traffic and deliver to S3."
  }
}

run "log_bucket_is_encrypted_private_and_expires" {
  command = plan

  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.logs.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms"
    error_message = "The log bucket must use SSE-KMS."
  }

  assert {
    condition     = aws_s3_bucket_public_access_block.logs.block_public_policy && aws_s3_bucket_public_access_block.logs.restrict_public_buckets
    error_message = "The log bucket must block public access."
  }

  assert {
    condition     = aws_s3_bucket_lifecycle_configuration.logs.rule[0].expiration[0].days == 365
    error_message = "Logs must expire after the retention period."
  }
}

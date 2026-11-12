# AWS implementation of the network baseline contract: a VPC with private subnets, a default
# security group that allows nothing, and VPC flow logs delivered to an encrypted S3 bucket.

resource "aws_vpc" "this" {
  cidr_block           = var.address_space
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.tags, { Name = "vpc-${local.prefix}" })
}

resource "aws_subnet" "private" {
  for_each = local.subnets

  vpc_id                  = aws_vpc.this.id
  cidr_block              = each.value
  map_public_ip_on_launch = false
  tags                    = merge(local.tags, { Name = "snet-${local.prefix}-${each.key}" })
}

# Adopting the default security group with no rules removes its allow-all defaults.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "default-deny-${local.prefix}" })
}

resource "aws_s3_bucket" "logs" {
  bucket_prefix = "netlogs-${local.prefix}-"
  tags          = local.tags
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket = aws_s3_bucket.logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "expire-network-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = var.log_retention_days
    }
  }
}

resource "aws_flow_log" "vpc" {
  vpc_id               = aws_vpc.this.id
  traffic_type         = "ALL"
  log_destination_type = "s3"
  log_destination      = aws_s3_bucket.logs.arn
  tags                 = local.tags
}

locals {
  network_id   = aws_vpc.this.id
  subnet_ids   = { for name, subnet in aws_subnet.private : name => subnet.id }
  log_store_id = aws_s3_bucket.logs.arn
}

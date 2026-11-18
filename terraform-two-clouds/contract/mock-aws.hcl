# The AWS provider validates the format of some values even when it is mocked: a flow log
# destination has to look like an ARN. Give the mock a well-formed one.
mock_provider "aws" {
  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::netlogs-mock"
    }
  }
}

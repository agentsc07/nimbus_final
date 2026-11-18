# Shared mocked AWS values for `terraform test` (offline, no credentials). The provider validates ARNs, so the
# mocked ones must look real.

mock_data "aws_caller_identity" {
  defaults = { account_id = "123456789012" }
}

mock_data "aws_ecr_image" {
  defaults = { image_digest = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" }
}

mock_resource "aws_lb" {
  defaults = { arn = "arn:aws:elasticloadbalancing:ap-south-1:123456789012:loadbalancer/app/nimbus-ds252-alb/0123456789abcdef" }
}

mock_resource "aws_lb_target_group" {
  defaults = { arn = "arn:aws:elasticloadbalancing:ap-south-1:123456789012:targetgroup/nimbus-ds252-tg/0123456789abcdef" }
}

mock_resource "aws_lb_listener" {
  defaults = { arn = "arn:aws:elasticloadbalancing:ap-south-1:123456789012:listener/app/nimbus-ds252-alb/0123456789abcdef/0123456789abcdef" }
}

mock_resource "aws_sqs_queue" {
  defaults = { arn = "arn:aws:sqs:ap-south-1:123456789012:nimbus-ds252-escalations" }
}

mock_resource "aws_iam_role" {
  defaults = { arn = "arn:aws:iam::123456789012:role/nimbus-ds252-role" }
}

mock_resource "aws_ecs_task_definition" {
  defaults = { arn = "arn:aws:ecs:ap-south-1:123456789012:task-definition/nimbus-ds252-app:1" }
}

mock_resource "aws_ecs_cluster" {
  defaults = {
    id  = "arn:aws:ecs:ap-south-1:123456789012:cluster/nimbus-ds252-cluster"
    arn = "arn:aws:ecs:ap-south-1:123456789012:cluster/nimbus-ds252-cluster"
  }
}

mock_resource "aws_secretsmanager_secret" {
  defaults = { arn = "arn:aws:secretsmanager:ap-south-1:123456789012:secret:nimbus-ds252-app-secrets-AbCdEf" }
}

mock_resource "aws_kms_key" {
  defaults = {
    arn    = "arn:aws:kms:ap-south-1:123456789012:key/01234567-89ab-cdef-0123-456789abcdef"
    key_id = "01234567-89ab-cdef-0123-456789abcdef"
  }
}

mock_resource "aws_s3_bucket" {
  defaults = { arn = "arn:aws:s3:::nimbus-ds252-mock" }
}

mock_resource "aws_cloudwatch_log_group" {
  defaults = { arn = "arn:aws:logs:ap-south-1:123456789012:log-group:/mock" }
}

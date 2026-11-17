# Red-team issue #20: the service image is pinned by digest and the container may only send HTTPS.
# Runs offline against a mocked AWS provider (no credentials, nothing created):
#   cd infra/terraform && terraform init && terraform test

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_ecr_image" {
    defaults = { image_digest = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" }
  }
  # The provider validates these ARNs, so the mocked ones must look real.
  mock_resource "aws_lb" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-south-1:123456789012:loadbalancer/app/nimbus-ds252-alb/0123456789abcdef" }
  }
  mock_resource "aws_lb_target_group" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-south-1:123456789012:targetgroup/nimbus-ds252-tg/0123456789abcdef" }
  }
  mock_resource "aws_sqs_queue" {
    defaults = { arn = "arn:aws:sqs:ap-south-1:123456789012:nimbus-ds252-escalations" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/nimbus-ds252-role" }
  }
  mock_resource "aws_lb_listener" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-south-1:123456789012:listener/app/nimbus-ds252-alb/0123456789abcdef/0123456789abcdef" }
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
}

run "latest_tag_is_refused" {
  command = plan
  variables { app_image_tag = "latest" }
  expect_failures = [var.app_image_tag]
}

run "image_by_tag_is_refused" {
  command = plan
  variables { app_image = "123456789012.dkr.ecr.ap-south-1.amazonaws.com/nimbus-app:latest" }
  expect_failures = [var.app_image]
}

run "no_image_stops_the_plan" {
  command         = plan
  expect_failures = [aws_ecs_task_definition.app]
}

run "commit_tag_deploys_by_digest_with_https_only_egress" {
  command = apply
  variables { app_image_tag = "3f2a1b9c0d1e" }

  assert {
    condition     = endswith(jsondecode(aws_ecs_task_definition.app.container_definitions)[0].image, "@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    error_message = "the task definition must name the image by digest"
  }
  assert {
    condition     = aws_ecr_repository.app.image_tag_mutability == "IMMUTABLE"
    error_message = "ECR tags must be immutable"
  }
  assert {
    condition     = alltrue([for rule in aws_security_group.app.egress : rule.protocol == "tcp" && rule.from_port == 443 && rule.to_port == 443])
    error_message = "the app security group may only allow HTTPS out"
  }
}

# Red-team issue #20: the service image is pinned by digest and the container may only send HTTPS.
# Runs offline against a mocked AWS provider (no credentials, nothing created):
#   cd infra/terraform && terraform init && terraform test

mock_provider "aws" {
  source = "./tests/mocks"
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

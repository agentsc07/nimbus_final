variable "aws_region" {
  description = "Single AWS region (PRD Sec. 2: AWS, single region, Terraform)."
  type        = string
  default     = "ap-south-1" # Mumbai; IISc is in Bengaluru
}

variable "project_name" {
  description = "Team project slug used in every resource name."
  type        = string
  default     = "ds252"
}

variable "app_image" {
  description = "Container image for the Fargate service. Pass the immutable reference scripts/build_push.sh prints (`<repo>:<git-sha>` or `<repo>@sha256:...`). Empty (the default) uses `<repo>:latest`, which does not redeploy anything when a new `latest` is pushed: the task definition text does not change, so ECS keeps running the old image."
  type        = string
  default     = ""
}

variable "egress_mode" {
  description = "How the Fargate task reaches the internet (image pull, Bedrock, Secrets Manager, DynamoDB): public_ip (cheapest: internet gateway plus a public IP per task) or none (no route out; supply NAT or VPC endpoints yourself)."
  type        = string
  default     = "public_ip"

  validation {
    condition     = contains(["public_ip", "none"], var.egress_mode)
    error_message = "egress_mode must be public_ip or none."
  }
}

variable "alert_email" {
  description = "E-mail for budget alerts and for the missed check-in alarm (SNS topic + e-mail subscription, which the recipient must confirm). Empty disables the budget and the SNS topic; the alarm then still changes state but notifies nobody."
  type        = string
  default     = ""
}

variable "expected_clusters" {
  description = "How many edge clusters should be healthy. The missed check-in alarm fires when the emitted Nimbus HealthyClusters metric drops below this (hospital_sim6 has two: east-wing and west-wing)."
  type        = number
  default     = 2
}

variable "metrics_pack" {
  description = "Pack name the container runs (Dockerfile NIMBUS_PACK). The service emits its CloudWatch metrics with a Pack dimension, so the alarm must use the same value to see them."
  type        = string
  default     = "hospital_sim6"
}

variable "budget_usd" {
  description = "Monthly budget in USD that the 50/80/100% alerts are measured against."
  type        = number
  default     = 50
}

variable "bedrock_model_id" {
  description = "Bedrock model or inference-profile id the orchestrator calls (NIMBUS_BEDROCK_MODEL)."
  type        = string
  default     = "apac.amazon.nova-lite-v1:0"
}

variable "nimbus_mode" {
  description = "Evaluation configuration the service runs: C1 (proposed), C2 (cloud-only) or C3 (no LLM)."
  type        = string
  default     = "C1"
}

variable "knowledge_base_id" {
  description = "Bedrock Knowledge Base id for rule retrieval (FR-19). Empty keeps keyword retrieval from the pack."
  type        = string
  default     = ""
}

variable "ecs_target_url" {
  description = "Unused by this configuration (API Gateway integrates with the internal ALB listener through the VPC link). Kept so existing tfvars files still load."
  type        = string
  default     = "http://127.0.0.1:8000"
}

variable "assign_public_ip" {
  description = "Override for the Fargate task's public IP. Null (the default) derives it from egress_mode: true for public_ip, false for none. Without a public IP and without NAT or VPC endpoints the task cannot pull its image or reach Bedrock, Secrets Manager or DynamoDB. Inbound traffic is limited by the app security group (internal ALB only) either way."
  type        = bool
  default     = null
}

variable "allowed_ingress_cidr_blocks" {
  description = "Unused by this configuration: inbound port 8000 is allowed only from the internal ALB's security group (aws_security_group.app). Kept so existing tfvars files still load."
  type        = list(string)
  default     = ["10.20.0.0/16"]
}

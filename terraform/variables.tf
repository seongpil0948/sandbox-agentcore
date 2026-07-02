variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
  default     = "sandbox-agentcore"
}

variable "orchestrator_name" {
  description = "Name for the orchestrator runtime."
  type        = string
  default     = "orchestrator"
}

variable "supervisor_name" {
  description = "Name for the HR supervisor runtime."
  type        = string
  default     = "supervisor_hr"
}

variable "leaf_name" {
  description = "Name for the cert leaf runtime."
  type        = string
  default     = "leaf_cert"
}

variable "memory_name" {
  description = "Name for the shared memory resource."
  type        = string
  default     = "agent_memory"
}

variable "region" {
  description = "AWS region for AgentCore runtime."
  type        = string
  default     = "us-east-1"
}

variable "network_mode" {
  description = "Network mode for AgentCore runtimes."
  type        = string
  default     = "PUBLIC"

  validation {
    condition     = contains(["PUBLIC", "PRIVATE"], var.network_mode)
    error_message = "Network mode must be PUBLIC or PRIVATE."
  }
}

variable "runtime_image_uri" {
  description = "Container image URI for AgentCore runtime. Leave empty to use the Terraform-managed ECR repo + image_tag."
  type        = string
  default     = ""
}

variable "image_tag" {
  description = "Container image tag used when runtime_image_uri is not set."
  type        = string
  default     = "latest"
}

variable "ecr_repository_name" {
  description = "ECR repository name for runtime image storage."
  type        = string
  default     = "sandbox-agentcore"
}

variable "common_tags" {
  description = "Common tags applied to shared resources."
  type        = map(string)
  default     = {}
}

variable "environment" {
  description = "Deployment environment tag (e.g. dev, staging, prod)."
  type        = string
  default     = "dev"
}

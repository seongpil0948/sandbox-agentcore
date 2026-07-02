output "agent_runtime_id" {
  description = "ID of the orchestrator AgentCore runtime."
  value       = aws_bedrockagentcore_agent_runtime.orchestrator.agent_runtime_id
}

output "agent_runtime_arn" {
  description = "ARN of the orchestrator AgentCore runtime."
  value       = aws_bedrockagentcore_agent_runtime.orchestrator.agent_runtime_arn
}

output "agent_runtime_version" {
  description = "Version of the orchestrator AgentCore runtime."
  value       = aws_bedrockagentcore_agent_runtime.orchestrator.agent_runtime_version
}

output "agent_execution_role_arn" {
  description = "ARN of the orchestrator AgentCore runtime execution role."
  value       = aws_iam_role.orchestrator_runtime.arn
}

output "orchestrator_runtime_arn" {
  description = "ARN of the orchestrator runtime."
  value       = aws_bedrockagentcore_agent_runtime.orchestrator.agent_runtime_arn
}

output "supervisor_runtime_arn" {
  description = "ARN of the supervisor runtime."
  value       = aws_bedrockagentcore_agent_runtime.supervisor.agent_runtime_arn
}

output "leaf_runtime_arn" {
  description = "ARN of the leaf runtime."
  value       = aws_bedrockagentcore_agent_runtime.leaf.agent_runtime_arn
}

output "runtime_ecr_repository_arn" {
  description = "ARN of the Terraform-managed ECR repository for runtime images."
  value       = aws_ecr_repository.runtime.arn
}

output "runtime_ecr_repository_url" {
  description = "URL of the Terraform-managed ECR repository for runtime images."
  value       = aws_ecr_repository.runtime.repository_url
}

output "effective_runtime_image_uri" {
  description = "Container image URI used by the runtime (custom runtime_image_uri or managed ECR URL + image_tag)."
  value       = local.runtime_image_uri
}

output "memory_id" {
  description = "ID of the shared AgentCore memory resource."
  value       = aws_bedrockagentcore_memory.memory.id
}

output "memory_arn" {
  description = "ARN of the shared AgentCore memory resource."
  value       = aws_bedrockagentcore_memory.memory.arn
}

output "source_bucket" {
  description = "S3 bucket holding the CodeBuild Docker source archive."
  value       = aws_s3_bucket.agent_source.id
}

output "codebuild_project" {
  description = "CodeBuild project that builds and pushes the runtime image."
  value       = aws_codebuild_project.runtime_image.name
}

output "invoke_command" {
  description = "Ready-to-run command to invoke the orchestrator runtime."
  value = join(" ", [
    "uv run python apps/client.py",
    "--agent-runtime-arn ${aws_bedrockagentcore_agent_runtime.orchestrator.agent_runtime_arn}",
    "--region ${data.aws_region.current.region}",
    "--session-id sandbox-agentcore-test-session-000000000001",
    "--prompt 'Is the certificate for api.example.com still valid?'",
  ])
}

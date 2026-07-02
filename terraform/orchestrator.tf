# ============================================================================
# Orchestrator Agent Runtime - Root entrypoint
# ============================================================================

resource "aws_bedrockagentcore_agent_runtime" "orchestrator" {
  agent_runtime_name = replace("${var.name_prefix}_${var.orchestrator_name}", "-", "_")
  role_arn           = aws_iam_role.orchestrator_runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = local.runtime_image_uri
    }
  }

  network_configuration {
    network_mode = var.network_mode
  }

  environment_variables = {
    AGENT_ROLE         = "orchestrator"
    APP_ENV            = var.environment
    AWS_REGION         = data.aws_region.current.region
    AWS_DEFAULT_REGION = data.aws_region.current.region
    SUPERVISOR_ARN     = aws_bedrockagentcore_agent_runtime.supervisor.agent_runtime_arn
  }

  depends_on = [
    aws_bedrockagentcore_agent_runtime.supervisor,
    aws_iam_role_policy.orchestrator_runtime,
    aws_iam_role_policy_attachment.orchestrator_managed,
  ]
}
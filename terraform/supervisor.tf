# ============================================================================
# Supervisor Agent Runtime - HR and identity
# ============================================================================

resource "aws_bedrockagentcore_agent_runtime" "supervisor" {
  agent_runtime_name = replace("${var.name_prefix}_${var.supervisor_name}", "-", "_")
  role_arn           = aws_iam_role.supervisor_runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = local.runtime_image_uri
    }
  }

  network_configuration {
    network_mode = var.network_mode
  }

  environment_variables = {
    AGENT_ROLE         = "supervisor"
    APP_ENV            = var.environment
    AWS_REGION         = data.aws_region.current.region
    AWS_DEFAULT_REGION = data.aws_region.current.region
    LEAF_ARN           = aws_bedrockagentcore_agent_runtime.leaf.agent_runtime_arn
    MEMORY_ID          = aws_bedrockagentcore_memory.memory.id
  }

  depends_on = [
    aws_bedrockagentcore_agent_runtime.leaf,
    aws_iam_role_policy.supervisor_runtime,
    aws_iam_role_policy_attachment.supervisor_managed,
    aws_bedrockagentcore_memory.memory,
  ]
}

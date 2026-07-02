# ============================================================================
# Leaf Agent Runtime - Certificate specialist
# ============================================================================

resource "aws_bedrockagentcore_agent_runtime" "leaf" {
  agent_runtime_name = replace("${var.name_prefix}_${var.leaf_name}", "-", "_")
  role_arn           = aws_iam_role.agentcore_runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = local.runtime_image_uri
    }
  }

  network_configuration {
    network_mode = var.network_mode
  }

  environment_variables = {
    AGENT_ROLE         = "leaf"
    APP_ENV            = var.environment
    AWS_REGION         = data.aws_region.current.region
    AWS_DEFAULT_REGION = data.aws_region.current.region
    MEMORY_ID          = aws_bedrockagentcore_memory.memory.id
  }

  depends_on = [
    null_resource.build_image,
    aws_iam_role_policy.agentcore_runtime,
    aws_iam_role_policy_attachment.agentcore_managed,
    aws_bedrockagentcore_memory.memory,
  ]
}

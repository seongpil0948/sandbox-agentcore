# ==========================================================================
# Shared Memory - Optional persistent context scaffold
# ============================================================================

resource "aws_bedrockagentcore_memory" "memory" {
  name                  = "${replace(var.name_prefix, "-", "_")}_${var.memory_name}"
  description           = "Shared memory for ${var.name_prefix} agent hierarchy"
  event_expiry_duration = 30

  tags = merge(
    var.common_tags,
    {
      Name   = "${var.name_prefix}-memory"
      Module = "AgentCore-Tools"
      Tool   = "Memory"
    }
  )
}

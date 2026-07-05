"""Render Terraform proposals for IAM permission gaps.

Offline advisory helper: given a principal's detected IAM access gaps, emit HCL ``module`` blocks
that use the community ``terraform-aws-modules/iam/aws`` module to close them. Presentation only —
the agent performs no live change; a human reviews and applies the proposal via their IaC pipeline.

Reference: https://registry.terraform.io/modules/terraform-aws-modules/iam/aws/latest
"""

from __future__ import annotations

from apps.mock_data import IamAccessRequirement

IAM_MODULE_SOURCE_PREFIX = "terraform-aws-modules/iam/aws//modules/"
IAM_MODULE_VERSION = "~> 6.0"

_HEADER = (
    "# Proposed by sandbox-agentcore account-manager (advisory — review before apply).\n"
    "# Module: terraform-aws-modules/iam/aws\n"
    "#   https://registry.terraform.io/modules/terraform-aws-modules/iam/aws/latest\n"
    "# Closes the detected IAM permission gaps below. The agent performs no live change.\n"
)


def _module_label(principal: str, name: str) -> str:
    """Return a Terraform-safe module label (identifiers cannot contain '.' or '-')."""
    slug = f"{principal}_{name}".replace(".", "_").replace("-", "_")
    return f"iam_{slug}"


def _hcl_str_list(items: tuple[str, ...]) -> str:
    """Render a tuple of strings as a single-line HCL list literal."""
    return "[" + ", ".join(f'"{item}"' for item in items) + "]"


def _tags(principal: str) -> str:
    return (
        "  tags = {\n"
        '    Terraform = "true"\n'
        f'    Principal = "{principal}"\n'
        '    ManagedBy = "sandbox-agentcore"\n'
        "  }\n"
    )


def _render_read_only_policy(requirement: IamAccessRequirement) -> str:
    return (
        f'module "{_module_label(requirement.principal, requirement.name)}" {{\n'
        f'  source  = "{IAM_MODULE_SOURCE_PREFIX}iam-read-only-policy"\n'
        f'  version = "{IAM_MODULE_VERSION}"\n'
        "\n"
        f'  name        = "{requirement.principal}-{requirement.name}"\n'
        '  path        = "/"\n'
        f'  description = "{requirement.description}"\n'
        "\n"
        f"  allowed_services = {_hcl_str_list(requirement.allowed_services)}\n"
        "\n"
        f"{_tags(requirement.principal)}"
        "}\n"
    )


def _render_policy(requirement: IamAccessRequirement) -> str:
    if requirement.kind == "assumable_role":
        actions: tuple[str, ...] = ("sts:AssumeRole",)
        resources = requirement.assume_role_arns
    else:
        actions = requirement.actions
        resources = requirement.resources
    return (
        f'module "{_module_label(requirement.principal, requirement.name)}" {{\n'
        f'  source  = "{IAM_MODULE_SOURCE_PREFIX}iam-policy"\n'
        f'  version = "{IAM_MODULE_VERSION}"\n'
        "\n"
        f'  name        = "{requirement.principal}-{requirement.name}"\n'
        '  path        = "/"\n'
        f'  description = "{requirement.description}"\n'
        "\n"
        "  policy = jsonencode({\n"
        '    Version = "2012-10-17"\n'
        "    Statement = [\n"
        "      {\n"
        '        Effect   = "Allow"\n'
        f"        Action   = {_hcl_str_list(actions)}\n"
        f"        Resource = {_hcl_str_list(resources)}\n"
        "      }\n"
        "    ]\n"
        "  })\n"
        "\n"
        f"{_tags(requirement.principal)}"
        "}\n"
    )


def render_requirement(requirement: IamAccessRequirement) -> str:
    """Render one IAM access requirement as an HCL module block."""
    if requirement.kind == "read_only_policy":
        return _render_read_only_policy(requirement)
    return _render_policy(requirement)


def render_iam_terraform(requirements: list[IamAccessRequirement]) -> str:
    """Render a full Terraform proposal (header + one module block per requirement)."""
    blocks = [_HEADER, *(render_requirement(requirement) for requirement in requirements)]
    return "\n".join(blocks).rstrip() + "\n"

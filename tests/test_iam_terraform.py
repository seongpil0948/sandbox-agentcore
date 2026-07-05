from __future__ import annotations

from apps.agents.iam_terraform import (
    IAM_MODULE_SOURCE_PREFIX,
    IAM_MODULE_VERSION,
    render_iam_terraform,
    render_requirement,
)
from apps.mock_data import IamAccessRequirement, iam_access_gaps


def _read_only() -> IamAccessRequirement:
    return IamAccessRequirement(
        principal="new.engineer",
        name="base-engineering-readonly",
        kind="read_only_policy",
        description="Base engineering read-only access",
        satisfied=False,
        allowed_services=("ec2", "s3"),
    )


def _custom_policy() -> IamAccessRequirement:
    return IamAccessRequirement(
        principal="deploy-bot",
        name="eks-rollout",
        kind="policy",
        description="Roll out EKS deployments",
        satisfied=False,
        actions=("eks:DescribeCluster",),
        resources=("*",),
    )


def _assume_role() -> IamAccessRequirement:
    return IamAccessRequirement(
        principal="new.engineer",
        name="dev-deployer-assume",
        kind="assumable_role",
        description="Assume the dev-deployer role",
        satisfied=False,
        assume_role_arns=("arn:aws:iam::444455556666:role/dev-deployer",),
    )


def test_read_only_policy_uses_read_only_submodule() -> None:
    block = render_requirement(_read_only())
    assert f'source  = "{IAM_MODULE_SOURCE_PREFIX}iam-read-only-policy"' in block
    assert f'version = "{IAM_MODULE_VERSION}"' in block
    assert 'allowed_services = ["ec2", "s3"]' in block
    # Terraform module label must be identifier-safe (no dots/dashes).
    assert 'module "iam_new_engineer_base_engineering_readonly"' in block


def test_custom_policy_uses_iam_policy_submodule() -> None:
    block = render_requirement(_custom_policy())
    assert f'source  = "{IAM_MODULE_SOURCE_PREFIX}iam-policy"' in block
    assert 'Action   = ["eks:DescribeCluster"]' in block
    assert 'Resource = ["*"]' in block


def test_assume_role_grants_sts_assume_role_on_target_arns() -> None:
    block = render_requirement(_assume_role())
    assert f'source  = "{IAM_MODULE_SOURCE_PREFIX}iam-policy"' in block
    assert 'Action   = ["sts:AssumeRole"]' in block
    assert 'Resource = ["arn:aws:iam::444455556666:role/dev-deployer"]' in block


def test_render_iam_terraform_includes_header_and_all_blocks() -> None:
    hcl = render_iam_terraform([_read_only(), _custom_policy()])
    assert "terraform-aws-modules/iam/aws" in hcl
    assert "advisory" in hcl.lower()
    assert hcl.count("module ") == 2


def test_new_engineer_gaps_exclude_satisfied_requirements() -> None:
    # deploy-bot has one satisfied (ecr-push) and one unsatisfied (eks-rollout) requirement.
    gap_names = {gap.name for gap in iam_access_gaps("deploy-bot")}
    assert gap_names == {"eks-rollout"}

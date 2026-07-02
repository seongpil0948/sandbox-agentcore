---
description: "Use when creating or modifying Terraform in sandbox-agentcore (runtime resources, IAM roles/policies, variables, outputs, or tf validation flow). Focuses on minimal AgentCore runtime scaffolding, least privilege, and plan/validate-first changes."
applyTo: "terraform/**/*.tf"
---
# Terraform Sandbox Rules

Baseline scope, IAM baseline, and the reference-reading workflow are defined in `minimal-agentcore-sandbox.instructions.md` and `reference-first-agentcore.instructions.md`. This file adds the Terraform-specific rules.

- Keep Terraform minimal: one AgentCore runtime scaffold plus its execution role/policy, variables, and outputs. No platform expansion.
- Least privilege beyond the baseline (template: samples `04-infrastructure-as-code/terraform/basic-runtime/iam.tf`):
  - replace `service:*` action wildcards (e.g. `cloudformation:*`, `s3:*`, `sagemaker:*`, `bedrock-agentcore:*`) with the specific actions actually required; keep a wildcard only with documented, approved justification
  - scope `Resource` to concrete ARNs instead of `"*"` — model invoke to `foundation-model/*`; logs to `/aws/bedrock-agentcore/runtimes/*`; ECR pull to the repo ARN (note: `ecr:GetAuthorizationToken`, X-Ray, and `cloudwatch:PutMetricData` legitimately require `"*"`)
  - the runtime execution role must trust `bedrock-agentcore.amazonaws.com` with `aws:SourceAccount`/`aws:SourceArn` conditions, not `sagemaker`/`bedrock`
- Preserve the Terraform contract unless asked to change it:
  - keep provider constraints compatible with repo defaults (`hashicorp/aws ~> 6.21`, terraform `>= 1.6.0`)
  - prefer variable-driven values over hardcoded account/region/image specifics
  - keep outputs small and focused (e.g. `agent_runtime_arn`)
- Validate before completion:
  - run `make tf-validate`
  - run `terraform -chdir=terraform plan` once initialized and `runtime_image_uri` is set
  - if validate or plan cannot run, state why and what remains unverified
- In change summaries: what resource/policy behavior changed, why it is needed, and which reference(s) informed it.

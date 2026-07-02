# ============================================================================
# S3 source bucket - Docker build context for CodeBuild
# ============================================================================
# CodeBuild reads the agent source (Dockerfile + apps/ + pyproject.toml) from
# this bucket, builds the ARM64 runtime image, and pushes it to ECR.

resource "aws_s3_bucket" "agent_source" {
  bucket_prefix = "${var.name_prefix}-src-"
  force_destroy = true

  tags = merge(var.common_tags, {
    Name    = "${var.name_prefix}-agent-source"
    Purpose = "CodeBuild source for AgentCore runtime image"
  })
}

resource "aws_s3_bucket_public_access_block" "agent_source" {
  bucket = aws_s3_bucket.agent_source.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "agent_source" {
  bucket = aws_s3_bucket.agent_source.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Zip the repo root as the Docker build context. Heavy/irrelevant paths are
# excluded so the archive stays small and deterministic; archive_file skips an
# excluded directory and its whole subtree.
data "archive_file" "agent_source" {
  type        = "zip"
  source_dir  = "${path.module}/.."
  output_path = "${path.module}/.terraform/agent-source.zip"

  excludes = [
    ".git",
    ".venv",
    ".terraform",
    "terraform",
    "tests",
    "doc",
    ".github",
    ".vscode",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
    "apps/__pycache__",
    "apps/agents/__pycache__",
  ]
}

resource "aws_s3_object" "agent_source" {
  bucket = aws_s3_bucket.agent_source.id
  key    = "agent-source-${data.archive_file.agent_source.output_md5}.zip"
  source = data.archive_file.agent_source.output_path
  etag   = data.archive_file.agent_source.output_md5

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-agent-source"
    MD5  = data.archive_file.agent_source.output_md5
  })
}

# ============================================================================
# CodeBuild - Build and push the ARM64 AgentCore runtime image
# ============================================================================

resource "aws_codebuild_project" "runtime_image" {
  name          = "${var.name_prefix}-runtime-build"
  description   = "Build the ARM64 AgentCore runtime image for ${var.name_prefix}"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 30

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_LARGE"
    image                       = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
    type                        = "ARM_CONTAINER"
    privileged_mode             = true
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = data.aws_region.current.region
    }

    environment_variable {
      name  = "AWS_ACCOUNT_ID"
      value = data.aws_caller_identity.current.id
    }

    environment_variable {
      name  = "IMAGE_REPO_NAME"
      value = aws_ecr_repository.runtime.name
    }

    environment_variable {
      name  = "IMAGE_TAG"
      value = var.image_tag
    }
  }

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.agent_source.id}/${aws_s3_object.agent_source.key}"
    buildspec = file("${path.module}/buildspec.yml")
  }

  logs_config {
    cloudwatch_logs {
      group_name = "/aws/codebuild/${var.name_prefix}-runtime-build"
    }
  }

  tags = merge(var.common_tags, {
    Name   = "${var.name_prefix}-runtime-build"
    Module = "CodeBuild"
  })

  depends_on = [aws_iam_role_policy.codebuild]
}

# ============================================================================
# Image build trigger - run CodeBuild during apply, before runtime creation
# ============================================================================
# Only runs when no explicit runtime_image_uri is provided (managed-image path).
# This makes `terraform apply` self-contained: the image is built and pushed to
# ECR before the AgentCore runtimes that consume it are created.

# Give freshly created CodeBuild IAM permissions time to propagate.
resource "time_sleep" "wait_for_codebuild_iam" {
  count           = local.build_managed_image ? 1 : 0
  create_duration = "30s"

  depends_on = [
    aws_iam_role_policy.codebuild,
    aws_codebuild_project.runtime_image,
    aws_s3_object.agent_source,
  ]
}

resource "null_resource" "build_image" {
  count = local.build_managed_image ? 1 : 0

  triggers = {
    source_hash = data.archive_file.agent_source.output_md5
    image_tag   = var.image_tag
    project     = aws_codebuild_project.runtime_image.name
  }

  provisioner "local-exec" {
    command = join(" ", [
      "bash",
      "\"${path.module}/scripts/build-image.sh\"",
      aws_codebuild_project.runtime_image.name,
      data.aws_region.current.region,
      aws_ecr_repository.runtime.name,
      var.image_tag,
      aws_ecr_repository.runtime.repository_url,
    ])
  }

  depends_on = [time_sleep.wait_for_codebuild_iam]
}

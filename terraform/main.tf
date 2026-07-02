data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

resource "aws_ecr_repository" "runtime" {
  name                 = var.ecr_repository_name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Keep the repository tidy - retain only the most recent images.
resource "aws_ecr_lifecycle_policy" "runtime" {
  repository = aws_ecr_repository.runtime.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

locals {
  # When no explicit image URI is supplied, Terraform builds and pushes the
  # image to the managed ECR repository during apply (see build.tf).
  build_managed_image = trimspace(var.runtime_image_uri) == ""
  runtime_image_uri   = local.build_managed_image ? "${aws_ecr_repository.runtime.repository_url}:${var.image_tag}" : var.runtime_image_uri
}

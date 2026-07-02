#!/usr/bin/env bash
# ============================================================================
# Build and verify the AgentCore runtime image via CodeBuild.
# Called by Terraform (null_resource.build_image) during `terraform apply`.
#
# Args:
#   $1 CodeBuild project name
#   $2 AWS region
#   $3 ECR repository name
#   $4 Image tag
#   $5 ECR repository URL
# ============================================================================
set -euo pipefail

PROJECT_NAME="$1"
REGION="$2"
REPO_NAME="$3"
IMAGE_TAG="$4"
REPO_URL="$5"

echo "[INFO] Starting CodeBuild project: $PROJECT_NAME"
echo "[INFO] Target image: $REPO_URL:$IMAGE_TAG"

BUILD_ID="$(aws codebuild start-build \
  --project-name "$PROJECT_NAME" \
  --region "$REGION" \
  --query 'build.id' \
  --output text)"

echo "[INFO] Build started: $BUILD_ID"
echo "[INFO] Waiting for build to complete (typically 5-10 minutes)..."

ATTEMPT=0
MAX_ATTEMPTS=90 # 15 minutes (90 * 10s)
STATUS="IN_PROGRESS"

while [ "$ATTEMPT" -lt "$MAX_ATTEMPTS" ]; do
  ATTEMPT=$((ATTEMPT + 1))

  STATUS="$(aws codebuild batch-get-builds \
    --ids "$BUILD_ID" \
    --region "$REGION" \
    --query 'builds[0].buildStatus' \
    --output text 2>/dev/null || echo "IN_PROGRESS")"

  if [ "$STATUS" != "IN_PROGRESS" ]; then
    break
  fi

  if [ $((ATTEMPT % 6)) -eq 0 ]; then
    echo "[INFO] Build in progress... ($((ATTEMPT / 6)) min elapsed)"
  fi

  sleep 10
done

if [ "$STATUS" != "SUCCEEDED" ]; then
  echo "[ERROR] Build did not succeed (status: $STATUS)"
  echo "[ERROR] Logs: https://console.aws.amazon.com/codesuite/codebuild/projects/$PROJECT_NAME/history?region=$REGION"
  exit 1
fi

echo "[OK] Build succeeded. Verifying image in ECR..."

VERIFY_ATTEMPT=0
MAX_VERIFY_ATTEMPTS=12 # 1 minute (12 * 5s)
while [ "$VERIFY_ATTEMPT" -lt "$MAX_VERIFY_ATTEMPTS" ]; do
  VERIFY_ATTEMPT=$((VERIFY_ATTEMPT + 1))

  if aws ecr describe-images \
    --repository-name "$REPO_NAME" \
    --image-ids imageTag="$IMAGE_TAG" \
    --region "$REGION" >/dev/null 2>&1; then
    echo "[OK] Image verified in ECR: $REPO_URL:$IMAGE_TAG"
    exit 0
  fi

  sleep 5
done

echo "[ERROR] Image $REPO_NAME:$IMAGE_TAG not found in ECR after build."
exit 1

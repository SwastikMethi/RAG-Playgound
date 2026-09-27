#!/usr/bin/env bash
set -euo pipefail
profile="${AWS_PROFILE:?Set AWS_PROFILE to the dedicated personal AWS profile}"
region="${AWS_REGION:-us-east-1}"
tag="${API_IMAGE_TAG:?Set API_IMAGE_TAG to an immutable tag}"
account="$(aws --profile "$profile" --region "$region" sts get-caller-identity --query Account --output text)"
registry="$account.dkr.ecr.$region.amazonaws.com"
aws --profile "$profile" --region "$region" ecr get-login-password | docker login --username AWS --password-stdin "$registry"
docker buildx build --platform linux/arm64 --provenance=false --sbom=false \
  -f Dockerfile.lambda -t "$registry/rag-playground-api:$tag" --push .

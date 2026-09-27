#!/usr/bin/env bash
set -euo pipefail
profile="${AWS_PROFILE:?Set AWS_PROFILE to the dedicated personal AWS profile}"
region="${AWS_REGION:-us-east-1}"
stack="${RAG_STACK_NAME:-rag-playground}"
api_image_tag="${API_IMAGE_TAG:-hosted-20260927-storagefix}"
worker_image_tag="${WORKER_IMAGE_TAG:-hosted-20260927-sleep}"
aws --profile "$profile" --region "$region" sts get-caller-identity >/dev/null
aws --profile "$profile" --region "$region" cloudformation deploy \
  --stack-name "$stack" --template-file infra/aws/template.yaml \
  --parameter-overrides ApiImageTag="$api_image_tag" WorkerImageTag="$worker_image_tag" \
  --capabilities CAPABILITY_IAM

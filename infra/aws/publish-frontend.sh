#!/usr/bin/env bash
set -euo pipefail
profile="${AWS_PROFILE:?Set AWS_PROFILE to the dedicated personal AWS profile}"
region="${AWS_REGION:-us-east-1}"
stack="${RAG_STACK_NAME:-rag-playground}"
bucket="$(aws --profile "$profile" --region "$region" cloudformation describe-stacks --stack-name "$stack" --query "Stacks[0].Outputs[?OutputKey=='FrontendBucket'].OutputValue" --output text)"
distribution="$(aws --profile "$profile" --region "$region" cloudformation describe-stacks --stack-name "$stack" --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" --output text)"
npm run build
aws --profile "$profile" --region "$region" s3 sync apps/web/dist "s3://$bucket" --delete
aws --profile "$profile" --region "$region" cloudfront create-invalidation --distribution-id "$distribution" --paths '/*' --query Invalidation.Id --output text

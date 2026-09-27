# AWS low-idle demo

The live demo is `https://d4ru0nym2caah.cloudfront.net`. CloudFront serves the private S3 frontend and the IAM-protected Lambda API. Committed jobs send a FIFO wake to a small control Lambda, which starts one public-subnet Fargate worker with no inbound ports. The worker exits after 60 seconds without work. Neon stores metadata and private artifacts; Qdrant Cloud stores vectors.

```sh
AWS_PROFILE=autorag-deployer AWS_REGION=us-east-1 ./infra/aws/deploy.sh
AWS_PROFILE=autorag-deployer AWS_REGION=us-east-1 API_IMAGE_TAG=<new-immutable-tag> ./infra/aws/publish-api.sh
AWS_PROFILE=autorag-deployer AWS_REGION=us-east-1 ./infra/aws/publish-frontend.sh
```

Use a demo upload below 5 MiB because browser uploads currently pass through Lambda. Add a user OpenAI key in Setup before preparing or comparing pipelines. The separate `rag-playground-budget` stack owns the $20 monthly budget. Never put provider keys or the Fernet master key in template parameters.

"""Load server-only deployment settings before starting the Lambda web process."""

import json
import os


def load_deployment_secret(secret_id, client=None, environment=None):
    if client is None:
        import boto3

        client = boto3.client("secretsmanager")
    environment = os.environ if environment is None else environment
    values = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
    allowed = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_ENDPOINT_URL_S3"}
    for key, value in values.items():
        if isinstance(value, str) and (key.startswith("RAG_") or key in allowed):
            environment[key] = value


def main():
    import uvicorn

    load_deployment_secret(os.environ["RAG_DEPLOYMENT_SECRET_ARN"])
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, access_log=False)


if __name__ == "__main__":
    main()

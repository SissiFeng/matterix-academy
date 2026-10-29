import base64
from uuid import uuid4

import boto3
import pytest
from academy.settings import Settings
from academy.simple_twins import BedrockTwins, CreateTwin, SimpleTwinService
from academy.store import SQLiteStore
from fastapi import HTTPException
from moto import mock_aws

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 32).decode()
AWS = dict(
    runtime="aws",
    table="academy-test",
    issuer="https://issuer.example",
    client_id="client",
    cognito_domain="https://auth.example",
    app_url="https://academy.example",
)


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ca-central-1")
    with mock_aws():
        client = boto3.client("secretsmanager", region_name="ca-central-1")
        arn = client.create_secret(Name="academy/twin", SecretString=" bedrock-key \n")["ARN"]
        yield client, arn


@pytest.mark.parametrize(
    "changes",
    [
        {"twin_region": "eu-west-1"},
        {"twin_region": "us-east-1", "twin_api_key_secret": "academy/twin"},
        {"twin_api_key": "key"},
        {**AWS, "twin_region": "us-east-1", "twin_api_key": "plaintext"},
    ],
)
def test_twin_key_settings_fail_closed(changes):
    with pytest.raises(ValueError):
        Settings(**changes)


def test_secret_is_read_once_and_cached(secret):
    client, arn = secret
    provider = BedrockTwins(Settings(**AWS, twin_region="us-east-1", twin_api_key_secret=arn))
    assert provider.available
    assert provider.api_key() == "bedrock-key"
    client.delete_secret(SecretId=arn, ForceDeleteWithoutRecovery=True)
    assert provider.api_key() == "bedrock-key"


def test_unreadable_secret_rejects_upload_without_claiming(secret, tmp_path):
    client, arn = secret
    client.delete_secret(SecretId=arn, ForceDeleteWithoutRecovery=True)
    settings = Settings(**AWS, twin_region="us-east-1", twin_api_key_secret=arn)
    service = SimpleTwinService(SQLiteStore(str(tmp_path / "db.sqlite")), settings)
    with pytest.raises(HTTPException) as error:
        service.create("owner", CreateTwin(expected_version=0, id=uuid4(), image=PNG))
    assert error.value.status_code == 503
    assert service.get("owner")["version"] == 0

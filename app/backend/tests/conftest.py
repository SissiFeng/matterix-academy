import boto3
import pytest
from academy.main import create_app
from academy.settings import Settings
from academy.store import DynamoStore, SQLiteStore
from fastapi.testclient import TestClient
from moto import mock_aws


@pytest.fixture(params=["sqlite", "dynamodb"])
def store(request, tmp_path, monkeypatch):
    if request.param == "sqlite":
        yield SQLiteStore(str(tmp_path / "records.sqlite"))
    else:
        monkeypatch.setenv("AWS_DEFAULT_REGION", "ca-central-1")
        with mock_aws():
            boto3.resource("dynamodb").create_table(
                TableName="academy-test",
                KeySchema=[
                    {"AttributeName": "pk", "KeyType": "HASH"},
                    {"AttributeName": "sk", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                    {"AttributeName": "created", "AttributeType": "S"},
                ],
                LocalSecondaryIndexes=[
                    {
                        "IndexName": "created_at",
                        "KeySchema": [
                            {"AttributeName": "pk", "KeyType": "HASH"},
                            {"AttributeName": "created", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            yield DynamoStore("academy-test")


@pytest.fixture
def app(store, tmp_path):
    return create_app(
        Settings(
            allow_demo=True,
            secret="test-secret-that-is-at-least-32-characters",
            data_path=str(tmp_path / "unused.sqlite"),
        ),
        store=store,
    )


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        assert client.post("/api/auth/guest", json={"name": "Ada"}).status_code == 200
        yield client


@pytest.fixture
def lab(store, tmp_path):
    """Lab Onboarding APIs, a qualified simulation worker and a Flex gateway (all fakes)."""
    from tests.sim2real_support import build_lab

    return build_lab(store, tmp_path)

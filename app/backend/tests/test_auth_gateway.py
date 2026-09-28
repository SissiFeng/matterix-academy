import time

import httpx
import pytest
from academy.auth import identify
from academy.gateway import GatewayUnavailable, MatterixGateway
from academy.main import create_app
from academy.settings import Settings
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request


def test_unsigned_identity_and_tampered_cookie_rejected(app):
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/sessions", headers={"X-User-ID": "someone", "Authorization": "Bearer fake"}
            ).status_code
            == 401
        )
        client.cookies.set("academy_local", "tampered")
        assert client.get("/api/me").status_code == 401


def test_cross_origin_mutation_and_untrusted_host_rejected(client):
    assert (
        client.post(
            "/api/sessions", json={}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_profile_and_logout(client):
    assert client.put(
        "/api/me", json={"name": "Ada", "experience": "some", "onboarded": True}
    ).json()["onboarded"]
    assert client.get("/api/me").json()["name"] == "Ada"
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def aws_settings(**kwargs):
    return Settings(
        runtime="aws",
        table="test",
        issuer="https://cognito-idp.ca-central-1.amazonaws.com/pool",
        client_id="client",
        cognito_domain="https://academy.auth.ca-central-1.amazoncognito.com",
        app_url="https://academy.example",
        **kwargs,
    )


def test_aws_cannot_enable_local_auth():
    with pytest.raises(ValueError):
        aws_settings(allow_demo=True)


@pytest.mark.parametrize(
    "override",
    [
        {"token_use": "id"},
        {"client_id": "other"},
        {"scope": "openid"},
        {"exp": 0},
        {"iss": "https://evil.example"},
        {"sub": ""},
        {"exp": "broken"},
    ],
)
def test_aws_authorizer_claims_checked(store, override):
    settings = aws_settings()
    app = create_app(settings, store)
    claims = {
        "iss": settings.issuer,
        "client_id": "client",
        "token_use": "access",
        "scope": "openid academy/learn",
        "sub": "student",
        "exp": time.time() + 300,
        **override,
    }
    request = Request(
        {
            "type": "http",
            "app": app,
            "aws.event": {"requestContext": {"authorizer": {"jwt": {"claims": claims}}}},
        }
    )
    with pytest.raises(HTTPException) as error:
        identify(request)
    assert error.value.status_code == 401


def test_aws_only_accepts_trusted_lambda_authorizer_context(store):
    settings = aws_settings()
    app = create_app(settings, store)
    with TestClient(app) as client:
        assert client.post("/api/auth/guest", json={"name": "Ada"}).status_code == 404
        assert (
            client.get(
                "/api/me", headers={"X-User-Sub": "student", "Authorization": "Bearer fake"}
            ).status_code
            == 401
        )
    claims = {
        "iss": settings.issuer,
        "client_id": "client",
        "token_use": "access",
        "scope": "academy/learn",
        "sub": "student",
        "exp": time.time() + 300,
    }
    request = Request(
        {
            "type": "http",
            "app": app,
            "aws.event": {"requestContext": {"authorizer": {"jwt": {"claims": claims}}}},
        }
    )
    assert identify(request) == "student"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {
            "contract_version": "1",
            "engine": "teaching",
            "simulation_only": True,
            "supports_isolated_sessions": True,
        },
        {
            "contract_version": "1",
            "engine": "matterix",
            "simulation_only": False,
            "supports_isolated_sessions": True,
        },
    ],
)
def test_gateway_rejects_unqualified_engine(body):
    gateway = MatterixGateway(
        "https://gateway.example",
        "test-token",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    )
    with pytest.raises(GatewayUnavailable):
        gateway.capabilities()
    gateway.close()


def test_gateway_does_not_follow_redirect_or_fallback_to_teaching():
    gateway = MatterixGateway(
        "https://gateway.example",
        "test-token",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "https://evil.example"})
        ),
    )
    with pytest.raises(GatewayUnavailable):
        gateway.capabilities()
    gateway.close()


def test_gateway_qualified_contract_and_service_auth():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer test-token"
        assert str(request.url) == "https://gateway.example/v1/capabilities"
        return httpx.Response(
            200,
            json={
                "contract_version": "1",
                "engine": "matterix",
                "simulation_only": True,
                "supports_isolated_sessions": True,
                "actions": ["aspirate"],
            },
        )

    gateway = MatterixGateway(
        "https://gateway.example", "test-token", transport=httpx.MockTransport(handler)
    )
    assert gateway.capabilities().engine == "matterix"
    gateway.close()

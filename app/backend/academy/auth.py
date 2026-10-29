import time

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .settings import Settings


def local_signer(settings: Settings):
    return URLSafeTimedSerializer(settings.secret, salt="academy-local-session-v1")


def identify(request: Request) -> str:
    settings = request.app.state.settings
    if settings.runtime == "aws":
        # Only API Gateway's authorizer context in the Lambda event is trusted.
        # HTTP headers (including forwarded identity headers) are never identity sources.
        claims = (
            request.scope.get("aws.event", {})
            .get("requestContext", {})
            .get("authorizer", {})
            .get("jwt", {})
            .get("claims", {})
        )
        try:
            valid = (
                claims.get("iss") == settings.issuer
                and claims.get("client_id") == settings.client_id
                and claims.get("token_use") == "access"
                and "academy/learn" in claims.get("scope", "").split()
                and float(claims.get("exp", 0)) > time.time()
                and isinstance(claims.get("sub"), str)
                and 0 < len(claims["sub"]) <= 128
            )
        except (TypeError, ValueError):
            valid = False
        if valid:
            return claims["sub"]
    elif settings.allow_demo:
        cookie = request.cookies.get("academy_local")
        if cookie:
            try:
                return local_signer(settings).loads(cookie, max_age=86400)["sub"]
            except (BadSignature, KeyError, TypeError):
                pass
    raise HTTPException(401, "Sign in to continue")


def operator_claims(request: Request) -> bool:
    """Operators are Cognito group members (AWS) or the explicit loopback demo operator."""
    settings = request.app.state.settings
    if settings.runtime == "aws":
        claims = (
            request.scope.get("aws.event", {})
            .get("requestContext", {})
            .get("authorizer", {})
            .get("jwt", {})
            .get("claims", {})
        )
        groups = claims.get("cognito:groups", "")
        if isinstance(groups, str):
            # API Gateway serializes claim arrays as "[a b]" strings.
            groups = groups.strip("[]").replace(",", " ").split()
        return isinstance(groups, list) and settings.operator_group in groups
    return settings.local_operator


def identify_operator(request: Request) -> str:
    """A signed-in learner identity that also holds the lab operator role."""
    subject = identify(request)
    if not operator_claims(request):
        raise HTTPException(403, "Lab operator role required")
    return subject

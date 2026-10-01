#!/usr/bin/env python3
"""Development deployment smoke checks; never native/GPU or Cognito login evidence.

Uses real HTTP auth gates, a temporary unqualified machine credential, and real
Lambda/DynamoDB. Learner persistence checks invoke Lambda with synthetic trusted
authorizer context, explicitly bypassing the browser login/JWT issuance flow.
Only records created by this process are removed. No credentials are printed.
"""

import argparse
import hashlib
import json
import secrets
import time
from pathlib import Path
from uuid import uuid4

import boto3
import httpx
from academy.runs import WORKERS, revised
from academy.store import Conflict, DynamoStore, Write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", required=True)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    account = boto3.client("sts").get_caller_identity()["Account"]
    if account != args.expected_account_id:
        raise SystemExit("AWS account mismatch")
    outputs = {k: v["value"] for k, v in json.loads(Path(args.outputs).read_text()).items()}
    if outputs["remote_execution_enabled"] is not False:
        raise SystemExit("This smoke procedure requires native execution disabled")
    checks = []
    store = DynamoStore(outputs["records_table"])
    function = outputs["lambda_function"]
    client = boto3.client("lambda")
    environment = client.get_function_configuration(FunctionName=function)["Environment"][
        "Variables"
    ]
    assert environment["ACADEMY_REMOTE_ENABLED"] == "false"
    assert environment["ACADEMY_ALLOW_DEMO"] == "false"
    prefix = "deployment-smoke-" + uuid4().hex[:12]
    owner_a, owner_b = prefix + "-a", prefix + "-b"
    created_keys = []
    worker_id = prefix
    token = worker_id + "." + secrets.token_urlsafe(48)
    worker = dict(
        version=1,
        worker_id=worker_id,
        credential_version=1,
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        credential_expires=time.time() + 600,
        revoked=False,
        qualified=False,
        state="quarantined",
        active_run=None,
        controls=[],
        engine_version="synthetic-smoke-only",
        asset_version="synthetic-smoke-only",
    )

    def checked(name, actual, expected):
        if actual != expected:
            raise AssertionError(f"{name}: expected {expected}, received {actual}")
        checks.append({"check": name, "result": actual})

    def invoke(method, path, owner, body=None):
        event = {
            "version": "2.0",
            "routeKey": "ANY /api/{proxy+}",
            "rawPath": path,
            "rawQueryString": "",
            "headers": {"host": "deployment-smoke.invalid", "content-type": "application/json"},
            "requestContext": {
                "stage": "$default",
                "requestId": str(uuid4()),
                "http": {
                    "method": method,
                    "path": path,
                    "sourceIp": "127.0.0.1",
                    "protocol": "HTTP/1.1",
                },
                "authorizer": {
                    "jwt": {
                        "claims": {
                            "sub": owner,
                            "iss": environment["ACADEMY_ISSUER"],
                            "client_id": environment["ACADEMY_CLIENT_ID"],
                            "token_use": "access",
                            "scope": "academy/learn",
                            "exp": str(int(time.time()) + 120),
                        }
                    }
                },
            },
            "body": json.dumps(body) if body is not None else None,
            "isBase64Encoded": False,
        }
        result = client.invoke(FunctionName=function, Payload=json.dumps(event).encode())
        response = json.loads(result["Payload"].read())
        if result.get("FunctionError"):
            raise AssertionError("Lambda smoke invocation failed; inspect CloudWatch")
        return response["statusCode"], json.loads(response.get("body") or "null")

    try:
        with httpx.Client(timeout=30, follow_redirects=False) as http:
            app = outputs["app_url"]
            machine = outputs["worker_api_url"]
            checked("public health HTTP", http.get(app + "/api/health").status_code, 200)
            checked("frontend HTTP", http.get(app + "/").status_code, 200)
            config = http.get(app + "/api/config")
            checked("Cognito configured", config.json()["auth"], "cognito")
            checked("learner unauthenticated", http.get(app + "/api/me").status_code, 401)
            checked(
                "learner forged identity rejected",
                http.get(app + "/api/me", headers={"x-user-id": owner_a}).status_code,
                401,
            )
            checked(
                "worker missing credential",
                http.get(machine + "/internal/workers/me").status_code,
                401,
            )
            checked(
                "worker invalid credential",
                http.get(
                    machine + "/internal/workers/me", headers={"Authorization": "Bearer invalid"}
                ).status_code,
                403,
            )
            store.put(WORKERS, worker_id, worker, None)
            created_keys.append((WORKERS, worker_id))
            headers = {"Authorization": "Bearer " + token}
            status = http.get(machine + "/internal/workers/me", headers=headers)
            checked("registered machine authorizer HTTP", status.status_code, 200)
            checked("machine remains unqualified", status.json()["qualified"], False)
            checked(
                "disabled native claim",
                http.post(machine + "/internal/runs/claim", headers=headers).status_code,
                403,
            )
            checked(
                "browser origin rejected",
                http.get(
                    machine + "/internal/workers/me", headers={**headers, "Origin": app}
                ).status_code,
                403,
            )
            checked(
                "machine token cannot access learner API",
                http.get(app + "/api/me", headers=headers).status_code,
                401,
            )
            store.put(WORKERS, worker_id, revised(worker, revoked=True), 1)
            checked(
                "revocation immediately enforced",
                http.get(machine + "/internal/workers/me", headers=headers).status_code,
                403,
            )

        experiment = dict(
            course_id="flex-first-transfer",
            title="Deployment smoke fixture",
            transfer_volume=100,
            source_volume=1000,
            diluent_volume=0,
            actions=[
                {"kind": "pickup"},
                {"kind": "aspirate", "volume": 100},
                {"kind": "dispense", "well": "A1", "volume": 100},
                {"kind": "drop"},
            ],
        )
        code, session = invoke("POST", "/api/sessions", owner_a, experiment)
        checked("synthetic-context Lambda create", code, 201)
        created_keys.append((owner_a, "session#" + session["id"]))
        path = "/api/sessions/" + session["id"]
        checked("synthetic-context Lambda persistence", invoke("GET", path, owner_a)[0], 200)
        checked("synthetic-context cross-sub isolation", invoke("GET", path, owner_b)[0], 404)
        checked(
            "synthetic-context stale version",
            invoke("POST", path + "/reset", owner_a, {"version": 999})[0],
            409,
        )
        checked(
            "synthetic-context native gate",
            invoke(
                "POST",
                "/api/runs",
                owner_a,
                {
                    "run_id": str(uuid4()),
                    "session_id": session["id"],
                    "expected_version": session["version"],
                },
            )[0],
            503,
        )
        checked(
            "synthetic-context remote disabled",
            invoke("GET", "/api/runs/status", owner_a)[1]["enabled"],
            False,
        )

        # Real DynamoDB conditional transactions under the operator role.
        created_keys.extend([(prefix, "one"), (prefix, "two")])
        store.transact([Write(prefix, "one", {"version": 1}, None)])
        try:
            store.transact(
                [
                    Write(prefix, "two", {"version": 1}, None),
                    Write(prefix, "one", {"version": 2}, 77),
                ]
            )
        except Conflict:
            pass
        else:
            raise AssertionError("Stale DynamoDB transaction was accepted")
        checked("live DynamoDB transaction rollback", store.get(prefix, "two"), None)
        checked("live DynamoDB original version retained", store.get(prefix, "one")["version"], 1)
    finally:
        for owner, key in reversed(created_keys):
            store.table.delete_item(Key={"pk": owner, "sk": key})

    report = dict(
        account=account,
        app_url=outputs["app_url"],
        checks=checks,
        synthetic_authorizer_context=True,
        real_cognito_login_verified=False,
        native_gpu_verified=False,
        smoke_records_removed=True,
    )
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

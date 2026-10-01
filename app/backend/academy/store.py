from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


class Conflict(Exception):
    pass


@dataclass(frozen=True)
class Write:
    owner: str
    key: str
    body: dict | None
    expected: int | None


class SQLiteStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS records (owner TEXT, id TEXT, version INTEGER, body TEXT, PRIMARY KEY(owner,id))"
            )

    def connection(self):
        return sqlite3.connect(self.path, timeout=10)

    def get(self, owner: str, key: str):
        with self.connection() as db:
            row = db.execute(
                "SELECT body FROM records WHERE owner=? AND id=?", (owner, key)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, owner: str):
        with self.connection() as db:
            rows = db.execute(
                "SELECT body FROM records WHERE owner=? AND id LIKE 'session#%' ORDER BY rowid DESC LIMIT 50",
                (owner,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, owner: str, key: str, body: dict, expected: int | None):
        serialized = json.dumps(body, allow_nan=False)
        with self.connection() as db:
            if expected is None:
                try:
                    db.execute(
                        "INSERT INTO records VALUES (?,?,?,?)",
                        (owner, key, body["version"], serialized),
                    )
                except sqlite3.IntegrityError as exc:
                    raise Conflict from exc
            else:
                count = db.execute(
                    "UPDATE records SET version=?, body=? WHERE owner=? AND id=? AND version=?",
                    (body["version"], serialized, owner, key, expected),
                ).rowcount
                if count != 1:
                    raise Conflict

    def partition(self, owner: str, prefix: str = "", limit: int = 100):
        with self.connection() as db:
            rows = db.execute(
                "SELECT body FROM records WHERE owner=? AND substr(id,1,?)=? ORDER BY id LIMIT ?",
                (owner, len(prefix), prefix, limit),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def transact(self, writes: list[Write]):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for write in writes:
                row = db.execute(
                    "SELECT version FROM records WHERE owner=? AND id=?",
                    (write.owner, write.key),
                ).fetchone()
                if (row[0] if row else None) != write.expected:
                    raise Conflict
                if write.body is None:
                    db.execute(
                        "DELETE FROM records WHERE owner=? AND id=?", (write.owner, write.key)
                    )
                else:
                    db.execute(
                        "INSERT INTO records VALUES (?,?,?,?) "
                        "ON CONFLICT(owner,id) DO UPDATE SET "
                        "version=excluded.version, body=excluded.body",
                        (
                            write.owner,
                            write.key,
                            write.body["version"],
                            json.dumps(write.body, allow_nan=False),
                        ),
                    )


class DynamoStore:
    def __init__(self, table: str):
        self.table = boto3.resource("dynamodb").Table(table)

    def get(self, owner: str, key: str):
        item = self.table.get_item(Key={"pk": owner, "sk": key}, ConsistentRead=True).get("Item")
        return json.loads(item["body"]) if item else None

    def list(self, owner: str):
        result = []
        cursor = None
        while len(result) < 50:
            args = dict(
                IndexName="created_at",
                KeyConditionExpression="pk = :owner",
                ExpressionAttributeValues={":owner": owner},
                ConsistentRead=True,
                ScanIndexForward=False,
                Limit=50 - len(result),
            )
            if cursor:
                args["ExclusiveStartKey"] = cursor
            response = self.table.query(**args)
            result.extend(json.loads(item["body"]) for item in response["Items"])
            cursor = response.get("LastEvaluatedKey")
            if not cursor:
                break
        return result

    def put(self, owner: str, key: str, body: dict, expected: int | None):
        args = {
            "Item": {
                "pk": owner,
                "sk": key,
                "version": body["version"],
                "body": json.dumps(body, allow_nan=False),
            }
        }
        if key.startswith("session#"):
            args["Item"]["created"] = f"{body['created_at']}#{body['id']}"
        if expected is None:
            args["ConditionExpression"] = "attribute_not_exists(pk)"
        else:
            args.update(
                ConditionExpression="#v = :v",
                ExpressionAttributeNames={"#v": "version"},
                ExpressionAttributeValues={":v": expected},
            )
        try:
            self.table.put_item(**args)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise Conflict from exc
            raise

    def partition(self, owner: str, prefix: str = "", limit: int = 100):
        args = {
            "KeyConditionExpression": "pk = :pk"
            + (" AND begins_with(sk, :prefix)" if prefix else ""),
            "ExpressionAttributeValues": {":pk": owner, **({":prefix": prefix} if prefix else {})},
            "ConsistentRead": True,
            "Limit": limit,
        }
        result = []
        while len(result) < limit:
            response = self.table.query(**args)
            result.extend(json.loads(item["body"]) for item in response["Items"])
            if "LastEvaluatedKey" not in response:
                break
            args["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            args["Limit"] = limit - len(result)
        return result

    def transact(self, writes: list[Write]):
        operations = []
        for write in writes:
            condition = (
                {"ConditionExpression": "attribute_not_exists(pk)"}
                if write.expected is None
                else {
                    "ConditionExpression": "#v = :v",
                    "ExpressionAttributeNames": {"#v": "version"},
                    "ExpressionAttributeValues": {":v": write.expected},
                }
            )
            entry = {"TableName": self.table.name, **condition}
            if write.body is None:
                entry["Key"] = {"pk": write.owner, "sk": write.key}
                operations.append({"Delete": entry})
            else:
                entry["Item"] = {
                    "pk": write.owner,
                    "sk": write.key,
                    "version": write.body["version"],
                    "body": json.dumps(write.body, allow_nan=False),
                }
                if write.key.startswith("session#"):
                    entry["Item"]["created"] = f"{write.body['created_at']}#{write.body['id']}"
                operations.append({"Put": entry})
        try:
            self.table.meta.client.transact_write_items(TransactItems=operations)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "TransactionCanceledException" and any(
                reason.get("Code") in {"ConditionalCheckFailed", "TransactionConflict"}
                for reason in exc.response.get("CancellationReasons", [])
            ):
                raise Conflict from exc
            raise

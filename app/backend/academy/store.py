import json
import sqlite3
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


class Conflict(Exception):
    pass


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

"""Pinned ChemLab-Assets GLB models for the 3D view.

  manifest            regenerate app/backend/academy/chemlab_models.json from the pinned
                      dataset revision (sha256 and size of every model.glb, from the Hub API)
  fetch [DIR]         download every listed model into DIR (default: the web app's
                      public/library-models, ignored by git) and verify its sha256
  upload BUCKET       fetch into the local cache, then put the models the bucket does not
                      already hold under library-models/chemlab/ (needs AWS credentials;
                      pass --account to pin the AWS account)

The models are CC-BY-NC-4.0; attribution travels with every twin started from them.
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app/backend/academy"
MANIFEST = BACKEND / "chemlab_models.json"
PUBLIC = ROOT / "app/frontend/public"
PREFIX = "library-models/chemlab"
REPO = "MBZUAI/ChemLab-Assets"
MAX_BYTES = 16_000_000


def revision():
    for line in (BACKEND / "chemlab.py").read_text().splitlines():
        if line.startswith("REVISION = "):
            return line.split('"')[1]
    raise SystemExit("REVISION not found in chemlab.py")


def manifest():
    rev = revision()
    rows = json.loads((BACKEND / "chemlab_catalog.json").read_text())["instruments"]

    def one(row):
        url = f"https://huggingface.co/api/datasets/{REPO}/tree/{rev}/{row['path']}"
        with urllib.request.urlopen(url, timeout=60) as response:
            files = json.load(response)
        glb = next((f for f in files if f["path"].endswith("/model.glb") and "lfs" in f), None)
        if not glb or glb["lfs"]["size"] > MAX_BYTES:
            return None
        return row["slug"], {
            "file": f"{PREFIX}/{row['slug']}.glb",
            "source": glb["path"],
            "sha256": glb["lfs"]["oid"],
            "bytes": glb["lfs"]["size"],
        }

    with ThreadPoolExecutor(12) as pool:
        found = dict(r for r in pool.map(one, rows) if r)
    MANIFEST.write_text(
        json.dumps({"revision": rev, "models": dict(sorted(found.items()))}, indent=1) + "\n"
    )
    print(f"{len(found)} of {len(rows)} instruments have a model ≤ {MAX_BYTES // 1_000_000} MB")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(dest):
    data = json.loads(MANIFEST.read_text())
    rev = data["revision"]

    def one(item):
        model = item[1]
        path = dest / model["file"]
        if path.exists() and digest(path) == model["sha256"]:
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/datasets/{REPO}/resolve/{rev}/{model['source']}"
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=120) as response:
                    body = response.read()
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        if hashlib.sha256(body).hexdigest() != model["sha256"]:
            raise SystemExit(f"{model['source']} does not match its pinned sha256")
        path.write_bytes(body)
        return len(body)

    with ThreadPoolExecutor(8) as pool:
        got = sum(pool.map(one, data["models"].items()))
    print(f"{len(data['models'])} models verified in {dest} ({got / 1e6:.0f} MB downloaded)")
    return data


def upload(bucket, account):
    import boto3

    session = boto3.Session()
    if account and session.client("sts").get_caller_identity()["Account"] != account:
        raise SystemExit("AWS account mismatch")
    cache = ROOT / "build/library-models"
    data = fetch(cache)
    s3 = session.client("s3")
    have = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=PREFIX):
        have.update(o["Key"] for o in page.get("Contents", []))
    todo = [m for m in data["models"].values() if m["file"] not in have]
    for model in todo:
        s3.put_object(
            Bucket=bucket,
            Key=model["file"],
            Body=(cache / model["file"]).read_bytes(),
            ContentType="model/gltf-binary",
            # Content-addressed by the pinned revision, so it never changes in place.
            CacheControl="public,max-age=31536000,immutable",
        )
    print(f"Uploaded {len(todo)} models; {len(have)} were already in s3://{bucket}/{PREFIX}/")


def main(argv):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("manifest")
    f = sub.add_parser("fetch")
    f.add_argument("dest", nargs="?", type=Path, default=PUBLIC)
    u = sub.add_parser("upload")
    u.add_argument("bucket")
    u.add_argument("--account")
    args = parser.parse_args(argv)
    if args.command == "manifest":
        manifest()
    elif args.command == "fetch":
        fetch(args.dest)
    else:
        upload(args.bucket, args.account)


if __name__ == "__main__":
    main(sys.argv[1:])

"""Pinned ChemLab-Assets GLB models for the 3D view.

  manifest            regenerate app/backend/academy/chemlab_models.json from the pinned
                      dataset revision (sha256 and size of every model.glb, from the Hub API,
                      and which axis each model stands on, from its own node tree)
  fetch [DIR]         download every listed model into DIR (default: the web app's
                      public/library-models, ignored by git) and verify its sha256
  upload BUCKET       fetch into the local cache, then put the models the bucket does not
                      already hold under library-models/chemlab/ (needs AWS credentials;
                      pass --account to pin the AWS account)
  time SLUG...        time importing single instruments end to end: Hub lookup, model
                      download and sha256 check, then the twin a learner starts from

The models are CC-BY-NC-4.0; attribution travels with every twin started from them.
"""

import argparse
import hashlib
import itertools
import json
import struct
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


def gltf(read):
    """The JSON chunk of a GLB; `read(start, end)` returns that inclusive byte range."""
    magic, _, _, length, kind = struct.unpack("<4sIIII", read(0, 19))
    if magic != b"glTF" or kind != 0x4E4F534A:
        raise SystemExit("Not a binary glTF file")
    return json.loads(read(20, 19 + length))


def _matrix(node):
    if "matrix" in node:
        m = node["matrix"]
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    sx, sy, sz = node.get("scale", (1, 1, 1))
    tx, ty, tz = node.get("translation", (0, 0, 0))
    return [
        [(1 - 2 * (y * y + z * z)) * sx, 2 * (x * y - z * w) * sy, 2 * (x * z + y * w) * sz, tx],
        [2 * (x * y + z * w) * sx, (1 - 2 * (x * x + z * z)) * sy, 2 * (y * z - x * w) * sz, ty],
        [2 * (x * z - y * w) * sx, 2 * (y * z + x * w) * sy, (1 - 2 * (x * x + y * y)) * sz, tz],
        [0, 0, 0, 1],
    ]


def extent(doc):
    """Overall (x, y, z) size of a glTF scene, from its accessor bounds and node transforms."""
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3

    def walk(index, parent):
        node = doc["nodes"][index]
        local = _matrix(node)
        world = [
            [sum(parent[r][k] * local[k][c] for k in range(4)) for c in range(4)] for r in range(4)
        ]
        if "mesh" in node:
            for primitive in doc["meshes"][node["mesh"]]["primitives"]:
                bounds = doc["accessors"][primitive["attributes"]["POSITION"]]
                for corner in itertools.product(*zip(bounds["min"], bounds["max"], strict=True)):
                    for axis in range(3):
                        v = sum(world[axis][k] * corner[k] for k in range(3)) + world[axis][3]
                        lo[axis], hi[axis] = min(lo[axis], v), max(hi[axis], v)
        for child in node.get("children", []):
            walk(child, world)

    identity = [[float(r == c) for c in range(4)] for r in range(4)]
    for root in doc["scenes"][doc.get("scene", 0)]["nodes"]:
        walk(root, identity)
    return [h - low for low, h in zip(lo, hi, strict=True)]


def up_axis(doc, size_zup):
    """'z' when the model's extent is the catalogue's (x, y, z) size, 'y' when it is turned.

    Most ChemLab models stand on z = 0, but some keep glTF's own Y-up convention; the
    3D view has to know which to stand them upright.
    """
    x, y, z = extent(doc)

    def error(got):
        return max(abs(g - want) / want for g, want in zip(got, size_zup, strict=True))

    return "y" if error((x, z, y)) < error((x, y, z)) else "z"


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

        def read(start, end):
            request = urllib.request.Request(
                f"https://huggingface.co/datasets/{REPO}/resolve/{rev}/{glb['path']}",
                headers={"Range": f"bytes={start}-{end}"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()

        model = {
            "file": f"{PREFIX}/{row['slug']}.glb",
            "source": glb["path"],
            "sha256": glb["lfs"]["oid"],
            "bytes": glb["lfs"]["size"],
        }
        if up_axis(gltf(read), row["size_m"]) == "y":
            model["up"] = "y"
        return row["slug"], model

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


def lookup(rev, path):
    url = f"https://huggingface.co/api/datasets/{REPO}/tree/{rev}/{path}"
    with urllib.request.urlopen(url, timeout=60) as response:
        files = json.load(response)
    return next((f for f in files if f["path"].endswith("/model.glb") and "lfs" in f), None)


def timed(slugs):
    """Seconds per stage for each instrument, as a new device would be imported."""
    sys.path.insert(0, str(ROOT / "app/backend"))
    from academy.chemlab import entry

    rev = revision()
    rows = {
        r["slug"]: r
        for r in json.loads((BACKEND / "chemlab_catalog.json").read_text())["instruments"]
    }
    cache = ROOT / "build/library-models"
    print(f"{'instrument':44} {'lookup':>7} {'model':>7} {'MB':>6} {'twin':>6} {'total':>7}")
    for slug in slugs:
        if slug not in rows:
            raise SystemExit(f"{slug} is not in the pinned ChemLab catalogue")
        start = time.perf_counter()
        glb = lookup(rev, rows[slug]["path"])
        found = time.perf_counter()
        size = 0
        if glb:
            url = f"https://huggingface.co/datasets/{REPO}/resolve/{rev}/{glb['path']}"
            with urllib.request.urlopen(url, timeout=120) as response:
                body = response.read()
            if hashlib.sha256(body).hexdigest() != glb["lfs"]["oid"]:
                raise SystemExit(f"{glb['path']} does not match the Hub's sha256")
            path = cache / PREFIX / f"{slug}.glb"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            size = len(body)
        loaded = time.perf_counter()
        entry(rows[slug])
        done = time.perf_counter()
        print(
            f"{slug[:44]:44} {found - start:7.2f} {loaded - found:7.2f} {size / 1e6:6.1f} "
            f"{done - loaded:6.3f} {done - start:7.2f}"
            + ("" if glb else "  (no model: footprint only)")
        )


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
    t = sub.add_parser("time")
    t.add_argument("slugs", nargs="+")
    args = parser.parse_args(argv)
    if args.command == "manifest":
        manifest()
    elif args.command == "time":
        timed(args.slugs)
    elif args.command == "fetch":
        fetch(args.dest)
    else:
        upload(args.bucket, args.account)


if __name__ == "__main__":
    main(sys.argv[1:])

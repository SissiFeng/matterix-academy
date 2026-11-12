"""Collision boxes of the pinned ChemLab-Assets models, for the arm planner.

  uv run --with trimesh --with numpy python scripts/library-models/chemlab_collision.py [DIR]

Reads every model listed in chemlab_models.json from DIR (default: the web app's
public/library-models/chemlab, as `chemlab_models.py fetch` leaves it), checks its sha256
and writes app/backend/academy/chemlab_collision.json: for each model, a few boxes that
cover its surface, so an enclosure keeps its openings instead of being one solid block.

A box is [cx, cy, cz, hx, hy, hz] (centre, half size) as fractions of the model's own
bounding box, in the twin's frame: x right, y up from the base, z toward the front.
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app/backend/academy"
MODELS = json.loads((BACKEND / "chemlab_models.json").read_text())["models"]
OUT = BACKEND / "chemlab_collision.json"
SAMPLES = 400_000
PITCH = 0.03  # metres; coarser for a model that would need more than MAX_BOXES
MAX_BOXES = 40


def twin_frame(points, up):
    """Model coordinates to the twin's: Z-up models face -Y, Y-up models face +Z."""
    if up == "y":
        return points
    return np.stack([points[:, 0], points[:, 2], -points[:, 1]], axis=1)


def occupancy(points, low, extent, pitch, per_area):
    shape = np.maximum(1, np.ceil(extent / pitch).astype(int))
    index = np.minimum(((points - low) / extent * shape).astype(int), shape - 1)
    counts = np.zeros(shape, int)
    np.add.at(counts, tuple(index.T), 1)
    # A voxel counts when a surface crosses a fair part of it, not when one grazes it.
    return counts > 0.08 * per_area * pitch * pitch


def boxes(grid):
    """Greedy cover of the occupied voxels by boxes, largest growth first along x, y, z."""
    left, found = grid.copy(), []
    while left.any():
        x, y, z = np.argwhere(left)[0]
        x1 = x + 1
        while x1 < grid.shape[0] and left[x1, y, z]:
            x1 += 1
        y1 = y + 1
        while y1 < grid.shape[1] and left[x:x1, y1, z].all():
            y1 += 1
        z1 = z + 1
        while z1 < grid.shape[2] and left[x:x1, y:y1, z1].all():
            z1 += 1
        left[x:x1, y:y1, z:z1] = False
        found.append(((x, y, z), (x1, y1, z1)))
    return found


def cover(path, up):
    mesh = trimesh.load(path, force="mesh")
    rng = np.random.default_rng(0)
    points, _ = trimesh.sample.sample_surface(mesh, SAMPLES, seed=rng)
    points = twin_frame(np.asarray(points), up)
    low, high = points.min(axis=0), points.max(axis=0)
    extent = np.maximum(high - low, 1e-6)
    pitch = PITCH
    while True:
        grid = occupancy(points, low, extent, pitch, SAMPLES / mesh.area)
        found = boxes(grid)
        if len(found) <= MAX_BOXES:
            break
        pitch *= 1.25
    out = []
    for start, end in found:
        lo = np.array(start) / grid.shape
        hi = np.array(end) / grid.shape
        centre, half = (lo + hi) / 2 - (0.5, 0, 0.5), (hi - lo) / 2
        out.append([round(float(v), 3) for v in (*centre, *half)])
    return out


def main():
    folder = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else ROOT / "app/frontend/public/library-models/chemlab"
    )
    result = {}
    for slug, model in sorted(MODELS.items()):
        path = folder / f"{slug}.glb"
        if hashlib.sha256(path.read_bytes()).hexdigest() != model["sha256"]:
            raise SystemExit(f"{path} does not match the pinned sha256")
        result[slug] = cover(path, model.get("up", "z"))
        print(f"{slug}: {len(result[slug])} boxes", flush=True)
    OUT.write_text(json.dumps(result, separators=(",", ":"), sort_keys=True) + "\n")


if __name__ == "__main__":
    main()

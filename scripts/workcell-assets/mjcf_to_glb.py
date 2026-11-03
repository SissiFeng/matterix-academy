"""Convert a compiled MuJoCo model's visual geoms to GLB nodes grouped by body."""
import collections
import numpy as np
import mujoco
import trimesh
from scipy.spatial.transform import Rotation as Rot


def geom_mesh(m, g):
    t = m.geom_type[g]
    s = m.geom_size[g]
    if t == mujoco.mjtGeom.mjGEOM_BOX:
        return trimesh.creation.box(extents=2 * s[:3])
    if t == mujoco.mjtGeom.mjGEOM_CYLINDER:
        return trimesh.creation.cylinder(radius=s[0], height=2 * s[1], sections=28)
    if t == mujoco.mjtGeom.mjGEOM_SPHERE:
        return trimesh.creation.icosphere(subdivisions=2, radius=s[0])
    if t == mujoco.mjtGeom.mjGEOM_CAPSULE:
        return trimesh.creation.capsule(radius=s[0], height=2 * s[1], count=[16, 8])
    if t == mujoco.mjtGeom.mjGEOM_ELLIPSOID:
        e = trimesh.creation.icosphere(subdivisions=2)
        e.apply_scale(s[:3])
        return e
    if t == mujoco.mjtGeom.mjGEOM_MESH:
        mid = m.geom_dataid[g]
        va, vn = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
        fa, fn = m.mesh_faceadr[mid], m.mesh_facenum[mid]
        return trimesh.Trimesh(m.mesh_vert[va:va + vn].copy(), m.mesh_face[fa:fa + fn].copy(), process=False)
    return None


def color(m, g):
    mat = m.geom_matid[g]
    c = m.mat_rgba[mat] if mat >= 0 else m.geom_rgba[g]
    return tuple(float(v) for v in np.round(c, 3))


def local_T(m, g):
    M = np.eye(4)
    q = m.geom_quat[g]
    M[:3, :3] = Rot.from_quat([q[1], q[2], q[3], q[0]]).as_matrix()
    M[:3, 3] = m.geom_pos[g]
    return M


def body_world(d, b):
    M = np.eye(4)
    M[:3, :3] = d.xmat[b].reshape(3, 3)
    M[:3, 3] = d.xpos[b]
    return M


def export(m, d, out, rename, keep_separate=lambda n: False, skip_groups=(4, 5), world_nodes=()):
    """Geoms in body-local frames. rename(body) -> node name, or None to skip.

    Node names are "<node>|<geom or ''>|<n>"; the body's home world transform is returned per node.
    """
    scene = trimesh.Scene()
    groups = collections.defaultdict(list)
    info = {}
    for g in range(m.ngeom):
        if m.geom_group[g] in skip_groups:
            continue
        b = m.geom_bodyid[g]
        node = rename(mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b))
        if node is None:
            continue
        gm = geom_mesh(m, g)
        if gm is None:
            continue
        gm.apply_transform((body_world(d, b) @ local_T(m, g)) if node in world_nodes else local_T(m, g))
        gn = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or ""
        c = color(m, g)
        groups[(node, gn if keep_separate(gn) else "", c)].append(gm)
        info[node] = np.eye(4).tolist() if node in world_nodes else body_world(d, b).tolist()
    for i, ((node, gn, c), ms) in enumerate(groups.items()):
        mm = trimesh.util.concatenate(ms)
        if len(mm.faces) > 6000:
            try:
                mm = mm.simplify_quadric_decimation(face_count=max(6000, int(len(mm.faces) * 0.3)))
            except Exception as exc:
                print("decimate failed", node, exc)
        rgba = (np.array(c) * 255).astype(np.uint8)
        translucent = c[3] < 0.99
        mat = trimesh.visual.material.PBRMaterial(
            baseColorFactor=rgba, metallicFactor=0.1, roughnessFactor=0.55,
            alphaMode="BLEND" if translucent else "OPAQUE", doubleSided=translucent)
        mm.visual = trimesh.visual.TextureVisuals(material=mat)
        name = f"{node}|{gn}|{i}"
        scene.add_geometry(mm, node_name=name, geom_name=name)
    scene.export(out)
    return info


if __name__ == "__main__":
    # usage: mjcf_to_glb.py <flex.xml with flex_assets/ beside it> <out.glb> <out_meta.json>
    import json
    import sys
    from pathlib import Path

    xml = Path(sys.argv[1])
    assets = {p.name: p.read_bytes() for p in (xml.parent / "flex_assets").glob("*") if p.is_file()}
    m = mujoco.MjModel.from_xml_string(xml.read_text(), assets)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    moving = {"bridge": "bridge", "carriage": "carriage", "pipette_1000": "pip", "gripper": "gripper",
              "gripper_jaw_front": "jaw_f", "gripper_jaw_back": "jaw_b"}
    skipped = {"head", "head_focus", "vials_lw", "stocks_lw"}  # drawn by the page from labware definitions

    def rename(body):
        if body in skipped:
            return None
        return moving.get(body) or (body if body in ("door", "window_left", "window_right") else "static")

    info = export(
        m, d, sys.argv[2], rename,
        keep_separate=lambda n: (n.startswith("tips_") and len(n) <= 8) or n in ("pipette_1000_tip", "pipette_1000_tip_liquid"),
        world_nodes={"static", "door", "window_left", "window_right"},
    )
    ranges = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j): m.jnt_range[j].tolist() for j in range(m.njnt)}
    Path(sys.argv[3]).write_text(json.dumps({"bodies": info, "ranges": ranges}, indent=1))

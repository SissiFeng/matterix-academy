"""UR5e (Universal_Robots_ROS2_Description, BSD-3) + Robotiq 2F-140 (ros2_robotiq_gripper, BSD-3) -> one GLB.

UR link meshes are baked with their URDF visual offsets so each node sits in its link frame.
Robotiq parts stay in their own link frames.
"""
import math
import sys
from pathlib import Path

import numpy as np
import trimesh

# usage: build_ur5e_glb.py <Universal_Robots_ROS2_Description> <ros2_robotiq_gripper> <out.glb>
UR = f"{sys.argv[1]}/meshes/ur5e/visual/"
RQ = f"{sys.argv[2]}/robotiq_description/meshes/visual/2f_140/"
OUT = Path(sys.argv[3])


def T(xyz, rpy):
    """URDF origin: translation and roll-pitch-yaw (R = Rz Ry Rx)."""
    r, p, y = rpy
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    M = np.eye(4)
    M[:3, :3] = [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]
    M[:3, 3] = xyz
    return M
OFF = {
    "base": ((0, 0, 0), (0, 0, math.pi)),
    "shoulder": ((0, 0, 0), (0, 0, math.pi)),
    "upperarm": ((0, 0, 0.138), (math.pi / 2, 0, -math.pi / 2)),
    "forearm": ((0, 0, 0.007), (math.pi / 2, 0, -math.pi / 2)),
    "wrist1": ((0, 0, -0.127), (math.pi / 2, 0, 0)),
    "wrist2": ((0, 0, -0.0997), (0, 0, 0)),
    "wrist3": ((0, -0.0005, -0.0989), (math.pi / 2, 0, 0)),
}


def material(rgba, rough):
    return trimesh.visual.material.PBRMaterial(
        baseColorFactor=np.array(rgba, dtype=np.uint8), metallicFactor=0.1, roughnessFactor=rough, doubleSided=True)


def finish(mesh, rgba, rough, target_faces=None):
    mesh = trimesh.Trimesh(mesh.vertices.copy(), mesh.faces.copy(), process=True)
    if target_faces and len(mesh.faces) > target_faces:
        mesh = mesh.simplify_quadric_decimation(face_count=target_faces)
    mesh.fix_normals()
    mesh.visual = trimesh.visual.TextureVisuals(material=material(rgba, rough))
    return mesh


out = trimesh.Scene()
total = 0
for name, (xyz, rpy) in OFF.items():
    scene = trimesh.load(UR + name + ".dae", force="scene")
    for i, m in enumerate(scene.dump()):
        mat = getattr(m.visual, "material", None)
        bc = getattr(mat, "baseColorFactor", None)
        rgba = [int(v) for v in bc] if bc is not None else [180, 180, 180, 255]
        m.apply_transform(T(xyz, rpy))
        f = len(m.faces)
        m = finish(m, rgba, 0.4 if rgba[0] > 150 else 0.6, int(f * 0.5) if f > 3000 else None)
        total += len(m.faces)
        out.add_geometry(m, node_name=f"ur_{name}_{i}", geom_name=f"ur_{name}_{i}")

DARK, LIGHT = [36, 37, 40, 255], [214, 218, 226, 255]
for name in ["base_link", "outer_knuckle", "outer_finger", "inner_finger", "inner_knuckle", "coupling"]:
    m = trimesh.load(RQ + f"robotiq_2f_140_{name}.stl", force="mesh")
    if m.bounds.max() > 1:
        m.apply_scale(0.001)
    m = finish(m, LIGHT if name == "outer_knuckle" else DARK, 0.55, 6000)
    total += len(m.faces)
    out.add_geometry(m, node_name="rq_" + name, geom_name="rq_" + name)
out.export(OUT)
print("faces", total)

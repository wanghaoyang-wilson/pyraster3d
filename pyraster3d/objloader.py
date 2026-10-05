"""
objloader.py — OBJ 网格解析器
支持：v（顶点）、vn（法线）、vt（UV）、f（面，含 v/vt/vn 组合）、o/g（名称）。
坐标直接以左手系读取（OBJ 与 UE 兼容）。
"""
from __future__ import annotations

import os

from .model import Model


def load_obj(path: str, name: str = None) -> Model:
    """从 .obj 文件加载网格。返回 Model。"""
    verts, normals, uvs = [], [], []
    tris, tri_normals, tri_uvs = [], [], []

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            tag = parts[0]
            if tag == "v":
                verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif tag == "vn":
                normals.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif tag == "vt":
                uvs.append((float(parts[1]), float(parts[2]) if len(parts) > 2 else 0.0))
            elif tag == "f":
                face_v, face_vn, face_vt = [], [], []
                for token in parts[1:]:
                    # 兼容 v / v/vt / v/vt/vn / v//vn
                    seg = token.split("/")
                    vi = int(seg[0]) - 1
                    face_v.append(vi)
                    if len(seg) > 1 and seg[1]:
                        face_vt.append(int(seg[1]) - 1)
                    else:
                        face_vt.append(None)
                    if len(seg) > 2 and seg[2]:
                        face_vn.append(int(seg[2]) - 1)
                    else:
                        face_vn.append(None)
                # 扇形三角化
                for k in range(1, len(face_v) - 1):
                    tris.append((face_v[0], face_v[k], face_v[k + 1]))
                    tri_uvs.append((face_vt[0], face_vt[k], face_vt[k + 1]))
                    tri_normals.append((face_vn[0], face_vn[k], face_vn[k + 1]))

    if not verts:
        raise ValueError(f"OBJ 文件无顶点: {path}")

    # 构建逐顶点 UV / 法线（按面索引查找）
    # 由于 OBJ 索引可能复用，这里直接给每个顶点取第一个可用 UV/法线。
    nv = len(verts)
    v_uvs = [[0.0, 0.0]] * nv
    v_normals = [[0.0, 0.0, 0.0]] * nv
    have_uv = [False] * nv
    have_n = [False] * nv

    for (a, b, c), (ua, ub, uc), (na, nb, nc) in zip(tris, tri_uvs, tri_normals):
        for idx, uv, nrm in ((a, ua, na), (b, ub, nb), (c, uc, nc)):
            if uv is not None and not have_uv[idx] and uv < len(uvs):
                v_uvs[idx] = list(uvs[uv]); have_uv[idx] = True
            if nrm is not None and not have_n[idx] and nrm < len(normals):
                v_normals[idx] = list(normals[nrm]); have_n[idx] = True

    return Model(
        name=name or os.path.basename(path),
        vertices=verts,
        triangles=tris,
        uvs=v_uvs if any(have_uv) else [[0.0, 0.0]] * nv,
        normals=v_normals if any(have_n) else None,
    )

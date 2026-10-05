"""
primitives.py — 内置基础几何体生成器（代码生成，无需外部模型文件）
生成的几何体均为左手系、法线外翻、附带 UV。
"""
from __future__ import annotations

import math

from .model import Model


def _push_quad(verts, tris, uvs, normals, quad, n):
    """把 4 个位置元组追加为独立顶点，并拆成两个三角形（法线/UV 一并生成）。"""
    base = len(verts)
    for vi in quad:
        verts.append(vi)
        normals.append(n)
    uvs.append((0.0, 0.0)); uvs.append((1.0, 0.0))
    uvs.append((0.0, 1.0)); uvs.append((1.0, 1.0))
    tris.append((base + 0, base + 1, base + 2))
    tris.append((base + 1, base + 3, base + 2))


def cube(size: float = 1.0, name: str = "cube") -> Model:
    """单位立方体，中心在原点。"""
    s = size * 0.5
    # 每个面独立 4 个顶点（法线正确、可平铺 UV），由 _push_quad 追加
    corners = {
        "n0": (-s, -s, -s), "n1": (s, -s, -s), "n2": (s, s, -s), "n3": (-s, s, -s),
        "p0": (-s, -s,  s), "p1": (s, -s,  s), "p2": (s, s,  s), "p3": (-s, s,  s),
    }
    v = corners
    tris, uvs, normals, verts = [], [], [], []
    faces = [
        (("n0", "n1", "n2", "n3"), (0, 0, -1)),   # 前 -Z
        (("p1", "p0", "p3", "p2"), (0, 0, 1)),    # 后 +Z
        (("p0", "n0", "n3", "p3"), (-1, 0, 0)),   # 左 -X
        (("n1", "p1", "p2", "n2"), (1, 0, 0)),    # 右 +X
        (("p0", "p1", "n1", "n0"), (0, -1, 0)),   # 下 -Y
        (("n3", "n2", "p2", "p3"), (0, 1, 0)),    # 上 +Y
    ]
    for (a, b, c, d), n in faces:
        _push_quad(verts, tris, uvs, normals, [v[a], v[b], v[c], v[d]], n)
    return Model(name=name, vertices=verts, triangles=tris, uvs=uvs, normals=normals)


def plane(width: float = 1.0, height: float = 1.0, name: str = "plane") -> Model:
    """XZ 平面（Y=0），法线朝 +Y。"""
    w, h = width * 0.5, height * 0.5
    v = [(-w, 0, -h), (w, 0, -h), (w, 0, h), (-w, 0, h)]
    tris, uvs, normals, verts = [], [], [], []
    _push_quad(verts, tris, uvs, normals, v, (0.0, 1.0, 0.0))
    return Model(name=name, vertices=verts, triangles=tris, uvs=uvs, normals=normals)


def sphere(radius: float = 0.5, stacks: int = 16, slices: int = 16,
           name: str = "sphere") -> Model:
    """经纬球体。"""
    verts, tris, uvs, normals = [], [], [], []
    for i in range(stacks + 1):
        theta = math.pi * i / stacks
        y = radius * math.cos(theta)
        r = radius * math.sin(theta)
        for j in range(slices + 1):
            phi = 2.0 * math.pi * j / slices
            x = r * math.cos(phi)
            z = r * math.sin(phi)
            verts.append((x, y, z))
            uvs.append((j / slices, i / stacks))
            normals.append((x / radius, y / radius, z / radius))
    for i in range(stacks):
        for j in range(slices):
            a = i * (slices + 1) + j
            b = a + slices + 1
            tris.append((a, b, a + 1))
            tris.append((a + 1, b, b + 1))
    return Model(name=name, vertices=verts, triangles=tris, uvs=uvs, normals=normals)


def cylinder(radius: float = 0.4, height: float = 1.0, slices: int = 24,
             name: str = "cylinder") -> Model:
    """圆柱体，沿 Y 轴。"""
    h = height * 0.5
    verts, tris, uvs, normals = [], [], [], []
    side_start = len(verts)
    for j in range(slices + 1):
        phi = 2.0 * math.pi * j / slices
        x, z = radius * math.cos(phi), radius * math.sin(phi)
        verts.append((x, -h, z)); normals.append((x / radius, 0.0, z / radius))
        verts.append((x,  h, z)); normals.append((x / radius, 0.0, z / radius))
        uvs.append((j / slices, 0.0)); uvs.append((j / slices, 1.0))
    for j in range(slices):
        a = side_start + j * 2
        tris.append((a, a + 1, a + 2))
        tris.append((a + 1, a + 3, a + 2))
    # 顶盖（+Y）
    top_start = len(verts)
    verts.append((0.0, h, 0.0)); normals.append((0.0, 1.0, 0.0)); uvs.append((0.5, 0.5))
    for j in range(slices):
        phi = 2.0 * math.pi * j / slices
        verts.append((radius * math.cos(phi), h, radius * math.sin(phi)))
        normals.append((0.0, 1.0, 0.0))
        uvs.append((0.5 + 0.5 * math.cos(phi), 0.5 + 0.5 * math.sin(phi)))
    for j in range(slices):
        a = top_start + 1 + j
        b = top_start + 1 + ((j + 1) % slices)
        tris.append((top_start, b, a))
    # 底盖（-Y）
    bot_start = len(verts)
    verts.append((0.0, -h, 0.0)); normals.append((0.0, -1.0, 0.0)); uvs.append((0.5, 0.5))
    for j in range(slices):
        phi = 2.0 * math.pi * j / slices
        verts.append((radius * math.cos(phi), -h, radius * math.sin(phi)))
        normals.append((0.0, -1.0, 0.0))
        uvs.append((0.5 + 0.5 * math.cos(phi), 0.5 + 0.5 * math.sin(phi)))
    for j in range(slices):
        a = bot_start + 1 + j
        b = bot_start + 1 + ((j + 1) % slices)
        tris.append((bot_start, a, b))
    return Model(name=name, vertices=verts, triangles=tris, uvs=uvs, normals=normals)


# 内置几何体注册表
PRIMITIVE_FACTORIES = {
    "cube": cube,
    "plane": plane,
    "sphere": sphere,
    "cylinder": cylinder,
}

PRIMITIVE_NAMES = list(PRIMITIVE_FACTORIES.keys())


def build_primitive(kind: str) -> Model:
    kind = kind.lower()
    if kind not in PRIMITIVE_FACTORIES:
        raise KeyError(f"未知基础几何体: {kind}，可选 {PRIMITIVE_NAMES}")
    return PRIMITIVE_FACTORIES[kind]()

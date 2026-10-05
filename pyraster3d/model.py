"""
model.py — 模型数据容器（顶点 / 三角面 / UV / 法线 / 材质）
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .material import Material, SolidColorMaterial


class Model:
    """
    一个网格资源（相当于 UE 里的 Static Mesh / Geometry 资产）。
    顶点为局部坐标（左手系），三角面为索引三元组。
    """

    def __init__(
        self,
        name: str = "mesh",
        vertices: Optional[list] = None,
        triangles: Optional[list] = None,
        uvs: Optional[list] = None,
        normals: Optional[list] = None,
        material: Optional[Material] = None,
    ):
        self.name = name
        self.vertices = np.asarray(vertices or [], dtype=np.float64).reshape(-1, 3)
        self.triangles = [tuple(t) for t in (triangles or [])]
        self.uvs = np.asarray(uvs or [[0, 0]] * len(self.vertices), dtype=np.float64).reshape(-1, 2)
        self.material = material or SolidColorMaterial((180, 180, 180))
        if normals is not None:
            self.normals = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
        else:
            self.normals = self._compute_normals()
        self._world_cache = None   # (world_matrix, transformed_vertices)

    # ------------------------------------------------------------------ #
    # 法线计算（未提供法线时：面法线 -> 顶点法线平均）
    # ------------------------------------------------------------------ #
    def _compute_normals(self) -> np.ndarray:
        n = len(self.vertices)
        normals = np.zeros((n, 3), dtype=np.float64)
        for (i, j, k) in self.triangles:
            a, b, c = self.vertices[i], self.vertices[j], self.vertices[k]
            face = np.cross(b - a, c - a)
            fn = np.linalg.norm(face)
            if fn > 1e-12:
                face = face / fn
                normals[i] += face
                normals[j] += face
                normals[k] += face
        for r in range(n):
            ln = np.linalg.norm(normals[r])
            if ln > 1e-12:
                normals[r] /= ln
        return normals

    # ------------------------------------------------------------------ #
    # 顶点变换缓存（供渲染器使用；世界矩阵变化时失效）
    # ------------------------------------------------------------------ #
    def transform(self, world_matrix: np.ndarray):
        """返回 (变换后顶点, 变换后法线)。带缓存避免重复矩阵运算。"""
        if self._world_cache is not None and self._world_cache[0] is world_matrix:
            return self._world_cache[1]
        ones = np.ones((len(self.vertices), 1), dtype=np.float64)
        v4 = np.hstack([self.vertices, ones])            # (n,4)
        wv = (v4 @ world_matrix.T)[:, :3]                 # (n,3)
        # 法线：用模型矩阵的旋转部分（忽略平移/非均匀缩放的近似）
        rot3 = world_matrix[:3, :3]
        wn = (self.normals @ rot3.T)
        for r in range(len(wn)):
            ln = np.linalg.norm(wn[r])
            if ln > 1e-12:
                wn[r] /= ln
        self._world_cache = (world_matrix, (wv, wn))
        return (wv, wn)

    def invalidate_cache(self):
        self._world_cache = None

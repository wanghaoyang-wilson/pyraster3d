"""
bvh.py — Bounding Volume Hierarchy 加速结构
用于：场景拾取（raycast）、轻度光线追踪（阴影射线 / 反射射线）。
BVH 在后台线程异步构建（见 tasks.py），主线程只读。
"""
from __future__ import annotations

import time
from typing import List, Optional

import numpy as np

from .scene import Scene, Entity


class BVH:
    """
    对场景中所有世界空间三角形构建的 BVH。
    构建时把三角形原地重排进全局数组，叶节点用 (tri_start, tri_count) 描述区间。
    每个三角形附带所属实体与「实体内三角面编号」（用于 UV/法线查询）。
    """

    def __init__(self):
        self.empty = True
        self.build_time_ms = 0.0

        # 重排后的全局三角形数组
        self.v0 = np.zeros((0, 3))
        self.v1 = np.zeros((0, 3))
        self.v2 = np.zeros((0, 3))
        self.centers = np.zeros((0, 3))
        self.entities: List[Optional[Entity]] = []
        self.tri_in_entity: List[int] = []     # 该三角形在实体模型内的面编号

        # 节点：每个节点为 (aabb_min, aabb_max, left, right, tri_start, tri_count)
        # left/right 为节点索引；-1 表示无（叶节点）
        self.aabb_min = []
        self.aabb_max = []
        self.left = []
        self.right = []
        self.tri_start = []
        self.tri_count = []

    # ------------------------------------------------------------------ #
    # 构建
    # ------------------------------------------------------------------ #
    def build(self, scene: Scene) -> None:
        t0 = time.perf_counter()
        v0s, v1s, v2s, ents, tris_in_ent = [], [], [], [], []
        for entity in scene.entities:
            if not entity.visible or entity.model is None:
                continue
            wv, _ = entity.world_vertices()
            if len(wv) == 0:
                continue
            model_tris = entity.model.triangles
            for ti, (i, j, k) in enumerate(model_tris):
                if i >= len(wv) or j >= len(wv) or k >= len(wv):
                    continue
                v0s.append(wv[i]); v1s.append(wv[j]); v2s.append(wv[k])
                ents.append(entity); tris_in_ent.append(ti)

        if not v0s:
            self.empty = True
            return

        self.v0 = np.asarray(v0s)
        self.v1 = np.asarray(v1s)
        self.v2 = np.asarray(v2s)
        self.centers = (self.v0 + self.v1 + self.v2) / 3.0
        self.entities = ents
        self.tri_in_entity = tris_in_ent
        self.empty = False

        self.aabb_min = []
        self.aabb_max = []
        self.left = []
        self.right = []
        self.tri_start = []
        self.tri_count = []

        order = list(range(len(ents)))
        self._build_recursive(order, 0)
        self.build_time_ms = (time.perf_counter() - t0) * 1000.0

    def _build_recursive(self, order: List[int], depth: int) -> int:
        count = len(order)
        node_idx = len(self.aabb_min)
        self.aabb_min.append(np.zeros(3))
        self.aabb_max.append(np.zeros(3))
        self.left.append(-1)
        self.right.append(-1)
        self.tri_start.append(0)
        self.tri_count.append(count)

        sub = self.v0[order]
        minp = sub.min(axis=0)
        maxp = sub.max(axis=0)
        for arr in (self.v1[order], self.v2[order]):
            minp = np.minimum(minp, arr.min(axis=0))
            maxp = np.maximum(maxp, arr.max(axis=0))
        self.aabb_min[node_idx] = minp
        self.aabb_max[node_idx] = maxp

        if count <= 4 or depth >= 18:
            # 叶节点：把 order 重排进全局数组对应区间
            base = len(self.v0) - count if False else self._reorder(order)
            self.tri_start[node_idx] = base
            self.tri_count[node_idx] = count
            return node_idx

        ext = maxp - minp
        axis = int(np.argmax(ext))
        mid = (minp[axis] + maxp[axis]) * 0.5
        centers = self.centers[order][:, axis]
        left = [order[i] for i in range(count) if centers[i] <= mid]
        right = [order[i] for i in range(count) if centers[i] > mid]
        if not left or not right:
            half = count // 2
            left = order[:half]
            right = order[half:]

        l_idx = self._build_recursive(left, depth + 1)
        r_idx = self._build_recursive(right, depth + 1)
        self.left[node_idx] = l_idx
        self.right[node_idx] = r_idx
        self.tri_start[node_idx] = self.tri_start[l_idx]
        self.tri_count[node_idx] = self.tri_count[l_idx] + self.tri_count[r_idx]
        return node_idx

    def _reorder(self, order: List[int]) -> int:
        """把 order 中的三角形移动/复制到数组尾部连续区段，返回起始下标。"""
        # 为简洁：将重排后的三角形直接覆盖到当前已用区间的末尾（就地紧凑化）
        # 这里采用「复制到新数组尾部」的简单策略：每次在末尾追加并返回起始位置。
        base = len(self.v0)
        new_v0 = self.v0[order]
        new_v1 = self.v1[order]
        new_v2 = self.v2[order]
        new_centers = self.centers[order]
        new_ent = [self.entities[i] for i in order]
        new_tri = [self.tri_in_entity[i] for i in order]

        self.v0 = np.concatenate([self.v0, new_v0])
        self.v1 = np.concatenate([self.v1, new_v1])
        self.v2 = np.concatenate([self.v2, new_v2])
        self.centers = np.concatenate([self.centers, new_centers])
        self.entities.extend(new_ent)
        self.tri_in_entity.extend(new_tri)
        return base

    # ------------------------------------------------------------------ #
    # 求交
    # ------------------------------------------------------------------ #
    def intersect(self, origin, direction, max_t=1e9):
        """
        返回最近的 (t, entity, global_tri_index, bary_uv) 或 None。
        """
        if self.empty or not self.aabb_min:
            return None
        o = np.asarray(origin, dtype=np.float64)
        d = np.asarray(direction, dtype=np.float64)
        d = d / (np.linalg.norm(d) + 1e-12)

        best_t = max_t
        best = None
        stack = [0]
        n = len(self.aabb_min)
        while stack:
            ni = stack.pop()
            if ni < 0 or ni >= n:
                continue
            if not self._aabb_hit(ni, o, d, best_t):
                continue
            if self.left[ni] == -1:
                start = self.tri_start[ni]
                for g in range(start, start + self.tri_count[ni]):
                    t, u, v = self._tri_intersect(g, o, d)
                    if t is not None and 0 < t < best_t:
                        best_t = t
                        best = (t, self.entities[g], g, (u, v))
            else:
                stack.append(self.right[ni])
                stack.append(self.left[ni])
        return best

    def _aabb_hit(self, ni, o, d, tmax) -> bool:
        mn = self.aabb_min[ni]
        mx = self.aabb_max[ni]
        inv = np.empty(3)
        for ax in range(3):
            inv[ax] = 1.0 / d[ax] if abs(d[ax]) > 1e-12 else 1e9
        t0 = (mn - o) * inv
        t1 = (mx - o) * inv
        tmin = np.minimum(t0, t1).max()
        tmaxv = np.maximum(t0, t1).min()
        return tmin <= tmaxv and tmaxv >= 0 and tmin < tmax

    def _tri_intersect(self, gi, o, d):
        v0 = self.v0[gi]; v1 = self.v1[gi]; v2 = self.v2[gi]
        e1 = v1 - v0
        e2 = v2 - v0
        p = np.cross(d, e2)
        det = np.dot(e1, p)
        if abs(det) < 1e-12:
            return None, 0.0, 0.0
        inv = 1.0 / det
        s = o - v0
        u = np.dot(s, p) * inv
        if u < 0.0 or u > 1.0:
            return None, 0.0, 0.0
        q = np.cross(s, e1)
        v = np.dot(d, q) * inv
        if v < 0.0 or u + v > 1.0:
            return None, 0.0, 0.0
        t = np.dot(e2, q) * inv
        if t <= 1e-6:
            return None, 0.0, 0.0
        return t, u, v

    def world_pos_normal_uv(self, gi, o, d, t, u, v):
        """由交点重心坐标计算世界坐标、法线、UV（用于拾取/光追着色）。"""
        w = 1.0 - u - v
        pos = w * self.v0[gi] + u * self.v1[gi] + v * self.v2[gi]
        normal = np.cross(self.v1[gi] - self.v0[gi], self.v2[gi] - self.v0[gi])
        ln = np.linalg.norm(normal)
        normal = normal / ln if ln > 1e-12 else np.array([0, 1, 0])
        entity = self.entities[gi]
        tri = entity.model.triangles[self.tri_in_entity[gi]]
        uv = (0.5, 0.5)
        if entity.model is not None and entity.model.uvs is not None:
            try:
                uv = (w * entity.model.uvs[tri[0]][0] + u * entity.model.uvs[tri[1]][0] +
                      v * entity.model.uvs[tri[2]][0],
                      w * entity.model.uvs[tri[0]][1] + u * entity.model.uvs[tri[1]][1] +
                      v * entity.model.uvs[tri[2]][1])
            except Exception:
                uv = (0.5, 0.5)
        return pos, normal, uv


def build_scene_bvh(scene: Scene) -> BVH:
    bvh = BVH()
    bvh.build(scene)
    return bvh

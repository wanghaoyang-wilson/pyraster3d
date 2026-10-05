"""
shadowmap.py — 阴影贴图（Shadow Map）
思路：从平行光方向渲染一张深度图，主渲染时把片元投影回光源空间，比较深度得出阴影因子。
阴影贴图在后台线程异步重建（见 tasks.py / renderer.py）。
"""
from __future__ import annotations

import numpy as np

from .matrix import look_at_lh


class ShadowMap:
    def __init__(self, size: int = 512, extent: float = 20.0,
                 z_near: float = 1.0, z_far: float = 200.0,
                 bias: float = 0.004):
        self.size = size
        self.extent = extent
        self.z_near = z_near
        self.z_far = z_far
        self.bias = bias
        self.depth = np.full((size, size), 1.0, dtype=np.float64)  # 归一化深度 [0,1]
        self.view = np.eye(4)
        self.light_eye = np.array([10.0, 10.0, 10.0])
        self.center = np.array([0.0, 0.0, 0.0])

    # ------------------------------------------------------------------ #
    # 构建（光源视角深度图）
    # ------------------------------------------------------------------ #
    def build(self, scene, light_dir, up=(0, 1, 0)):
        # 场景中心/包围
        center, extent = self._scene_center_extent(scene)
        self.center = center
        self.extent = max(extent, 1.0)
        ld = np.asarray(light_dir, dtype=np.float64)
        ld = ld / (np.linalg.norm(ld) + 1e-12)
        light_eye = center + ld * (self.z_far * 0.9)   # 光源置于上方（ld 指向光源）
        self.light_eye = light_eye
        self.view = look_at_lh(light_eye, center, up)

        z = self.size
        depth = np.full((z, z), 1.0, dtype=np.float64)

        # 光空间正交投影参数
        half = self.extent
        for entity in scene.entities:
            if not entity.visible or entity.model is None or not entity.cast_shadow:
                continue
            wv, _ = entity.world_vertices()
            if len(wv) == 0:
                continue
            # 顶点转到光空间
            v4 = np.hstack([wv, np.ones((len(wv), 1))]) @ self.view.T
            cx, cy, cz = v4[:, 0], v4[:, 1], v4[:, 2]
            px = cx * (z / (2 * half)) + z / 2
            py = z / 2 - cy * (z / (2 * half))
            pz = (cz - self.z_near) / (self.z_far - self.z_near)
            for (i, j, k) in entity.model.triangles:
                if i >= len(px) or j >= len(px) or k >= len(px):
                    continue
                self._fill_depth(depth, px[i], py[i], pz[i],
                                 px[j], py[j], pz[j],
                                 px[k], py[k], pz[k], z)
        self.depth = depth

    def _fill_depth(self, depth, x0, y0, z0, x1, y1, z1, x2, y2, z2, z):
        minx = int(max(0, min(x0, x1, x2)))
        maxx = int(min(z - 1, max(x0, x1, x2)))
        miny = int(max(0, min(y0, y1, y2)))
        maxy = int(min(z - 1, max(y0, y1, y2)))
        if maxx < minx or maxy < miny:
            return
        area = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
        if abs(area) < 1e-9:
            return
        inv = 1.0 / abs(area)
        flip = area < 0

        px = np.arange(minx, maxx + 1)[None, :]
        py = np.arange(miny, maxy + 1)[:, None]
        Px = np.broadcast_to(px, (maxy - miny + 1, maxx - minx + 1)).astype(np.float64)
        Py = np.broadcast_to(py, (maxy - miny + 1, maxx - minx + 1)).astype(np.float64)

        def e(a, b, X, Y):
            return (b[0] - a[0]) * (Y - a[1]) - (b[1] - a[1]) * (X - a[0])

        w0 = e((x1, y1), (x2, y2), Px, Py)
        w1 = e((x2, y2), (x0, y0), Px, Py)
        w2 = e((x0, y0), (x1, y1), Px, Py)
        if flip:
            w0, w1, w2 = -w0, -w1, -w2
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            return
        b0 = w0 * inv
        b1 = w1 * inv
        b2 = w2 * inv
        zd = b0 * z0 + b1 * z1 + b2 * z2
        region = depth[miny:maxy + 1, minx:maxx + 1]
        # 用 numpy 最小写入：在区域内取 min（离光源近的更小深度）
        new_depth = np.where(inside, zd, region)
        # 采用更近（更小）的深度
        region[:] = np.minimum(region, new_depth)

    def _scene_center_extent(self, scene):
        mins = []
        maxs = []
        for e in scene.entities:
            if not e.visible or e.model is None or not e.cast_shadow:
                continue
            bb = e.bounding_box()
            if bb is None:
                continue
            mn, mx = bb
            mins.append(mn); maxs.append(mx)
        if not mins:
            return np.array([0.0, 0.0, 0.0]), 5.0
        mn = np.min(np.array(mins), axis=0)
        mx = np.max(np.array(maxs), axis=0)
        center = (mn + mx) / 2.0
        extent = float(np.max(mx - mn)) * 0.6 + 1.0
        return center, extent

    # ------------------------------------------------------------------ #
    # 采样
    # ------------------------------------------------------------------ #
    def sample(self, wx, wy, wz):
        """世界坐标 -> 光空间 -> 深度比较。返回光照因子 1=亮 0=阴影。"""
        z = self.size
        pts = np.stack([wx, wy, wz, np.ones_like(wx)], axis=-1) @ self.view.T
        cx, cy, cz = pts[:, 0], pts[:, 1], pts[:, 2]
        half = self.extent
        px = cx * (z / (2 * half)) + z / 2
        py = z / 2 - cy * (z / (2 * half))
        pz = (cz - self.z_near) / (self.z_far - self.z_near)
        xi = np.clip(np.floor(px).astype(int), 0, z - 1)
        yi = np.clip(np.floor(py).astype(int), 0, z - 1)
        stored = self.depth[yi, xi]
        lit = (pz <= stored + self.bias) & (cz > self.z_near) & (cz < self.z_far)
        return lit.astype(np.float64)

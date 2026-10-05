"""
renderer.py — 渲染管线（软光栅主循环）
流程：
  1. 清空帧缓存/深度缓存（天空色填充）
  2. 对每个实体：世界顶点 -> 相机空间 -> 透视投影 -> 屏幕三角形
  3. 不透明三角形：Z-Buffer 光栅化
  4. 透明三角形：按面中心深度由远到近（画家算法）叠加绘制
  5. 可选轻度光追：反射后处理（G-Buffer + BVH 反射射线）
返回 numpy 帧缓存（由 App 转为 Pygame Surface 呈现）。
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .camera import Camera
from .rasterizer import rasterize_triangle, ShaderConfig, make_vertex
from .scene import Scene, Entity


class Renderer:
    def __init__(self, width=800, height=600):
        self.width = width
        self.height = height
        self.framebuffer = np.zeros((height, width, 3), dtype=np.float64)
        self.zbuffer = np.full((height, width), np.inf, dtype=np.float64)
        self.shader = ShaderConfig()
        self.shadow_map = None
        self.enable_shadows = False
        self.enable_raytracing = False
        self.raytracing_bounces = 1
        self.raytrace_shadow = False
        self.raytrace_ao = False
        self.sky_color = (24, 26, 34)
        self.gbuffer = None

    def resize(self, width, height):
        self.width = width
        self.height = height
        self.framebuffer = np.zeros((height, width, 3), dtype=np.float64)
        self.zbuffer = np.full((height, width), np.inf, dtype=np.float64)

    # ------------------------------------------------------------------ #
    # 配置（来自 config / app）
    # ------------------------------------------------------------------ #
    def apply_config(self, cfg: dict):
        r = cfg.get("renderer", {})
        self.enable_shadows = r.get("shadows", True)
        self.enable_raytracing = r.get("raytracing", False)
        self.raytracing_bounces = r.get("max_bounces", 1)
        self.raytrace_shadow = r.get("raytrace_shadows", False)
        self.raytrace_ao = r.get("raytrace_ao", False)
        self.shader.edge_depth_sample = r.get("edge_depth_sampling", True)
        self.shader.cull_backface = r.get("cull_backface", True)
        self.shader.ambient = tuple(r.get("ambient", self.shader.ambient))
        self.shader.sun_color = tuple(r.get("sun_color", self.shader.sun_color))
        sd = r.get("sun_direction")
        if sd is not None:
            arr = np.array(sd, dtype=np.float64)
            self.shader.sun_dir = tuple(arr / (np.linalg.norm(arr) + 1e-12))

    # ------------------------------------------------------------------ #
    # 主渲染
    # ------------------------------------------------------------------ #
    def render(self, scene: Scene, camera: Camera) -> np.ndarray:
        W, H = self.width, self.height
        camera.width, camera.height = W, H
        fb = self.framebuffer
        zb = self.zbuffer
        fb[:] = self.sky_color
        zb[:] = np.inf

        side, up, forward = camera.basis()
        eye = np.array(camera.position, dtype=np.float64)
        focal = camera.focal()
        z_near = camera.z_near
        cfg = self.shader

        # 场景灯光配置
        cfg.ambient = scene.ambient
        sd = np.array(scene.sun_direction, dtype=np.float64)
        sd = sd / (np.linalg.norm(sd) + 1e-12)
        cfg.sun_dir = tuple(sd)
        cfg.sun_color = tuple(scene.sun_color)
        self.sky_color = scene.sky_color

        if self.enable_shadows and self.shadow_map is not None:
            cfg.enable_shadows = True
        else:
            cfg.enable_shadows = False

        transparent = []   # (depth, v0, v1, v2, material, alpha, receive_shadow)

        for entity in scene.entities:
            if not entity.visible or entity.model is None:
                continue
            mat = entity.material
            # 确保贴图数组就绪
            ensure_tex = getattr(mat, "_ensure_array", None)
            if ensure_tex is not None:
                ensure_tex()
            wv, wn = entity.world_vertices()
            if len(wv) == 0:
                continue
            tris = entity.model.triangles
            uvs = entity.model.uvs
            base_rgb = np.array(mat.color, dtype=np.float64) if hasattr(mat, "color") \
                else np.array([180, 180, 180], dtype=np.float64)

            # 世界 -> 相机空间
            rel = wv - eye[None, :]
            cam = np.empty_like(wv)
            cam[:, 0] = rel @ side
            cam[:, 1] = rel @ up
            cam[:, 2] = rel @ forward

            alpha = mat.alpha
            is_transparent = (not entity.solid) or getattr(mat, "transparent", False)

            for (i, j, k) in tris:
                if i >= len(cam) or j >= len(cam) or k >= len(cam):
                    continue
                cz = (cam[i, 2], cam[j, 2], cam[k, 2])
                if min(cz) < z_near:
                    continue
                # 投影
                def proj(idx):
                    sc = focal / cam[idx, 2]
                    sx = W / 2 + cam[idx, 0] * sc
                    sy = H / 2 - cam[idx, 1] * sc
                    return sx, sy

                s0 = proj(i); s1 = proj(j); s2 = proj(k)
                v0 = make_vertex(s0[0], s0[1], cz[0], wv[i], wn[i], uvs[i] if len(uvs) > i else (0, 0), base_rgb)
                v1 = make_vertex(s1[0], s1[1], cz[1], wv[j], wn[j], uvs[j] if len(uvs) > j else (0, 0), base_rgb)
                v2 = make_vertex(s2[0], s2[1], cz[2], wv[k], wn[k], uvs[k] if len(uvs) > k else (0, 0), base_rgb)

                if is_transparent:
                    center = (cz[0] + cz[1] + cz[2]) / 3.0
                    transparent.append((center, v0, v1, v2, mat, alpha,
                                        entity.receive_shadow))
                else:
                    rasterize_triangle(fb, zb, v0, v1, v2, mat, cfg,
                                       write_depth=True, alpha=1.0,
                                       receive_shadow=entity.receive_shadow)

        # 透明物体：画家算法（远 -> 近）
        transparent.sort(key=lambda t: t[0], reverse=True)
        for center, v0, v1, v2, mat, alpha, rsh in transparent:
            rasterize_triangle(fb, zb, v0, v1, v2, mat, cfg,
                               write_depth=False, alpha=alpha,
                               receive_shadow=rsh)

        # 可选轻度光追反射
        if self.enable_raytracing:
            self._build_gbuffer(scene, camera)
            from .raytrace import apply_reflection_pass
            apply_reflection_pass(fb, self.gbuffer, scene._bvh if hasattr(scene, "_bvh") else None,
                                  max_bounces=self.raytracing_bounces,
                                  sun_dir=tuple(sd), sun_color=tuple(scene.sun_color))

        return fb

    def _build_gbuffer(self, scene, camera):
        """为光追反射构建 G-Buffer（世界坐标/法线/反射率）。"""
        H, W = self.height, self.width
        if self.gbuffer is None:
            self.gbuffer = {
                "world_pos": np.zeros((H, W, 3), dtype=np.float64),
                "normal": np.zeros((H, W, 3), dtype=np.float64),
                "reflectivity": np.zeros((H, W), dtype=np.float64),
            }
        g = self.gbuffer
        g["reflectivity"][:] = 0.0
        # 复用当前帧缓存有内容的位置，从已渲染像素近似：这里在反射 pass 内直接
        # 用阴影贴图式几何信息会复杂，故反射率仅基于材质并交给 raytrace 模块逐像素。
        # 简化：直接标记所有已绘制像素（非天空）为潜在反射源（见 apply_reflection 的 mask）。
        for entity in scene.entities:
            if not entity.visible or entity.model is None:
                continue
            if entity.material is None or entity.material.reflectivity <= 0.01:
                continue
            # 通过再次投影填充反射率掩码
            wv, wn = entity.world_vertices()
            if len(wv) == 0:
                continue
            side, up, forward = camera.basis()
            eye = np.array(camera.position, dtype=np.float64)
            focal = camera.focal()
            rel = wv - eye[None, :]
            cam = np.empty_like(wv)
            cam[:, 0] = rel @ side; cam[:, 1] = rel @ up; cam[:, 2] = rel @ forward
            for (i, j, k) in entity.model.triangles:
                if min(cam[i, 2], cam[j, 2], cam[k, 2]) < camera.z_near:
                    continue
                pts = []
                for idx in (i, j, k):
                    sc = focal / cam[idx, 2]
                    pts.append((W / 2 + cam[idx, 0] * sc, H / 2 - cam[idx, 1] * sc))
                self._fill_gbuffer_tri(g, pts,
                                       (wv[i], wv[j], wv[k]),
                                       (wn[i], wn[j], wn[k]),
                                       entity.material.reflectivity)

    def _fill_gbuffer_tri(self, g, pts, wps, nrm, refl):
        minx = int(max(0, min(p[0] for p in pts)))
        maxx = int(min(self.width - 1, max(p[0] for p in pts)))
        miny = int(max(0, min(p[1] for p in pts)))
        maxy = int(min(self.height - 1, max(p[1] for p in pts)))
        if maxx < minx or maxy < miny:
            return
        (x0, y0), (x1, y1), (x2, y2) = pts
        area = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
        if abs(area) < 1e-9:
            return
        inv = 1.0 / abs(area)
        flip = area < 0
        px = np.arange(minx, maxx + 1)[None, :]
        py = np.arange(miny, maxy + 1)[:, None]
        Px = np.broadcast_to(px, (maxy - miny + 1, maxx - minx + 1)).astype(np.float64)
        Py = np.broadcast_to(py, (maxy - miny + 1, maxx - minx + 1)).astype(np.float64)

        def e(a, b):
            return (b[0] - a[0]) * (Py - a[1]) - (b[1] - a[1]) * (Px - a[0])

        w0 = e((x1, y1), (x2, y2)); w1 = e((x2, y2), (x0, y0)); w2 = e((x0, y0), (x1, y1))
        if flip:
            w0, w1, w2 = -w0, -w1, -w2
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            return
        b0 = w0 * inv; b1 = w1 * inv; b2 = w2 * inv
        region_pos = g["world_pos"][miny:maxy + 1, minx:maxx + 1]
        region_n = g["normal"][miny:maxy + 1, minx:maxx + 1]
        region_r = g["reflectivity"][miny:maxy + 1, minx:maxx + 1]
        wp0, wp1, wp2 = wps
        n0, n1, n2 = nrm
        for c in range(3):
            region_pos[inside, c] = (b0 * wp0[c] + b1 * wp1[c] + b2 * wp2[c])[inside]
            region_n[inside, c] = (b0 * n0[c] + b1 * n1[c] + b2 * n2[c])[inside]
        region_r[inside] = refl

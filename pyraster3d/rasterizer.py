"""
rasterizer.py — 软光栅核心（软件三角形光栅化 + 逐像素着色）
特性：
- Z-Buffer 深度缓冲（不透明物体）
- 可选「仅边缘深度采样」优化（压榨老硬件）：三角形内部像素跳过深度比较，
  只对靠近三条边/顶点的像素做完整深度测试。
- 不透明像素写深度；透明像素由上层用画家算法叠加（本模块负责着色+混合）。
- 逐像素 Lambert + 简易 Blinn-Phong 高光；可选阴影贴图采样；贴图双线性采样。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# --------------------------------------------------------------------------- #
# 顶点格式：一张三角形 = 3 个顶点，每个顶点为 1D 数组
# idx: 0 sx,1 sy,2 depth(camera-z),3-5 world pos,6-8 normal,9-10 uv,11-13 base rgb
# --------------------------------------------------------------------------- #
SX, SY, DEPTH, WX, WY, WZ, NX, NY, NZ, UU, VV, R, G, B = range(14)
NV = 14


def make_vertex(sx, sy, depth, wp, nrm, uv, color):
    return np.array([sx, sy, depth, wp[0], wp[1], wp[2],
                     nrm[0], nrm[1], nrm[2], uv[0], uv[1],
                     color[0], color[1], color[2]], dtype=np.float64)


@dataclass
class ShaderConfig:
    ambient: tuple = (0.16, 0.16, 0.20)
    sun_dir: tuple = (0.4, -0.8, 0.45)      # 指向光源的单位向量（世界空间）
    sun_color: tuple = (1.0, 0.98, 0.94)
    specular_strength: float = 0.35
    specular_power: float = 24.0
    enable_shadows: bool = False
    shadow_map: object = None               # ShadowMap 实例
    shadow_intensity: float = 0.55
    edge_depth_sample: bool = False         # 仅边缘深度采样
    edge_threshold: float = 0.02            # 边缘判定阈值（重心坐标）
    cull_backface: bool = True
    wireframe: bool = False
    wire_color: tuple = (255, 255, 255)


def _material_base_rgb(material) -> np.ndarray:
    if material is not None and hasattr(material, "color"):
        return np.array(material.color, dtype=np.float64)
    return np.array([180, 180, 180], dtype=np.float64)


def sample_texture_array(material, u, v) -> np.ndarray:
    """向量化贴图采样（nearest / bilinear），返回 (n,3)。"""
    tex = getattr(material, "_tex_array", None)
    if tex is None:
        base = _material_base_rgb(material)
        return np.broadcast_to(base, (u.shape[0], 3)).copy()
    th, tw = tex.shape[0], tex.shape[1]
    uu = np.mod(u, 1.0) if material.repeat else np.clip(u, 0, 1)
    vv = np.mod(v, 1.0) if material.repeat else np.clip(v, 0, 1)
    x = uu * tw
    y = vv * th
    if material.filtering == "nearest":
        xi = np.clip(np.floor(x).astype(int), 0, tw - 1)
        yi = np.clip(np.floor(y).astype(int), 0, th - 1)
        return tex[yi, xi]
    x0 = np.floor(x).astype(int) % tw
    x1 = (x0 + 1) % tw
    y0 = np.floor(y).astype(int) % th
    y1 = (y0 + 1) % th
    fx = (x - np.floor(x))[:, None]
    fy = (y - np.floor(y))[:, None]
    c = (tex[y0, x0] * (1 - fx) * (1 - fy) +
         tex[y0, x1] * fx * (1 - fy) +
         tex[y1, x0] * (1 - fx) * fy +
         tex[y1, x1] * fx * fy)
    return c


def rasterize_triangle(framebuffer, zbuffer, v0, v1, v2,
                       material, shader: ShaderConfig,
                       write_depth: bool = True,
                       alpha: float = 1.0,
                       receive_shadow: bool = True) -> None:
    """
    光栅化一个三角形到 framebuffer(H,W,3,float) 与 zbuffer(H,W,float)。
    write_depth=False 时只混合颜色、不写深度（供透明物体画家算法使用）。
    """
    H, W = framebuffer.shape[:2]
    vs = (v0, v1, v2)
    xs = [v[SX] for v in vs]
    ys = [v[SY] for v in vs]

    # 剔除屏幕外 / 近平面后方（深度<=0 时投影已失效，上层会跳过）
    minx = int(max(0, min(xs)))
    maxx = int(min(W - 1, max(xs)))
    miny = int(max(0, min(ys)))
    maxy = int(min(H - 1, max(ys)))
    if maxx < minx or maxy < miny:
        return

    # 面积与背面剔除
    a0, a1, a2 = xs[0], ys[0], xs[1]
    area2 = (xs[1] - xs[0]) * (ys[2] - ys[0]) - (ys[1] - ys[0]) * (xs[2] - xs[0])
    if abs(area2) < 1e-9:
        return
    flip = area2 < 0
    if shader.cull_backface and not flip:
        return
    inv_area = 1.0 / abs(area2)

    if maxx - minx + 1 > 0 and maxy - miny + 1 > 0:
        px = np.arange(minx, maxx + 1)[None, :]
        py = np.arange(miny, maxy + 1)[:, None]
        P = np.stack([np.broadcast_to(px, (maxy - miny + 1, maxx - minx + 1)),
                      np.broadcast_to(py, (maxy - miny + 1, maxx - minx + 1))], axis=-1).astype(np.float64)
    else:
        return

    def e(a, b, pt):
        # 标准边缘函数：cross(b-a, p-a) 的 z 分量
        return (b[0] - a[0]) * (pt[..., 1] - a[1]) - (b[1] - a[1]) * (pt[..., 0] - a[0])

    w0 = e((xs[1], ys[1]), (xs[2], ys[2]), P)
    w1 = e((xs[2], ys[2]), (xs[0], ys[0]), P)
    w2 = e((xs[0], ys[0]), (xs[1], ys[1]), P)
    if flip:
        w0, w1, w2 = -w0, -w1, -w2
    inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    if not inside.any():
        return

    b0 = w0 * inv_area
    b1 = w1 * inv_area
    b2 = w2 * inv_area

    # 插值深度 / 世界坐标 / 法线 / UV / 颜色（屏幕空间仿射插值）
    depth = (b0 * v0[DEPTH] + b1 * v1[DEPTH] + b2 * v2[DEPTH])
    wx = (b0 * v0[WX] + b1 * v1[WX] + b2 * v2[WX])
    wy = (b0 * v0[WY] + b1 * v1[WY] + b2 * v2[WY])
    wz = (b0 * v0[WZ] + b1 * v1[WZ] + b2 * v2[WZ])
    nx = (b0 * v0[NX] + b1 * v1[NX] + b2 * v2[NX])
    ny = (b0 * v0[NY] + b1 * v1[NY] + b2 * v2[NY])
    nz = (b0 * v0[NZ] + b1 * v1[NZ] + b2 * v2[NZ])
    u = (b0 * v0[UU] + b1 * v1[UU] + b2 * v2[UU])
    v = (b0 * v0[VV] + b1 * v1[VV] + b2 * v2[VV])

    nlen = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-12
    nx /= nlen; ny /= nlen; nz /= nlen

    # 逐像素深度测试
    zb = zbuffer[miny:maxy + 1, minx:maxx + 1]
    if write_depth:
        if shader.edge_depth_sample:
            # 仅边缘像素做深度比较；内部像素直接通过
            edge = (b0 < shader.edge_threshold) | (b1 < shader.edge_threshold) | \
                   (b2 < shader.edge_threshold)
            pass_mask = inside & (~edge | (depth < zb))
        else:
            pass_mask = inside & (depth < zb)
    else:
        pass_mask = inside

    if not pass_mask.any():
        return

    # 着色
    sd = np.array(shader.sun_dir, dtype=np.float64)
    sd = sd / (np.linalg.norm(sd) + 1e-12)
    sun = np.array(shader.sun_color, dtype=np.float64)
    amb = np.array(shader.ambient, dtype=np.float64)

    ndl = nx * sd[0] + ny * sd[1] + nz * sd[2]   # 世界空间法线 * 指向光源
    diff = np.clip(ndl, 0.0, 1.0)

    # 贴图 / 纯色采样
    npx = int(pass_mask.sum())
    flat = pass_mask.ravel()
    if material is not None and hasattr(material, "_tex_array") and material._tex_array is not None:
        base = sample_texture_array(material, u[pass_mask], v[pass_mask])
    else:
        base = _material_base_rgb(material)
        base = np.broadcast_to(base, (npx, 3)).copy()

    # 阴影
    shadow_f = np.ones(npx, dtype=np.float64)
    if (shader.enable_shadows and shader.shadow_map is not None and
            material is not None and receive_shadow):
        shadow_f = shader.shadow_map.sample(wx[pass_mask], wy[pass_mask], wz[pass_mask])
        shadow_f = 1.0 - shader.shadow_intensity * (1.0 - shadow_f)

    lit = base * (amb[None, :] + (sun[None, :] * diff[pass_mask, None] * shadow_f[:, None]))

    # 高光
    if shader.specular_strength > 0:
        nrm = np.stack([nx[pass_mask], ny[pass_mask], nz[pass_mask]], axis=-1)
        ndl3 = diff[pass_mask, None]
        # 视线向量近似：从世界坐标指向原点(简化)
        view = -np.stack([wx[pass_mask], wy[pass_mask], wz[pass_mask]], axis=-1)
        vl = np.sqrt((view ** 2).sum(axis=-1, keepdims=True)) + 1e-12
        view = view / vl
        half = nrm + sd[None, :]
        hl = np.sqrt((half ** 2).sum(axis=-1, keepdims=True)) + 1e-12
        half = half / hl
        spec = np.clip((nrm * half).sum(axis=-1), 0, 1) ** shader.specular_power
        lit += sun[None, :] * (spec[:, None] * shader.specular_strength)

    # 写入帧缓存
    region = framebuffer[miny:maxy + 1, minx:maxx + 1]
    if alpha >= 0.999:
        region[pass_mask] = lit
    else:
        dst = region[pass_mask]
        region[pass_mask] = lit * alpha + dst * (1.0 - alpha)

    if write_depth:
        zb[pass_mask] = depth[pass_mask]

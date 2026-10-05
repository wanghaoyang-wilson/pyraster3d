"""
raytrace.py — 轻度光线追踪（在软光栅之上叠加的光追效果）
不是全帧光追，而是只对需要效果的像素发射少量射线：
- 阴影射线：从片元向光源发射，检测是否被遮挡（替代/补充阴影贴图）。
- 反射射线：镜面物体一次或多次反弹，采样场景颜色。
- 环境遮蔽(AO)：向半球随机发若干短射线，估计被遮蔽程度。
所有求交走 BVH（后台线程异步构建）。
"""
from __future__ import annotations

import numpy as np

from .matrix import normalize


def trace_shadow(bvh, origin, light_dir, max_dist=1e9) -> float:
    """阴影射线：返回 1=无遮挡(亮)，0=完全遮挡(暗)。"""
    o = np.asarray(origin, dtype=np.float64)
    d = normalize(np.asarray(light_dir, dtype=np.float64))
    hit = bvh.intersect(o, d, max_t=max_dist)
    return 0.0 if hit is not None else 1.0


def trace_reflection(bvh, origin, direction, bounces=1, ambient=(0.3, 0.3, 0.35),
                     sun_dir=None, sun_color=(1, 1, 1)) -> np.ndarray:
    """
    反射射线：递归最多 bounces 次，返回 RGB。
    每次命中：用命中实体材质颜色 + 简单光照。
    """
    o = np.asarray(origin, dtype=np.float64)
    d = normalize(np.asarray(direction, dtype=np.float64))
    col = np.zeros(3)
    coeff = 1.0
    for _ in range(max(1, bounces + 1)):
        hit = bvh.intersect(o, d, max_t=1e9)
        if hit is None:
            col += coeff * np.array(ambient, dtype=np.float64) * 0.6
            break
        t, entity, gi, (u, v) = hit
        pos, normal, uv = bvh.world_pos_normal_uv(gi, o, d, t, u, v)
        mat = entity.material
        base = np.array(mat.color if hasattr(mat, "color") else (180, 180, 180),
                        dtype=np.float64)
        # 漫反射
        if sun_dir is not None:
            sd = normalize(np.asarray(sun_dir, dtype=np.float64))
            diff = max(float(np.dot(normal, sd)), 0.0)
            lit = base * (0.25 + 0.75 * diff)
        else:
            lit = base * 0.8
        col += coeff * lit
        # 反射继续
        refl = entity.material.reflectivity if entity.material is not None else 0.0
        if refl <= 0.01 or bounces <= 0:
            break
        r = d - 2 * np.dot(d, normal) * normal
        coeff *= refl
        o = pos + r * 1e-3
        d = r
    return col


def trace_ao(bvh, origin, normal, radius=0.5, samples=6, seed=0) -> float:
    """简单环境遮蔽：向法线半球发射 samples 条短射线。返回 AO 因子(0..1)。"""
    o = np.asarray(origin, dtype=np.float64)
    n = normalize(np.asarray(normal, dtype=np.float64))
    # 构造正交基
    helper = np.array([1, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1, 0])
    t1 = normalize(np.cross(n, helper))
    t2 = np.cross(n, t1)
    occluded = 0.0
    rng = np.random.default_rng(seed)
    for k in range(samples):
        zz = rng.random()
        theta = rng.random() * 2 * np.pi
        r = np.sqrt(1 - zz * zz)
        dirv = normalize(t1 * (r * np.cos(theta)) + t2 * (r * np.sin(theta)) + n * zz)
        hit = bvh.intersect(o + n * 1e-3, dirv, max_t=radius)
        if hit is not None:
            occluded += 1.0
    return 1.0 - occluded / max(1, samples)


# --------------------------------------------------------------------------- #
# 反射后处理：对已光栅化的帧进行轻量反射叠加（使用 G-Buffer）
# --------------------------------------------------------------------------- #
def apply_reflection_pass(framebuffer, gbuffer, bvh, max_bounces=1,
                          sun_dir=None, sun_color=(1, 1, 1),
                          samples_scale=1.0):
    """
    gbuffer 需提供：world_pos(H,W,3), normal(H,W,3), reflectivity(H,W)。
    对 reflectivity>0 的像素，沿反射方向追踪并叠加。
    """
    if bvh is None or bvh.empty:
        return
    H, W = framebuffer.shape[:2]
    wp = gbuffer["world_pos"]
    nr = gbuffer["normal"]
    refl = gbuffer["reflectivity"]
    mask = refl > 0.01
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return
    # 视线：从相机近似看向像素（这里用像素世界坐标取负作为视线方向）
    rng = np.random.default_rng(0)
    for yi, xi in zip(ys, xs):
        p = wp[yi, xi]
        n = normalize(nr[yi, xi])
        v = -p
        v = v / (np.linalg.norm(v) + 1e-12)
        r = v - 2 * np.dot(v, n) * n
        color = trace_reflection(bvh, p + r * 1e-3, r, bounces=max_bounces,
                                 sun_dir=sun_dir, sun_color=sun_color)
        f = refl[yi, xi]
        framebuffer[yi, xi] = framebuffer[yi, xi] * (1 - f) + color * f

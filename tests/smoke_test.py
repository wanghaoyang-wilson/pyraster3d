#!/usr/bin/env python3
"""无头冒烟测试：不打开窗口，验证引擎各模块可正常跑通。"""
import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT)

import numpy as np

from pyraster3d import (App, Scene, Entity, FPPCamera, SolidColorMaterial,
                        build_primitive, load_level, save_level, build_scene_bvh,
                        ShadowMap, trace_shadow, trace_reflection, HitInfo)

ok = []

def check(name, cond):
    ok.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)

# 1. App 初始化 + 渲染一帧
app = App(width=480, height=360)
fb = app.renderer.render(app.scene, app.camera)
check("renderer 输出帧缓存形状", fb.shape == (360, 480, 3) and np.isfinite(fb).all())
check("帧缓存非纯黑", float(np.abs(fb).sum()) > 0)

# 2. 关卡加载/保存往返
scene, cam_info = load_level("levels/sample_level.json")
check("关卡加载实体数", len(scene.entities) == 4)
save_level("/tmp/_test_level.json", scene, cam_info, name="test")
s2, c2 = load_level("/tmp/_test_level.json")
check("关卡保存/加载往返实体数", len(s2.entities) == len(scene.entities))

# 3. BVH 构建 + 拾取射线（瞄准无旋转的球体中心 (3.2,1.2,4.5)）
bvh = build_scene_bvh(scene)
check("BVH 非空", not bvh.empty)
origin = np.array([0, 2, -10.0])
target = np.array([3.2, 1.2, 4.5])
direction = (target - origin)
direction = direction / (np.linalg.norm(direction) + 1e-12)
hit = bvh.intersect(origin, direction)
check("BVH 命中场景", hit is not None and hit[1].name == "sphere_1")

# 4. 相机屏幕射线
cam = FPPCamera(position=(0, 2, -10))
cam.width, cam.height = 480, 360
ro, rd = cam.screen_ray(240, 180)
check("屏幕射线方向有效", np.linalg.norm(rd) > 0)
# 球体中心在相机 (0,2,-10) 下投影到约 (297, 194)
hit_info = cam.raycast(297, 194, bvh)
check("相机 raycast 命中", hit_info is not None and hit_info.entity.name == "sphere_1")

# 5. 阴影贴图
sm = ShadowMap(size=128)
sm.build(scene, scene.sun_direction)
lit = sm.sample(np.array([0.0]), np.array([1.0]), np.array([5.0]))
check("阴影贴图采样在 [0,1]", 0.0 <= lit[0] <= 1.0)

# 6. 光线追踪函数
s = trace_shadow(bvh, np.array([0, 2, 5.0]), np.array([0.5, -0.8, 0.4]))
check("阴影射线返回 [0,1]", 0.0 <= s <= 1.0)
ref = trace_reflection(bvh, np.array([0, 2, 6.0]), np.array([0, 0, -1]), bounces=1)
check("反射射线返回 RGB", len(ref) == 3 and np.isfinite(ref).all())

# 7. 关闭 worker（App 尚未 run）
app.worker.shutdown()

print("\n==== 结果 ====")
fails = [n for n, c in ok if not c]
print(f"通过 {len(ok)-len(fails)}/{len(ok)}")
if fails:
    print("失败项:", fails)
    sys.exit(1)
print("SMOKE TEST OK")

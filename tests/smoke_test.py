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
                        ShadowMap, trace_shadow, trace_reflection, HitInfo,
                        PhysicsWorld, CharacterController, add_collider, Collider,
                        AABBCollider)

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

# 3. BVH 构建 + 拾取射线
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

# 8. 物理引擎
pscene = Scene("phys")
pground = Entity(model=build_primitive("plane"), name="ground",
                 position=(0, 0, 0), scale=(40, 1, 40))
add_collider(pground, Collider.BLOCK)
pscene.add(pground)

wall = Entity(model=build_primitive("cube"), name="wall",
              position=(0, 1, 6), scale=(1, 2, 1))
add_collider(wall, Collider.BLOCK)
pscene.add(wall)

trigger = Entity(model=build_primitive("cube"), name="trig",
                 position=(4, 1, 4), scale=(1, 1, 1))
add_collider(trigger, Collider.OVERLAP)
pscene.add(trigger)

player = CharacterController(position=(0, 20, 0), radius=0.4, height=1.8,
                             gravity=-20, jump_speed=6, move_speed=4)
landed_pos = []
player.on_land = lambda: landed_pos.append(player.position[1])
world = PhysicsWorld(pscene, player, broadphase_radius=20, broadphase_interval=60)
for _ in range(400):
    world.step(0.016)
check("物理落地 grounded", player.grounded is True)
check("物理落地高度(≈0.9)", abs(player.position[1] - 0.9) < 0.05)
check("物理落地回调触发", len(landed_pos) >= 1)

world.step(0.016, jump=True)
check("物理跳跃离地", player.grounded is False and player.velocity[1] > 0)
for _ in range(60):
    world.step(0.016)
check("物理跳跃后回到地面", player.grounded is True)

player.position = np.array([0.0, 0.9, 0.0])
player.velocity = np.zeros(3)
for _ in range(200):
    world.step(0.016, move_input=(1, 0), yaw=0.0)
check("Block 阻挡玩家无法穿过墙", player.position[2] < 5.5)

began = []; ended = []
trigger.on_begin_overlap = lambda o: began.append(True)
trigger.on_end_overlap = lambda o: ended.append(True)
player.position = np.array([4.0, 0.9, 4.0])
world._refresh_nearby()
for _ in range(10):
    world.step(0.016)
check("Overlap 进入事件触发", len(began) >= 1)
player.position = np.array([4.0, 0.9, 9.0])
world._refresh_nearby()
for _ in range(10):
    world.step(0.016)
check("Overlap 离开事件触发", len(ended) >= 1)

far = Entity(model=build_primitive("cube"), name="far",
             position=(0, 0, 200), scale=(1, 1, 1))
add_collider(far, Collider.BLOCK)
pscene.add(far)
world._refresh_nearby()
names = {e.name for e in world._nearby}
check("宽相筛选(远处物体不在附近)", "far" not in names and "ground" in names)

# 9. UI 主题系统
from pyraster3d.ui import UILayer, Button, Label, Panel, set_theme, UITheme
import pygame as _pygame
if not _pygame.get_init():
    _pygame.init()
_usurf = _pygame.Surface((400, 300))
_uil = UILayer()
_uil.add(Button("按钮", (10, 10, 120, 30), name="b"))
_uil.add(Panel((10, 60, 180, 140), name="p", title="面板"))
_uil.add(Label("文本", (20, 90, 200, 20), name="l", shadow=True))
_uil.draw(_usurf)
check("UI 绘制正常", True)
set_theme(UITheme())
_uil.draw(_usurf)
check("UI 主题可切换", True)

# 10. 配置项
from pyraster3d.config import DEFAULT_CONFIG
check("默认配置含 physics", "physics" in DEFAULT_CONFIG)
check("默认配置含 renderer.backend", DEFAULT_CONFIG["renderer"].get("backend") == "pygame")

# 11. Direct2D 后端 Python 部分
sys.path.insert(0, os.path.join(_PROJECT, "direct2d"))
from direct2d import write_frame_file, get_backend, is_windows
_rgb = np.zeros((100, 120, 3), np.uint8); _rgb[:, :, 0] = 255
_raw = write_frame_file(_rgb, "/tmp/_d2d.raw")
with open(_raw, "rb") as fh:
    _data = fh.read(4)
check("D2D BGRA 帧写出正确(红->BGRA)", tuple(_data) == (0, 0, 255, 255))
_b = get_backend({"renderer": {"backend": "direct2d"},
                  "window": {"width": 100, "height": 100}})
check("D2D 后端在非Windows优雅回退", _b is None and not is_windows())

# 7. 关闭 worker
app.worker.shutdown()

print("\n==== 结果 ====")
fails = [n for n, c in ok if not c]
print(f"通过 {len(ok)-len(fails)}/{len(ok)}")
if fails:
    print("失败项:", fails)
    sys.exit(1)
print("SMOKE TEST OK")

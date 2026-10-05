"""
app.py — Pyraster3D 引擎主入口（App / GameInstance）
职责：
- 初始化 Pygame 窗口与渲染上下文
- 管理 场景(Scene) / 相机(Camera) / 渲染器(Renderer) / UI(UILayer)
- 事件循环：输入采集 -> 交互事件分发(Hover/Hit/Clicked) -> 相机更新 -> 渲染 -> 呈现
- FPS 统计与显示
- 异步场景编译调度（BVH / 阴影贴图后台重建）
- 关卡编辑器（Editor）挂载
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import numpy as np
import pygame

from .camera import FPPCamera, TPPCamera
from .config import load_config
from .editor import Editor
from .interaction import HitInfo
from .material import SolidColorMaterial
from .renderer import Renderer
from .scene import Scene, Entity
from .tasks import AsyncWorker, AsyncSceneCompiler
from .ui import UILayer, Label
from .primitives import build_primitive


class App:
    def __init__(self, config_path: Optional[str] = None,
                 width: Optional[int] = None, height: Optional[int] = None,
                 title: Optional[str] = None):
        self.pygame = pygame
        self.config = load_config(config_path)
        if width or height:
            self.config["window"].update({
                "width": width or self.config["window"]["width"],
                "height": height or self.config["window"]["height"],
            })
        if title:
            self.config["window"]["title"] = title

        self.width = self.config["window"]["width"]
        self.height = self.config["window"]["height"]

        pygame.init()
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption(self.config["window"].get("title", "Pyraster3D"))
        self.clock = pygame.time.Clock()

        # 渲染
        self.renderer = Renderer(self.width, self.height)
        self.renderer.apply_config(self.config)

        # 场景与相机
        self.scene = Scene("Untitled")
        self._build_default_scene()
        cdefaults = self.config.get("camera_defaults", {})
        self.camera = FPPCamera(
            position=(0, 1.5, -8.0),      # 左手系相机朝 +Z，物体放在相机前方
            fov_degrees=self.config["renderer"]["fov_degrees"],
            speed=cdefaults.get("speed", 0.25),
        )
        self.camera.sensitivity = cdefaults.get("mouse_sensitivity", 0.003)

        # UI 与交互
        self.ui = UILayer()
        self._fps_label = Label("FPS: --", (12, 12, 120, 22), name="fps",
                                color=(210, 230, 255))
        self.ui.add(self._fps_label)
        self.mouse_pos = (0, 0)

        # 异步场景编译
        self.worker = AsyncWorker(self.config.get("threading", {}).get("workers", 2))
        self.compiler = AsyncSceneCompiler(self.worker)

        # 关卡编辑器
        self.editor = Editor(self, enabled=self.config["editor"].get("enabled", True))
        self.editor.active = False

        # 运行状态
        self.running = False
        self.on_update: Optional[Callable[[float], None]] = None
        self.on_mouse_down_3d: Optional[Callable[[HitInfo], None]] = None
        self.fps = 0.0
        self.frame_time = 0.0
        self._last = time.perf_counter()
        self._press_target = None
        self._bvh_requested = False
        self._shadow_requested = False

        # 请求初始异步编译
        self.request_rebuild()

    # ------------------------------------------------------------------ #
    # 场景
    # ------------------------------------------------------------------ #
    def _build_default_scene(self):
        ground = Entity(model=build_primitive("plane"), name="ground",
                        position=(0, 0, 0), scale=(14, 1, 14),
                        material=SolidColorMaterial((66, 84, 66)))
        cube = Entity(model=build_primitive("cube"), name="cube_1",
                      position=(0, 1, 6), rotation=(0, 0.6, 0),
                      material=SolidColorMaterial((198, 88, 78)))
        sphere = Entity(model=build_primitive("sphere"), name="sphere_1",
                        position=(3, 1.2, 5), material=SolidColorMaterial((70, 120, 190)))
        cyl = Entity(model=build_primitive("cylinder"), name="cylinder_1",
                     position=(-3, 1, 6), material=SolidColorMaterial((150, 150, 80)))
        for e in (ground, cube, sphere, cyl):
            self.scene.add(e)

    def set_scene(self, scene: Scene):
        self.scene = scene
        self.request_rebuild()

    def request_rebuild(self):
        """提交 BVH / 阴影贴图异步重建（后台线程）。"""
        th = self.config.get("threading", {})
        if th.get("async_scene_compile", True):
            if not self._bvh_requested:
                self.compiler.request_bvh(self.scene)
                self._bvh_requested = True
        if self.renderer.enable_shadows and th.get("async_shadow", True):
            if not self._shadow_requested:
                self.compiler.request_shadow(self.scene)
                self._shadow_requested = True

    # ------------------------------------------------------------------ #
    # 射线拾取（UI 优先于 3D）
    # ------------------------------------------------------------------ #
    def raycast_ui_or_scene(self, mx, my) -> Optional[HitInfo]:
        ui = self.ui.pick(mx, my)
        if ui is not None:
            return ui.hit_info(mx, my)
        bvh = self.compiler.bvh
        return self.camera.raycast(mx, my, bvh)

    # ------------------------------------------------------------------ #
    # 事件分发（Hover / Hit / Clicked / MouseDown / MouseUp）
    # ------------------------------------------------------------------ #
    def _dispatch_interaction(self, events):
        mx, my = pygame.mouse.get_pos()
        self.mouse_pos = (mx, my)
        ui_hit = self.ui.pick(mx, my)
        scene_hit = None
        if ui_hit is None:
            bvh = self.compiler.bvh
            scene_hit = self.camera.raycast(mx, my, bvh)

        # Hover / enter / exit：遍历所有可交互对象
        targets = list(self.ui.elements) + list(self.scene.entities)
        for obj in targets:
            if not getattr(obj, "visible", True):
                obj.process_unhit()
                continue
            active = False
            if ui_hit is not None and obj is ui_hit:
                active = True
                obj.process_hit(ui_hit.hit_info(mx, my))
            elif scene_hit is not None and obj is scene_hit.entity:
                active = True
                obj.process_hit(scene_hit)
            if not active:
                obj.process_unhit()

        # 按下/松开 -> clicked
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                target = ui_hit or (scene_hit.entity if scene_hit is not None else None)
                if target is not None:
                    hit = (ui_hit.hit_info(mx, my) if ui_hit is not None else scene_hit)
                    target.process_press(hit)
                    if target is scene_hit and self.on_mouse_down_3d:
                        self.on_mouse_down_3d(scene_hit)
                self._press_target = target
            elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                released_on = ui_hit or (scene_hit.entity if scene_hit is not None else None)
                if self._press_target is not None:
                    hit = (ui_hit.hit_info(mx, my) if ui_hit is not None
                           else (scene_hit if scene_hit is not None
                                 else HitInfo(entity=self._press_target)))
                    self._press_target.process_release(hit, released_on is self._press_target)
                self._press_target = None

    # ------------------------------------------------------------------ #
    # 相机 / 输入
    # ------------------------------------------------------------------ #
    def _update_camera(self, dt):
        if self.editor.active:
            # 编辑器自由相机（不锁定鼠标，便于拖拽/UI）
            pygame.mouse.set_visible(True)
            pygame.event.set_grab(False)
            keys = pygame.key.get_pressed()
            fwd = (1 if keys[pygame.K_w] else 0) - (1 if keys[pygame.K_s] else 0)
            rgt = (1 if keys[pygame.K_d] else 0) - (1 if keys[pygame.K_a] else 0)
            up = (1 if keys[pygame.K_e] else 0) - (1 if keys[pygame.K_q] else 0)
            self.camera.move(fwd, rgt, up, dt)
            if not self.editor._dragging and self.ui.pick(*self.mouse_pos) is None:
                dx, dy = pygame.mouse.get_rel()
                self.camera.look_delta(dx, dy)
            return
        if isinstance(self.camera, TPPCamera):
            self.camera.update(dt)
            # 鼠标拖拽环绕
            if pygame.mouse.get_pressed()[0]:
                dx, dy = pygame.mouse.get_rel()
                self.camera.orbit(dx, dy)
            return
        # 第一人称：锁定鼠标
        if isinstance(self.camera, FPPCamera):
            self.camera.lock_mouse(pygame, True)
            self.camera.update_input(pygame, dt)

    def _toggle_camera(self):
        if isinstance(self.camera, TPPCamera):
            self.camera = FPPCamera(
                position=[self.camera.position[0], self.camera.position[1],
                          self.camera.position[2]],
                fov_degrees=self.config["renderer"]["fov_degrees"],
            )
        elif isinstance(self.camera, FPPCamera):
            tpp = TPPCamera(target=self._pick_target_for_tpp(), distance=6.0)
            tpp.fov_degrees = self.config["renderer"]["fov_degrees"]
            self.camera = tpp

    def _pick_target_for_tpp(self):
        for e in self.scene.entities:
            if e.name != "ground" and e.model is not None:
                return e
        return None

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #
    def run(self, update_func: Optional[Callable[[float], None]] = None):
        self.on_update = update_func
        self.running = True
        while self.running:
            now = time.perf_counter()
            dt = now - self._last
            self._last = now
            self.frame_time = dt
            self.fps = 1.0 / dt if dt > 0 else 0.0

            events = pygame.event.get()
            for e in events:
                if e.type == pygame.QUIT:
                    self.running = False
                elif e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_F1:
                        self.editor.active = not self.editor.active
                    elif e.key == pygame.K_F2:
                        self._toggle_camera()

            # 异步结果切换到当前场景
            self.compiler.apply_ready(self.scene)
            if self.compiler.bvh is not None:
                self.scene._bvh = self.compiler.bvh
            if self.renderer.enable_shadows and self.compiler.shadow_map is not None:
                self.renderer.shadow_map = self.compiler.shadow_map
            if self._bvh_requested and self.compiler.bvh is not None:
                self._bvh_requested = False
            if self._shadow_requested and self.compiler.shadow_map is not None:
                self._shadow_requested = False

            # 编辑器处理（先于渲染）
            self.editor.update(events)

            # 相机输入
            self._update_camera(dt)

            # 交互事件分发（UI + 3D 拾取）
            self._dispatch_interaction(events)

            # 用户更新回调
            if self.on_update is not None:
                self.on_update(dt)

            # 渲染
            fb = self.renderer.render(self.scene, self.camera)
            arr = np.clip(fb, 0, 255).astype("uint8")
            surface = pygame.surfarray.make_surface(np.ascontiguousarray(arr.transpose(1, 0, 2)))
            self.screen.blit(surface, (0, 0))

            # UI 绘制（含编辑器面板 + FPS）
            if self.config["editor"].get("show_fps", True):
                self._fps_label.text = f"FPS: {self.fps:5.1f}  {self.frame_time*1000:5.1f}ms"
                self._fps_label.visible = True
            else:
                self._fps_label.visible = False
            self.editor.draw_ui(self.screen)
            self.ui.draw(self.screen)

            pygame.display.flip()
            cap = self.config["window"].get("fps_cap", 0)
            if cap and cap > 0:
                self.clock.tick(cap)
            else:
                self.clock.tick(0)

        self.worker.shutdown()
        pygame.quit()

    # 兼容别名
    @property
    def pygame_module(self):
        return pygame

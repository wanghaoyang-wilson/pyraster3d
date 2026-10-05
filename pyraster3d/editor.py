"""
editor.py — 基础关卡编辑器（Level Editor / Viewport 模式）
能力：
- WASD 移动相机，Q/E 上下，鼠标视角（可切换编辑器自由相机或第一人称）
- 左键：选中实体；按住拖拽：沿地面/相机平面移动选中实体
- R + 鼠标左右：旋转选中实体；[ / ]：缩放；滚轮：缩放或推拉
- 数字键 1/2/3/4：快速放置 立方体/平面/球体/圆柱
- Delete：删除选中实体
- Ctrl+O 打开关卡 / Ctrl+S 保存关卡（JSON）
- 右侧面板：实体列表 + 按钮（新增/删除/保存/加载）
所有操作在主线程完成（仅涉及场景编辑；BVH/阴影异步重建）。
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .interaction import HitInfo
from .levelio import save_level, load_level
from .matrix import normalize
from .primitives import PRIMITIVE_NAMES, build_primitive
from .material import SolidColorMaterial, TextureMaterial
from .ui import Panel, Button, Label, UILayer
from .scene import Entity


def _ray_plane_intersect(origin, direction, plane_y, plane_normal=(0, 1, 0)):
    n = np.asarray(plane_normal, dtype=np.float64)
    d = np.asarray(direction, dtype=np.float64)
    denom = float(np.dot(d, n))
    if abs(denom) < 1e-9:
        return None
    t = (plane_y - np.dot(np.asarray(origin), n)) / denom
    if t < 0:
        return None
    return np.asarray(origin) + d * t


class Editor:
    def __init__(self, app, enabled: bool = True):
        self.app = app
        self.enabled = enabled
        self.active = enabled
        self.selected: Optional[Entity] = None
        self.current_file: Optional[str] = None
        self._dragging = False
        self._drag_plane_y = 0.0
        self._free_camera = True        # 编辑器使用自由相机（WASD+QE）
        self.snap_translate = 0.5
        self.snap_rotate = 15.0
        self.ui = UILayer()
        self._build_panel()

    # ------------------------------------------------------------------ #
    # UI 面板
    # ------------------------------------------------------------------ #
    def _build_panel(self):
        self.panel = Panel((self.app.width - 232, 12, 220, 320), name="editor_panel",
                           bg=(24, 26, 32))
        self.panel.add(Label("关卡编辑器", (self.app.width - 224, 16, 200, 24),
                             name="title", color=(255, 210, 90)))
        self.panel.add(Label("选择实体并拖动", (self.app.width - 224, 40, 200, 20),
                             name="hint", color=(160, 160, 160)))
        self.panel.add(Label("数字键 1-4 放置物体", (self.app.width - 224, 58, 200, 20),
                             name="hint2", color=(160, 160, 160)))
        self.btn_cube = Button("+ 立方体(1)", (self.app.width - 220, 82, 100, 28),
                               name="btn_cube")
        self.btn_plane = Button("+ 平面(2)", (self.app.width - 116, 82, 100, 28),
                                name="btn_plane")
        self.btn_sphere = Button("+ 球体(3)", (self.app.width - 220, 116, 100, 28),
                                 name="btn_sphere")
        self.btn_cyl = Button("+ 圆柱(4)", (self.app.width - 116, 116, 100, 28),
                              name="btn_cyl")
        self.btn_del = Button("删除选中(Del)", (self.app.width - 220, 150, 100, 28),
                              name="btn_del")
        self.btn_save = Button("保存关卡(Ctrl+S)", (self.app.width - 116, 150, 100, 28),
                               name="btn_save")
        self.btn_load = Button("打开关卡(Ctrl+O)", (self.app.width - 220, 184, 204, 28),
                               name="btn_load")
        for b in (self.btn_cube, self.btn_plane, self.btn_sphere,
                  self.btn_cyl, self.btn_del, self.btn_save, self.btn_load):
            self.ui.add(b)
            self.panel.add(b)
        self.ui.add(self.panel)
        self.info = Label("", (12, 12, 320, 22), name="info", color=(210, 230, 255))
        self.ui.add(self.info)

    def _wire_panel_events(self):
        self.btn_cube.on_clicked = lambda h: self.add_primitive("cube")
        self.btn_plane.on_clicked = lambda h: self.add_primitive("plane")
        self.btn_sphere.on_clicked = lambda h: self.add_primitive("sphere")
        self.btn_cyl.on_clicked = lambda h: self.add_primitive("cylinder")
        self.btn_del.on_clicked = lambda h: self.delete_selected()
        self.btn_save.on_clicked = lambda h: self.save_current()
        self.btn_load.on_clicked = lambda h: self.open_dialog()

    # ------------------------------------------------------------------ #
    # 场景操作
    # ------------------------------------------------------------------ #
    def add_primitive(self, kind: str, position=None) -> Entity:
        scene = self.app.scene
        idx = 1
        while scene.find(f"{kind}_{idx}"):
            idx += 1
        ent = Entity(
            model=build_primitive(kind),
            name=f"{kind}_{idx}",
            position=position or [self.app.camera.position[0],
                                  -1.0,
                                  self.app.camera.position[2] + 3.0],
            material=SolidColorMaterial((190, 90, 80)),
        )
        scene.add(ent)
        self.select(ent)
        self.app.request_rebuild()
        return ent

    def delete_selected(self):
        if self.selected is not None:
            self.app.scene.remove(self.selected)
            self.selected = None
            self.app.request_rebuild()

    def select(self, entity):
        if self.selected is entity:
            return
        self.selected = entity
        self.app.request_rebuild()

    # ------------------------------------------------------------------ #
    # 保存 / 打开
    # ------------------------------------------------------------------ #
    def save_current(self, path: Optional[str] = None):
        path = path or self.current_file or self._default_path()
        cam = self.app.camera
        save_level(path, self.app.scene, {
            "mode": cam.mode,
            "position": list(cam.position),
            "yaw": cam.yaw,
            "pitch": cam.pitch,
            "tpp_distance": getattr(cam, "distance", 6.0),
            "tpp_height_offset": getattr(cam, "height_offset", 1.5),
        }, name=self.app.scene.name)
        self.current_file = path
        self.info.text = f"已保存: {path}"

    def load(self, path: str):
        scene, cam_info = load_level(path)
        self.app.set_scene(scene)
        c = self.app.camera
        c.position = list(cam_info.get("position", [0, 1.5, 8]))
        c.yaw = cam_info.get("yaw", 0.0)
        c.pitch = cam_info.get("pitch", 0.0)
        if cam_info.get("mode") == "tpp" and hasattr(c, "distance"):
            c.distance = cam_info.get("tpp_distance", 6.0)
            c.height_offset = cam_info.get("tpp_height_offset", 1.5)
        self.current_file = path
        self.selected = None
        self.info.text = f"已加载: {path}"

    def _default_path(self) -> str:
        import os
        base = os.path.join(os.getcwd(), "levels")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "my_level.json")

    def open_dialog(self):
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            path = filedialog.askopenfilename(
                title="打开关卡", defaultextension=".json",
                filetypes=[("Level JSON", "*.json")])
            root.destroy()
            if path:
                self.load(path)
        except Exception:                    # noqa: BLE001
            self.info.text = "文件对话框不可用，请在代码中调用 editor.load(path)"

    # ------------------------------------------------------------------ #
    # 每帧处理（输入 + 拖拽 + 拾取）
    # ------------------------------------------------------------------ #
    def update(self, events) -> None:
        if not self.active:
            self._dragging = False
            return
        self._wire_panel_events()
        app = self.app
        cam = app.camera
        W, H = app.width, app.height
        cam.width, cam.height = W, H

        mouse = False
        for e in events:
            if e.type == app.pygame.KEYDOWN:
                self._on_key(e.key)
            elif e.type == app.pygame.MOUSEBUTTONDOWN and e.button == 1:
                if app.ui.pick(*app.mouse_pos) is None:
                    self._begin_click()
                    mouse = True
            elif e.type == app.pygame.MOUSEBUTTONUP and e.button == 1:
                self._end_click()
                mouse = True
            elif e.type == app.pygame.MOUSEWHEEL:
                self._on_wheel(e.y)
                mouse = True

        # 拖拽移动选中实体（沿穿过其位置的水平面）
        if self._dragging and self.selected is not None:
            origin, direction = cam.screen_ray(app.mouse_pos[0], app.mouse_pos[1])
            plane_y = self._drag_plane_y
            hit = _ray_plane_intersect(origin, direction, plane_y)
            if hit is not None:
                self.selected.position = self._snap(list(hit))
                self.selected.set_transform(position=self.selected.position)
                app.request_rebuild()

        # 旋转：按住 R + 鼠标移动
        r_key = app.pygame.key.get_pressed()[app.pygame.K_r]
        if r_key and self.selected is not None and not self._dragging:
            dx, dy = app.pygame.mouse.get_rel()
            self.selected.rotation[1] += dx * 0.02
            self.selected.rotation[0] += dy * 0.02
            self.selected.set_transform(rotation=self.selected.rotation)
            app.request_rebuild()

        # 更新信息栏
        sel = self.selected
        if sel is not None:
            self.info.text = (f"选中: {sel.name}  pos={[round(v,2) for v in sel.position]}"
                              f"  rot={[round(v,1) for v in sel.rotation]}"
                              f"  scale={[round(v,2) for v in sel.scale]}")
        else:
            self.info.text = f"关卡: {app.scene.name}  文件: {self.current_file or '未保存'}"

    def _begin_click(self):
        app = self.app
        hit = app.raycast_ui_or_scene(app.mouse_pos[0], app.mouse_pos[1])
        if hit is not None and hit.entity is not None:
            self.select(hit.entity)
            self._dragging = True
            self._drag_plane_y = float(hit.world_pos[1])
        else:
            self._dragging = False
            if app.ui.pick(*app.mouse_pos) is None:
                self.select(None)

    def _end_click(self):
        self._dragging = False

    def _on_key(self, key):
        app = self.app
        if key == app.pygame.K_1:
            self.add_primitive("cube")
        elif key == app.pygame.K_2:
            self.add_primitive("plane")
        elif key == app.pygame.K_3:
            self.add_primitive("sphere")
        elif key == app.pygame.K_4:
            self.add_primitive("cylinder")
        elif key == app.pygame.K_DELETE:
            self.delete_selected()
        elif key == app.pygame.K_LEFTBRACKET and self.selected:
            self.selected.scale = [max(0.05, s * 0.9) for s in self.selected.scale]
            self.selected.set_transform(scale=self.selected.scale)
            app.request_rebuild()
        elif key == app.pygame.K_RIGHTBRACKET and self.selected:
            self.selected.scale = [min(50.0, s * 1.1) for s in self.selected.scale]
            self.selected.set_transform(scale=self.selected.scale)
            app.request_rebuild()
        elif key == app.pygame.K_s and (app.pygame.key.get_mods() & app.pygame.KMOD_CTRL):
            self.save_current()
        elif key == app.pygame.K_o and (app.pygame.key.get_mods() & app.pygame.KMOD_CTRL):
            self.open_dialog()

    def _on_wheel(self, dy):
        if self.selected is None:
            if hasattr(self.app.camera, "distance"):
                self.app.camera.zoom(dy)
            return
        self.selected.scale = [max(0.05, min(50.0, s * (1.0 + dy * 0.1)))
                               for s in self.selected.scale]
        self.selected.set_transform(scale=self.selected.scale)
        self.app.request_rebuild()

    def _snap(self, pos):
        s = self.snap_translate
        return [round(v / s) * s for v in pos]

    def draw_ui(self, surface):
        if self.active:
            self.ui.draw(surface)

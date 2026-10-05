"""
camera.py — 相机系统（第一人称 / 第三人称 / 基础编辑器相机）
- 左手坐标系：X 右，Y 上，Z 前。
- 第一人称：鼠标锁定 + 相对位移控制俯仰/偏航，WASD 移动，Q/E 上下。
- 第三人称：跟随目标 Actor，围绕目标旋转，滚轮推拉距离。
- 提供 屏幕坐标 -> 世界射线（用于拾取/交互）。
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from .matrix import camera_basis_from_yaw_pitch, normalize
from .interaction import HitInfo, hit_info_from_ray


class Camera:
    mode = "base"

    def __init__(self, position=(0, 0, 6), yaw=0.0, pitch=0.0,
                 fov_degrees=70.0, z_near=0.1, z_far=200.0,
                 speed=0.25, sensitivity=0.003):
        self.position = list(position)
        self.yaw = yaw
        self.pitch = pitch
        self.fov_degrees = fov_degrees
        self.z_near = z_near
        self.z_far = z_far
        self.sensitivity = sensitivity
        self.speed = speed
        self.width = 0
        self.height = 0

    # ------------------------------------------------------------------ #
    # 基向量（世界空间）
    # ------------------------------------------------------------------ #
    def basis(self):
        return camera_basis_from_yaw_pitch(self.yaw, self.pitch)

    @property
    def forward(self):
        return self.basis()[2]

    @property
    def right(self):
        return self.basis()[0]

    @property
    def up(self):
        return self.basis()[1]

    def focal(self):
        return (self.height / 2.0) / math.tan(math.radians(self.fov_degrees / 2.0))

    # ------------------------------------------------------------------ #
    # 视角控制
    # ------------------------------------------------------------------ #
    def look_delta(self, dx, dy, lock_pitch=True):
        self.yaw += dx * self.sensitivity
        self.pitch -= dy * self.sensitivity
        if lock_pitch:
            lim = math.radians(89.0)
            self.pitch = max(-lim, min(lim, self.pitch))

    def move(self, forward_amt, right_amt, up_amt=0.0, dt=1.0):
        s, u, f = self.basis()
        step = self.speed * dt
        self.position[0] += (f[0] * forward_amt + s[0] * right_amt) * step
        self.position[1] += (f[1] * forward_amt + u[1] * right_amt + up_amt) * step
        self.position[2] += (f[2] * forward_amt + s[2] * right_amt) * step

    # ------------------------------------------------------------------ #
    # 屏幕 -> 世界射线
    # ------------------------------------------------------------------ #
    def screen_ray(self, mx, my):
        s, u, f = self.basis()
        focal = self.focal()
        dx = mx - self.width / 2.0
        dy = self.height / 2.0 - my
        origin = np.array(self.position, dtype=np.float64)
        direction = normalize(s * dx + u * dy + f * focal)
        return origin, direction

    def raycast(self, mx, my, bvh, max_t=1e9) -> Optional[HitInfo]:
        """从屏幕坐标发射射线，与 BVH 求交，返回最近 HitInfo。"""
        if bvh is None or bvh.empty:
            return None
        origin, direction = self.screen_ray(mx, my)
        hit = bvh.intersect(origin, direction, max_t)
        if hit is None:
            return None
        t, entity, gi, (u, v) = hit
        pos, normal, uv = bvh.world_pos_normal_uv(gi, origin, direction, t, u, v)
        return hit_info_from_ray(entity, t, pos, normal, uv, gi)


class FPPCamera(Camera):
    """第一人称相机（Pawn/Character 视角）。"""
    mode = "fpp"

    def __init__(self, position=(0, 0, 6), yaw=0.0, pitch=0.0, **kw):
        super().__init__(position=position, yaw=yaw, pitch=pitch, **kw)
        self.mouse_locked = False

    def lock_mouse(self, pygame, grab):
        pygame.mouse.set_visible(not grab)
        pygame.event.set_grab(grab)
        self.mouse_locked = grab

    def update_input(self, pygame, dt=1.0):
        """WASD + Q/E 移动；鼠标相对位移旋转。返回是否使用了鼠标。"""
        if self.mouse_locked:
            dx, dy = pygame.mouse.get_rel()
            if dx or dy:
                self.look_delta(dx, dy)
        keys = pygame.key.get_pressed()
        fwd = (1 if keys[pygame.K_w] else 0) - (1 if keys[pygame.K_s] else 0)
        rgt = (1 if keys[pygame.K_d] else 0) - (1 if keys[pygame.K_a] else 0)
        up = (1 if keys[pygame.K_e] else 0) - (1 if keys[pygame.K_q] else 0)
        self.move(fwd, rgt, up, dt)


class TPPCamera(Camera):
    """第三人称相机：围绕目标 Actor 旋转，保持距离。"""
    mode = "tpp"

    def __init__(self, target=None, distance=6.0, height_offset=1.5, **kw):
        super().__init__(position=(0, 0, 6), **kw)
        self.target = target
        self.distance = distance
        self.height_offset = height_offset
        self.orbit_yaw = 0.0
        self.orbit_pitch = 0.25

    def update(self, dt=1.0):
        if self.target is None:
            return
        target_pos = self.target.world_position if hasattr(self.target, "world_position") \
            else np.array(self.target.position)
        cy, sy = math.cos(self.orbit_yaw), math.sin(self.orbit_yaw)
        cp, sp = math.cos(self.orbit_pitch), math.sin(self.orbit_pitch)
        # 相机在世界：目标 + 距离 * (-forward_dir)
        offset = np.array([sy * cp, sp, cy * cp]) * self.distance
        self.position = [target_pos[0] + offset[0],
                         target_pos[1] + self.height_offset + offset[1],
                         target_pos[2] + offset[2]]
        # 面向目标
        f = target_pos - np.array(self.position)
        f = f / (np.linalg.norm(f) + 1e-12)
        up = np.array([0, 1, 0])
        s = np.cross(up, f)
        sn = np.linalg.norm(s)
        if sn > 1e-9:
            s = s / sn
        u2 = np.cross(f, s)
        self.yaw = math.atan2(f[0], f[2])
        self.pitch = math.asin(max(-1, min(1, f[1])))

    def orbit(self, dx, dy):
        self.orbit_yaw += dx * self.sensitivity
        self.orbit_pitch = max(-1.4, min(1.4, self.orbit_pitch - dy * self.sensitivity))

    def zoom(self, amount):
        self.distance = max(0.5, min(100.0, self.distance * (1.0 - amount * 0.1)))

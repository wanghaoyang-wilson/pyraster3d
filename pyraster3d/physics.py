"""
physics.py — 轻量物理引擎
====================================================
面向软光栅引擎的轻量物理系统，纯 Python 实现（原型阶段；后续内核转译到 C++/GPU 时保持接口不变）。

设计（对应 UE4.27 术语）：
- `AABBCollider` ≈ Primitive Collision Component（Block / Overlap 两种响应模式）。
- `CharacterController` ≈ Capsule Component + CharacterMovement（玩家胶囊体：重力/跳跃/落地/阻挡）。
- `PhysicsWorld` ≈ PhysicsSubsystem / World Physics：
    * 宽相：以玩家为中心 `broadphase_radius`（默认 20 单位），每 `broadphase_interval`（默认 60 游戏刻）刷新附近碰撞体候选列表；
    * 窄相：胶囊体-AABB 相交检测（细分时间步防穿透）；
    * 重叠对差分 → 触发 `on_begin_overlap` / `on_end_overlap` / `on_hit` 事件。

坐标系：左手系，Y 向上，重力沿 -Y。
"""
from __future__ import annotations

import math
from typing import Callable, List, Optional, Set

import numpy as np

from .matrix import camera_basis_from_yaw_pitch
from .scene import Entity, Scene


class Collider:
    """碰撞响应模式（对应 UE Collision Preset）。"""
    BLOCK = "block"        # 阻挡：玩家无法穿过，产生碰撞命中 on_hit
    OVERLAP = "overlap"    # 触发：不阻挡，只产生重叠事件 on_begin/end_overlap


class AABBCollider:
    """附着在 Entity 上的轴对齐包围盒（AABB）碰撞体。"""

    def __init__(self, mode: str = Collider.BLOCK,
                 half_extents: Optional[tuple] = None,
                 offset=(0.0, 0.0, 0.0), enabled: bool = True):
        self.mode = mode
        self.half_extents = half_extents
        self.offset = list(offset)
        self.enabled = enabled

    def compute_aabb(self, entity: Entity):
        """返回 (min, max) 世界空间 AABB。"""
        center = np.array(entity.position, dtype=np.float64) + np.array(self.offset, dtype=np.float64)
        if self.half_extents is not None:
            h = np.array(self.half_extents, dtype=np.float64)
        else:
            bb = entity.bounding_box()
            if bb is None:
                h = np.array([0.5, 0.5, 0.5], dtype=np.float64)
            else:
                mn, mx = bb
                h = (np.array(mx, float) - np.array(mn, float)) * 0.5 + 1e-6
        return (center - h, center + h)


def add_collider(entity: Entity, mode: str = Collider.BLOCK,
                 half_extents: Optional[tuple] = None,
                 offset=(0.0, 0.0, 0.0)) -> AABBCollider:
    """给实体挂上碰撞体，返回该碰撞体（便于链式设置）。"""
    entity.collider = AABBCollider(mode, half_extents, offset)
    return entity.collider


# --------------------------------------------------------------------------- #
# 几何工具
# --------------------------------------------------------------------------- #
def _segment_hits_box(a, b, lo, hi, eps: float = 1e-12) -> bool:
    """线段 a->b 是否与轴对齐盒 [lo, hi] 相交（Liang-Barsky 线段-盒判交）。"""
    d = b - a
    tmin, tmax = 0.0, 1.0
    for i in range(3):
        if abs(d[i]) < eps:
            if a[i] < lo[i] or a[i] > hi[i]:
                return False
        else:
            t1 = (lo[i] - a[i]) / d[i]
            t2 = (hi[i] - a[i]) / d[i]
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
            if tmin > tmax:
                return False
    return True


def aabb_overlap(a, b) -> bool:
    (amin, amax), (bmin, bmax) = a, b
    return all(amin[i] <= bmax[i] and amax[i] >= bmin[i] for i in range(3))


def capsule_intersects_aabb(seg_a, seg_b, radius, aabb_min, aabb_max) -> bool:
    """胶囊体（线段 + 半径）是否与 AABB 相交：把 AABB 各向膨胀 radius 后再做线段判交。"""
    lo = np.array(aabb_min, float) - radius
    hi = np.array(aabb_max, float) + radius
    return _segment_hits_box(np.array(seg_a, float), np.array(seg_b, float), lo, hi)


# --------------------------------------------------------------------------- #
# 玩家胶囊体控制器
# --------------------------------------------------------------------------- #
class CharacterController:
    """胶囊体玩家控制器：重力 / 跳跃 / 落地 / 水平移动。"""

    def __init__(self, position=(0.0, 0.0, 0.0), radius: float = 0.4,
                 height: float = 1.8, eye_height: float = 1.6,
                 gravity: float = -20.0, jump_speed: float = 6.0,
                 move_speed: float = 4.0):
        self.position = np.array(position, dtype=np.float64)
        self.velocity = np.zeros(3, dtype=np.float64)
        self.radius = float(radius)
        self.height = float(height)
        self.eye_height = float(eye_height)
        self.gravity = float(gravity)
        self.jump_speed = float(jump_speed)
        self.move_speed = float(move_speed)
        self.grounded = False
        self.collider: Optional[AABBCollider] = None
        self.on_begin_overlap: Optional[Callable] = None
        self.on_end_overlap: Optional[Callable] = None
        self.on_hit: Optional[Callable] = None
        self.on_land: Optional[Callable] = None
        self.on_jump: Optional[Callable] = None

    # ------------------------------------------------------------------ #
    def bottom(self) -> np.ndarray:
        return self.position - np.array([0.0, self.height / 2.0, 0.0])

    def top(self) -> np.ndarray:
        return self.position + np.array([0.0, self.height / 2.0, 0.0])

    def eye_position(self) -> np.ndarray:
        return self.position + np.array([0.0, self.eye_height, 0.0])

    def relaxed_aabb(self):
        """胶囊体的宽松 AABB（供窄相 Box-Box 解析）。"""
        r, h2 = self.radius, self.height / 2.0
        return (self.position - np.array([r, h2, r]),
                self.position + np.array([r, h2, r]))

    def set_move(self, forward: float, right: float, yaw: float) -> None:
        """根据相机偏航把 WASD 输入换算为水平移动速度（仅 XZ）。"""
        s, _u, f = camera_basis_from_yaw_pitch(yaw, 0.0)
        wx = f[0] * forward + s[0] * right
        wz = f[2] * forward + s[2] * right
        ln = math.hypot(wx, wz)
        if ln > 1e-9:
            self.velocity[0] = (wx / ln) * self.move_speed
            self.velocity[2] = (wz / ln) * self.move_speed
        else:
            self.velocity[0] = 0.0
            self.velocity[2] = 0.0

    def jump(self) -> None:
        if self.grounded:
            self.velocity[1] = self.jump_speed
            self.grounded = False
            if self.on_jump:
                self.on_jump()

    def integrate(self, dt: float) -> None:
        """单步积分：水平速度保持，垂直受重力，位置推进。"""
        if not self.grounded:
            self.velocity[1] += self.gravity * dt
        else:
            self.velocity[1] = min(self.velocity[1], 0.0)
        self.position = self.position + self.velocity * dt


# --------------------------------------------------------------------------- #
# 物理世界
# --------------------------------------------------------------------------- #
class PhysicsWorld:
    """轻量物理世界：宽相筛选 + 窄相解析 + 重叠事件。"""

    def __init__(self, scene: Scene, player: CharacterController,
                 broadphase_radius: float = 20.0, broadphase_interval: int = 60,
                 substeps: int = 4, **kwargs):
        self.scene = scene
        self.player = player
        self.broadphase_radius = float(broadphase_radius)
        self.broadphase_interval = max(1, int(broadphase_interval))
        self.substeps = max(1, int(substeps))
        self.tick = 0
        self._nearby: List[Entity] = []
        self._player_overlaps: Set[Entity] = set()
        self._refresh_nearby()

    # ------------------------------------------------------------------ #
    def set_scene(self, scene: Scene) -> None:
        self.scene = scene
        self._player_overlaps.clear()
        self._refresh_nearby()

    def collider_entities(self):
        for e in self.scene.entities:
            col = getattr(e, "collider", None)
            if col is not None and col.enabled:
                yield e

    def _aabb_near_player(self, entity: Entity) -> bool:
        col = entity.collider
        if col is None:
            return False
        mn, mx = col.compute_aabb(entity)
        center = (mn + mx) * 0.5
        d = np.linalg.norm(center - self.player.position)
        return d <= self.broadphase_radius + self.player.radius

    def _refresh_nearby(self) -> None:
        self._nearby = [e for e in self.collider_entities() if self._aabb_near_player(e)]

    # ------------------------------------------------------------------ #
    def _resolve_player_block(self, entity: Entity) -> bool:
        """把玩家从 Block 碰撞体中推出；返回是否发生接触（命中）。"""
        col = entity.collider
        bmin, bmax = col.compute_aabb(entity)
        pmn, pmx = self.player.relaxed_aabb()

        if not all(pmn[i] <= bmax[i] and pmx[i] >= bmin[i] for i in range(3)):
            return False

        pen = []
        for i in range(3):
            pen.append(min(pmx[i] - bmin[i], bmax[i] - pmn[i]))
        axis = int(np.argmin(pen))
        box_center = (bmin[axis] + bmax[axis]) * 0.5
        sign = 1.0 if self.player.position[axis] > box_center else -1.0

        self.player.position[axis] += sign * pen[axis]
        self.player.velocity[axis] = 0.0

        if axis == 1:  # Y 轴接触
            if sign > 0.0:   # 玩家在盒上方被顶住 → 落地
                if not self.player.grounded:
                    self.player.grounded = True
                    if self.player.on_land:
                        self.player.on_land()
            else:            # 玩家在盒下方（头顶）→ 撞天花板
                self.player.grounded = False
        return True

    # ------------------------------------------------------------------ #
    def _player_overlaps_aabb(self, entity: Entity) -> bool:
        col = entity.collider
        mn, mx = col.compute_aabb(entity)
        return capsule_intersects_aabb(self.player.bottom(), self.player.top(),
                                       self.player.radius, mn, mx)

    def _fire(self, other: Entity, attr: str, target) -> None:
        fn = getattr(other, attr, None)
        if fn is not None:
            try:
                fn(target)
            except TypeError:
                fn(target, target.position)
        pfn = getattr(self.player, attr, None)
        if pfn is not None:
            try:
                pfn(other)
            except TypeError:
                pfn(other, other.position)

    # ------------------------------------------------------------------ #
    def step(self, dt: float, move_input=None, jump: bool = False,
             yaw: float = 0.0) -> None:
        """推进一帧物理。move_input=(forward, right)；jump=是否请求跳跃。"""
        self.tick += 1
        if self.tick % self.broadphase_interval == 0:
            self._refresh_nearby()

        if move_input is not None:
            self.player.set_move(move_input[0], move_input[1], yaw)
        if jump:
            self.player.jump()

        self.player.grounded = False
        sdt = dt / self.substeps
        hit = set()
        for _ in range(self.substeps):
            self.player.integrate(sdt)
            for e in self._nearby:
                col = getattr(e, "collider", None)
                if col is None or not col.enabled or col.mode != Collider.BLOCK:
                    continue
                if self._resolve_player_block(e):
                    hit.add(e)

        new_overlaps = set()
        for e in self._nearby:
            col = getattr(e, "collider", None)
            if col is None or not col.enabled or col.mode != Collider.OVERLAP:
                continue
            if self._player_overlaps_aabb(e):
                new_overlaps.add(e)

        for e in new_overlaps - self._player_overlaps:
            self._fire(e, "on_begin_overlap", self.player)
        for e in self._player_overlaps - new_overlaps:
            self._fire(e, "on_end_overlap", self.player)
        self._player_overlaps = new_overlaps

        for e in hit:
            self._fire(e, "on_hit", self.player)

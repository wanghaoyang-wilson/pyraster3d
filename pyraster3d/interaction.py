"""
interaction.py — 交互事件系统（Hover / Hit / Clicked / MouseDown / MouseUp）
所有可交互对象（3D Actor 与 2D UI 组件）继承 Interactive 基类。
事件优先级：UI(2D) > 场景(3D 射线拾取)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np

if TYPE_CHECKING:
    from .scene import Entity


@dataclass
class HitInfo:
    """一次命中检测的结果。"""
    entity: Optional["Entity"] = None
    distance: float = 0.0
    world_pos: tuple = (0.0, 0.0, 0.0)
    normal: tuple = (0.0, 1.0, 0.0)
    uv: tuple = (0.0, 0.0)
    triangle_index: int = -1
    ui_element: object = None           # 命中的 2D UI 元素（若有）
    payload: dict = field(default_factory=dict)


class Interactive:
    """
    可交互对象基类。子类在命中检测命中/未命中、按下/松开时被回调。
    事件回调签名统一为 callable(HitInfo) 或 callable()。
    """

    def __init__(self):
        self.on_hover: Optional[Callable[[HitInfo], None]] = None
        self.on_mouse_enter: Optional[Callable[[HitInfo], None]] = None
        self.on_mouse_exit: Optional[Callable[[], None]] = None
        self.on_clicked: Optional[Callable[[HitInfo], None]] = None
        self.on_mouse_down: Optional[Callable[[HitInfo], None]] = None
        self.on_mouse_up: Optional[Callable[[HitInfo], None]] = None
        self.on_drag: Optional[Callable[[HitInfo], None]] = None
        self.on_scroll: Optional[Callable[[int], None]] = None

        # 内部状态
        self._is_hovered = False
        self._pressed = False

    # ------------------------------------------------------------------ #
    # 命中状态处理
    # ------------------------------------------------------------------ #
    def process_hit(self, hit: HitInfo) -> None:
        if not self._is_hovered:
            self._is_hovered = True
            if self.on_mouse_enter:
                self.on_mouse_enter(hit)
        if self.on_hover:
            self.on_hover(hit)

    def process_unhit(self) -> None:
        if self._is_hovered:
            self._is_hovered = False
            if self.on_mouse_exit:
                self.on_mouse_exit()

    def process_press(self, hit: HitInfo) -> None:
        self._pressed = True
        if self.on_mouse_down:
            self.on_mouse_down(hit)

    def process_release(self, hit: HitInfo, released_on_self: bool) -> None:
        was_pressed = self._pressed
        self._pressed = False
        if was_pressed and released_on_self and self.on_clicked:
            self.on_clicked(hit)
        if self.on_mouse_up:
            self.on_mouse_up(hit)

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #
    @property
    def is_hovered(self) -> bool:
        return self._is_hovered


def hit_info_from_ray(entity, t, world_pos, normal, uv, tri_index) -> HitInfo:
    return HitInfo(
        entity=entity,
        distance=float(t),
        world_pos=tuple(float(v) for v in world_pos),
        normal=tuple(float(v) for v in normal),
        uv=(float(uv[0]), float(uv[1])),
        triangle_index=tri_index,
    )

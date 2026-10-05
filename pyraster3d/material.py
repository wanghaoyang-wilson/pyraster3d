"""
material.py — 材质系统
- SolidColorMaterial：纯色（含 Alpha）
- TextureMaterial：贴图（含可选重复、过滤）
- 额外可选参数：反射率 reflectivity（供轻度光追反射用）
"""
from __future__ import annotations

from typing import Optional

import numpy as np

try:
    import pygame
    _HAS_PYGAME = True
except Exception:                       # pragma: no cover
    _HAS_PYGAME = False


def _clamp_color(c) -> tuple:
    r, g, b = int(c[0]), int(c[1]), int(c[2])
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


class Material:
    """材质基类。"""
    kind = "base"
    reflectivity = 0.0      # 0..1，反射强度（轻度光追）
    alpha = 1.0             # 0..1，透明度
    transparent = False
    wireframe = False

    def to_dict(self) -> dict:
        return {"type": self.kind}


class SolidColorMaterial(Material):
    kind = "solid"

    def __init__(self, color=(180, 180, 180), alpha=1.0, reflectivity=0.0):
        self.color = _clamp_color(color)
        self.alpha = max(0.0, min(1.0, alpha))
        self.reflectivity = max(0.0, min(1.0, reflectivity))
        self.transparent = self.alpha < 0.999

    def sample(self, uv) -> tuple:
        return (self.color, self.alpha)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "color": list(self.color),
            "alpha": self.alpha,
            "reflectivity": self.reflectivity,
        })
        return d


class TextureMaterial(Material):
    kind = "texture"

    def __init__(self, path: str, texture: Optional["pygame.Surface"] = None,
                 alpha=1.0, reflectivity=0.0, repeat=True, filtering="bilinear"):
        self.path = path
        self.alpha = max(0.0, min(1.0, alpha))
        self.reflectivity = max(0.0, min(1.0, reflectivity))
        self.transparent = self.alpha < 0.999
        self.repeat = repeat
        self.filtering = filtering
        self.texture = texture
        self._tex_array = None
        if self.texture is None and _HAS_PYGAME and path:
            self._load()

    def _load(self):
        surf = pygame.image.load(self.path).convert_alpha()
        self.texture = surf
        self._tex_array = None

    def _ensure_array(self):
        if self._tex_array is None and self.texture is not None:
            self._tex_array = pygame.surfarray.array3d(self.texture).astype(np.float64)

    def sample(self, uv) -> tuple:
        self._ensure_array()
        if self._tex_array is None:
            return ((200, 200, 200), self.alpha)
        tex = self._tex_array
        th, tw = tex.shape[0], tex.shape[1]
        u, v = uv[0], uv[1]
        if self.repeat:
            u = u % 1.0
            v = v % 1.0
        x = u * tw
        y = v * th
        if self.filtering == "nearest":
            xi = int(min(tw - 1, max(0, int(x))))
            yi = int(min(th - 1, max(0, int(y))))
            c = tex[yi, xi]
        else:  # bilinear
            x0 = int(x) % tw
            x1 = (x0 + 1) % tw
            y0 = int(y) % th
            y1 = (y0 + 1) % th
            fx, fy = x - int(x), y - int(y)
            c = (tex[y0, x0] * (1 - fx) * (1 - fy) +
                 tex[y0, x1] * fx * (1 - fy) +
                 tex[y1, x0] * (1 - fx) * fy +
                 tex[y1, x1] * fx * fy)
        return (tuple(int(c[i]) for i in range(3)), self.alpha)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "path": self.path,
            "alpha": self.alpha,
            "reflectivity": self.reflectivity,
            "repeat": self.repeat,
            "filtering": self.filtering,
        })
        return d


def material_from_dict(data: Optional[dict]) -> Material:
    if not data:
        return SolidColorMaterial()
    typ = data.get("type", "solid")
    if typ == "texture":
        return TextureMaterial(
            path=data.get("path", ""),
            alpha=data.get("alpha", 1.0),
            reflectivity=data.get("reflectivity", 0.0),
            repeat=data.get("repeat", True),
            filtering=data.get("filtering", "bilinear"),
        )
    return SolidColorMaterial(
        color=tuple(data.get("color", (180, 180, 180))),
        alpha=data.get("alpha", 1.0),
        reflectivity=data.get("reflectivity", 0.0),
    )

"""
ui.py — 2D UI 系统（叠加在 3D 画面之上）
元素：Label / Button / Panel / InputLine
绘制顺序：先渲染完整 3D 场景，再由 App 在主线程绘制 UI 层。
UI 事件优先级高于 3D 射线拾取（见 app.py 的事件分发）。
"""
from __future__ import annotations

from typing import Optional

from .interaction import Interactive, HitInfo


class UIElement(Interactive):
    def __init__(self, rect=(0, 0, 120, 30), name="ui"):
        super().__init__()
        self.rect = list(rect)          # (x, y, w, h)
        self.name = name
        self.visible = True
        self.background = (48, 48, 54)
        self.hover_background = (72, 72, 82)

    @property
    def x(self): return self.rect[0]

    @property
    def y(self): return self.rect[1]

    @property
    def w(self): return self.rect[2]

    @property
    def h(self): return self.rect[3]

    def point_in_rect(self, mx, my) -> bool:
        x, y, w, h = self.rect
        return x <= mx <= x + w and y <= my <= y + h

    def draw(self, surface) -> None:
        import pygame
        bg = self.hover_background if self._is_hovered else self.background
        pygame.draw.rect(surface, bg, tuple(int(v) for v in self.rect))

    def hit_info(self, mx, my) -> HitInfo:
        return HitInfo(entity=None, distance=0.0,
                       world_pos=(0.0, 0.0, 0.0), normal=(0.0, 1.0, 0.0),
                       uv=(0.0, 0.0), ui_element=self)


class Label(UIElement):
    def __init__(self, text="", rect=(0, 0, 200, 26), name="label", color=(230, 230, 230)):
        super().__init__(rect, name)
        self.text = text
        self.color = color
        self.background = None
        self.hover_background = None

    def draw(self, surface) -> None:
        import pygame
        font = pygame.font.SysFont("microsoftyahei,simhei,notosanscjk,arial", 16)
        surf = font.render(self.text, True, self.color)
        surface.blit(surf, (int(self.rect[0]), int(self.rect[1])))


class Button(UIElement):
    def __init__(self, text="", rect=(0, 0, 120, 30), name="button",
                 bg=(60, 90, 140), hover=(90, 120, 170), fg=(240, 240, 240)):
        super().__init__(rect, name)
        self.text = text
        self.background = bg
        self.hover_background = hover
        self.fg = fg

    def draw(self, surface) -> None:
        import pygame
        bg = self.hover_background if self._is_hovered else self.background
        pygame.draw.rect(surface, bg, tuple(int(v) for v in self.rect), border_radius=4)
        font = pygame.font.SysFont("microsoftyahei,simhei,notosanscjk,arial", 14)
        txt = font.render(self.text, True, self.fg)
        tw, th = txt.get_size()
        surface.blit(txt, (int(self.rect[0] + (self.w - tw) / 2),
                           int(self.rect[1] + (self.h - th) / 2)))


class Panel(UIElement):
    def __init__(self, rect=(0, 0, 220, 300), name="panel", bg=(24, 26, 32)):
        super().__init__(rect, name)
        self.background = bg
        self.hover_background = bg
        self.children = []
        self.alpha = 200

    def add(self, child: UIElement) -> "Panel":
        self.children.append(child)
        return self

    def draw(self, surface) -> None:
        import pygame
        bg = (*self.background, self.alpha)
        s = pygame.Surface((int(self.w), int(self.h)), pygame.SRCALPHA)
        s.fill(bg)
        surface.blit(s, (int(self.x), int(self.y)))
        for c in self.children:
            if c.visible:
                c.draw(surface)

    def point_in_rect(self, mx, my) -> bool:
        # 面板自身也参与命中；子元素由上层单独判定
        x, y, w, h = self.rect
        return x <= mx <= x + w and y <= my <= y + h


class UILayer:
    def __init__(self):
        self.elements: list = []

    def add(self, element: UIElement) -> UIElement:
        self.elements.append(element)
        return element

    def remove(self, element: UIElement) -> None:
        if element in self.elements:
            self.elements.remove(element)

    def clear(self) -> None:
        self.elements.clear()

    def pick(self, mx, my) -> Optional[UIElement]:
        """命中检测（后添加者优先，模拟层级）。"""
        for el in reversed(self.elements):
            if el.visible and el.point_in_rect(mx, my):
                return el
        return None

    def draw(self, surface) -> None:
        for el in self.elements:
            if el.visible:
                el.draw(surface)

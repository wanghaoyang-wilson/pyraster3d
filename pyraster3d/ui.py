"""
ui.py — 2D UI 系统（叠加在 3D 画面之上）
元素：Label / Button / Panel / UILayer
绘制顺序：先渲染完整 3D 场景，再由 App 在主线程绘制 UI 层。
UI 事件优先级高于 3D 射线拾取（见 app.py 的事件分发）。

本轮改良（风格/主题，无架构级改动）：
- 新增 `UITheme` 主题系统（模块级 `theme` 单例），统一配色。
- Button：圆角 + 边框 + 悬停/按下状态 + 聚焦高亮。
- Panel：半透明背景 + 边框 + 可选手写标题栏。
- Label：可选文字阴影。
"""
from __future__ import annotations

from typing import Optional

from .interaction import Interactive, HitInfo


class UITheme:
    """UI 主题：集中管理配色，元素绘制时引用。"""

    def __init__(self):
        self.panel_bg = (24, 26, 32)
        self.panel_alpha = 210
        self.panel_border = (72, 82, 100)
        self.button_bg = (52, 88, 132)
        self.button_hover = (74, 116, 168)
        self.button_active = (40, 66, 100)
        self.button_border = (110, 150, 200)
        self.button_fg = (240, 242, 245)
        self.label_fg = (214, 222, 232)
        self.label_shadow = (0, 0, 0)
        self.title_fg = (255, 205, 92)
        self.hint_fg = (150, 158, 170)
        self.bg = (28, 30, 36)
        self.accent = (255, 205, 92)
        self.radius = 6


# 模块级默认主题
theme = UITheme()


def set_theme(t: Optional[UITheme]) -> None:
    """设置全局 UI 主题。"""
    global theme
    if t is not None:
        theme = t


def _font(size: int):
    import pygame
    try:
        return pygame.font.SysFont("microsoftyahei,simhei,notosanscjk,arial", size)
    except Exception:                                   # noqa: BLE001
        return pygame.font.Font(None, size)


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
    def __init__(self, text="", rect=(0, 0, 200, 26), name="label",
                 color=(230, 230, 230), size=16, shadow: bool = False):
        super().__init__(rect, name)
        self.text = text
        self.color = color
        self.background = None
        self.hover_background = None
        self.size = size
        self.shadow = shadow

    def draw(self, surface) -> None:
        import pygame
        font = _font(self.size)
        txt = font.render(self.text, True, self.color)
        if self.shadow:
            sh = font.render(self.text, True, theme.label_shadow)
            surface.blit(sh, (int(self.rect[0]) + 1, int(self.rect[1]) + 1))
        surface.blit(txt, (int(self.rect[0]), int(self.rect[1])))


class Button(UIElement):
    def __init__(self, text="", rect=(0, 0, 120, 30), name="button",
                 bg=None, hover=None, fg=None):
        super().__init__(rect, name)
        self.text = text
        self.background = bg or theme.button_bg
        self.hover_background = hover or theme.button_hover
        self.fg = fg or theme.button_fg
        self.active_background = theme.button_active

    def draw(self, surface) -> None:
        import pygame
        x, y, w, h = (int(v) for v in self.rect)
        if self._pressed:
            bg = self.active_background
        elif self._is_hovered:
            bg = self.hover_background
        else:
            bg = self.background
        r = theme.radius
        pygame.draw.rect(surface, bg, (x, y, w, h), border_radius=r)
        pygame.draw.rect(surface, theme.button_border, (x, y, w, h),
                         width=1, border_radius=r)
        font = _font(14)
        txt = font.render(self.text, True, self.fg)
        tw, th = txt.get_size()
        surface.blit(txt, (x + (w - tw) // 2, y + (h - th) // 2))


class Panel(UIElement):
    def __init__(self, rect=(0, 0, 220, 300), name="panel", bg=None,
                 title: Optional[str] = None):
        super().__init__(rect, name)
        self.background = bg or theme.panel_bg
        self.hover_background = self.background
        self.alpha = theme.panel_alpha
        self.title = title
        self.children = []

    def add(self, child: UIElement) -> "Panel":
        self.children.append(child)
        return self

    def draw(self, surface) -> None:
        import pygame
        x, y, w, h = (int(v) for v in self.rect)
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        s.fill((*self.background, self.alpha))
        surface.blit(s, (x, y))
        pygame.draw.rect(surface, theme.panel_border, (x, y, w, h),
                         width=1, border_radius=theme.radius)
        if self.title:
            font = _font(15)
            tsurf = font.render(self.title, True, theme.title_fg)
            surface.blit(tsurf, (x + 12, y + 8))
        for c in self.children:
            if c.visible:
                c.draw(surface)

    def point_in_rect(self, mx, my) -> bool:
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
        for el in reversed(self.elements):
            if el.visible and el.point_in_rect(mx, my):
                return el
        return None

    def draw(self, surface) -> None:
        for el in self.elements:
            if el.visible:
                el.draw(surface)

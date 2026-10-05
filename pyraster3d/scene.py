"""
scene.py — 场景管理（Scene）与实体（Entity）
- Entity：对应 UE 里「Actor」，含 Transform（Position/Rotation/Scale）与网格、材质。
- Scene：对应 UE 里的「Level / World」，管理场景实体集合，支持场景树（父子）。
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .material import Material, SolidColorMaterial
from .matrix import model_matrix, translate, rotation as rot_matrix
from .model import Model
from .interaction import Interactive


class Entity(Interactive):
    """场景中的一个物体（Actor）。"""

    def __init__(self, model: Optional[Model] = None, name: str = "actor",
                 position=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0),
                 scale=(1.0, 1.0, 1.0), material: Optional[Material] = None,
                 parent: Optional["Entity"] = None):
        super().__init__()
        self.name = name
        self.model = model
        self.material = material or (model.material if model is not None
                                     else SolidColorMaterial((180, 180, 180)))
        self.position = list(position)
        self.rotation = list(rotation)
        self.scale = list(scale)
        self.parent = parent
        self.children = []
        self.visible = True
        self.solid = True                      # 是否写入 Z 缓冲（关闭=透明）
        self.cast_shadow = True
        self.receive_shadow = True
        self.is_light = False
        if parent is not None:
            parent.children.append(self)

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    def set_transform(self, position=None, rotation=None, scale=None):
        if position is not None:
            self.position = list(position)
        if rotation is not None:
            self.rotation = list(rotation)
        if scale is not None:
            self.scale = list(scale)
        if self.model is not None:
            self.model.invalidate_cache()

    @property
    def world_matrix(self) -> np.ndarray:
        local = model_matrix(self.position, self.rotation, self.scale)
        if self.parent is None:
            return local
        return self.parent.world_matrix @ local

    @property
    def world_position(self) -> np.ndarray:
        m = self.world_matrix
        return np.array([m[0, 3], m[1, 3], m[2, 3]])

    def world_vertices(self):
        """当前世界空间顶点（带缓存）。"""
        if self.model is None:
            return np.zeros((0, 3)), np.zeros((0, 3))
        return self.model.transform(self.world_matrix)

    def bounding_box(self):
        """世界空间 AABB（min, max）。"""
        wv, _ = self.world_vertices()
        if len(wv) == 0:
            return None
        return wv.min(axis=0), wv.max(axis=0)

    # ------------------------------------------------------------------ #
    # 序列化（关卡保存/加载）
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "model": self.model.name if self.model is not None else None,
            "position": list(self.position),
            "rotation": list(self.rotation),
            "scale": list(self.scale),
            "solid": self.solid,
            "cast_shadow": self.cast_shadow,
            "receive_shadow": self.receive_shadow,
            "visible": self.visible,
            "material": self.material.to_dict() if self.material else None,
        }
        if self.model is not None and self.model.name not in ("cube", "plane",
                                                               "sphere", "cylinder"):
            d["mesh_path"] = getattr(self.model, "_mesh_path", None)
        return d

    def __repr__(self):
        return f"<Entity '{self.name}' model={self.model.name if self.model else None} pos={self.position}>"


class Scene:
    """场景 / 关卡（Level）。"""

    def __init__(self, name: str = "Untitled"):
        self.name = name
        self.entities = []
        self.lights = []            # Entity 中 is_light=True 的灯光（或独立灯光）
        self.ambient = (0.22, 0.22, 0.26)
        self.sun_direction = np.array([0.5, 0.8, 0.4], dtype=np.float64)
        self.sun_color = (1.0, 1.0, 1.0)
        self.sky_color = (24, 26, 34)

    def add(self, entity: Entity) -> Entity:
        if entity.parent is None:
            self.entities.append(entity)
        if entity.is_light:
            self.lights.append(entity)
        return entity

    def remove(self, entity: Entity) -> None:
        if entity in self.entities:
            self.entities.remove(entity)
        if entity in self.lights:
            self.lights.remove(entity)
        if entity.parent is not None and entity in entity.parent.children:
            entity.parent.children.remove(entity)

    def clear(self) -> None:
        self.entities.clear()
        self.lights.clear()

    def find(self, name: str) -> Optional[Entity]:
        for e in self.entities:
            if e.name == name:
                return e
        return None

    def all_world_models(self):
        """遍历所有可见、有网格的实体及其世界顶点。"""
        for e in self.entities:
            if not e.visible or e.model is None:
                continue
            yield e

    # ------------------------------------------------------------------ #
    # 序列化
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ambient": list(self.ambient),
            "sun_direction": list(self.sun_direction),
            "sun_color": list(self.sun_color),
            "sky_color": list(self.sky_color),
            "entities": [e.to_dict() for e in self.entities],
        }

    def from_dict(self, data: dict) -> None:
        self.name = data.get("name", self.name)
        self.ambient = tuple(data.get("ambient", self.ambient))
        self.sun_direction = np.array(data.get("sun_direction", list(self.sun_direction)))
        self.sun_color = tuple(data.get("sun_color", self.sun_color))
        self.sky_color = tuple(data.get("sky_color", self.sky_color))
        for ed in data.get("entities", []):
            self.add(entity_from_dict(ed))


# 延迟导入避免循环依赖
def entity_from_dict(d: dict) -> Entity:
    from .primitives import PRIMITIVE_FACTORIES
    from .material import material_from_dict
    from .objloader import load_obj

    model = None
    kind = d.get("model")
    if kind:
        if kind.lower() in PRIMITIVE_FACTORIES:
            model = PRIMITIVE_FACTORIES[kind.lower()]()
        else:
            mesh_path = d.get("mesh_path")
            if mesh_path:
                model = load_obj(mesh_path)
                model.name = kind
    entity = Entity(
        model=model,
        name=d.get("name", "actor"),
        position=d.get("position", [0, 0, 0]),
        rotation=d.get("rotation", [0, 0, 0]),
        scale=d.get("scale", [1, 1, 1]),
        material=material_from_dict(d.get("material")),
    )
    entity.solid = d.get("solid", True)
    entity.cast_shadow = d.get("cast_shadow", True)
    entity.receive_shadow = d.get("receive_shadow", True)
    entity.visible = d.get("visible", True)
    return entity

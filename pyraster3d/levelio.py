"""
levelio.py — 关卡配置文件读写（Level Save/Load）
关卡文件为 JSON，包含：
  - 关卡名、光照/天空设置
  - 相机生成信息
  - 实体列表（模型、Transform、材质、标志位）
支持：关卡编辑器打开/加载/保存关卡。
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .scene import Scene, entity_from_dict


def default_level_dict(name: str = "Untitled") -> dict:
    return {
        "name": name,
        "version": 1,
        "camera": {
            "mode": "fpp",
            "position": [0.0, 1.5, -8.0],
            "yaw": 0.0,
            "pitch": 0.0,
            "tpp_distance": 6.0,
            "tpp_height_offset": 1.5,
        },
        "scene": {
            "name": name,
            "ambient": [0.22, 0.22, 0.26],
            "sun_direction": [0.4, 0.8, 0.45],
            "sun_color": [1.0, 0.98, 0.94],
            "sky_color": [24, 26, 34],
            "entities": [],
        },
    }


def save_level(path: str, scene: Scene, camera_info: dict, name: Optional[str] = None) -> None:
    """把场景与相机信息保存为关卡 JSON 文件。"""
    data = default_level_dict(name or scene.name)
    data["name"] = name or scene.name
    data["camera"] = {
        "mode": camera_info.get("mode", "fpp"),
        "position": list(camera_info.get("position", [0.0, 1.5, -8.0])),
        "yaw": float(camera_info.get("yaw", 0.0)),
        "pitch": float(camera_info.get("pitch", 0.0)),
        "tpp_distance": float(camera_info.get("tpp_distance", 6.0)),
        "tpp_height_offset": float(camera_info.get("tpp_height_offset", 1.5)),
    }
    data["scene"] = scene.to_dict()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def load_level(path: str) -> tuple:
    """
    加载关卡 JSON，返回 (Scene, camera_info dict)。
    路径可以是绝对路径或相对路径。
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    scene_dict = data.get("scene", {})
    scene = Scene(name=scene_dict.get("name", data.get("name", "Level")))
    scene.from_dict(scene_dict)

    cam = data.get("camera", {})
    camera_info = {
        "mode": cam.get("mode", "fpp"),
        "position": cam.get("position", [0.0, 1.5, -8.0]),
        "yaw": cam.get("yaw", 0.0),
        "pitch": cam.get("pitch", 0.0),
        "tpp_distance": cam.get("tpp_distance", 6.0),
        "tpp_height_offset": cam.get("tpp_height_offset", 1.5),
    }
    return scene, camera_info


def level_from_entities(entities: list, camera_info: Optional[dict] = None) -> dict:
    """从实体列表构造关卡字典（供编辑器即时构建）。"""
    data = default_level_dict()
    data["scene"]["entities"] = [e.to_dict() for e in entities]
    if camera_info:
        data["camera"].update(camera_info)
    return data

"""
config.py — 引擎配置文件（JSON）
提供默认配置与深合并加载；App 启动时读取。
"""
from __future__ import annotations

import json
import os
from typing import Optional

DEFAULT_CONFIG = {
    "window": {
        "width": 1000,
        "height": 700,
        "title": "Pyraster3D",
        "fps_cap": 0,                 # 0 = 不限帧率
    },
    "renderer": {
        "fov_degrees": 70.0,
        "z_near": 0.1,
        "z_far": 200.0,
        "shadows": True,
        "shadow_map_size": 512,
        "raytracing": False,          # 轻度光追总开关
        "max_bounces": 1,
        "raytrace_shadows": False,
        "raytrace_ao": False,
        "edge_depth_sampling": False,  # 仅边缘深度采样优化   true
        "cull_backface": True,
        "ambient": [0.22, 0.22, 0.26],
        "sun_direction": [0.4, 0.8, 0.45],
        "sun_color": [1.0, 0.98, 0.94],
    },
    "camera_defaults": {
        "fov_degrees": 70.0,
        "speed": 0.25,
        "mouse_sensitivity": 0.003,
        "tpp_distance": 6.0,
        "tpp_height_offset": 1.5,
    },
    "threading": {
        "workers": 2,
        "async_scene_compile": True,
        "async_shadow": True,
    },
    "editor": {
        "enabled": True,
        "grid": True,
        "grid_size": 1.0,
        "snap_translate": 0.5,
        "snap_rotate": 15.0,
        "show_fps": True,
        "default_sun_direction": [0.4, 0.8, 0.45],
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Optional[str] = None) -> dict:
    """读取配置文件并深合并到默认值；文件不存在/解析失败则用默认值。"""
    cfg = deep_merge(DEFAULT_CONFIG, {})
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                user = json.load(fh)
            cfg = deep_merge(cfg, user)
        except Exception as e:          # noqa: BLE001
            print(f"[config] 读取配置失败 {path}: {e}，使用默认配置")
    return cfg


def save_config(cfg: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)

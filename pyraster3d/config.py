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
        "edge_depth_sampling": True,  # 仅边缘深度采样优化
        "cull_backface": True,
        "backend": "pygame",         # 渲染后端："pygame" | "direct2d"(Windows-only, 预留)
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
    "physics": {
        "enabled": True,              # 物理引擎总开关
        "player_radius": 0.4,         # 玩家胶囊体半径
        "player_height": 1.8,         # 玩家胶囊体高度
        "eye_height": 1.6,            # 相机眼高（玩家中心到眼睛）
        "gravity": -20.0,             # 重力（-Y）
        "jump_speed": 6.0,            # 跳跃初速度
        "move_speed": 4.0,            # 水平移动速度
        "broadphase_radius": 20.0,    # 宽相筛选半径（单位）
        "broadphase_interval": 60,    # 每多少游戏刻刷新一次附近碰撞体
        "substeps": 4,                # 每帧细分时间步数（防穿透）
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

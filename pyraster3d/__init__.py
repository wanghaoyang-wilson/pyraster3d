"""
Pyraster3D — 基于 Pygame 的软光栅 3D 引擎库
====================================================
一套仿 Ursina 风格 API、底层为自研软光栅的轻量 3D 引擎：
- 左手坐标系
- Z-Buffer 软光栅 + 可选「仅边缘深度采样」优化
- 透明物体画家算法叠加
- 轻度光线追踪（BVH 加速：阴影射线 / 反射 / AO）
- 第一人称 / 第三人称相机、鼠标锁定
- OBJ 模型导入 + 基础几何体 + 纯色/贴图材质
- 阴影贴图
- 多线程异步场景编译（BVH / 阴影后台重建）
- UI 系统 + Hover/Hit/Clicked 交互事件
- 物理引擎（AABB 碰撞体 / 胶囊体玩家 / 重叠事件）
- 关卡编辑器 + 关卡配置文件（JSON）读写
- 引擎配置文件（JSON）
"""
from __future__ import annotations

__version__ = "0.2.0"

# 核心入口
from .app import App

# 场景 / 实体
from .scene import Scene, Entity, entity_from_dict

# 相机
from .camera import Camera, FPPCamera, TPPCamera

# 材质
from .material import Material, SolidColorMaterial, TextureMaterial, material_from_dict

# 几何体 / 模型
from .model import Model
from .primitives import (cube, plane, sphere, cylinder,
                         build_primitive, PRIMITIVE_NAMES)
from .objloader import load_obj

# 渲染 / 阴影 / 光追
from .renderer import Renderer
from .rasterizer import ShaderConfig
from .shadowmap import ShadowMap
from .bvh import BVH, build_scene_bvh
from .raytrace import trace_shadow, trace_reflection, trace_ao

# 交互 / UI
from .interaction import Interactive, HitInfo
from .ui import UIElement, Label, Button, Panel, UILayer

# 关卡 / 配置
from .levelio import save_level, load_level
from .config import load_config, save_config, DEFAULT_CONFIG

# 任务
from .tasks import AsyncWorker, AsyncSceneCompiler

# 关卡编辑器
from .editor import Editor

# 物理引擎
from .physics import (Collider, AABBCollider, add_collider,
                      CharacterController, PhysicsWorld,
                      capsule_intersects_aabb, aabb_overlap)

__all__ = [
    "App", "Scene", "Entity", "entity_from_dict",
    "Camera", "FPPCamera", "TPPCamera",
    "Material", "SolidColorMaterial", "TextureMaterial", "material_from_dict",
    "Model", "cube", "plane", "sphere", "cylinder", "build_primitive",
    "PRIMITIVE_NAMES", "load_obj",
    "Renderer", "ShaderConfig", "ShadowMap", "BVH", "build_scene_bvh",
    "trace_shadow", "trace_reflection", "trace_ao",
    "Interactive", "HitInfo", "UIElement", "Label", "Button", "Panel", "UILayer",
    "save_level", "load_level", "load_config", "save_config", "DEFAULT_CONFIG",
    "AsyncWorker", "AsyncSceneCompiler", "Editor",
    "Collider", "AABBCollider", "add_collider", "CharacterController",
    "PhysicsWorld", "capsule_intersects_aabb", "aabb_overlap",
]

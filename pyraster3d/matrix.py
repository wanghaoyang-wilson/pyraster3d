"""
matrix.py — 左手坐标系（Left-Handed）数学模块
================================================
约定（UE / DirectX 风格）：
    X 向右，Y 向上，Z 向前（朝向屏幕外）。
    正旋转方向：沿旋转轴 + 端看过去为顺时针（左手定则）。
"""
from __future__ import annotations

import math
import numpy as np

# --------------------------------------------------------------------------- #
# 基础 4x4 矩阵
# --------------------------------------------------------------------------- #
def identity() -> np.ndarray:
    return np.eye(4, dtype=np.float64)


def mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """矩阵乘法 a * b（列向量约定：先应用 b，再应用 a）。"""
    return a @ b


# --------------------------------------------------------------------------- #
# 平移 / 旋转 / 缩放（左手系）
# --------------------------------------------------------------------------- #
def translate(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float64)
    m[0, 3], m[1, 3], m[2, 3] = x, y, z
    return m


def scale(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float64)
    m[0, 0], m[1, 1], m[2, 2] = x, y, z
    return m


def rotate_x(angle: float) -> np.ndarray:
    """绕 X 轴旋转（左手，Y 向 Z 旋转）。"""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([
        [1.0, 0.0, 0.0, 0.0],
        [0.0,  c,  -s, 0.0],
        [0.0,  s,   c, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ], dtype=np.float64)


def rotate_y(angle: float) -> np.ndarray:
    """绕 Y 轴旋转（左手，Z 向 X 旋转）。"""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([
        [ c, 0.0,  -s, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [ s, 0.0,   c, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ], dtype=np.float64)


def rotate_z(angle: float) -> np.ndarray:
    """绕 Z 轴旋转（左手，X 向 Y 旋转）。"""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([
        [ c, -s, 0.0, 0.0],
        [ s,  c, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ], dtype=np.float64)


def rotation(x: float, y: float, z: float) -> np.ndarray:
    """组合旋转（顺序：Rz * Ry * Rx，先绕 X，再绕 Y，再绕 Z）。"""
    return rotate_z(z) @ rotate_y(y) @ rotate_x(x)


def model_matrix(position, rotation, s) -> np.ndarray:
    """局部 -> 世界（TRS）。"""
    pos = position if position is not None else (0, 0, 0)
    rot = rotation if rotation is not None else (0, 0, 0)
    sc = s if s is not None else (1, 1, 1)
    return translate(*pos) @ rotate_z(rot[2]) @ rotate_y(rot[1]) @ rotate_x(rot[0]) @ scale(*sc)


# --------------------------------------------------------------------------- #
# 相机（Left-Handed LookAt / 由 yaw+pitch 构建）
# --------------------------------------------------------------------------- #
def look_at_lh(eye, center, up=(0, 1, 0)):
    """
    左手系 LookAt 视图矩阵（世界 -> 相机）。
    返回 4x4；用列向量：cam_pos = view @ world_pos。
    """
    eye = np.asarray(eye, dtype=np.float64)
    center = np.asarray(center, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)

    f = center - eye
    fn = np.linalg.norm(f)
    if fn < 1e-9:
        f = np.array([0, 0, 1.0])
    else:
        f = f / fn

    s = np.cross(up, f)            # right（左手：+X）
    sn = np.linalg.norm(s)
    if sn < 1e-9:
        s = np.array([1.0, 0.0, 0.0])
    else:
        s = s / sn

    u = np.cross(f, s)             # up（+Y）

    view = np.eye(4, dtype=np.float64)
    view[0, 0], view[0, 1], view[0, 2] = s
    view[1, 0], view[1, 1], view[1, 2] = u
    view[2, 0], view[2, 1], view[2, 2] = f
    view[0, 3] = -float(s @ eye)
    view[1, 3] = -float(u @ eye)
    view[2, 3] = -float(f @ eye)
    return view


def camera_basis_from_yaw_pitch(yaw: float, pitch: float):
    """
    由偏航/俯仰计算相机右手(side)、上(up)、前(forward)（世界空间单位向量）。
    yaw=0, pitch=0 -> forward=(0,0,1)。正 pitch -> 抬头。
    """
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    forward = np.array([cp * sy, sp, cp * cy], dtype=np.float64)  # +Z forward
    up = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    side = np.cross(up, forward)
    sn = np.linalg.norm(side)
    if sn < 1e-9:
        side = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    else:
        side = side / sn
    up2 = np.cross(forward, side)
    up2 = up2 / (np.linalg.norm(up2) + 1e-12)
    return side, up2, forward


def make_view_from_basis(eye, side, up, forward) -> np.ndarray:
    view = np.eye(4, dtype=np.float64)
    view[0, 0], view[0, 1], view[0, 2] = side
    view[1, 0], view[1, 1], view[1, 2] = up
    view[2, 0], view[2, 1], view[2, 2] = forward
    view[0, 3] = -float(side @ eye)
    view[1, 3] = -float(up @ eye)
    view[2, 3] = -float(forward @ eye)
    return view


# --------------------------------------------------------------------------- #
# 向量工具
# --------------------------------------------------------------------------- #
def vec3(*args) -> np.ndarray:
    if len(args) == 1:
        return np.asarray(args[0], dtype=np.float64).reshape(3)
    return np.asarray(args, dtype=np.float64).reshape(3)


def normalize(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64).reshape(3)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def cross(a, b) -> np.ndarray:
    return np.cross(np.asarray(a, dtype=np.float64).reshape(3),
                    np.asarray(b, dtype=np.float64).reshape(3))


def dot(a, b) -> float:
    return float(np.dot(a, b))


def length(v) -> float:
    return float(np.linalg.norm(v))

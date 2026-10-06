"""
direct2d.py — Direct2D 渲染后端桥接（Windows-only，本轮未在 Linux 编译/运行验证）
==================================================================================
这是「纯 Python 软光栅 + C++/GPU 呈现」混合架构中的窗口输出后端。

设计（对齐前期讨论的 IPC 方案）：
- 引擎在 Python 侧把帧缓冲渲染为 RGB 数组；
- 通过本模块把帧写为 BGRA（共享内存 或 .raw 文件）；
- C++ 程序 `direct2d_presenter.exe`（见本目录）读取该帧，用 Direct2D/D3D11
  呈现到窗口（Present）。

⚠️ 重要：当前运行环境是 Linux，Direct2D 是 Windows 独占 API，无法在此编译与
冒烟验证。因此：
- 本模块提供可在 Linux 上验证的纯 Python 部分（`write_frame_file`）；
- `get_backend()` / `Direct2DBackend` 为 Windows 专用装载逻辑，在非 Windows
  上一律返回 None 并给出原因，绝不会让主引擎在 Linux 上崩溃。

启用方式：引擎配置 renderer.backend 设为 "direct2d"（默认 "pygame"）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional, Tuple

import numpy as np

_BACKEND_NAME = "direct2d"


def is_windows() -> bool:
    return sys.platform == "win32" or os.name == "nt"


def write_frame_file(rgb: np.ndarray, path: str, order: str = "rgb") -> str:
    """把 RGB 帧缓存写为 BGRA .raw（可跨平台验证的纯 Python 部分）。

    rgb: (H, W, 3) uint8 数组；order: 'rgb' | 'bgr'（输入通道顺序）。
    返回写入路径。
    """
    arr = np.asarray(rgb, dtype=np.uint8)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"期望 (H,W,3) RGB 数组，得到 {arr.shape}")
    bgra = arr[:, :, ::-1]                      # RGB -> BGR
    bgra = np.concatenate([bgra, np.full((*bgra.shape[:2], 1), 255, np.uint8)],
                          axis=-1)              # + A=255 -> BGRA
    with open(path, "wb") as fh:
        fh.write(np.ascontiguousarray(bgra).tobytes())
    return path


def frame_file_path(width: int, height: int, workdir: str = ".") -> str:
    return os.path.join(workdir, f"frame_{width}x{height}.raw")


class BackendUnavailable(Exception):
    pass


class Direct2DBackend:
    """Windows 上启动 direct2d_presenter.exe 并把帧喂给它（未在 Linux 验证）。"""

    def __init__(self, width: int, height: int,
                 source: str = "file", workdir: str = "."):
        self.width = int(width)
        self.height = int(height)
        self.source = source                      # 'file' | 'shm'
        self.workdir = workdir
        self._proc: Optional[subprocess.Popen] = None
        self._exe = os.path.join(os.path.dirname(__file__), "direct2d_presenter.exe")
        if source == "shm":
            self._shm_name = "Global\\pyraster_frame"
        else:
            self._raw_path = frame_file_path(width, height, workdir)

    def _ensure_running(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        if not is_windows():
            raise BackendUnavailable("Direct2D 仅支持 Windows，当前环境无法启动")
        if not os.path.isfile(self._exe):
            raise BackendUnavailable(
                f"缺少 {self._exe}，请先在本目录用 build.bat 编译 "
                f"(需要 MSVC + Windows)")
        src = self._shm_name if self.source == "shm" else self._raw_path
        self._proc = subprocess.Popen(
            [self._exe, str(self.width), str(self.height), src],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def present(self, rgb: np.ndarray) -> None:
        """把一帧 RGB 帧缓存交给后端呈现。"""
        self._ensure_running()
        if self.source == "shm":
            raise BackendUnavailable(
                "共享内存(shm)写入后端尚未在本轮完成，请使用 source='file'")
        write_frame_file(rgb, self._raw_path)

    def close(self):
        if self._proc is not None:
            self._proc.terminate()
            self._proc = None


def backend_available() -> Tuple[bool, str]:
    """检测 Direct2D 后端是否可在此环境使用。"""
    if not is_windows():
        return False, "当前环境非 Windows，Direct2D 无法使用"
    if not os.path.isfile(os.path.join(os.path.dirname(__file__),
                                        "direct2d_presenter.exe")):
        return False, "未找到编译好的 direct2d_presenter.exe（请先 build.bat）"
    return True, "ok"


def get_backend(config: dict, workdir: str = ".") -> Optional[Direct2DBackend]:
    """根据引擎配置解析渲染后端。

    返回 Direct2DBackend（Windows 且已编译）；否则返回 None 并打印原因，
    由主引擎回退到 'pygame' 后端。
    """
    backend = (config or {}).get("renderer", {}).get("backend", "pygame")
    if backend != _BACKEND_NAME:
        return None
    ok, reason = backend_available()
    if not ok:
        print(f"[direct2d] 后端不可用，回退 pygame: {reason}")
        return None
    win = config["window"]
    return Direct2DBackend(win["width"], win["height"],
                           source=config.get("renderer", {}).get(
                               "direct2d_source", "file"),
                           workdir=workdir)

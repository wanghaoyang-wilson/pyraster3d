# Direct2D 渲染后端（Windows-only，本轮未在 Linux 编译/运行验证）

本目录是 Pyraster3D 的 **Direct2D 窗口呈现后端**，属于「纯 Python 软光栅 +
C++/GPU 呈现」混合架构中的 GPU 输出一环。

> ⚠️ **重要**：当前开发环境是 Linux。Direct2D 是 Windows 独占 API，因此本目录的
> C++ 程序**无法在 Linux 上编译与冒烟验证**。这里的实现是**可移植的参考代码**，
> 需在 Windows + MSVC 环境下按下方步骤编译、并补齐 `direct2d_presenter.cpp`
> 内标注的 D2D1.1 device-context 完整管线后使用。

## 文件说明

| 文件 | 作用 |
|------|------|
| `direct2d_presenter.cpp` | C++ 呈现器：读取 BGRA 帧缓冲（共享内存 或 `.raw`），用 Direct2D/D3D11 呈现到窗口 |
| `direct2d.py` | Python 桥接：`write_frame_file()`（可在任意平台验证）+ Windows 专用后端装载 |
| `build.bat` | MSVC 编译脚本 |

## 架构（对齐前期 IPC 方案）

```
Python 引擎(软光栅渲染出 RGB 帧)
   │  write_frame_file() / 共享内存
   ▼
frame.raw (BGRA, W*H*4) 或 Global\pyraster_frame
   │
   ▼
direct2d_presenter.exe  →  Direct2D 呈现到窗口 (Present)
```

- **共享内存**（`Global\pyraster_frame`）：帧缓冲大块数据零拷贝，性能最优；
- **文件**（`frame_<W>x<H>.raw`）：跨进程最简，便于调试；
- 控制指令（分辨率、AA 开关等）后续可叠加命名管道。

## 编译（Windows）

1. 安装 Visual Studio 2022（勾选「使用 C++ 的桌面开发」）。
2. 打开 **VS x64 Native Tools Command Prompt**。
3. 运行：

```bat
cd direct2d
build.bat
```

生成 `direct2d_presenter.exe`。

## 使用（Windows，示意）

```python
import numpy as np
from direct2d import Direct2DBackend

backend = Direct2DBackend(1000, 700, source="file", workdir=".")
frame = np.random.randint(0, 255, (700, 1000, 3), dtype=np.uint8)
backend.present(frame)      # 写入 frame_1000x700.raw，呈现器读帧并显示
```

## 在 Linux 上可验证的部分

`direct2d.py` 中的 `write_frame_file()` 是纯 Python 实现，可在 Linux 上把 RGB
帧缓存正确写为 BGRA `.raw`（已纳入冒烟测试）。`get_backend()` 在非 Windows
环境一律返回 `None`，主引擎自动回退到 `pygame` 后端，**不会在 Linux 上崩溃**。

## 引擎接入（可选）

把引擎配置 `renderer.backend` 设为 `"direct2d"` 可启用；当前主循环默认
`"pygame"`。将 `App.run()` 中的 `pygame.display.flip()` 替换为：
`backend.present(fb)` 即完成接入（需先在 Windows 上验证 C++ 呈现器）。

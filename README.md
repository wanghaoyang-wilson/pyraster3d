# Pyraster3D

一套**基于 Pygame 的软光栅 3D 引擎库**：仿 Ursina 风格 API，底层自研软光栅（Z-Buffer + 画家算法 + 轻度光线追踪），左手坐标系。

> 定位类比（UE4.27 术语）：`App`≈GameInstance/GameMode，`Scene`≈Level/World，`Entity`≈Actor，`Model`≈Static Mesh，`Camera`≈CameraActor，`editor`≈关卡编辑视图。引擎所有渲染与输入在主线程；**BVH / 阴影贴图等耗时编译放在后台工作线程**（异步，不阻塞主渲染）。

## 目录结构

```
pyraster3d/
├── __init__.py      公共 API 导出
├── app.py           App 主入口：事件循环 / 输入 / 交互分发 / FPS / 异步调度
├── matrix.py        左手系矩阵 / 向量 / LookAt / 相机基向量
├── model.py         网格数据（顶点/面/UV/法线 + 变换缓存）
├── primitives.py    内置几何体：cube / plane / sphere / cylinder
├── objloader.py     OBJ 解析器
├── material.py      材质：纯色 / 贴图（含 Alpha / 反射率）
├── scene.py         场景（Level）与实体（Actor），场景树
├── camera.py        相机：第一人称(FPP，鼠标锁定) / 第三人称(TPP)
├── interaction.py   Hover / Hit / Clicked / MouseDown / MouseUp 事件
├── ui.py            2D UI：Label / Button / Panel / UILayer
├── bvh.py           BVH 加速结构（后台线程构建）
├── raytrace.py      轻度光追：阴影射线 / 反射 / AO
├── rasterizer.py    软光栅核心：Z-Buffer / 仅边缘深度采样 / 逐像素着色
├── shadowmap.py     阴影贴图
├── renderer.py      渲染管线：不透明+透明画家算法+光追混合
├── tasks.py         工作线程池 + 异步场景编译（双缓冲切换）
├── config.py        引擎配置（JSON，深合并）
├── levelio.py       关卡文件（JSON）读写
├── physics.py       轻量物理引擎（AABB 碰撞体 / 胶囊体玩家 / 重叠事件）
└── editor.py        基础关卡编辑器
direct2d/            Direct2D 渲染后端（Windows-only，本轮未在 Linux 验证）
examples/main.py     综合演示（含物理）
engine_config.json   默认引擎配置
levels/sample_level.json  示例关卡
tests/smoke_test.py  无头冒烟测试（26 项）
```

## 安装依赖

```
pip install pygame numpy
```

## 运行演示

```
python examples/main.py
```

无显示环境也可跑无头冒烟测试验证：

```
python tests/smoke_test.py
```

## 快速上手（用户业务代码）

```python
from pyraster3d import *

app = App(config_path="engine_config.json")

cube = Entity(model="cube", position=(0, 1, 5),
              material=SolidColorMaterial((210, 80, 70)))
app.scene.add(cube)

def cube_clicked(hit):
    print("点击", hit.entity.name, hit.world_pos)
cube.on_clicked = cube_clicked

camera = FPPCamera(position=(0, 2, -10))   # 左手系相机朝 +Z，物体放前方 z>0
app.camera = camera

def update(dt):
    cube.rotation[1] += 0.6 * dt
    cube.set_transform(rotation=cube.rotation)

app.run(update_func=update)
```

## 操作 / 按键

| 按键 | 作用 |
|---|---|
| `W A S D` | 移动（第一人称 / 编辑器自由相机） |
| `空格` | 跳跃（第一人称物理模式） |
| `Q` / `E` | 上下移动 |
| `F1` | 开关关卡编辑器 |
| `F2` | 切换 第一人称 / 第三人称 相机 |
| 鼠标 | 视角 / 点击交互（Hover / Clicked） |
| `1` `2` `3` `4` | 编辑器放置 立方体 / 平面 / 球体 / 圆柱 |
| `[` `]` | 缩放选中实体 |
| `Delete` | 删除选中实体 |
| `Ctrl+S` / `Ctrl+O` | 保存 / 打开关卡（JSON） |
| `R + 鼠标` | 旋转选中实体 |
| 左键拖拽 | 沿地面移动选中实体 |

## 渲染管线特性

- **Z-Buffer 主渲染**：不透明物体逐像素深度测试。
- **仅边缘深度采样**（`edge_depth_sampling`）：三角形内部像素跳过深度比较，只对靠近边/顶点的像素做完整测试——压榨老硬件；有穿插时会牺牲内部遮挡精度。
- **透明物体画家算法**：透明面不写深度，整体按面中心深度由远到近叠加。
- **轻度光线追踪**（`raytracing=true`）：基于 BVH 的阴影射线 / 反射射线 / AO，不是全帧光追。
- **阴影贴图**：平行光深度图，逐像素采样。
- **左手坐标系**：X 右、Y 上、Z 前。

## 多线程场景编译

`App` 内置 `AsyncSceneCompiler`（基于工作线程池）：OBJ 加载、BVH 构建、阴影贴图重建均在后台执行；主线程在帧首 `apply_ready()` 原子切换就绪数据（双缓冲），**不阻塞渲染**。主线程绝不直接修改正在渲染的实体，避免竞态。

## 物理引擎

`physics.py` 提供轻量物理（原型阶段，后续内核转译到 C++/GPU 时保持接口不变）：

- `AABBCollider`（Block / Overlap）：给实体挂碰撞体，`add_collider(entity, mode, ...)`。
- `CharacterController`：胶囊体玩家，重力 / 跳跃 / 落地 / 水平移动。
- `PhysicsWorld`：**宽相**（以玩家为中心 20 单位，每 60 游戏刻刷新附近碰撞体候选）+ **窄相**（胶囊-AABB，细分时间步防穿透）。
- 重叠对差分触发事件：`on_begin_overlap` / `on_end_overlap` / `on_hit`（挂到碰撞体实体或玩家上）。

```python
add_collider(ground, "block")                    # 地面阻挡
ball_collider = add_collider(ball, "overlap")    # 触发区
def enter(other): print("进入触发区", other.position)
ball.on_begin_overlap = enter
```

第一人称模式下，物理驱动相机跟随玩家（`App.player` / `App.physics`）；编辑器模式下物理暂停。

## UI 主题

`ui.py` 新增 `UITheme` 主题系统（模块级 `theme` 单例，`set_theme()` 切换）。Button 支持圆角 + 边框 + 悬停/按下态，Panel 支持半透明 + 边框 + 标题栏，Label 支持阴影。现有 API 完全向后兼容。

## Direct2D 后端（Windows-only）

`direct2d/` 提供「纯 Python 软光栅 + C++/GPU 呈现」的窗口输出后端：Python 侧把帧缓存写为 BGRA（文件/共享内存），C++ 程序 `direct2d_presenter.exe` 用 Direct2D/D3D11 呈现。**注意：当前开发环境是 Linux，C++ 部分无法编译/运行验证，仅交付参考代码**；Python 侧的 `write_frame_file()` 已纳入冒烟测试，且非 Windows 环境自动回退 `pygame` 后端。

## 配置文件 `engine_config.json`

```jsonc
{
  "window":  { "width": 1000, "height": 700, "title": "Pyraster3D", "fps_cap": 0 },
  "renderer": {
    "fov_degrees": 70, "z_near": 0.1, "z_far": 200,
    "shadows": true, "shadow_map_size": 512,
    "raytracing": false, "max_bounces": 1,
    "edge_depth_sampling": true, "cull_backface": true, "backend": "pygame",
    "ambient": [0.22,0.22,0.26], "sun_direction": [0.4,0.8,0.45], "sun_color": [1,0.98,0.94]
  },
  "camera_defaults": { "fov_degrees": 70, "speed": 0.25, "mouse_sensitivity": 0.003 },
  "threading": { "workers": 2, "async_scene_compile": true, "async_shadow": true },
  "editor": { "enabled": true, "grid": true, "snap_translate": 0.5, "snap_rotate": 15, "show_fps": true },
  "physics": {
    "enabled": true, "player_radius": 0.4, "player_height": 1.8, "eye_height": 1.6,
    "gravity": -20, "jump_speed": 6, "move_speed": 4,
    "broadphase_radius": 20, "broadphase_interval": 60, "substeps": 4
  }
}
```

## 关卡文件格式 `levels/sample_level.json`

JSON，含关卡名、相机生成信息、光照/天空设置与实体列表（模型、Transform、材质、标志位）。由 `levelio.save_level / load_level` 读写，编辑器可直接打开/保存。

## 已知边界（说明）

- 软光栅逐像素 CPU 运算，高分辨率/高面数性能受限（这正是测试硬件极限的用途）。
- 屏幕空间仿射插值（非透视校正），小三角形下可接受。
- 仅边缘深度采样开启时，内部穿插模型遮挡可能不准（预期内）。
- BVH 按结构变更异步重建；运行时持续旋转物体时拾取射线可能略微滞后（玩具级限制）。

## 验证

`python tests/smoke_test.py`：26 项无头测试全部通过——帧缓存输出、关卡读写往返、BVH 求交、相机拾取、阴影贴图采样、阴影/反射射线、物理引擎（落地/跳跃/Block 阻挡/Overlap 事件/宽相筛选）、UI 主题、配置项、Direct2D Python 桥接。

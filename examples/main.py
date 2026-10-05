#!/usr/bin/env python3
"""
Pyraster3D 综合演示
====================
运行：python examples/main.py

操作：
  F1       开关关卡编辑器
  F2       切换 第一人称 / 第三人称 相机
  鼠标     视角 / 点击交互（Hover/Clicked）
  WASD+QE  移动（第一人称 / 编辑器自由相机）
  1/2/3/4  编辑器模式放置 立方体/平面/球体/圆柱
  [ / ]    缩放选中实体     Delete 删除选中
  Ctrl+S 保存关卡  Ctrl+O 打开关卡
  T        切换 阴影   R(光追键) 见下
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyraster3d import (App, Entity, FPPCamera, TPPCamera, SolidColorMaterial,
                        TextureMaterial, HitInfo, Button, Label, build_primitive)


def main():
    app = App(config_path=os.path.join(os.path.dirname(__file__), "..", "engine_config.json"),
              title="Pyraster3D Demo")

    # 3D 场景
    app.scene.ambient = (0.22, 0.22, 0.26)
    app.scene.sun_direction = (0.5, 0.8, 0.4)
    app.scene.sky_color = (30, 34, 44)

    ground = app.scene.find("ground")
    if ground:
        ground.material = SolidColorMaterial((70, 90, 70))

    cube = Entity(model=build_primitive("cube"), name="demo_cube",
                  position=(0, 1, 5), rotation=(0, 0.4, 0),
                  material=SolidColorMaterial((210, 80, 70), reflectivity=0.25))
    ball = Entity(model=build_primitive("sphere"), name="demo_ball",
                  position=(3.2, 1.2, 4.5), material=SolidColorMaterial((80, 140, 200)))
    pillar = Entity(model=build_primitive("cylinder"), name="demo_pillar",
                    position=(-3, 1, 5), material=SolidColorMaterial((160, 150, 70)))

    for e in (cube, ball, pillar):
        app.scene.add(e)

    # 交互事件演示
    def cube_clicked(hit: HitInfo):
        print(f"[Clicked] {hit.entity.name} 命中点={hit.world_pos}")
        cube.material.color = (120, 230, 120)

    def cube_hover(hit: HitInfo):
        cube.material.color = (230, 200, 90)

    def cube_exit():
        cube.material.color = (210, 80, 70)

    cube.on_clicked = cube_clicked
    cube.on_hover = cube_hover
    cube.on_mouse_exit = cube_exit

    # 第一人称相机（默认，相机朝 +Z，物体放在前方 z>0）
    app.camera = FPPCamera(position=(0, 2.0, -10.0),
                           fov_degrees=app.config["renderer"]["fov_degrees"])

    # UI 示例
    ui = app.ui
    tip = Label("F1 编辑器 / F2 切相机 / 点击立方体 / WASD 移动", (14, 40, 400, 24),
                name="tip", color=(200, 210, 220))
    ui.add(tip)

    btn_light = Button("切换阴影(T)", (14, 70, 140, 30), name="btn_light",
                       bg=(50, 90, 60), hover=(70, 120, 80))
    btn_rt = Button("切换光追(G)", (160, 70, 140, 30), name="btn_rt",
                    bg=(120, 70, 60), hover=(160, 95, 80))

    def toggle_shadow(hit):
        app.renderer.enable_shadows = not app.renderer.enable_shadows
        btn_light.text = f"阴影 {'开' if app.renderer.enable_shadows else '关'}"
        app.request_rebuild()

    def toggle_rt(hit):
        app.renderer.enable_raytracing = not app.renderer.enable_raytracing
        btn_rt.text = f"光追 {'开' if app.renderer.enable_raytracing else '关'}"

    btn_light.on_clicked = toggle_shadow
    btn_rt.on_clicked = toggle_rt
    ui.add(btn_light)
    ui.add(btn_rt)

    # 运行时开关（键盘）
    def update(dt):
        keys = app.pygame.key.get_pressed()
        if keys[app.pygame.K_t] and app.pygame.key.get_mods() & app.pygame.KMOD_CTRL:
            pass
        # 让物体轻轻旋转，展示动态场景
        cube.rotation[1] += 0.6 * dt
        cube.set_transform(rotation=cube.rotation)
        ball.rotation[0] += 0.4 * dt
        ball.set_transform(rotation=ball.rotation)

    # 按键切换（简单轮询一次）
    update.last_t = 0.0
    update.last_g = 0.0

    app.run(update_func=update)


if __name__ == "__main__":
    main()

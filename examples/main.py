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
                        TextureMaterial, HitInfo, Button, Label, build_primitive,
                        add_collider, Collider)


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

    # ---- 物理演示：给物体挂碰撞体 ----
    add_collider(cube, Collider.BLOCK)
    add_collider(pillar, Collider.BLOCK)
    add_collider(ball, Collider.OVERLAP)

    def ball_overlap_enter(other):
        print(f"[Overlap 进入] 玩家触碰 {ball.name}，玩家位置={other.position.tolist()}")
        ball.material.color = (120, 230, 120)

    def ball_overlap_exit(_other):
        print(f"[Overlap 离开] 离开 {ball.name}")
        ball.material.color = (80, 140, 200)

    def cube_hit(_other):
        print(f"[Hit] 撞到 {cube.name}（被阻挡）")

    ball.on_begin_overlap = ball_overlap_enter
    ball.on_end_overlap = ball_overlap_exit
    cube.on_hit = cube_hit

    app.physics._refresh_nearby()

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

    # 第一人称相机
    app.camera = FPPCamera(position=(0, 2.0, -10.0),
                           fov_degrees=app.config["renderer"]["fov_degrees"])

    # UI 示例（新主题风格）
    ui = app.ui
    tip = Label("F1 编辑器 / F2 切相机 / 点击立方体 / WASD 移动 / 空格跳跃",
                (14, 40, 460, 24), name="tip", color=(200, 210, 220), shadow=True)
    ui.add(tip)

    hud = Label("物理: 待机", (14, 88, 300, 22), name="phys_hud",
                color=(160, 230, 170), shadow=True)
    ui.add(hud)

    btn_light = Button("切换阴影(T)", (14, 70, 140, 30), name="btn_light")
    btn_rt = Button("切换光追(G)", (160, 70, 140, 30), name="btn_rt")

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

    def update(dt):
        keys = app.pygame.key.get_pressed()
        if keys[app.pygame.K_t] and app.pygame.key.get_mods() & app.pygame.KMOD_CTRL:
            pass
        cube.rotation[1] += 0.6 * dt
        cube.set_transform(rotation=cube.rotation)
        ball.rotation[0] += 0.4 * dt
        ball.set_transform(rotation=ball.rotation)
        if app.player is not None:
            p = app.player
            state = "地面" if p.grounded else "空中"
            hud.text = (f"物理: {state}  位置={[round(v,1) for v in p.position]}  "
                        f"速度y={p.velocity[1]:+.1f}")
        app.physics._refresh_nearby() if app.physics is not None else None

    update.last_t = 0.0
    update.last_g = 0.0

    app.run(update_func=update)


if __name__ == "__main__":
    main()

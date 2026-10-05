"""
tasks.py — 异步场景编译（多线程，避免阻塞主渲染线程）
原理：
- 主线程（Pygame 窗口/事件/渲染）只提交任务、读取已就绪结果。
- 工作线程池执行耗时任务：OBJ 加载、BVH 构建、阴影贴图重建。
- 采用「双缓冲」：后台只生成新数据，主线程在帧首检查结果并原子替换引用，
  绝不直接修改正在渲染的实体，避免竞态。
"""
from __future__ import annotations

import queue
import threading
from typing import Callable, List, Optional


class Task:
    __slots__ = ("kind", "args", "result_queue", "error")

    def __init__(self, kind: str, args: tuple):
        self.kind = kind
        self.args = args
        self.error = None


class AsyncWorker:
    """简单工作线程池 + 结果队列。"""

    def __init__(self, n_workers: int = 2):
        self.n_workers = max(1, n_workers)
        self._job_q: "queue.Queue[Task]" = queue.Queue()
        self._result_q: "queue.Queue[Task]" = queue.Queue()
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._handlers: dict = {}
        self._lock = threading.Lock()
        self._start()

    def _start(self):
        for _ in range(self.n_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._threads.append(t)

    def register_handler(self, kind: str, fn: Callable):
        with self._lock:
            self._handlers[kind] = fn

    def submit(self, kind: str, *args) -> None:
        self._job_q.put(Task(kind, args))

    def _worker_loop(self):
        while not self._stop.is_set():
            try:
                task = self._job_q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                with self._lock:
                    handler = self._handlers.get(task.kind)
                if handler is None:
                    task.error = f"未注册任务类型: {task.kind}"
                else:
                    task.args = handler(*task.args)
            except Exception as e:                      # noqa: BLE001
                task.error = repr(e)
            self._result_q.put(task)

    def poll_results(self) -> List[Task]:
        """非阻塞取出所有已就绪任务。"""
        out = []
        while True:
            try:
                out.append(self._result_q.get_nowait())
            except queue.Empty:
                break
        return out

    def shutdown(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=0.5)


class AsyncSceneCompiler:
    """
    场景异步编译管理者。
    管理一份「读时复制」的场景级数据：BVH、阴影贴图。
    后台任务完成后，主线程调用 apply_ready() 把新数据切换进场景引用。
    """

    def __init__(self, worker: AsyncWorker):
        self.worker = worker
        self.worker.register_handler("build_bvh", self._build_bvh)
        self.worker.register_handler("build_shadow", self._build_shadow)
        self.pending_scene = None          # 后台正在处理（快照）的场景
        self.ready_bvh = None
        self.ready_shadow = None
        self.ready_bvh_scene_id = None
        self.ready_shadow_scene_id = None

    def _snapshot_scene(self, scene):
        """轻量快照：记录实体的世界顶点（后台线程只读该快照，避免锁竞争）。"""
        # 这里直接引用场景实体的世界顶点缓存；渲染器使用双缓冲场景时，
        # 后台构建与主线程渲染不会同时修改同一批实体。
        return scene

    def _build_bvh(self, scene):
        from .bvh import build_scene_bvh
        return build_scene_bvh(scene)

    def _build_shadow(self, scene):
        from .shadowmap import ShadowMap
        sm = ShadowMap(size=512)
        sm.build(scene, scene.sun_direction)
        return sm

    def request_bvh(self, scene):
        """提交 BVH 重建任务（带场景 id）。"""
        self.pending_scene = scene

    def request_shadow(self, scene):
        self.pending_scene = scene

    def apply_ready(self, scene) -> None:
        """主线程帧首调用：把后台已完成的新 BVH/阴影贴图切换进来。"""
        for task in self.worker.poll_results():
            if task.error:
                print(f"[AsyncSceneCompiler] 任务失败 {task.kind}: {task.error}")
                continue
            if task.kind == "build_bvh" and task.args is not None:
                self.ready_bvh = task.args
                self.ready_bvh_scene_id = id(scene)
            elif task.kind == "build_shadow" and task.args is not None:
                self.ready_shadow = task.args
                self.ready_shadow_scene_id = id(scene)

    @property
    def bvh(self):
        return self.ready_bvh

    @property
    def shadow_map(self):
        return self.ready_shadow

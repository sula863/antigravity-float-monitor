# -*- coding: utf-8 -*-
import json
import time
import os
from datetime import datetime

TARGET_FILES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "task_status.json"),
    os.path.expanduser(r"~\.gemini\task_status.json"),
]

def emit_status(task_name, total_steps, current_step, step_name, progress_pct, quota_pct, status, subtasks, data_source="task-1016.log"):
    payload = {
        "task_name": task_name,
        "total_steps": total_steps,
        "current_step": current_step,
        "current_step_name": step_name,
        "progress_pct": progress_pct,
        "quota_remaining_pct": quota_pct,
        "status": status,
        "data_source": data_source,
        "updated_at": datetime.now().isoformat(),
        "heartbeat_interval_sec": 60,
        "subtasks": subtasks
    }
    for file_path in TARGET_FILES:
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"写入 {file_path} 失败: {e}")

def run_simulation():
    print(">>> 启动 Antigravity 状态机全特性动态仿真...")
    
    subtasks = [
        {"title": "检查硬件与安装系统级并发工具 (aria2 /...)", "status": "pending", "pct": 0},
        {"title": "启动三路全并发预热 (ComfyUI 环境构建 ||...)", "status": "pending", "pct": 0},
        {"title": "Monitoring /content/k2_10s_render", "status": "pending", "pct": 0}
    ]

    # 阶段 1: 初始化
    print("阶段 1: 检查硬件环境...")
    subtasks[0]["status"] = "running"
    subtasks[0]["pct"] = 40
    emit_status("ComfyUI 环境构建", 3, 1, "[1/3] 检查并发工具 (消耗极低)", 15, 85, "running", subtasks)
    time.sleep(2)

    subtasks[0]["status"] = "done"
    subtasks[0]["pct"] = 100
    emit_status("ComfyUI 环境构建", 3, 1, "[1/3] 硬件环境就绪", 33, 84, "running", subtasks)
    time.sleep(2)

    # 阶段 2: 启动预热 (与图一完全一致的场景)
    print("阶段 2: 启动三路全并发预热 (双圆环高光时刻)...")
    subtasks[1]["status"] = "running"
    subtasks[1]["pct"] = 0
    emit_status("ComfyUI 环境构建", 3, 2, "[2/3] 启动三路全并发预热 (ComfyUI 环境构建 ||...", 33, 83, "running", subtasks)
    time.sleep(3)

    subtasks[1]["pct"] = 50
    emit_status("ComfyUI 环境构建", 3, 2, "[2/3] 启动三路全并发预热 (并发流 2/3 就绪)", 50, 82, "running", subtasks)
    time.sleep(2)

    subtasks[1]["status"] = "done"
    subtasks[1]["pct"] = 100
    emit_status("ComfyUI 环境构建", 3, 2, "[2/3] 三路预热全部完成", 66, 81, "running", subtasks)
    time.sleep(2)

    # 阶段 3: 监控产物
    print("阶段 3: 监控产物生成...")
    subtasks[2]["status"] = "running"
    subtasks[2]["pct"] = 30
    emit_status("ComfyUI 环境构建", 3, 3, "[3/3] 渲染模型产物输出中...", 80, 80, "running", subtasks)
    time.sleep(2)

    subtasks[2]["status"] = "done"
    subtasks[2]["pct"] = 100
    emit_status("ComfyUI 环境构建", 3, 3, "[3/3] 全部流程执行完毕", 100, 80, "completed", subtasks)
    print(">>> 模拟完成！双圆环：任务 100% 翠绿，额度 80% 霓虹紫，秒表冻结总耗时。")

if __name__ == "__main__":
    run_simulation()

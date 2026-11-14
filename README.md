<div align="center">

# Antigravity Float Monitor · 桌面任务与实时额度监控悬浮窗

**专为 Google Antigravity 打造的 Windows 轻量级桌面悬浮监控窗（多窗口感知 · 实时额度直连 · 防假死探针）**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)

**简体中文** | [English](README.en.md) | [日本語](README.ja.md)

</div>

---

## ✨ 核心特性

- **双形态无缝切换**：支持极简**迷你胶囊态（Pill）**与**完整大卡片态（Card）**，胶囊宽度自适应内容并保持右边缘锚定，Windows 11 下自动启用原生亚克力毛玻璃质感。
- **多窗口智能感知**：自动扫描 Antigravity 所有活跃会话窗口，优先置顶正在运行的任务（`W1`），支持鼠标滚轮、连体导航键及菜单一键切换，并可双击唤醒对应主窗口。
- **0 Token 损耗直连真实额度**：后台线程直连本地 Language Server RPC 接口，毫秒级获取各模型 5 小时 / 周真实剩余额度与重置倒计时，底部四模型徽章按剩余额度自动切换绿 / 黄 / 红预警配色。
- **本地 WAL Token & API 价值遥测**（借鉴 [antigravity-token-monitor](https://github.com/STARKTANG108/antigravity-token-monitor)）：以只读 SQLite URI 模式（`?mode=ro`）增量扫描本地会话 `.db` 与 `-wal`，实时展示**单窗口 Token 消耗与调用次数**、**今日总花费（支持点击切换 `$ USD` / `¥ CNY`）**及 **15 分钟实时消耗速率（`tok/m` & `$/h`）**。
- **防假死心跳探针 & 急停保护**：实时监测任务活跃度，超时未更新自动亮红告警；支持一键 `🛑 急停中止` 与 `🔄 重新调起`，并配备全屏应用智能隐身免打扰模式。
- **异步不卡顿**：所有 RPC 探测与磁盘任务扫描均在独立 `QThread` 后台线程执行，拖拽、切换丝滑无卡顿。

---

## 🚀 快速开始

### 1. 环境准备

确保已安装 **Python 3.10+**（Windows），并安装依赖：

```bash
pip install -r requirements.txt
```

### 2. 一键无框启动

直接双击运行目录中的：

* **`start_monitor.bat`** 或 **`start_monitor.vbs`**（使用 `pythonw.exe` 后台静默启动，无黑色控制台窗口）

也可以通过命令行启动：

```bash
pythonw float_monitor.py
```

### 3. 效果仿真测试

如果想在不运行长任务的情况下体验三阶段动态推进效果，可双击运行：

```bash
simulate_task.bat
```

---

## 📁 项目结构

```text
antigravity-float-monitor/
├── float_monitor.py    # 悬浮窗主程序（PySide6 UI + 后台 RPC/文件监控线程）
├── telemetry_wal.py    # 本地 SQLite WAL 只读 Token & API 价值遥测引擎
├── start_monitor.bat   # 一键启动脚本（Windows 批处理）
├── start_monitor.vbs   # 静默无控制台启动脚本
├── simulate_task.py    # 三阶段任务仿真测试脚本
├── simulate_task.bat   # 仿真测试快捷启动
├── sync_github.bat     # 一键提交并推送更新到 GitHub
├── requirements.txt    # Python 依赖清单
├── README.md           # 中文文档
├── README.en.md        # English Documentation
├── README.ja.md        # 日本語ドキュメント
└── LICENSE             # MIT 开源协议
```

---

## ⚙️ 任务状态文件规范（可选集成）

除自动感知 Antigravity 会话外，悬浮窗也会监听 `~/.gemini/task_status.json` 与 `~/.gemini/tasks/*.json`。写入如下结构即可在大卡片中展示精细阶段清单：

```json
{
  "task_name": "项目任务总名称",
  "total_steps": 3,
  "current_step": 2,
  "current_step_name": "[2/3] 正在执行构建...",
  "progress_pct": 60,
  "status": "running",
  "subtasks": [
    { "title": "检查环境依赖", "status": "done", "pct": 100 },
    { "title": "执行核心构建", "status": "running", "pct": 50 },
    { "title": "验收与清理", "status": "pending", "pct": 0 }
  ]
}
```

---

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源，欢迎 Star、Fork 与提交 Issue / PR！

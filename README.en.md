<div align="center">

# Antigravity Float Monitor · 桌面任务与实时额度监控悬浮窗

**A lightweight Windows floating task & live quota monitor built for Google Antigravity**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)

[简体中文](README.md) | **English** | [日本語](README.ja.md)

</div>

---

## ✨ Key Features

- **Dual View Modes**: Seamlessly toggle between a compact **Mini Pill** (auto-sizing width, right-edge anchored) and an expanded **Detail Card** with native Windows 11 Acrylic blur.
- **Multi-Window Awareness**: Automatically discovers active Antigravity sessions, prioritizes running tasks (`W1`), and supports quick switching via mouse wheel, navigation buttons, or dropdown menu. Double-click to focus the target Antigravity window.
- **Zero-Token Live Quota Tracking**: Connects directly to the local Antigravity Language Server RPC in a background thread to display real-time 5-hour / weekly quotas and reset countdowns, with dynamic green / amber / red status badges for all model families.
- **Heartbeat Watchdog & Emergency Stop**: Monitors task activity and flags stalled processes; provides one-click `🛑 Stop` / `🔄 Restart` controls and automatic stealth fade-out when fullscreen apps are active.
- **Smooth Non-Blocking UI**: All RPC probing and disk scans run asynchronously in a dedicated `QThread`, keeping dragging and interactions completely stutter-free.

---

## 🚀 Quick Start

### 1. Install Dependencies

Requires **Python 3.10+** on Windows:

```bash
pip install -r requirements.txt
```

### 2. Launch Silently

Double-click **`start_monitor.bat`** or **`start_monitor.vbs`** (runs via `pythonw.exe` without a console window), or run:

```bash
pythonw float_monitor.py
```

### 3. Simulation Demo

Run `simulate_task.bat` to preview a 3-stage animated task lifecycle in the floating monitor.

---

## 📄 License

Released under the [MIT License](LICENSE).

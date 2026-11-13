# -*- coding: utf-8 -*-
"""
Antigravity 全功能多窗口任务监视与实时额度看板
- 完美多窗口感知：自适应联动 Antigravity 所有干活窗口 (如 111 等任意新建窗口即开即显)
- 智能陈旧过滤：自动排查与归档完结超过阈值的项目 (彻底解决 Field Ops 等过期任务赖屏)
- 真实官方直连：0% Token 损耗直连本地 Language Server RPC 接口获取 100% 真实额度
- 精准模型与周期显示：具体显示 Opus 5.5 / Flash 3.8 / Argon 4 / Sonnet 5.5，并清晰标注 (5h) 与 (周) 额度
"""
import sys
import os
import json
import time
import winreg
import glob
import traceback
import winsound
import shutil
import ctypes
import urllib.request
import ssl
import re
import subprocess
import threading
from ctypes import wintypes
from datetime import datetime, timezone

DEBUG_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_debug.log")
def log(msg):
    try:
        if os.path.exists(DEBUG_LOG) and os.path.getsize(DEBUG_LOG) > 512 * 1024:
            with open(DEBUG_LOG, "r", encoding="utf-8", errors="ignore") as f:
                tail = f.readlines()[-200:]
            with open(DEBUG_LOG, "w", encoding="utf-8") as f:
                f.writelines(tail)
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

log("=== 正在启动 float_monitor.py ===")

try:
    from PySide6.QtCore import (
        Qt, QTimer, QPoint, QRectF, QFileSystemWatcher,
        QPropertyAnimation, QEasingCurve, QThread, Signal
    )
    from PySide6.QtGui import (
        QPainter, QColor, QPen, QFont, QFontMetrics, QGuiApplication,
        QCursor, QIcon, QPixmap, QAction
    )
    from PySide6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QFrame, QProgressBar, QSystemTrayIcon, QMenu, QPushButton,
        QInputDialog, QLineEdit, QStackedLayout
    )
except Exception as e:
    log(f"导入 PySide6 失败: {traceback.format_exc()}")
    sys.exit(1)

TASKS_DIR = os.path.expanduser(r"~\.gemini\tasks")
GLOBAL_STATUS_PATH = os.path.expanduser(r"~\.gemini\task_status.json")
CONV_DIR = os.path.expanduser(r"~\.gemini\antigravity\conversations")
BRAIN_DIR = os.path.expanduser(r"~\.gemini\antigravity\brain")


class AntigravityRPC:
    """直连 Antigravity 本地语言服务 RPC 客户端 (极速时延 < 20ms)"""
    _cached_port = None
    _cached_csrf = None
    _model_map_cache = {}
    _traj_detail_cache = {}  # cid -> (stepCount, detected_model, last_step_summary, user_prompt)
    _ctx = ssl._create_unverified_context()
    _conn_lock = threading.Lock()

    @classmethod
    def get_connection(cls, force_refresh=False):
        if not force_refresh and cls._cached_port and cls._cached_csrf:
            try:
                url = f"https://127.0.0.1:{cls._cached_port}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
                req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json", "x-codeium-csrf-token": cls._cached_csrf}, method="POST")
                with urllib.request.urlopen(req, context=cls._ctx, timeout=0.8) as resp:
                    if resp.status == 200:
                        return cls._cached_port, cls._cached_csrf
            except Exception:
                pass

        with cls._conn_lock:
            try:
                no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                cmd = 'powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \\"Name = \'language_server.exe\'\\") | Select-Object -ExpandProperty CommandLine"'
                proc_out = subprocess.check_output(cmd, shell=True, text=True, timeout=3, creationflags=no_win) or ""
                csrf_m = re.search(r'--csrf_token\s+([a-f0-9\-]+)', proc_out)
                if csrf_m:
                    new_csrf = csrf_m.group(1)
                    pids = set()
                    try:
                        tasklist_out = subprocess.check_output('tasklist /fi "imagename eq language_server.exe" /fo csv /nh', shell=True, text=True, timeout=2, creationflags=no_win)
                        for line in tasklist_out.splitlines():
                            parts = line.strip().split(',')
                            if len(parts) >= 2:
                                pid = parts[1].strip('"')
                                if pid.isdigit():
                                    pids.add(pid)
                    except Exception:
                        pass

                    ports = []
                    try:
                        net_out = subprocess.check_output('netstat -ano -p tcp', shell=True, text=True, timeout=2, creationflags=no_win)
                        for line in net_out.splitlines():
                            for pid in pids:
                                if line.strip().endswith(pid) and 'LISTENING' in line:
                                    m = re.search(r'127\.0\.0\.1:(\d+)', line)
                                    if m:
                                        ports.append(int(m.group(1)))
                    except Exception:
                        pass

                    for p in sorted(set(ports)):
                        try:
                            url = f"https://127.0.0.1:{p}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
                            req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json", "x-codeium-csrf-token": new_csrf}, method="POST")
                            with urllib.request.urlopen(req, context=cls._ctx, timeout=0.8) as resp:
                                if resp.status == 200:
                                    cls._cached_port = p
                                    cls._cached_csrf = new_csrf
                                    return p, new_csrf
                        except Exception:
                            continue
            except Exception as e:
                log(f"RPC连接探测异常: {e}")
        return cls._cached_port, cls._cached_csrf

    @classmethod
    def call(cls, method, body={}):
        port, csrf = cls.get_connection()
        if not port or not csrf:
            return None
        url = f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}"
        req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers={"Content-Type": "application/json", "x-codeium-csrf-token": csrf}, method="POST")
        try:
            with urllib.request.urlopen(req, context=cls._ctx, timeout=1.8) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception:
            try:
                port, csrf = cls.get_connection(force_refresh=True)
                if port and csrf:
                    url = f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}"
                    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers={"Content-Type": "application/json", "x-codeium-csrf-token": csrf}, method="POST")
                    with urllib.request.urlopen(req, context=cls._ctx, timeout=1.8) as resp:
                        return json.loads(resp.read().decode('utf-8'))
            except Exception:
                pass
            return None

    @classmethod
    def get_model_map(cls):
        if cls._model_map_cache:
            return cls._model_map_cache
        m_data = cls.call("GetAvailableModels")
        models_dict = m_data.get("response", {}).get("models", {}) if m_data else {}
        mapping = {}
        for mid, item in models_dict.items():
            code = item.get("model")
            disp = item.get("displayName") or mid
            clean_disp = re.sub(r'\s*\((High|Medium|Low)\)', '', disp).strip()
            if code:
                mapping[code] = clean_disp
            mapping[mid] = clean_disp
        if mapping:
            cls._model_map_cache = mapping
        return cls._model_map_cache


def format_reset_countdown(iso_str):
    if not iso_str:
        return "周期刷新"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = dt - now
        total_sec = int(diff.total_seconds())
        if total_sec <= 0:
            return "即将刷新"
        days = total_sec // 86400
        hours = (total_sec % 86400) // 3600
        minutes = (total_sec % 3600) // 60
        if days > 0:
            return f"{days}天{hours}小时后刷新"
        elif hours > 0:
            return f"{hours}小时{minutes}分后刷新"
        else:
            return f"{minutes}分钟后刷新"
    except Exception:
        return "周期刷新"


def clean_stale_tasks_on_disk():
    """清理已完成且超时的陈旧任务文件，防止已不工作的项目长期赖在悬浮窗上"""
    archive_dir = os.path.join(TASKS_DIR, ".archive")
    os.makedirs(archive_dir, exist_ok=True)
    now = time.time()

    if os.path.exists(TASKS_DIR):
        for fpath in glob.glob(os.path.join(TASKS_DIR, "*.json")):
            try:
                mtime = os.path.getmtime(fpath)
                with open(fpath, "r", encoding="utf-8") as f:
                    d = json.load(f)
                st = d.get("status", "idle")
                # 已完成超过 15 分钟 或 超过 24 小时未更新
                if (st in ["completed", "done"] and (now - mtime > 900)) or (now - mtime > 86400):
                    shutil.move(fpath, os.path.join(archive_dir, f"{int(now)}_{os.path.basename(fpath)}"))
                    log(f"自动清理陈旧任务文件: {fpath}")
            except Exception:
                pass

    if os.path.exists(GLOBAL_STATUS_PATH):
        try:
            mtime = os.path.getmtime(GLOBAL_STATUS_PATH)
            with open(GLOBAL_STATUS_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
            st = d.get("status", "idle")
            # 全局文件如果已完成且超过 15 分钟无活动，自动归档并复位
            if st in ["completed", "done"] and (now - mtime > 900):
                arch_path = os.path.join(archive_dir, f"{int(now)}_task_status_done.json")
                try:
                    shutil.copy2(GLOBAL_STATUS_PATH, arch_path)
                except Exception:
                    pass
                d["status"] = "idle"
                d["task_name"] = "Antigravity 待命"
                d["window_title"] = "待命窗口"
                d["current_step_name"] = "等待下发新任务..."
                d["progress_pct"] = 0
                d["subtasks"] = []
                with open(GLOBAL_STATUS_PATH, "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False, indent=2)
                log("全局状态文件已完成超过 15 分钟，自动复位为待命")
        except Exception:
            pass


def query_antigravity_live_quotas():
    """从 Language Server 获取官方原始额度分组"""
    q_data = AntigravityRPC.call("RetrieveUserQuotaSummary")
    groups = q_data.get("response", {}).get("groups", []) if q_data else []
    raw = {}
    for g in groups:
        g_name = g.get("displayName", "").lower()
        buckets = g.get("buckets", [])
        b_info = {"weekly": None, "5h": None}
        for b in buckets:
            win = b.get("window")
            frac = b.get("remainingFraction")
            pct = round(frac * 100, 1) if frac is not None else 0.0
            reset_iso = b.get("resetTime")
            desc = format_reset_countdown(reset_iso)
            if win == "weekly":
                b_info["weekly"] = {"pct": pct, "reset": desc}
            elif win == "5h":
                b_info["5h"] = {"pct": pct, "reset": desc}
        if "gemini models" in g_name:
            raw["gemini"] = b_info
        elif "claude" in g_name or "gpt" in g_name:
            raw["claude"] = b_info
        elif "argon" in g_name:
            raw["argon"] = b_info
    return raw


def resolve_model_quota(model_name, raw_groups, preferred_cycle="5h"):
    """
    根据窗口具体模型与用户选择的周期 (5h 或 周)，精准解析额度与展示文案
    """
    m_lower = (model_name or "").lower()
    c_info = raw_groups.get("claude", {})
    g_info = raw_groups.get("gemini", {})
    a_info = raw_groups.get("argon", {})

    c_5h = c_info.get("5h") or {"pct": 0.0, "reset": "未知"}
    c_wk = c_info.get("weekly") or {"pct": 0.0, "reset": "未知"}
    g_5h = g_info.get("5h") or {"pct": 100.0, "reset": "未知"}
    g_wk = g_info.get("weekly") or {"pct": 100.0, "reset": "未知"}
    a_wk = a_info.get("weekly") or {"pct": 0.0, "reset": "未知"}

    if "argon" in m_lower:
        full_name = "Gemini 4 Argon"
        short_name = "Argon 4"
        cycle = "周"
        active_pct = a_wk["pct"]
        h5_pct, h5_reset = None, None
        wk_pct, wk_reset = a_wk["pct"], a_wk["reset"]
        desc = f"周额度 {a_wk['pct']}% · {a_wk['reset']}"
    elif "opus" in m_lower:
        full_name = "Claude Opus 5.5"
        short_name = "Opus 5.5"
        cycle = preferred_cycle if preferred_cycle in ["5h", "周"] else "5h"
        active_pct = c_wk["pct"] if cycle == "周" else c_5h["pct"]
        h5_pct, h5_reset = c_5h["pct"], c_5h["reset"]
        wk_pct, wk_reset = c_wk["pct"], c_wk["reset"]
        desc = f"5h: {c_5h['pct']}% ({c_5h['reset']}) · 周: {c_wk['pct']}% ({c_wk['reset']})"
    elif "sonnet" in m_lower:
        full_name = "Claude Sonnet 5.5"
        short_name = "Sonnet 5.5"
        cycle = preferred_cycle if preferred_cycle in ["5h", "周"] else "5h"
        active_pct = c_wk["pct"] if cycle == "周" else c_5h["pct"]
        h5_pct, h5_reset = c_5h["pct"], c_5h["reset"]
        wk_pct, wk_reset = c_wk["pct"], c_wk["reset"]
        desc = f"5h: {c_5h['pct']}% ({c_5h['reset']}) · 周: {c_wk['pct']}% ({c_wk['reset']})"
    elif "pro" in m_lower:
        full_name = "Gemini 2.5 Pro"
        short_name = "Pro 2.5"
        cycle = preferred_cycle if preferred_cycle in ["5h", "周"] else "5h"
        active_pct = g_wk["pct"] if cycle == "周" else g_5h["pct"]
        h5_pct, h5_reset = g_5h["pct"], g_5h["reset"]
        wk_pct, wk_reset = g_wk["pct"], g_wk["reset"]
        desc = f"5h: {g_5h['pct']}% ({g_5h['reset']}) · 周: {g_wk['pct']}% ({g_wk['reset']})"
    elif "hydrogen" in m_lower:
        full_name = "Gemini 4 Hydrogen"
        short_name = "Hydrogen 4"
        cycle = preferred_cycle if preferred_cycle in ["5h", "周"] else "5h"
        active_pct = g_wk["pct"] if cycle == "周" else g_5h["pct"]
        h5_pct, h5_reset = g_5h["pct"], g_5h["reset"]
        wk_pct, wk_reset = g_wk["pct"], g_wk["reset"]
        desc = f"5h: {g_5h['pct']}% ({g_5h['reset']}) · 周: {g_wk['pct']}% ({g_wk['reset']})"
    else:
        full_name = model_name if (model_name and "flash" not in m_lower) else "Gemini 3.8 Flash"
        short_name = full_name.replace("Gemini ", "").strip()[:12] if "flash" not in m_lower else "Flash 3.8"
        cycle = preferred_cycle if preferred_cycle in ["5h", "周"] else "5h"
        active_pct = g_wk["pct"] if cycle == "周" else g_5h["pct"]
        h5_pct, h5_reset = g_5h["pct"], g_5h["reset"]
        wk_pct, wk_reset = g_wk["pct"], g_wk["reset"]
        desc = f"5h: {g_5h['pct']}% ({g_5h['reset']}) · 周: {g_wk['pct']}% ({g_wk['reset']})"

    ring_tag = f"{short_name}({cycle})"
    custom_pct_str = f"{active_pct:.1f}%" if (0 < active_pct < 10) else f"{int(active_pct)}%"

    return {
        "full_name": full_name,
        "short_name": short_name,
        "cycle": cycle,
        "active_pct": active_pct,
        "custom_pct_str": custom_pct_str,
        "ring_tag": ring_tag,
        "h5_pct": h5_pct,
        "h5_reset": h5_reset,
        "wk_pct": wk_pct,
        "wk_reset": wk_reset,
        "desc": desc
    }


def find_matching_rpc_task(tasks, data, fpath, mtime):
    """
    智能窗口关联算法：
    将磁盘任务状态（如 float_monitor.json 或全局 task_status.json）精准关联到 Antigravity 实际窗口。
    杜绝同窗口任务因文件名或标题不同被错误拆分成两个独立窗口。
    """
    if not tasks:
        return None

    fname = os.path.splitext(os.path.basename(fpath))[0].lower() if fpath else ""
    data_name = (data.get("task_name") or "").lower()
    data_cid = (data.get("conversation_id") or data.get("cid") or "").lower()

    # 1. 精确 CID / ConversationID 匹配
    if data_cid:
        for t in tasks:
            if (t.get("_cid") or "").lower() == data_cid:
                return t

    # 2. 窗口名称/项目名/中英文别名包含匹配
    alias_pairs = [("float_monitor", "悬浮"), ("float", "悬浮"), ("monitor", "监控")]
    for t in tasks:
        t_name = (t.get("task_name") or "").lower()
        t_title = (t.get("window_title") or "").lower()
        if fname and (fname in t_name or fname in t_title or t_name in fname):
            return t
        if data_name and (data_name in t_name or t_name in data_name):
            return t
        for en, cn in alias_pairs:
            if (en in fname or en in data_name) and (cn in t_name or cn in t_title):
                return t

    # 3. 单窗口唯一定律：当前系统只有 1 个 Antigravity 活跃会话时，本环境产生的任务状态 100% 属于该窗口
    if len(tasks) == 1:
        return tasks[0]

    # 4. 时间戳临近匹配 (活跃时间相差 300 秒以内)
    closest_task = None
    min_diff = 300
    for t in tasks:
        diff = abs(t.get("_mtime", 0) - mtime)
        if diff < min_diff:
            min_diff = diff
            closest_task = t

    return closest_task


def merge_task_data(t, data, fpath, mtime):
    """将磁盘阶段步骤与子任务丰富信息融合进对应会话任务"""
    if data.get("subtasks"):
        t["subtasks"] = data.get("subtasks")
        t["has_stage_plan"] = True
    if data.get("total_steps") is not None:
        t["total_steps"] = data.get("total_steps")
        if data.get("total_steps", 1) > 1:
            t["has_stage_plan"] = True
    if data.get("current_step") is not None:
        t["current_step"] = data.get("current_step")
    if data.get("current_step_name"):
        t["current_step_name"] = data.get("current_step_name")
    if data.get("progress_pct") is not None:
        t["progress_pct"] = data.get("progress_pct")
    if data.get("status"):
        if data.get("status") == "blocked":
            t["status"] = "blocked"
        elif t.get("status") != "running":
            t["status"] = data.get("status")
    t["_file_path"] = fpath
    t["_mtime"] = max(t.get("_mtime", 0), mtime)
    if data.get("task_name") and data.get("task_name") not in ["Antigravity 待命", "待命窗口"]:
        t["detailed_task_name"] = data.get("task_name")


def scan_all_tasks():
    """
    智能全场景任务扫描器：
    1. 动态过滤已完结、长期无心跳的非活跃窗口 (如已结束的 FIELD OPS 绝不赖屏)
    2. 无感自动探测 Antigravity 正在干活的新窗口 (如 111 等任意新建窗口即开即显)
    3. 正在运行的任务自动赋予最高权重 (优先排序为 [W1] 第一位)
    """
    tasks = []
    seen_cids = set()
    seen_names = set()
    now = time.time()
    model_map = AntigravityRPC.get_model_map()

    # 1. 优先通过 Antigravity 官方 RPC GetAllCascadeTrajectories 获取所有会话窗口
    trajs_data = AntigravityRPC.call("GetAllCascadeTrajectories")
    traj_summaries = trajs_data.get("trajectorySummaries", {}) if trajs_data else {}

    for cid, tinfo in traj_summaries.items():
        st_rpc = tinfo.get("status", "")
        is_running = (st_rpc == "CASCADE_RUN_STATUS_RUNNING")
        mod_time_str = tinfo.get("lastModifiedTime")

        age_sec = 999999
        if mod_time_str:
            try:
                dt = datetime.fromisoformat(mod_time_str.replace("Z", "+00:00"))
                age_sec = (datetime.now(timezone.utc) - dt).total_seconds()
            except Exception:
                pass

        # 核心过滤：超过 2 小时未更新且不在 running 状态的会话（例如昨天的 Field Ops），坚决自动下线
        if age_sec > 7200 and not is_running:
            continue

        raw_title = tinfo.get("summary") or tinfo.get("annotations", {}).get("title") or f"会话 {cid[:6]}"
        step_count = tinfo.get("stepCount", 0)

        # 清理已失效会话缓存，防止长时运行内存泄漏
        active_cids = set(traj_summaries.keys())
        for stale_cid in [k for k in list(AntigravityRPC._traj_detail_cache.keys()) if k not in active_cids]:
            AntigravityRPC._traj_detail_cache.pop(stale_cid, None)

        # 获取该窗口绑定的真实具体模型 (仅缓存摘要字段，不常驻整份轨迹 JSON)
        cached = AntigravityRPC._traj_detail_cache.get(cid)
        if not cached or cached[0] != step_count:
            detail = AntigravityRPC.call("GetCascadeTrajectory", {"cascadeId": cid})
            detected_model = "Gemini 3.8 Flash"
            last_step_summary = ""
            user_prompt = ""

            if detail:
                steps = detail.get("trajectory", {}).get("steps", [])
                for s in reversed(steps[-30:]):
                    meta = s.get("metadata", {})
                    gen_m = meta.get("generatorModel")
                    if gen_m and gen_m in model_map:
                        detected_model = model_map[gen_m]
                        break
                for s in reversed(steps):
                    if s.get("type") == "CORTEX_STEP_TYPE_USER_INPUT" and not user_prompt:
                        cnt = s.get("userInput", {}).get("query", "")
                        clean = re.sub(r'<[^>]+>', '', cnt).strip()
                        if clean:
                            user_prompt = clean.splitlines()[0]
                    tool_call = s.get("metadata", {}).get("toolCall", {})
                    if tool_call and not last_step_summary:
                        args = tool_call.get("args", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {}
                        last_step_summary = args.get("toolSummary") or tool_call.get("name")
                    if user_prompt and last_step_summary:
                        break
            AntigravityRPC._traj_detail_cache[cid] = (step_count, detected_model, last_step_summary, user_prompt)
        else:
            _, detected_model, last_step_summary, user_prompt = cached

        task_st = "running" if is_running else ("completed" if age_sec < 600 else "idle")
        progress = 50 if task_st == "running" else (100 if task_st == "completed" else 0)

        tasks.append({
            "task_name": raw_title[:28],
            "window_title": f"窗口 · {raw_title[:16]}",
            "model_name": detected_model,
            "total_steps": 1,
            "current_step": 1,
            "step_count": step_count,
            "has_stage_plan": False,
            "current_step_name": last_step_summary or user_prompt or "任务进行中...",
            "progress_pct": progress,
            "status": task_st,
            "data_source": f"ag-rpc/{cid[:6]}",
            "subtasks": [
                {"title": user_prompt[:32] or "执行指令", "status": "done" if task_st != "running" else "running", "pct": 100 if task_st != "running" else 50}
            ],
            "_file_path": None,
            "_mtime": time.time() - age_sec,
            "_cid": cid
        })
        seen_cids.add(cid)
        seen_names.add(raw_title)

    # 2. 扫描 ~/.gemini/tasks/*.json 专用多任务文件并智能关联
    if os.path.exists(TASKS_DIR):
        for fpath in glob.glob(os.path.join(TASKS_DIR, "*.json")):
            try:
                mtime = os.path.getmtime(fpath)
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                name = data.get("task_name") or os.path.splitext(os.path.basename(fpath))[0]
                st = data.get("status", "idle")

                # 如果已完成且超过 15 分钟，自动跳过
                if st in ["completed", "done"] and (now - mtime > 900):
                    continue
                if now - mtime > 7200:
                    continue

                matched = find_matching_rpc_task(tasks, data, fpath, mtime)
                if matched:
                    merge_task_data(matched, data, fpath, mtime)
                else:
                    data["_file_path"] = fpath
                    data["_mtime"] = mtime
                    data.setdefault("window_title", name)
                    data.setdefault("has_stage_plan", bool(data.get("subtasks") or data.get("total_steps", 1) > 1))
                    tasks.append(data)
            except Exception:
                pass

    # 3. 扫描全局 task_status.json 并智能融合 (严禁为同一窗口产生重复幽灵任务)
    if os.path.exists(GLOBAL_STATUS_PATH):
        try:
            mtime = os.path.getmtime(GLOBAL_STATUS_PATH)
            with open(GLOBAL_STATUS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("task_name", "")
            st = data.get("status", "idle")

            # 如果全局状态已完结超过 15 分钟，跳过
            if not (st in ["done", "completed"] and (now - mtime > 900)):
                if name and name not in ["Antigravity 待命", "待命窗口"]:
                    matched = find_matching_rpc_task(tasks, data, GLOBAL_STATUS_PATH, mtime)
                    if matched:
                        merge_task_data(matched, data, GLOBAL_STATUS_PATH, mtime)
                    else:
                        data["_file_path"] = GLOBAL_STATUS_PATH
                        data["_mtime"] = mtime
                        data.setdefault("window_title", name)
                        tasks.append(data)
        except Exception:
            pass

    # 4. 智能优先级排序：
    # running 任务永远置顶第一位 (当前真正干活的窗口永远是 W1！)
    # blocked 告警任务次优先
    # completed 随后
    # 按照最近活跃时间倒序排列
    status_score = {"running": 10, "blocked": 8, "pending": 5, "completed": 3, "done": 2, "idle": 1}
    tasks.sort(key=lambda x: (status_score.get(x.get("status", "idle"), 0), x.get("_mtime", 0)), reverse=True)

    if not tasks:
        tasks = [{
            "task_name": "Antigravity 待命中",
            "window_title": "待命窗口",
            "model_name": "Gemini 3.8 Flash",
            "total_steps": 1,
            "current_step": 0,
            "current_step_name": "等待下发新任务...",
            "progress_pct": 0,
            "status": "idle",
            "subtasks": []
        }]

    return tasks


REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_KEY_NAME = "AntigravityFloatMonitor"

def is_autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, REG_KEY_NAME)
            return True
    except WindowsError:
        return False

def set_autostart(enable: bool):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                pythonw_exe = r"C:\Users\苏拉\AppData\Local\Programs\Python\Python312\pythonw.exe"
                script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "float_monitor.py")
                cmd = f'"{pythonw_exe}" "{script_path}"'
                winreg.SetValueEx(key, REG_KEY_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, REG_KEY_NAME)
                except WindowsError:
                    pass
    except Exception as e:
        log(f"注册表设置开机自启失败: {e}")

def apply_acrylic_effect(hwnd, enable_acrylic=True):
    """为窗口开启或调整 Windows 11 原生亚克力 (Acrylic) 特效 (胶囊态彻底禁用 DWM 边框与背景，避免双重轮廓)"""
    try:
        dwmapi = ctypes.windll.dwmapi
        # 1. 沉浸式暗黑模式 (DWMWA_USE_IMMERSIVE_DARK_MODE = 20)
        darkMode = wintypes.BOOL(True)
        dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(darkMode), ctypes.sizeof(darkMode))

        if enable_acrylic:
            # 大卡片态：开启原生亚克力磨砂背景与优雅大圆角
            backdropType = wintypes.DWORD(3)  # DWMSBT_TRANSIENTWINDOW (Acrylic)
            dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdropType), ctypes.sizeof(backdropType))
            cornerPref = wintypes.DWORD(2)     # DWMWCP_ROUND (8px system round)
            dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(cornerPref), ctypes.sizeof(cornerPref))
            ncPolicy = wintypes.DWORD(2)       # DWMNCRP_ENABLED
            dwmapi.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(ncPolicy), ctypes.sizeof(ncPolicy))
        else:
            # 极简胶囊态：彻底关闭 DWM 边框、阴影与系统背景，确保外围100%全透，杜绝双层外框
            backdropNone = wintypes.DWORD(1)   # DWMSBT_NONE
            dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdropNone), ctypes.sizeof(backdropNone))
            cornerNone = wintypes.DWORD(1)     # DWMWCP_DONOTROUND
            dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(cornerNone), ctypes.sizeof(cornerNone))
            ncDisable = wintypes.DWORD(1)      # DWMNCRP_DISABLED (彻底关闭系统外框和高光边框)
            dwmapi.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(ncDisable), ctypes.sizeof(ncDisable))
    except Exception as e:
        log(f"应用亚克力特效异常: {e}")

def create_tray_icon():
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(56, 189, 248))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(4, 4, 24, 24)
    painter.setPen(QPen(QColor(255, 255, 255), 2))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "A")
    painter.end()
    return QIcon(pixmap)


class ProgressRing(QWidget):
    """通用仪表圆环：自适应各窗口模型与额度状态 (支持精准小数与明确周期标签)"""
    def __init__(self, ring_type="task", label="进度", parent=None):
        super().__init__(parent)
        self.setFixedSize(68, 66)
        self.ring_type = ring_type
        self.label_text = label
        self.progress = 0.0
        self.display_pct_str = "0%"
        self.status = "idle"
        self.on_click_callback = None
        self.setCursor(Qt.PointingHandCursor if ring_type == "quota" else Qt.ArrowCursor)

    def set_value(self, progress, status="running", custom_str=None):
        self.progress = max(0.0, min(100.0, float(progress)))
        if custom_str is not None:
            self.display_pct_str = custom_str
        else:
            self.display_pct_str = f"{self.progress:.1f}%" if (0 < self.progress < 10) else f"{int(self.progress)}%"
        self.status = status
        self.update()

    def mousePressEvent(self, event):
        if self.ring_type == "quota" and self.on_click_callback:
            self.on_click_callback()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        center_x = self.width() / 2.0
        rect = QRectF(center_x - 21, 2, 42, 42)

        # 1. 轨道底色
        bg_pen = QPen(QColor(255, 255, 255, 22), 4)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(rect, 0, 360 * 16)

        # 2. 前景环配色
        if self.ring_type == "quota":
            if self.progress > 40:
                fg_color = QColor(16, 185, 129)  # 充沛充足时翠绿
            elif self.progress > 15:
                fg_color = QColor(245, 158, 11)  # 警示橙黄
            else:
                fg_color = QColor(239, 68, 68)   # 濒危鲜红
        else:
            if self.status == "completed":
                fg_color = QColor(16, 185, 129)
            elif self.status == "blocked":
                fg_color = QColor(239, 68, 68)
            elif self.status == "idle":
                fg_color = QColor(156, 163, 175)
            else:
                fg_color = QColor(56, 189, 248)

        # 3. 绘制进度弧
        if self.progress > 0:
            fg_pen = QPen(fg_color, 4)
            fg_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(fg_pen)
            start_angle = 90 * 16
            span_angle = -int(self.progress * 3.6 * 16)
            painter.drawArc(rect, start_angle, span_angle)

        # 4. 中心数值
        painter.setPen(QColor(255, 255, 255))
        fsize = 7 if len(self.display_pct_str) >= 5 else 8
        font = QFont("Segoe UI", fsize, QFont.Bold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self.display_pct_str)

        # 5. 下方说明标签
        is_danger = (self.ring_type == "quota" and self.progress <= 15)
        painter.setPen(QColor(239, 68, 68) if is_danger else QColor(156, 163, 175))
        lbl_font = QFont("Microsoft YaHei", 7)
        painter.setFont(lbl_font)
        painter.drawText(QRectF(0, 46, self.width(), 16), Qt.AlignCenter, self.label_text)


class DataRefreshWorker(QThread):
    """后台异步拉取 RPC 任务与实时额度，彻底消除主线程卡顿"""
    tasks_ready = Signal(list)
    quotas_ready = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._wake_event = threading.Event()
        self._force_quota = True
        self._last_quota_ts = 0.0

    def trigger_now(self, with_quota=False):
        if with_quota:
            self._force_quota = True
        self._wake_event.set()

    def stop(self):
        self._running = False
        self._wake_event.set()

    def run(self):
        while self._running:
            now = time.time()
            if self._force_quota or (now - self._last_quota_ts >= 8.0):
                self._force_quota = False
                self._last_quota_ts = now
                try:
                    raw = query_antigravity_live_quotas()
                    if raw and self._running:
                        self.quotas_ready.emit(raw)
                except Exception as e:
                    log(f"后台刷新实时额度异常: {e}")

            try:
                tasks = scan_all_tasks()
                if self._running:
                    self.tasks_ready.emit(tasks)
            except Exception as e:
                log(f"后台扫描任务异常: {e}")

            self._wake_event.wait(1.5)
            self._wake_event.clear()


class MultiWindowMonitor(QWidget):
    """
    Antigravity 全功能高级悬浮窗
    - 支持多窗口固定坐标 1-Click 自由切换（按键绝对不移位）
    - 智能动态定位真正干活的窗口（running 优先置顶，陈旧完结项目自动归档下线）
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Antigravity 任务监视器")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.drag_position = QPoint()
        self.is_pill_mode = True
        self.current_window_idx = 0
        self.tasks_list = []
        self.raw_quotas = {}
        self.preferred_cycle = "5h"  # 可在 5h / 周 之间快速切换
        self.current_status = "idle"
        self.current_pct = 0
        self.quota_pct = 95.0
        self.quota_refresh_desc = "正在连接语言服务..."
        self.last_task_status = {}
        self.model_name = "Gemini 3.8 Flash"
        self.task_start_times = {}
        self.task_elapsed_secs = {}
        self.manual_models = {}
        self.manual_status = {}
        self.elapsed_sec = 0

        self.is_dragging = False

        # 全屏免打扰智能隐身状态
        self.stealth_enabled = True
        self.is_stealthed = False

        self.setWindowOpacity(1.0)

        self.init_ui()
        self.init_tray()
        self.init_file_watcher()

        # 每 30 秒执行一次陈旧任务磁盘静默归档
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(clean_stale_tasks_on_disk)
        self.cleanup_timer.start(30000)

        self.sec_timer = QTimer(self)
        self.sec_timer.timeout.connect(self.on_second_tick)
        self.sec_timer.start(1000)

        # 启动后台异步拉取线程 (任务 1.5s / 额度 8s)
        self.worker = DataRefreshWorker(self)
        self.worker.tasks_ready.connect(self.on_tasks_updated)
        self.worker.quotas_ready.connect(self.on_quotas_updated)
        self.worker.start()

        self.update_view_mode()
        self.reposition_to_bottom_right()

    def enterEvent(self, event):
        super().enterEvent(event)

    def leaveEvent(self, event):
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.transparent)

    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        if angle > 0:
            self.switch_prev_window()
        elif angle < 0:
            self.switch_next_window()
        event.accept()

    def fade_to(self, target):
        if hasattr(self, 'anim') and self.anim.state() == QPropertyAnimation.Running:
            self.anim.stop()
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(200)
        self.anim.setStartValue(self.windowOpacity())
        self.anim.setEndValue(target)
        self.anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.anim.start()

    def init_tray(self):
        try:
            self.tray = QSystemTrayIcon(self)
            self.tray.setIcon(create_tray_icon())
            self.tray.setToolTip("Antigravity 多窗口任务监视器")

            tray_menu = QMenu()
            toggle_action = QAction("展开/折叠监视窗", self)
            toggle_action.triggered.connect(self.on_tray_toggle)
            tray_menu.addAction(toggle_action)

            next_win_action = QAction("切换至下一个窗口任务", self)
            next_win_action.triggered.connect(self.switch_next_window)
            tray_menu.addAction(next_win_action)

            cycle_action = QAction("切换额度显示周期 (5小时 / 周)", self)
            cycle_action.triggered.connect(self.toggle_quota_cycle)
            tray_menu.addAction(cycle_action)

            focus_action = QAction("↗ 聚焦激活 Antigravity 窗口", self)
            focus_action.triggered.connect(self.focus_antigravity_window)
            tray_menu.addAction(focus_action)

            clean_action = QAction("🧹 清理已结束/非活跃窗口任务", self)
            clean_action.triggered.connect(self.clean_all_completed_tasks)
            tray_menu.addAction(clean_action)

            self.stealth_action = QAction("🕶 全屏应用智能隐身免打扰", self, checkable=True)
            self.stealth_action.setChecked(self.stealth_enabled)
            self.stealth_action.triggered.connect(self.toggle_stealth)
            tray_menu.addAction(self.stealth_action)

            calibrate_action = QAction("指定当前窗口使用的模型...", self)
            calibrate_action.triggered.connect(self.calibrate_quota)
            tray_menu.addAction(calibrate_action)

            self.autostart_action = QAction("开机自动启动", self, checkable=True)
            self.autostart_action.setChecked(is_autostart_enabled())
            self.autostart_action.triggered.connect(self.on_toggle_autostart)
            tray_menu.addAction(self.autostart_action)

            tray_menu.addSeparator()
            quit_action = QAction("退出监控", self)
            quit_action.triggered.connect(QApplication.instance().quit)
            tray_menu.addAction(quit_action)

            self.tray.setContextMenu(tray_menu)
            self.tray.activated.connect(self.on_tray_activated)
            self.tray.messageClicked.connect(self.on_tray_message_clicked)
            self.tray.show()
        except Exception as e:
            log(f"托盘初始化异常: {e}")

    def on_tray_message_clicked(self):
        if self.is_pill_mode:
            self.toggle_mode()
        self.focus_antigravity_window()

    def toggle_quota_cycle(self):
        """点击圆环在 5小时额度 与 周额度 之间切换显示"""
        self.preferred_cycle = "周" if self.preferred_cycle == "5h" else "5h"
        self.apply_current_task()

    def _task_id(self, task):
        return task.get("_cid") or task.get("_file_path") or task.get("task_name")

    def _write_task_json(self, task, target_file):
        if target_file and target_file.endswith(".json") and os.path.exists(target_file):
            try:
                clean = {k: v for k, v in task.items() if not k.startswith("_")}
                with open(target_file, "w", encoding="utf-8") as f:
                    json.dump(clean, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def assign_model_to_current_window(self, model_display_name):
        """点击全景额度微标直接给当前窗口分配模型"""
        if self.tasks_list and self.current_window_idx < len(self.tasks_list):
            cur_task = self.tasks_list[self.current_window_idx]
            tid = self._task_id(cur_task)
            self.manual_models[tid] = model_display_name
            cur_task["model_name"] = model_display_name
            self._write_task_json(cur_task, cur_task.get("_file_path"))
            log(f"窗口任务已切换模型为: {model_display_name}")
            self.apply_current_task()

    def calibrate_quota(self):
        defaults = ["Gemini 4 Hydrogen", "Gemini 3.8 Flash", "Gemini 4 Argon", "Claude Opus 5.5", "Claude Sonnet 5.5", "Gemini 2.5 Pro"]
        rpc_models = list(dict.fromkeys(AntigravityRPC.get_model_map().values()))
        models = list(dict.fromkeys(rpc_models + defaults))
        cur_idx = 0
        for i, m in enumerate(models):
            if m.lower() == (self.model_name or "").lower():
                cur_idx = i
                break

        item, ok = QInputDialog.getItem(
            self, "选择当前窗口所用模型",
            "请选择当前窗口任务绑定的具体模型 (额度将自动精准联动):",
            models, cur_idx, False
        )
        if ok and item:
            self.assign_model_to_current_window(item)

    def on_toggle_autostart(self, checked):
        set_autostart(checked)
        self.autostart_action.setChecked(is_autostart_enabled())

    def on_tray_toggle(self):
        self.ensure_visible_on_screen()
        self.toggle_mode()
        self.show()
        self.raise_()
        self.activateWindow()
        if self.is_stealthed:
            self.exit_stealth()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.on_tray_toggle()

    def init_file_watcher(self):
        self.watcher = QFileSystemWatcher(self)
        watch_dirs = [
            os.path.expanduser(r"~\.gemini"),
            TASKS_DIR,
            CONV_DIR,
            os.path.dirname(os.path.abspath(__file__))
        ]
        for d in watch_dirs:
            if os.path.exists(d):
                self.watcher.addPath(d)
        if os.path.exists(GLOBAL_STATUS_PATH):
            self.watcher.addPath(GLOBAL_STATUS_PATH)
            
        self.watcher.fileChanged.connect(self.reload_and_refresh)
        self.watcher.directoryChanged.connect(self.reload_and_refresh)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # ── 1. 极简胶囊态 (Pill) ─────────────────────────
        self.pill_frame = QFrame(self)
        self.pill_frame.setObjectName("PillFrame")
        self.pill_frame.setStyleSheet("""
            QFrame#PillFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(28, 36, 52, 0.88), stop:1 rgba(14, 19, 31, 0.90));
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 17px;
            }
        """)
        self.pill_frame.setFixedHeight(34)
        self.pill_frame.setCursor(Qt.PointingHandCursor)
        self.pill_frame.mousePressEvent = self.on_pill_mouse_press
        self.pill_frame.mouseMoveEvent = self.on_pill_mouse_move
        self.pill_frame.mouseReleaseEvent = self.on_pill_mouse_release
        self.pill_frame.mouseDoubleClickEvent = lambda e: self.focus_antigravity_window()

        pill_layout = QHBoxLayout(self.pill_frame)
        pill_layout.setContentsMargins(12, 0, 12, 0)
        pill_layout.setSpacing(7)

        self.pill_win_badge = QLabel("W1", self.pill_frame)
        self.pill_win_badge.setFixedSize(30, 18)
        self.pill_win_badge.setAlignment(Qt.AlignCenter)
        self.pill_win_badge.setStyleSheet("""
            background-color: rgba(56, 189, 248, 0.18);
            color: #38BDF8;
            font-size: 10px;
            font-weight: bold;
            border-radius: 3px;
        """)
        self.pill_win_badge.setCursor(Qt.PointingHandCursor)
        self.pill_win_badge.mousePressEvent = self.on_badge_mouse_press
        self.pill_win_badge.mouseMoveEvent = self.on_pill_mouse_move
        self.pill_win_badge.mouseReleaseEvent = self.on_badge_mouse_release
        self.pill_win_badge.mouseDoubleClickEvent = lambda e: self.focus_antigravity_window()
        self.pill_win_badge.setToolTip("点击切换窗口 (双击唤醒 Antigravity)")
        pill_layout.addWidget(self.pill_win_badge)

        self.pill_dot = QLabel("●", self.pill_frame)
        self.pill_dot.setStyleSheet("font-size: 11px; border:none; background: transparent; color: #10B981;")
        self.pill_dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        pill_layout.addWidget(self.pill_dot)

        self.pill_task_badge = QLabel("待命", self.pill_frame)
        self.pill_task_badge.setStyleSheet("color: #38BDF8; font-size: 11px; font-weight: bold; border:none; background: transparent;")
        self.pill_task_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        pill_layout.addWidget(self.pill_task_badge)

        self.pill_quota_badge = QLabel("✦ 95% Flash 3.8(5h)", self.pill_frame)
        self.pill_quota_badge.setStyleSheet("color: #34D399; font-size: 10px; font-weight: bold; border:none; background: transparent;")
        self.pill_quota_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        pill_layout.addWidget(self.pill_quota_badge)

        self.pill_timer_lbl = QLabel("⏱ 00:00", self.pill_frame)
        self.pill_timer_lbl.setStyleSheet("color: #94A3B8; font-size: 10px; border:none; background: transparent;")
        self.pill_timer_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        pill_layout.addWidget(self.pill_timer_lbl)

        pill_arrow = QLabel("▲", self.pill_frame)
        pill_arrow.setStyleSheet("color: #64748B; font-size: 9px; border:none; background: transparent;")
        pill_arrow.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        pill_layout.addWidget(pill_arrow)

        # ── 2. 完整大卡片态 (Card) ────────────────────────
        self.card_frame = QFrame(self)
        self.card_frame.setStyleSheet("""
            QFrame#CardFrame {
                background-color: rgba(16, 22, 34, 0.72);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 16px;
            }
        """)
        self.card_frame.setObjectName("CardFrame")
        self.card_frame.mouseDoubleClickEvent = lambda e: self.focus_antigravity_window()
        self.card_layout = QVBoxLayout(self.card_frame)
        self.card_layout.setContentsMargins(14, 12, 14, 12)
        self.card_layout.setSpacing(7)

        # ── 窗口多任务导航条（硬锁定左侧连体键）──
        win_nav_layout = QHBoxLayout()
        win_nav_layout.setContentsMargins(0, 0, 0, 0)
        win_nav_layout.setSpacing(0)

        self.btn_prev_win = QPushButton("◀", self.card_frame)
        self.btn_prev_win.setFixedSize(24, 22)
        self.btn_prev_win.setCursor(Qt.PointingHandCursor)
        self.btn_prev_win.setToolTip("上一窗口 (支持鼠标滚轮上滑)")
        self.btn_prev_win.setStyleSheet("""
            QPushButton {
                background-color: rgba(96, 165, 250, 0.15);
                color: #60A5FA;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid rgba(96, 165, 250, 0.35);
                border-top-left-radius: 4px;
                border-bottom-left-radius: 4px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
            }
            QPushButton:hover {
                background-color: rgba(96, 165, 250, 0.35);
                color: #FFFFFF;
            }
        """)
        self.btn_prev_win.clicked.connect(self.switch_prev_window)
        win_nav_layout.addWidget(self.btn_prev_win)

        self.btn_next_win = QPushButton("▶", self.card_frame)
        self.btn_next_win.setFixedSize(24, 22)
        self.btn_next_win.setCursor(Qt.PointingHandCursor)
        self.btn_next_win.setToolTip("下一窗口 (支持鼠标滚轮下滑)")
        self.btn_next_win.setStyleSheet("""
            QPushButton {
                background-color: rgba(96, 165, 250, 0.15);
                color: #60A5FA;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid rgba(96, 165, 250, 0.35);
                border-left: none;
                border-radius: 0px;
            }
            QPushButton:hover {
                background-color: rgba(96, 165, 250, 0.35);
                color: #FFFFFF;
            }
        """)
        self.btn_next_win.clicked.connect(self.switch_next_window)
        win_nav_layout.addWidget(self.btn_next_win)

        self.btn_menu_win = QPushButton("☰", self.card_frame)
        self.btn_menu_win.setFixedSize(24, 22)
        self.btn_menu_win.setCursor(Qt.PointingHandCursor)
        self.btn_menu_win.setToolTip("所有窗口任务清单 (1-Click直达)")
        self.btn_menu_win.setStyleSheet("""
            QPushButton {
                background-color: rgba(96, 165, 250, 0.15);
                color: #60A5FA;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid rgba(96, 165, 250, 0.35);
                border-left: none;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(96, 165, 250, 0.35);
                color: #FFFFFF;
            }
        """)
        self.btn_menu_win.clicked.connect(self.show_window_menu)
        win_nav_layout.addWidget(self.btn_menu_win)

        self.win_nav_lbl = QLabel("窗口 (1/1)", self.card_frame)
        self.win_nav_lbl.setCursor(Qt.PointingHandCursor)
        self.win_nav_lbl.setToolTip("点击直接切换至下一窗口")
        self.win_nav_lbl.mousePressEvent = lambda e: self.switch_next_window()
        self.win_nav_lbl.setStyleSheet("""
            QLabel {
                color: #93C5FD;
                font-size: 11px;
                font-weight: bold;
                padding-left: 6px;
                border: none;
            }
            QLabel:hover {
                color: #BFDBFE;
            }
        """)
        win_nav_layout.addWidget(self.win_nav_lbl, 1)

        self.btn_focus = QPushButton("↗", self.card_frame)
        self.btn_focus.setFixedSize(22, 22)
        self.btn_focus.setCursor(Qt.PointingHandCursor)
        self.btn_focus.setToolTip("唤醒并置顶当前任务对应的 Antigravity 窗口")
        self.btn_focus.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #38BDF8;
                font-size: 12px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                color: #FFFFFF;
                background-color: rgba(56, 189, 248, 0.25);
                border-radius: 4px;
            }
        """)
        self.btn_focus.clicked.connect(self.focus_antigravity_window)
        win_nav_layout.addWidget(self.btn_focus)

        self.btn_close_task = QPushButton("✕", self.card_frame)
        self.btn_close_task.setFixedSize(22, 22)
        self.btn_close_task.setCursor(Qt.PointingHandCursor)
        self.btn_close_task.setToolTip("移除/归档当前窗口任务监控记录")
        self.btn_close_task.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #9CA3AF;
                font-size: 11px;
                border: none;
            }
            QPushButton:hover {
                color: #EF4444;
                background-color: rgba(239, 68, 68, 0.25);
                border-radius: 4px;
            }
        """)
        self.btn_close_task.clicked.connect(self.close_current_task)
        win_nav_layout.addWidget(self.btn_close_task)

        btn_collapse = QPushButton("▼", self.card_frame)
        btn_collapse.setFixedSize(22, 22)
        btn_collapse.setCursor(Qt.PointingHandCursor)
        btn_collapse.setToolTip("收起为迷你胶囊")
        btn_collapse.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #9CA3AF;
                font-size: 11px;
                border: none;
            }
            QPushButton:hover {
                color: #FFFFFF;
            }
        """)
        btn_collapse.clicked.connect(self.toggle_mode)
        win_nav_layout.addWidget(btn_collapse)

        self.card_layout.addLayout(win_nav_layout)

        # 顶部指标栏：单额度圆环 + 纯文字阶段进度详情 (全面移除不准的任务百分比)
        header = QHBoxLayout()
        header.setSpacing(10)

        self.ring_quota = ProgressRing(ring_type="quota", label="Flash(5h)", parent=self.card_frame)
        self.ring_quota.on_click_callback = self.toggle_quota_cycle
        self.ring_quota.setToolTip("点击可切换查看 [5小时额度] 或 [周额度]")
        header.addWidget(self.ring_quota)

        center_info = QVBoxLayout()
        center_info.setSpacing(4)
        title_row = QHBoxLayout()
        self.status_badge = QLabel("• 待命中", self.card_frame)
        self.status_badge.setStyleSheet("color: #38BDF8; font-weight: bold; font-size: 12px; border:none; background: transparent;")
        self.status_badge.setCursor(Qt.PointingHandCursor)
        self.status_badge.mousePressEvent = lambda e: self.focus_antigravity_window()
        self.status_badge.setToolTip("点击置顶激活当前 Antigravity 窗口")

        self.task_title = QLabel("Antigravity", self.card_frame)
        self.task_title.setStyleSheet("color: #F9FAFB; font-weight: bold; font-size: 12px; border:none; background: transparent;")
        self.task_title.setCursor(Qt.PointingHandCursor)
        self.task_title.mousePressEvent = lambda e: self.focus_antigravity_window()
        self.task_title.setToolTip("点击置顶激活当前 Antigravity 窗口")
        title_row.addWidget(self.status_badge)
        title_row.addWidget(self.task_title, 1)

        self.stopwatch_lbl = QLabel("⏱ 00:00", self.card_frame)
        self.stopwatch_lbl.setStyleSheet("color: #38BDF8; font-size: 11px; font-weight: bold; border:none; background: transparent;")
        title_row.addWidget(self.stopwatch_lbl)
        center_info.addLayout(title_row)

        self.step_label = QLabel("等待任务调度...", self.card_frame)
        self.step_label.setStyleSheet("color: #D1D5DB; font-size: 10px; border:none; background: transparent;")
        self.step_label.setWordWrap(True)
        self.step_label.setMaximumHeight(36)
        center_info.addWidget(self.step_label)

        self.quota_refresh_lbl = QLabel("⏱ 刷新倒计时获取中...", self.card_frame)
        self.quota_refresh_lbl.setStyleSheet("color: #6EE7B7; font-size: 9px; border:none; background: transparent;")
        center_info.addWidget(self.quota_refresh_lbl)

        header.addLayout(center_info)
        self.card_layout.addLayout(header)

        # ── 全景四模型精细额度看板 ──
        all_models_box = QVBoxLayout()
        all_models_box.setContentsMargins(0, 1, 0, 3)
        all_models_box.setSpacing(4)

        row1_box = QHBoxLayout()
        row1_box.setSpacing(6)
        self.badge_argon = QLabel("🔴 Argon 4 (周) 2.7%", self.card_frame)
        self.badge_argon.setCursor(Qt.PointingHandCursor)
        self.badge_argon.setStyleSheet("""
            QLabel {
                background-color: rgba(239, 68, 68, 0.15);
                color: #F87171;
                font-size: 10px;
                font-weight: bold;
                padding: 2px 6px;
                border: 1px solid rgba(239, 68, 68, 0.35);
                border-radius: 4px;
            }
            QLabel:hover {
                background-color: rgba(239, 68, 68, 0.3);
            }
        """)
        self.badge_argon.mousePressEvent = lambda e: self.assign_model_to_current_window("Gemini 4 Argon")
        row1_box.addWidget(self.badge_argon)

        self.badge_flash = QLabel("🟢 Flash 3.8 (5h) 95% · 周 90%", self.card_frame)
        self.badge_flash.setCursor(Qt.PointingHandCursor)
        self.badge_flash.setStyleSheet("""
            QLabel {
                background-color: rgba(16, 185, 129, 0.15);
                color: #34D399;
                font-size: 10px;
                font-weight: bold;
                padding: 2px 6px;
                border: 1px solid rgba(16, 185, 129, 0.35);
                border-radius: 4px;
            }
            QLabel:hover {
                background-color: rgba(16, 185, 129, 0.3);
            }
        """)
        self.badge_flash.mousePressEvent = lambda e: self.assign_model_to_current_window("Gemini 3.8 Flash")
        row1_box.addWidget(self.badge_flash)
        row1_box.addStretch()

        row2_box = QHBoxLayout()
        row2_box.setSpacing(6)
        self.badge_opus = QLabel("🟡 Opus 5.5 (5h) 35% · 周 12%", self.card_frame)
        self.badge_opus.setCursor(Qt.PointingHandCursor)
        self.badge_opus.setStyleSheet("""
            QLabel {
                background-color: rgba(245, 158, 11, 0.15);
                color: #FBBF24;
                font-size: 10px;
                font-weight: bold;
                padding: 2px 6px;
                border: 1px solid rgba(245, 158, 11, 0.35);
                border-radius: 4px;
            }
            QLabel:hover {
                background-color: rgba(245, 158, 11, 0.3);
            }
        """)
        self.badge_opus.mousePressEvent = lambda e: self.assign_model_to_current_window("Claude Opus 5.5")
        row2_box.addWidget(self.badge_opus)

        self.badge_sonnet = QLabel("🟡 Sonnet 5.5 (5h) 35%", self.card_frame)
        self.badge_sonnet.setCursor(Qt.PointingHandCursor)
        self.badge_sonnet.setStyleSheet("""
            QLabel {
                background-color: rgba(245, 158, 11, 0.15);
                color: #FBBF24;
                font-size: 10px;
                font-weight: bold;
                padding: 2px 6px;
                border: 1px solid rgba(245, 158, 11, 0.35);
                border-radius: 4px;
            }
            QLabel:hover {
                background-color: rgba(245, 158, 11, 0.3);
            }
        """)
        self.badge_sonnet.mousePressEvent = lambda e: self.assign_model_to_current_window("Claude Sonnet 5.5")
        row2_box.addWidget(self.badge_sonnet)
        row2_box.addStretch()

        all_models_box.addLayout(row1_box)
        all_models_box.addLayout(row2_box)
        self.card_layout.addLayout(all_models_box)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.08); border:none; max-height: 1px;")
        self.card_layout.addWidget(sep)

        list_header = QHBoxLayout()
        self.stage_info_lbl = QLabel("📋 项目阶段进度 (0/0)", self.card_frame)
        self.stage_info_lbl.setStyleSheet("color: #9CA3AF; font-size: 10px; border:none;")
        self.data_source_lbl = QLabel("task.log", self.card_frame)
        self.data_source_lbl.setStyleSheet("color: #6B7280; font-size: 10px; border:none;")
        list_header.addWidget(self.stage_info_lbl)
        list_header.addStretch()
        list_header.addWidget(self.data_source_lbl)
        self.card_layout.addLayout(list_header)

        self.subtasks_container = QVBoxLayout()
        self.subtasks_container.setSpacing(4)
        self.card_layout.addLayout(self.subtasks_container)

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 4, 0, 0)

        self.heartbeat_lbl = QLabel("🟢 探针待命中", self.card_frame)
        self.heartbeat_lbl.setStyleSheet("color: #10B981; font-size: 9px; border:none;")
        footer_layout.addWidget(self.heartbeat_lbl)
        footer_layout.addStretch()

        self.btn_stop = QPushButton("🛑 急停中止", self.card_frame)
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setFixedHeight(22)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background-color: rgba(239, 68, 68, 0.2);
                color: #EF4444;
                border: 1px solid rgba(239, 68, 68, 0.4);
                border-radius: 4px;
                font-size: 10px;
                padding: 0 8px;
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 0.4);
            }
        """)
        self.btn_stop.clicked.connect(self.on_click_stop)
        footer_layout.addWidget(self.btn_stop)

        self.btn_restart = QPushButton("🔄 重新调起", self.card_frame)
        self.btn_restart.setCursor(Qt.PointingHandCursor)
        self.btn_restart.setFixedHeight(22)
        self.btn_restart.setStyleSheet("""
            QPushButton {
                background-color: rgba(56, 189, 248, 0.2);
                color: #38BDF8;
                border: 1px solid rgba(56, 189, 248, 0.4);
                border-radius: 4px;
                font-size: 10px;
                padding: 0 8px;
            }
            QPushButton:hover {
                background-color: rgba(56, 189, 248, 0.4);
            }
        """)
        self.btn_restart.clicked.connect(self.on_click_restart)
        footer_layout.addWidget(self.btn_restart)

        self.card_layout.addLayout(footer_layout)

        self.main_layout.addWidget(self.pill_frame)
        self.main_layout.addWidget(self.card_frame)

    def switch_next_window(self):
        if not self.tasks_list:
            return
        self.current_window_idx = (self.current_window_idx + 1) % len(self.tasks_list)
        self.apply_current_task()

    def switch_prev_window(self):
        if not self.tasks_list:
            return
        self.current_window_idx = (self.current_window_idx - 1 + len(self.tasks_list)) % len(self.tasks_list)
        self.apply_current_task()

    def switch_to_window(self, idx):
        if 0 <= idx < len(self.tasks_list):
            self.current_window_idx = idx
            self.apply_current_task()

    def clean_all_completed_tasks(self):
        """一键清理归档所有已结束或陈旧的任务"""
        clean_stale_tasks_on_disk()
        self.current_window_idx = 0
        self.reload_and_refresh()
        if hasattr(self, 'tray') and self.tray:
            self.tray.showMessage(
                "🧹 任务列表已完成整理",
                "已自动将历史与已完结的任务移入归档，当前窗口列表已刷新！",
                QSystemTrayIcon.Information,
                3000
            )

    def rename_current_task(self):
        if not self.tasks_list:
            return
        cur_task = self.tasks_list[self.current_window_idx]
        old_title = cur_task.get("window_title", "")
        new_title, ok = QInputDialog.getText(
            self, "自定义当前窗口标题/项目名",
            "请输入窗口简称 (例如: 111 或 SP60):",
            QLineEdit.Normal, old_title
        )
        if ok and new_title.strip():
            cur_task["window_title"] = f"窗口 · {new_title.strip()}"
            cur_task["task_name"] = new_title.strip()
            self._write_task_json(cur_task, cur_task.get("_file_path"))
            self.apply_current_task()

    def show_window_menu(self):
        """弹出所有窗口任务直达菜单"""
        if not self.tasks_list:
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(20, 24, 34, 0.98);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 8px;
                padding: 4px;
                color: #E5E7EB;
            }
            QMenu::item {
                padding: 6px 18px 6px 10px;
                border-radius: 4px;
                font-size: 11px;
                margin: 2px 0px;
            }
            QMenu::item:selected {
                background-color: rgba(96, 165, 250, 0.3);
                color: #FFFFFF;
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(255, 255, 255, 0.1);
                margin: 4px 6px;
            }
        """)

        total = len(self.tasks_list)
        for idx, t in enumerate(self.tasks_list):
            status = t.get("status", "idle")
            title = t.get("window_title") or t.get("task_name", f"窗口 {idx+1}")
            m_name = t.get("model_name", "Gemini 3.8 Flash")
            cur_s = t.get("current_step", 1)
            tot_s = t.get("total_steps", 1)

            q_info = resolve_model_quota(m_name, self.raw_quotas, self.preferred_cycle)
            spec_str = f"{q_info['ring_tag']} {q_info['custom_pct_str']}"

            dot = "🔵" if status == "running" else ("🔴" if status == "blocked" else ("🟢" if status == "completed" else "⚪"))
            prefix = "✓ " if idx == self.current_window_idx else "    "

            has_plan = t.get("has_stage_plan", False)
            step_tag = f"阶段 [{cur_s}/{tot_s}]" if (has_plan and tot_s > 1) else ("进行中" if status == "running" else ("已完成" if status == "completed" else "待命"))
            action_text = f"{prefix}[W{idx+1}/{total}] {dot} {title[:14]} ({step_tag} | {spec_str})"
            action = menu.addAction(action_text)
            action.triggered.connect(lambda checked=False, i=idx: self.switch_to_window(i))

        menu.addSeparator()
        act_cycle = menu.addAction(f"⏱ 切换额度周期显示 (当前: {self.preferred_cycle})")
        act_cycle.triggered.connect(self.toggle_quota_cycle)

        act_rename = menu.addAction("🏷 自定义当前窗口简称 (如: 111)...")
        act_rename.triggered.connect(self.rename_current_task)

        act_clean = menu.addAction("🧹 一键清理已结束/非活跃任务")
        act_clean.triggered.connect(self.clean_all_completed_tasks)

        act_focus = menu.addAction("↗ 聚焦唤醒当前 Antigravity 窗口")
        act_focus.triggered.connect(self.focus_antigravity_window)

        act_stealth = menu.addAction(f"🕶 全屏智能隐身免打扰 (当前: {'开启' if self.stealth_enabled else '关闭'})")
        act_stealth.triggered.connect(self.toggle_stealth)

        act_close = menu.addAction("✕ 移除/归档当前窗口任务监控")
        act_close.triggered.connect(self.close_current_task)

        pos = self.btn_menu_win.mapToGlobal(QPoint(0, self.btn_menu_win.height() + 4))
        menu.exec(pos)

    def focus_antigravity_window(self):
        """唤醒并置顶当前任务对应的 Antigravity 窗口"""
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            cur_task = self.tasks_list[self.current_window_idx] if self.tasks_list else {}
            win_title = cur_task.get("window_title", "")
            task_name = cur_task.get("task_name", "")

            matched_hwnds = []
            all_ag_hwnds = []

            def enum_cb(hwnd, lparam):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value

                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    hProcess = kernel32.OpenProcess(0x1000, False, pid.value)
                    exe_name = ""
                    if hProcess:
                        size = wintypes.DWORD(512)
                        pbuf = ctypes.create_unicode_buffer(512)
                        if kernel32.QueryFullProcessImageNameW(hProcess, 0, pbuf, ctypes.byref(size)):
                            exe_name = os.path.basename(pbuf.value).lower()
                        kernel32.CloseHandle(hProcess)

                    if "antigravity" in exe_name or "antigravity" in title.lower():
                        all_ag_hwnds.append((hwnd, title))
                        kws = [w for w in [win_title, task_name] if w]
                        for kw in kws:
                            subkws = [k for k in kw.replace("·", " ").replace("(", " ").replace(")", " ").split() if len(k) >= 2]
                            if any(sk.lower() in title.lower() for sk in subkws):
                                matched_hwnds.append((hwnd, title))
                                break
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

            target_hwnd = None
            if matched_hwnds:
                target_hwnd = matched_hwnds[0][0]
            elif all_ag_hwnds:
                target_hwnd = all_ag_hwnds[0][0]

            if target_hwnd:
                SW_RESTORE = 9
                SW_SHOW = 5
                # 如果处于最小化 (Iconic) 状态，必须调用 SW_RESTORE 召回主界面
                if user32.IsIconic(target_hwnd):
                    user32.ShowWindow(target_hwnd, SW_RESTORE)
                else:
                    user32.ShowWindow(target_hwnd, SW_SHOW)
                cur_thread = kernel32.GetCurrentThreadId()
                fore_hwnd = user32.GetForegroundWindow()
                fore_thread = user32.GetWindowThreadProcessId(fore_hwnd, None)
                if cur_thread != fore_thread:
                    user32.AttachThreadInput(cur_thread, fore_thread, True)
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x12, 0, 2, 0)
                user32.BringWindowToTop(target_hwnd)
                user32.SetForegroundWindow(target_hwnd)
                user32.SetFocus(target_hwnd)
                if cur_thread != fore_thread:
                    user32.AttachThreadInput(cur_thread, fore_thread, False)
                log(f"已唤醒置顶 Antigravity 窗口: {target_hwnd}")
            else:
                ag_exe = os.path.expandvars(r"%LOCALAPPDATA%\Programs\antigravity\Antigravity.exe")
                if os.path.exists(ag_exe):
                    os.startfile(ag_exe)
                    log("调用 startfile 激活 Antigravity 进程")
        except Exception as e:
            log(f"聚焦置顶 Antigravity 窗口异常: {e}")

    def close_current_task(self):
        """移除/归档当前窗口任务监控记录"""
        if not self.tasks_list:
            return
        cur_task = self.tasks_list[self.current_window_idx]
        task_file = cur_task.get("_file_path")
        task_name = cur_task.get("task_name", "任务")

        archive_dir = os.path.join(TASKS_DIR, ".archive")
        os.makedirs(archive_dir, exist_ok=True)

        if task_file and os.path.exists(task_file):
            try:
                if os.path.abspath(task_file) == os.path.abspath(GLOBAL_STATUS_PATH):
                    cur_task["status"] = "idle"
                    cur_task["task_name"] = "Antigravity 待命"
                    cur_task["window_title"] = "待命窗口"
                    cur_task["current_step_name"] = "任务已由用户归档清理"
                    cur_task["progress_pct"] = 0
                    cur_task["subtasks"] = []
                    self._write_task_json(cur_task, task_file)
                elif task_file.endswith(".json"):
                    fname = os.path.basename(task_file)
                    target_dest = os.path.join(archive_dir, f"{int(time.time())}_{fname}")
                    shutil.move(task_file, target_dest)
            except Exception as e:
                log(f"归档任务文件异常: {e}")

        log(f"已归档移除任务记录: {task_name}")
        self.current_window_idx = max(0, self.current_window_idx - 1)
        self.reload_and_refresh()

    def ensure_visible_on_screen(self):
        """确保悬浮窗坐标绝不跑出显示器可视范围"""
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if not screen:
            return
        geom = screen.availableGeometry()
        x = max(geom.x() + 4, min(self.x(), geom.right() - self.width() - 4))
        y = max(geom.y() + 4, min(self.y(), geom.bottom() - self.height() - 4))
        if x != self.x() or y != self.y():
            self.move(x, y)

    def toggle_stealth(self):
        self.stealth_enabled = not self.stealth_enabled
        if hasattr(self, 'stealth_action'):
            self.stealth_action.setChecked(self.stealth_enabled)
        if not self.stealth_enabled and self.is_stealthed:
            self.exit_stealth()

    def check_fullscreen_stealth(self):
        """检测前台应用是否为全屏独占状态 (游戏/全屏视频/PPT)，智能淡出免打扰"""
        if not self.stealth_enabled:
            return
        try:
            user32 = ctypes.windll.user32
            fore_hwnd = user32.GetForegroundWindow()
            if not fore_hwnd:
                return

            my_hwnd = int(self.winId())
            if fore_hwnd == my_hwnd:
                if self.is_stealthed:
                    self.exit_stealth()
                return

            cbuf = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(fore_hwnd, cbuf, 128)
            cname = cbuf.value
            if cname in ["Progman", "WorkerW", "Shell_TrayWnd", "NotifyIconOverflowWindow"]:
                if self.is_stealthed:
                    self.exit_stealth()
                return

            f_rect = wintypes.RECT()
            user32.GetWindowRect(fore_hwnd, ctypes.byref(f_rect))

            hMon = user32.MonitorFromWindow(fore_hwnd, 2)
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)
                ]
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(hMon, ctypes.byref(mi))
            m = mi.rcMonitor

            is_fs = (f_rect.left <= m.left and f_rect.top <= m.top and
                     f_rect.right >= m.right and f_rect.bottom >= m.bottom)

            if is_fs:
                if not self.is_stealthed:
                    self.enter_stealth()
            else:
                if self.is_stealthed:
                    self.exit_stealth()
        except Exception:
            pass

    def enter_stealth(self):
        self.is_stealthed = True
        self.fade_to(0.0)

    def exit_stealth(self):
        self.is_stealthed = False
        self.fade_to(0.85)

    def notify_completion(self, data):
        win_title = data.get("window_title", "Antigravity")
        task_name = data.get("task_name", "任务")
        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass
        if hasattr(self, 'tray') and self.tray:
            self.tray.showMessage(
                "🎉 任务已 100% 顺利交付！",
                f"【{win_title}】\n{task_name}\n所有阶段已全部达成，点击可查看聚焦窗口。",
                QSystemTrayIcon.Information,
                5000
            )

    def notify_blocked(self, data):
        win_title = data.get("window_title", "Antigravity")
        task_name = data.get("task_name", "任务")
        step = data.get("current_step_name", "任务异常阻断")
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass
        if hasattr(self, 'tray') and self.tray:
            self.tray.showMessage(
                "🛑 任务异常阻断警报！",
                f"【{win_title}】\n{task_name}\n状态：{step}",
                QSystemTrayIcon.Warning,
                6000
            )

    def on_click_stop(self):
        if self.tasks_list and self.current_window_idx < len(self.tasks_list):
            cur_task = self.tasks_list[self.current_window_idx]
            tid = self._task_id(cur_task)
            self.manual_status[tid] = "blocked"
            cur_task["status"] = "blocked"
            cur_task["current_step_name"] = "已由用户手动急停中止"
            self._write_task_json(cur_task, cur_task.get("_file_path"))
            self.apply_current_task()

    def on_click_restart(self):
        if self.tasks_list and self.current_window_idx < len(self.tasks_list):
            cur_task = self.tasks_list[self.current_window_idx]
            tid = self._task_id(cur_task)
            self.manual_status[tid] = "running"
            cur_task["status"] = "running"
            cur_task["current_step_name"] = "用户手动触发重新调起执行"
            self._write_task_json(cur_task, cur_task.get("_file_path"))
            self.apply_current_task()

    def on_second_tick(self):
        self.check_fullscreen_stealth()

        cur_tid = None
        if self.tasks_list and self.current_window_idx < len(self.tasks_list):
            cur_tid = self._task_id(self.tasks_list[self.current_window_idx])

        if self.current_status == "running" and cur_tid:
            if cur_tid not in self.task_start_times:
                self.task_start_times[cur_tid] = time.time()
            self.elapsed_sec = int(time.time() - self.task_start_times[cur_tid])
            self.task_elapsed_secs[cur_tid] = self.elapsed_sec
            m, s = divmod(self.elapsed_sec, 60)
            time_str = f"⏱ {m:02d}:{s:02d}"
            self.stopwatch_lbl.setText(time_str)
            self.pill_timer_lbl.setText(time_str)
            self.check_heartbeat()
        elif self.current_status == "completed" and cur_tid:
            sec = self.task_elapsed_secs.get(cur_tid, self.elapsed_sec)
            m, s = divmod(sec, 60)
            self.stopwatch_lbl.setText(f"⏱ 总耗时 {m:02d}:{s:02d}")
            self.pill_timer_lbl.setText(f"⏱ {m:02d}:{s:02d}")
        else:
            self.stopwatch_lbl.setText("⏱ 00:00")
            self.pill_timer_lbl.setText("⏱ 00:00")

        if self.is_pill_mode:
            self.pill_frame.update()

    def toggle_mode(self):
        old_right = self.x() + self.width()
        old_bottom = self.y() + self.height()
        old_y = self.y()
        self.is_pill_mode = not self.is_pill_mode
        self.update_view_mode()

        # 核心：确保展开与缩小收起时右侧边缘严格平行对齐 (Right Edge Anchored)
        new_width = self.width()
        new_x = old_right - new_width

        # 智能垂直对齐：若位于屏幕下半区，保持底侧平行向上展开；若位于上半区，保持顶侧向下展开
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geom = screen.availableGeometry() if screen else None

        if geom and old_bottom > (geom.y() + geom.height() / 2):
            new_y = old_bottom - self.height()
        else:
            new_y = old_y

        self.move(new_x, new_y)
        self.ensure_visible_on_screen()

    def _sync_pill_size(self):
        if not self.is_pill_mode:
            return
        old_right = self.x() + self.width()
        self.pill_frame.setMinimumSize(260, 34)
        self.pill_frame.setMaximumSize(480, 34)
        self.pill_frame.adjustSize()
        w = max(260, min(480, self.pill_frame.sizeHint().width() + 4))
        self.pill_frame.setFixedSize(w, 34)
        self.setFixedSize(w, 34)
        if self.isVisible() and old_right > 0:
            self.move(old_right - w, self.y())

    def update_view_mode(self):
        if self.is_pill_mode:
            self.card_frame.hide()
            self.pill_frame.show()
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self._sync_pill_size()
            apply_acrylic_effect(int(self.winId()), enable_acrylic=False)
            self.pill_frame.update()
        else:
            self.pill_frame.hide()
            self.card_frame.show()
            self.setMinimumSize(440, 240)
            self.setMaximumSize(440, 650)
            self.setFixedWidth(440)
            self.adjustSize()
            apply_acrylic_effect(int(self.winId()), enable_acrylic=True)
            self.card_frame.update()

    def reposition_to_bottom_right(self):
        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos)
        if not screen:
            screen = QGuiApplication.primaryScreen()

        geom = screen.availableGeometry()
        x = geom.x() + geom.width() - self.width() - 16
        y = geom.y() + geom.height() - self.height() - 16
        self.move(x, y)

    def refresh_live_quotas(self):
        if hasattr(self, "worker"):
            self.worker.trigger_now(with_quota=True)

    def reload_and_refresh(self):
        if hasattr(self, "worker"):
            self.worker.trigger_now(with_quota=False)

    def on_quotas_updated(self, raw):
        if raw:
            self.raw_quotas = raw
            self.apply_current_task()

    def on_tasks_updated(self, all_tasks):
        for t in all_tasks:
            tid = self._task_id(t)
            if tid in self.manual_models:
                t["model_name"] = self.manual_models[tid]
            if tid in self.manual_status and t.get("_file_path") is None:
                t["status"] = self.manual_status[tid]

            cur_st = t.get("status", "idle")
            if cur_st == "running" and tid not in self.task_start_times:
                self.task_start_times[tid] = time.time()
            elif cur_st == "completed" and tid in self.task_start_times and tid not in self.task_elapsed_secs:
                self.task_elapsed_secs[tid] = int(time.time() - self.task_start_times[tid])

            old_st = self.last_task_status.get(tid)
            if old_st is not None and old_st != cur_st:
                if cur_st == "completed":
                    self.notify_completion(t)
                elif cur_st == "blocked":
                    self.notify_blocked(t)
            self.last_task_status[tid] = cur_st

        self.tasks_list = all_tasks
        if self.current_window_idx >= len(self.tasks_list):
            self.current_window_idx = max(0, len(self.tasks_list) - 1)
        self.apply_current_task()

    def _style_model_badge(self, badge, pct, label_text, tooltip, is_active=False):
        if pct <= 15:
            dot = "🔴"
            bg, fg, border = "rgba(239, 68, 68, 0.16)", "#F87171", "rgba(239, 68, 68, 0.40)"
            hover_bg = "rgba(239, 68, 68, 0.30)"
        elif pct <= 40:
            dot = "🟡"
            bg, fg, border = "rgba(245, 158, 11, 0.16)", "#FBBF24", "rgba(245, 158, 11, 0.40)"
            hover_bg = "rgba(245, 158, 11, 0.30)"
        else:
            dot = "🟢"
            bg, fg, border = "rgba(16, 185, 129, 0.16)", "#34D399", "rgba(16, 185, 129, 0.40)"
            hover_bg = "rgba(16, 185, 129, 0.30)"

        if is_active:
            border = "#38BDF8"
            border_w = "1.5px"
        else:
            border_w = "1px"

        badge.setText(f"{dot} {label_text}")
        badge.setToolTip(tooltip)
        badge.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                font-size: 10px;
                font-weight: bold;
                padding: 2px 6px;
                border: {border_w} solid {border};
                border-radius: 4px;
            }}
            QLabel:hover {{
                background-color: {hover_bg};
            }}
        """)

    def apply_current_task(self):
        if not self.tasks_list:
            return
        data = self.tasks_list[self.current_window_idx]
        total_wins = len(self.tasks_list)
        cur_win_num = self.current_window_idx + 1
        has_stage_plan = data.get("has_stage_plan", False)
        step_count = data.get("step_count", 0)

        task_name = data.get("task_name", "Antigravity")
        window_title = data.get("window_title", f"窗口 {cur_win_num}/{total_wins}")
        total_steps = data.get("total_steps", 1)
        current_step = data.get("current_step", 1)
        step_name = data.get("current_step_name", "")
        progress_pct = data.get("progress_pct", 0)
        status = data.get("status", "idle")
        data_source = data.get("data_source", "task.log")
        subtasks = data.get("subtasks", [])
        
        self.model_name = data.get("model_name", "Gemini 3.8 Flash")

        # 核心：精准联动当前窗口模型的额度
        q_info = resolve_model_quota(self.model_name, self.raw_quotas, self.preferred_cycle)
        self.quota_pct = q_info["active_pct"]
        custom_pct_str = q_info["custom_pct_str"]
        ring_tag = q_info["ring_tag"]
        self.quota_refresh_desc = q_info["desc"]

        self.current_status = status
        self.current_pct = progress_pct

        # 1. 胶囊态独立同步
        self.pill_win_badge.setText(f"W{cur_win_num}")
        quota_color = "#EF4444" if self.quota_pct <= 15 else ("#F59E0B" if self.quota_pct <= 40 else "#10B981")
        self.pill_quota_badge.setStyleSheet(f"color: {quota_color}; font-size: 10px; font-weight: bold; border:none; background: transparent;")
        self.pill_quota_badge.setText(f"✦ {custom_pct_str} {ring_tag}")

        show_stage_ratio = has_stage_plan and total_steps > 1
        if status == "running":
            self.pill_dot.setText("🔵")
            self.pill_task_badge.setText(f"[{current_step}/{total_steps}]" if show_stage_ratio else "进行中")
            self.btn_stop.setVisible(True)
            self.btn_restart.setVisible(False)
        elif status == "completed":
            self.pill_dot.setText("🟢")
            self.pill_task_badge.setText(f"[{total_steps}/{total_steps}] 达成" if show_stage_ratio else "已完成")
            self.btn_stop.setVisible(False)
            self.btn_restart.setVisible(True)
        elif status == "blocked":
            self.pill_dot.setText("🔴")
            self.pill_task_badge.setText(f"[{current_step}/{total_steps}] 阻断" if show_stage_ratio else "熔断")
            self.btn_stop.setVisible(False)
            self.btn_restart.setVisible(True)
        else:
            self.pill_dot.setText("⚪")
            self.pill_task_badge.setText("待命")
            self.btn_stop.setVisible(False)
            self.btn_restart.setVisible(False)

        # 2. 大卡片态同步
        win_display_title = (data.get("window_title") or f"窗口 {cur_win_num}")
        if "·" not in win_display_title and not win_display_title.startswith("窗口"):
            win_display_title = f"窗口 · {win_display_title}"
        if len(win_display_title) > 16:
            win_display_title = win_display_title[:15] + ".."
        self.win_nav_lbl.setText(f"{win_display_title}  ({cur_win_num}/{total_wins})")

        self.ring_quota.label_text = ring_tag
        self.ring_quota.set_value(self.quota_pct, status, custom_pct_str)

        self.quota_refresh_lbl.setText(f"⏱ {q_info['short_name']} | {self.quota_refresh_desc}")
        if self.quota_pct <= 15:
            self.quota_refresh_lbl.setStyleSheet("color: #F87171; font-size: 9px; font-weight: bold; border:none;")
        else:
            self.quota_refresh_lbl.setStyleSheet("color: #6EE7B7; font-size: 9px; border:none;")

        h5_str = f"{q_info['h5_pct']}% ({q_info['h5_reset']})" if q_info['h5_pct'] is not None else "无"
        wk_str = f"{q_info['wk_pct']}% ({q_info['wk_reset']})" if q_info['wk_pct'] is not None else "无"
        self.ring_quota.setToolTip(
            f"【{q_info['full_name']}】\n"
            f"• 5小时额度: {h5_str}\n"
            f"• 周额度: {wk_str}\n"
            f"• 当前显示: {q_info['cycle']}额度\n"
            f"💡 点击圆环可直接切换查看 [5小时] 或 [周] 额度"
        )
        self.pill_quota_badge.setToolTip(f"{q_info['full_name']}: {custom_pct_str} · {self.quota_refresh_desc}")

        # 3. 底部全景四模型看板更新 (动态配色 + 高亮当前模型 + 补全周额度)
        if hasattr(self, 'badge_argon') and self.raw_quotas:
            arg = resolve_model_quota("Gemini 4 Argon", self.raw_quotas)
            fls = resolve_model_quota("Gemini 3.8 Flash", self.raw_quotas)
            opu = resolve_model_quota("Claude Opus 5.5", self.raw_quotas)
            son = resolve_model_quota("Claude Sonnet 5.5", self.raw_quotas)
            cur_short = q_info["short_name"]

            self._style_model_badge(
                self.badge_argon,
                arg["active_pct"],
                f"Argon 4 (周) {arg['custom_pct_str']}",
                f"【{arg['full_name']}】\n• 当前周额度: {arg['active_pct']}%\n• 刷新时间: {arg['wk_reset']}\n• 点击绑定至本窗口",
                is_active=(cur_short == "Argon 4")
            )
            self._style_model_badge(
                self.badge_flash,
                float(fls["h5_pct"] or 0),
                f"Flash 3.8 (5h) {int(fls['h5_pct'] or 0)}% · 周 {int(fls['wk_pct'] or 0)}%",
                f"【{fls['full_name']}】\n• 5小时: {fls['h5_pct']}% ({fls['h5_reset']})\n• 周: {fls['wk_pct']}% ({fls['wk_reset']})\n• 点击绑定至本窗口",
                is_active=(cur_short in ("Flash 3.8", "Hydrogen 4", "Pro 2.5"))
            )
            self._style_model_badge(
                self.badge_opus,
                float(opu["h5_pct"] or 0),
                f"Opus 5.5 (5h) {int(opu['h5_pct'] or 0)}% · 周 {int(opu['wk_pct'] or 0)}%",
                f"【{opu['full_name']}】\n• 5小时: {opu['h5_pct']}% ({opu['h5_reset']})\n• 周: {opu['wk_pct']}% ({opu['wk_reset']})\n• 点击绑定至本窗口",
                is_active=(cur_short == "Opus 5.5")
            )
            self._style_model_badge(
                self.badge_sonnet,
                float(son["h5_pct"] or 0),
                f"Sonnet 5.5 (5h) {int(son['h5_pct'] or 0)}% · 周 {int(son['wk_pct'] or 0)}%",
                f"【{son['full_name']}】\n• 5小时: {son['h5_pct']}% ({son['h5_reset']})\n• 周: {son['wk_pct']}% ({son['wk_reset']})\n• 点击绑定至本窗口",
                is_active=(cur_short == "Sonnet 5.5")
            )

        raw_task_title = data.get("detailed_task_name") or task_name
        elided_title = QFontMetrics(self.task_title.font()).elidedText(raw_task_title, Qt.ElideRight, 195)
        self.task_title.setText(elided_title)
        self.task_title.setToolTip(raw_task_title)

        step_disp = step_name if step_name else f"当前模型: {q_info['full_name']}"
        if len(step_disp) > 90:
            step_disp = step_disp[:88] + "…"
        self.step_label.setText(step_disp)
        self.step_label.setToolTip(step_name if step_name else "")

        if status == "running":
            self.status_badge.setText("• 进行中")
            self.status_badge.setStyleSheet("color: #38BDF8; font-weight: bold; font-size: 12px; border:none; background: transparent;")
        elif status == "completed":
            self.status_badge.setText("• 已完成")
            self.status_badge.setStyleSheet("color: #10B981; font-weight: bold; font-size: 12px; border:none; background: transparent;")
        elif status == "blocked":
            self.status_badge.setText("• 熔断阻断")
            self.status_badge.setStyleSheet("color: #EF4444; font-weight: bold; font-size: 12px; border:none; background: transparent;")
        else:
            self.status_badge.setText("• 待命中")
            self.status_badge.setStyleSheet("color: #9CA3AF; font-weight: bold; font-size: 12px; border:none; background: transparent;")

        if show_stage_ratio:
            self.stage_info_lbl.setText(f"📋 任务阶段 ({current_step}/{total_steps})")
        elif step_count > 0:
            self.stage_info_lbl.setText(f"📋 会话活动 · 共 {step_count} 步")
        else:
            self.stage_info_lbl.setText("📋 任务清单")
        self.data_source_lbl.setText(data_source[:18])

        subtasks_key = json.dumps(subtasks)
        if getattr(self, "_cached_subtasks_key", None) != subtasks_key:
            self._cached_subtasks_key = subtasks_key
            while self.subtasks_container.count():
                item = self.subtasks_container.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()

            for sub in subtasks:
                sub_title = sub.get("title", "")
                sub_status = sub.get("status", "pending")

                row = QWidget(self.card_frame)
                row.setFixedHeight(22)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(2, 0, 2, 0)
                row_layout.setSpacing(6)

                if sub_status == "done":
                    icon = "✔"
                    color = "#10B981"
                    desc = "已达成"
                elif sub_status == "running":
                    icon = "∿"
                    color = "#38BDF8"
                    desc = "执行中"
                else:
                    icon = "🕒"
                    color = "#9CA3AF"
                    desc = "未开始"

                title_lbl = QLabel(f"{icon} {sub_title[:30]}", row)
                title_lbl.setStyleSheet(f"color: {color}; font-size: 11px; border:none; background: transparent;")
                state_lbl = QLabel(f"{desc}", row)
                state_lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold; border:none; background: transparent;")

                row_layout.addWidget(title_lbl, 1)
                row_layout.addWidget(state_lbl)
                self.subtasks_container.addWidget(row)

        self.check_heartbeat()
        if not self.is_pill_mode:
            self.adjustSize()
        else:
            self._sync_pill_size()
            self.pill_frame.update()
        self.update()

    def check_heartbeat(self):
        if not self.tasks_list or self.current_window_idx >= len(self.tasks_list):
            return
        cur_task = self.tasks_list[self.current_window_idx]
        cur_file = cur_task.get("_file_path")
        mtime = cur_task.get("_mtime")
        if cur_file and os.path.exists(cur_file):
            diff = int(time.time() - os.path.getmtime(cur_file))
        elif mtime:
            diff = int(time.time() - mtime)
        else:
            diff = 0

        if self.current_status == "completed":
            text = "✔ 任务流程已圆满完成"
            color = "#10B981"
        elif self.current_status == "blocked":
            text = "🛑 任务已触发熔断保护 (已暂停)"
            color = "#EF4444"
        elif self.current_status == "running":
            if diff < 15:
                text = "💓 探针状态: 正常 (刚刚更新)"
                color = "#10B981"
            elif diff < 90:
                text = f"💓 探针状态: 活跃 ({diff}秒前心跳)"
                color = "#38BDF8"
            else:
                text = f"⚠️ 探针告警: 已有 {diff}秒未刷新 (疑似卡死)"
                color = "#EF4444"
        else:
            text = "🟢 探针待命中 · 0% CPU 占用"
            color = "#10B981"

        self.heartbeat_lbl.setText(text)
        self.heartbeat_lbl.setStyleSheet(f"color: {color}; font-size: 9px; border:none;")

    def on_pill_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_global = event.globalPosition().toPoint()
            self.drag_start_pos = self.pos()
            self.is_drag_moved = False
            event.accept()

    def on_pill_mouse_move(self, event):
        if event.buttons() & Qt.LeftButton and hasattr(self, 'drag_start_global'):
            delta = event.globalPosition().toPoint() - self.drag_start_global
            if delta.manhattanLength() > 4:
                self.is_drag_moved = True
                self.move(self.drag_start_pos + delta)
            event.accept()

    def on_pill_mouse_release(self, event):
        if event.button() == Qt.LeftButton:
            if not getattr(self, 'is_drag_moved', False):
                # 原地单击胶囊（未拖拽）-> 展开为完整大卡片
                self.toggle_mode()
            else:
                self.ensure_visible_on_screen()
            self.is_drag_moved = False
            event.accept()

    def on_badge_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_global = event.globalPosition().toPoint()
            self.drag_start_pos = self.pos()
            self.is_drag_moved = False
            event.accept()

    def on_badge_mouse_release(self, event):
        if event.button() == Qt.LeftButton:
            if not getattr(self, 'is_drag_moved', False):
                # 原地单击 [W1] -> 切换到下一窗口
                self.switch_next_window()
            else:
                self.ensure_visible_on_screen()
            self.is_drag_moved = False
            event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_global = event.globalPosition().toPoint()
            self.drag_start_pos = self.pos()
            self.is_drag_moved = False
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and hasattr(self, 'drag_start_global'):
            delta = event.globalPosition().toPoint() - self.drag_start_global
            if delta.manhattanLength() > 4:
                self.is_drag_moved = True
                self.move(self.drag_start_pos + delta)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_drag_moved = False
            self.ensure_visible_on_screen()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        self.focus_antigravity_window()
        event.accept()


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        monitor = MultiWindowMonitor()
        app.aboutToQuit.connect(lambda: (monitor.worker.stop(), monitor.worker.wait(1000)))
        monitor.show()
        sys.exit(app.exec())
    except Exception as e:
        log(f"崩溃异常: {traceback.format_exc()}")

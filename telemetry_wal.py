# -*- coding: utf-8 -*-
"""
Antigravity 本地 SQLite WAL 只读遥测引擎
借鉴 STARKTANG108/antigravity-token-monitor 的零依赖 WAL 解析与 mtime_ns 增量缓存方案：
- 严格以 ?mode=ro 只读 URI 模式读取 ~/.gemini/antigravity/conversations/*.db
- 追踪 .db 与 .db-wal 的 (mtime_ns, size) 指纹，未变更会话 <1ms 跳过
- 输出单窗口 Token/API 价值、今日汇总、近 7 天汇总与 15 分钟实时速率
"""
import datetime
import glob
import os
import sqlite3
import threading
import time

CONVERSATIONS_DIR = os.path.expanduser(r"~\.gemini\antigravity\conversations")

ENUM_TO_NAME = {
    1318: "Gemini 3.8 Flash (High)",
    1319: "Gemini 3.8 Flash (Medium)",
    1320: "Gemini 3.8 Flash (Low)",
    1322: "Gemini 3.8 Flash Tiered",
    1401: "Claude Opus 5.5 (Medium)",
    1402: "Claude Opus 5.5 (High)",
    1403: "Claude Opus 5.5 (Low)",
    1404: "Claude Sonnet 5.5 (Medium)",
    1405: "Claude Sonnet 5.5 (High)",
    1417: "Gemini 4 Argon (High)",
    1418: "Gemini 4 Argon (Medium)",
    1419: "Gemini 4 Argon (Low)",
    1427: "Gemini 4 Carbon (High)",
    1428: "Gemini 4 Carbon (Medium)",
    1525: "Gemini 4 Hydrogen (High)",
    1526: "Gemini 4 Hydrogen (Medium)",
    1528: "Gemini 4 Hydrogen (XHigh)",
}

# 每百万 Token 费率 ($ USD): (promo_in, promo_cache, promo_out)
PRICING_PROMO = {
    "opus":     (4.00, 0.20, 20.00),
    "sonnet":   (3.00, 0.30, 15.00),
    "flash":    (0.75, 0.075, 3.75),
    "argon":    (2.00, 0.10, 10.00),
    "carbon":   (2.00, 0.10, 10.00),
    "hydrogen": (2.00, 0.10, 10.00),
}
IMAGE_GEN_UNIT_COST = 0.04


def _parse_varint(data, i):
    val = 0
    shift = 0
    n = len(data)
    while i < n:
        b = data[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return val, i


def _parse_proto_dict(data):
    i = 0
    n = len(data)
    res = {}
    while i < n:
        tag, i = _parse_varint(data, i)
        fn = tag >> 3
        wt = tag & 7
        if wt == 0:
            val, i = _parse_varint(data, i)
        elif wt == 1:
            val = data[i:i + 8]
            i += 8
        elif wt == 2:
            ln, i = _parse_varint(data, i)
            val = data[i:i + ln]
            i += ln
        elif wt == 5:
            val = data[i:i + 4]
            i += 4
        else:
            break
        res.setdefault(fn, []).append(val)
    return res


def _get_promo_rates(model_name, model_id=""):
    low = f"{model_name} {model_id}".lower()
    for key, rates in PRICING_PROMO.items():
        if key in low:
            return rates
    return (2.00, 0.10, 10.00)


def format_tokens(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


class TelemetryReader:
    """线程安全的只读 SQLite WAL Token & API 价值统计器"""

    def __init__(self, usd_to_cny=7.20):
        self._lock = threading.Lock()
        self._db_cache = {}  # db_path -> (sig, records, img_events)
        self.usd_to_cny = usd_to_cny

    @staticmethod
    def _file_sig(path):
        try:
            st = os.stat(path)
            s1 = (st.st_mtime_ns, st.st_size)
        except OSError:
            s1 = (0, 0)
        try:
            st2 = os.stat(path + "-wal")
            s2 = (st2.st_mtime_ns, st2.st_size)
        except OSError:
            s2 = (0, 0)
        return (s1, s2)

    @staticmethod
    def _parse_single_db(db_path):
        cid = os.path.basename(db_path)[:-3]
        records = []
        img_events = []
        con = None
        try:
            uri_path = db_path.replace("\\", "/")
            con = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True, timeout=1.2)
            cur = con.cursor()
            step_map = {}
            step_idx_ts = {}
            cur.execute("SELECT idx, step_type, metadata FROM steps WHERE metadata IS NOT NULL")
            for idx, st, meta in cur.fetchall():
                d = _parse_proto_dict(meta)
                ts = _parse_proto_dict(d[1][0]).get(1, [0])[0] if 1 in d else 0
                step_idx_ts[idx] = ts
                if 4 in d:
                    t4 = _parse_proto_dict(d[4][0])
                    tname = t4.get(2, [b""])[0].decode(errors="ignore")
                    if tname == "generate_image":
                        img_events.append((ts, cid))
                if 9 in d:
                    u9 = _parse_proto_dict(d[9][0])
                    bot_id = u9[7][0].decode(errors="ignore") if 7 in u9 else f"step_{idx}"
                    step_map[bot_id] = (ts, idx, st, u9)

            cur.execute("SELECT idx, data FROM gen_metadata")
            seen_bots = set()
            for gidx, blob in cur.fetchall():
                d = _parse_proto_dict(blob)
                if 1 not in d:
                    continue
                m1 = _parse_proto_dict(d[1][0])
                u4 = _parse_proto_dict(m1[4][0]) if 4 in m1 else {}
                bot_id = u4[7][0].decode(errors="ignore") if 7 in u4 else f"gen_{gidx}"
                seen_bots.add(bot_id)
                me = m1.get(3, [0])[0] or u4.get(1, [0])[0]
                mid = m1[19][0].decode(errors="ignore") if 19 in m1 else ""
                mn = m1[21][0].decode(errors="ignore") if 21 in m1 else ""
                kv = {}
                for item in m1.get(20, []):
                    kvd = _parse_proto_dict(item)
                    if 1 in kvd and 2 in kvd:
                        kv[kvd[1][0].decode(errors="ignore")] = kvd[2][0].decode(errors="ignore")
                if bot_id in step_map:
                    ts = step_map[bot_id][0]
                else:
                    last_sidx = int(kv.get("last_step_index", -1))
                    ts = step_idx_ts.get(last_sidx, step_idx_ts.get(last_sidx + 1, 0))
                inp = u4.get(2, [0])[0]
                out = u4.get(3, [0])[0]
                cache = u4.get(5, [0])[0]
                think = u4.get(9, [0])[0]
                mname = ENUM_TO_NAME.get(me) or mn or mid or f"Unknown({me})"
                records.append((ts, cid, mid, mname, inp, cache, out, think))

            for bot_id, (ts, sidx, st, u9) in step_map.items():
                if bot_id not in seen_bots:
                    me = u9.get(1, [0])[0]
                    inp = u9.get(2, [0])[0]
                    out = u9.get(3, [0])[0]
                    cache = u9.get(5, [0])[0]
                    think = u9.get(9, [0])[0]
                    mname = ENUM_TO_NAME.get(me) or f"Unknown({me})"
                    records.append((ts, cid, "", mname, inp, cache, out, think))
        except Exception:
            pass
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
        return records, img_events

    def get_summary(self):
        t0 = time.perf_counter()
        if not os.path.exists(CONVERSATIONS_DIR):
            return {}

        with self._lock:
            db_paths = glob.glob(os.path.join(CONVERSATIONS_DIR, "*.db"))
            current_set = set(db_paths)
            for stale in [k for k in self._db_cache if k not in current_set]:
                del self._db_cache[stale]

            all_records = []
            all_imgs = []
            for p in db_paths:
                sig = self._file_sig(p)
                cached = self._db_cache.get(p)
                if cached is not None and cached[0] == sig:
                    recs, imgs = cached[1], cached[2]
                else:
                    recs, imgs = self._parse_single_db(p)
                    self._db_cache[p] = (sig, recs, imgs)
                all_records.extend(recs)
                all_imgs.extend(imgs)

        now_ts = time.time()
        local_now = datetime.datetime.now()
        today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        week_start = now_ts - 7 * 86400
        burn_start = now_ts - 900  # 近 15 分钟

        today_tok = today_in = today_ca = today_out = today_th = today_calls = 0
        today_usd = 0.0
        week_tok = 0
        week_usd = 0.0
        burn_tok = 0
        burn_usd = 0.0
        by_cid = {}

        for ts, cid, mid, mname, inp, ca, out, th in all_records:
            p_in, p_ca, p_out = _get_promo_rates(mname, mid)
            usd = inp / 1e6 * p_in + ca / 1e6 * p_ca + out / 1e6 * p_out
            tok = inp + ca + out

            c_stat = by_cid.setdefault(cid, {
                "calls": 0, "in": 0, "cache": 0, "out": 0, "think": 0, "total": 0, "usd": 0.0
            })
            c_stat["calls"] += 1
            c_stat["in"] += inp
            c_stat["cache"] += ca
            c_stat["out"] += out
            c_stat["think"] += th
            c_stat["total"] += tok
            c_stat["usd"] += usd

            if ts >= today_start:
                today_tok += tok
                today_in += inp
                today_ca += ca
                today_out += out
                today_th += th
                today_calls += 1
                today_usd += usd

            if ts >= week_start:
                week_tok += tok
                week_usd += usd

            if ts >= burn_start:
                burn_tok += tok
                burn_usd += usd

        for ts, cid in all_imgs:
            if cid in by_cid:
                by_cid[cid]["usd"] += IMAGE_GEN_UNIT_COST
            if ts >= today_start:
                today_usd += IMAGE_GEN_UNIT_COST
            if ts >= week_start:
                week_usd += IMAGE_GEN_UNIT_COST
            if ts >= burn_start:
                burn_usd += IMAGE_GEN_UNIT_COST

        scan_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "today": {
                "tokens": today_tok, "in": today_in, "cache": today_ca,
                "out": today_out, "think": today_th, "calls": today_calls,
                "usd": round(today_usd, 3)
            },
            "week": {
                "tokens": week_tok,
                "usd": round(week_usd, 2)
            },
            "burn_rate": {
                "tok_per_min": round(burn_tok / 15.0, 1),
                "usd_per_hr": round(burn_usd * 4.0, 2)
            },
            "by_cid": by_cid,
            "usd_to_cny": self.usd_to_cny,
            "scan_ms": scan_ms,
        }

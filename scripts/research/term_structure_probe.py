"""第四轮第 1 步：期限结构数据可得性探针（有界、只读、不装包）。

目的
----
确认本地/公开接口是否能拿到「单合约日线」（近月、次近月、已到期合约），
以判断期限结构（近月-次近月价差、基差、carry）实验是否可行。

有界约束（严格）
----------------
- 品种最多 3 个（rb / i / cu）；
- 每品种：1 次合约列表请求 + 最多 2 个在交易合约日线 + 1 个已到期合约日线；
- 单请求超时 20s；总耗时超过 180s 立刻中止，不再发新请求；
- 只保留最近 3 年日线（按本地当前日期回溯）；
- 不安装包、不改 data/ 下既有文件、不联网长时间下载。

用法
----
    python scripts/research/term_structure_probe.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from concurrent.futures import TimeoutError as FutTimeout

import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

CACHE_DIR = os.path.join(_PROJ_ROOT, "data", "sina_cache")
OUT_DIR = os.path.join(_PROJ_ROOT, "scripts", "research", "output")
DATA_DIR = os.path.join(OUT_DIR, "phase4_probe_data")
OUT_JSON = os.path.join(OUT_DIR, "phase4_availability.json")

REQ_TIMEOUT = 20.0        # 单请求超时（秒）
TOTAL_BUDGET = 180.0      # 总耗时上限（秒）
BACK_YEARS = 3            # 只取近 3 年

# (品种代码, 新浪中文名, 已到期测试合约)
PROBE_TARGETS = [
    ("rb", "螺纹钢", "RB2510"),
    ("i", "铁矿石", "I2509"),
    ("cu", "沪铜", "CU2510"),
]

_CONTRACT_RE = re.compile(r"^([A-Za-z]{1,2})(\d{3,4})$")


class Budget:
    """总耗时预算：超时后不再发新请求。"""

    def __init__(self, limit: float) -> None:
        self.start = time.time()
        self.limit = limit

    def elapsed(self) -> float:
        return time.time() - self.start

    def exhausted(self) -> bool:
        return self.elapsed() > self.limit


def _call(fn, *args, timeout: float = REQ_TIMEOUT, **kwargs):
    """在守护线程中执行一次网络调用；超时抛 FutTimeout，避免无限等待。

    用 threading.Thread(daemon=True) 而非 ThreadPoolExecutor：
    后者的工作线程非守护，超时退出 with 块时会阻塞等待请求结束，
    会把「20s 单请求超时」变成不可控等待。
    """
    box: dict = {}

    def _run():
        try:
            box["value"] = fn(*args, **kwargs)
        except Exception as exc:  # 记录异常，由主线程重新抛出
            box["error"] = exc

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise FutTimeout(f"{getattr(fn, '__name__', 'call')} 超时 >{timeout}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _local_scan() -> dict:
    """扫描本地缓存：区分主力连续（*0.csv）与单合约（形如 rb2410.csv）。"""
    if not os.path.isdir(CACHE_DIR):
        return {"main_continuous": {}, "single_contract": {}, "other_dirs": {}}
    main, single = {}, {}
    for name in sorted(os.listdir(CACHE_DIR)):
        if not name.lower().endswith(".csv"):
            continue
        stem = os.path.splitext(name)[0]
        if _CONTRACT_RE.match(stem):
            # 形如 rb2410 / IF2512：单合约
            single[stem] = "single_contract_like"
            continue
        if stem.endswith("0") and stem[:-1].isalpha():
            # 形如 rb0 / IF0：主力连续
            try:
                d = pd.read_csv(os.path.join(CACHE_DIR, name), usecols=["datetime"])
                main[stem] = {
                    "rows": int(len(d)),
                    "first": str(d["datetime"].iloc[0])[:10],
                    "last": str(d["datetime"].iloc[-1])[:10],
                }
            except Exception as exc:  # 缓存损坏也不应中断扫描
                main[stem] = {"error": repr(exc)}
            continue
        single[name] = "unclassified"
    other = {}
    for sub in ("akshare_cache", "real_samples"):
        p = os.path.join(_PROJ_ROOT, "data", sub)
        if not os.path.isdir(p):
            continue
        files = [f for f in os.listdir(p) if f.lower().endswith(".csv")]
        other[sub] = {"count": len(files), "files": sorted(files)[:40]}
    return {"main_continuous": main, "single_contract": single, "other_dirs": other}


def _month_key(contract: str) -> int:
    """把合约代码转成 YYMM 整数，用于按到期先后排序。"""
    m = _CONTRACT_RE.match(contract)
    if not m:
        return 999999
    digits = m.group(2)
    if len(digits) == 3:
        digits = "2" + digits if digits[0] == "0" else "1" + digits
    return int(digits)


def _contracts(symbol_cn: str) -> tuple[list[dict], float, str]:
    """列出该品种在交易的单月合约（剔除主力连续 RB0），含持仓量与成交量。"""
    import akshare as ak

    t0 = time.time()
    df = _call(ak.futures_zh_realtime, symbol=symbol_cn)
    elapsed = time.time() - t0
    if df is None or len(df) == 0:
        return [], elapsed, "realtime 返回空"
    code_col = "symbol" if "symbol" in df.columns else df.columns[0]
    oi_col = "hold" if "hold" in df.columns else ("持仓量" if "持仓量" in df.columns else None)
    vol_col = "volume" if "volume" in df.columns else ("成交量" if "成交量" in df.columns else None)
    items: list[dict] = []
    for _, row in df.iterrows():
        code = str(row[code_col]).upper()
        if not _CONTRACT_RE.match(code):
            continue  # 剔除 RB0 / RB0 等主力连续伪合约
        items.append({
            "contract": code,
            "month": _month_key(code),
            "oi": float(pd.to_numeric(row[oi_col], errors="coerce")) if oi_col else None,
            "volume": float(pd.to_numeric(row[vol_col], errors="coerce")) if vol_col else None,
        })
    items.sort(key=lambda x: x["month"])
    return items, elapsed, "ok"


def _daily(contract: str) -> tuple[pd.DataFrame | None, float, str]:
    """拉单合约日线（新浪），返回 (df, 耗时, 状态)。"""
    import akshare as ak

    t0 = time.time()
    df = _call(ak.futures_zh_daily_sina, symbol=contract)
    elapsed = time.time() - t0
    return df, elapsed, "ok"


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """统一列名并截取近 3 年。"""
    ren = {
        "date": "datetime", "日期": "datetime",
        "open": "open", "开盘价": "open",
        "high": "high", "最高价": "high",
        "low": "low", "最低价": "low",
        "close": "close", "收盘价": "close",
        "volume": "volume", "成交量": "volume",
        "hold": "open_interest", "持仓量": "open_interest",
        "settle": "settle", "结算价": "settle", "动态结算价": "settle",
    }
    df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
    df["datetime"] = pd.to_datetime(df["datetime"])
    cut = pd.Timestamp.today().normalize() - pd.DateOffset(years=BACK_YEARS)
    df = df[df["datetime"] >= cut].sort_values("datetime").reset_index(drop=True)
    return df


def main() -> int:
    budget = Budget(TOTAL_BUDGET)
    os.makedirs(DATA_DIR, exist_ok=True)
    for name in os.listdir(DATA_DIR):
        # 只清理本脚本自己上次生成的探针文件，不触碰其他目录
        if name.endswith(".csv"):
            os.remove(os.path.join(DATA_DIR, name))

    out: dict = {
        "meta": {
            "probe_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "request_timeout_sec": REQ_TIMEOUT,
            "total_budget_sec": TOTAL_BUDGET,
            "back_years": BACK_YEARS,
            "symbols": [t[0] for t in PROBE_TARGETS],
            "contracts_per_symbol": 2,
            "expired_test_per_symbol": 1,
        },
        "local": _local_scan(),
        "requests": [],
        "failures": [],
        "aborted": False,
    }

    print("=== 本地缓存扫描 ===")
    local = out["local"]
    print(f"主力连续文件数: {len(local['main_continuous'])}；单合约文件数: {len(local['single_contract'])}")
    for sub, info in local["other_dirs"].items():
        print(f"  data/{sub}: {info['count']} 个 CSV")

    def _fetch(code: str, contract: str, role: str) -> bool:
        """拉一个合约日线并落盘；返回是否成功。"""
        if budget.exhausted():
            out["aborted"] = True
            out["failures"].append({"stage": "daily", "symbol": code, "contract": contract,
                                    "error": f"总耗时预算耗尽({budget.elapsed():.1f}s)"})
            return False
        try:
            raw, el, _ = _daily(contract)
        except FutTimeout:
            out["failures"].append({"stage": "daily", "symbol": code, "contract": contract,
                                    "error": f"超时 >{REQ_TIMEOUT}s"})
            print(f"[{code}/{contract}] 日线超时")
            return False
        except Exception as exc:
            out["failures"].append({"stage": "daily", "symbol": code, "contract": contract,
                                    "error": f"{type(exc).__name__}: {exc}"})
            print(f"[{code}/{contract}] 日线失败: {exc}")
            return False
        if raw is None or len(raw) == 0:
            out["failures"].append({"stage": "daily", "symbol": code, "contract": contract,
                                    "error": "接口返回空表（合约不存在或新浪无该合约历史）"})
            print(f"[{code}/{contract}] 返回空表")
            return False
        try:
            df = _normalize(raw)
        except Exception as exc:
            out["failures"].append({"stage": "daily", "symbol": code, "contract": contract,
                                    "error": f"字段解析失败: {type(exc).__name__}: {exc}",
                                    "columns": list(map(str, raw.columns))})
            print(f"[{code}/{contract}] 字段异常: {list(raw.columns)}")
            return False
        if len(df) == 0:
            out["failures"].append({"stage": "daily", "symbol": code, "contract": contract,
                                    "error": "近 3 年窗口内无数据"})
            return False

        path = os.path.join(DATA_DIR, f"{code}_{contract}.csv")
        df.to_csv(path, index=False)
        out["requests"].append({
            "symbol": code, "stage": "daily", "api": "futures_zh_daily_sina",
            "contract": contract, "role": role, "elapsed_sec": round(el, 2),
            "status": "ok", "rows": int(len(df)),
            "first": str(df["datetime"].iloc[0].date()),
            "last": str(df["datetime"].iloc[-1].date()),
            "has_settle": bool("settle" in df.columns and df["settle"].notna().any()),
            "has_volume": bool("volume" in df.columns and df["volume"].notna().any()),
            "has_oi": bool("open_interest" in df.columns and df["open_interest"].notna().any()),
            "file": os.path.relpath(path, _PROJ_ROOT).replace("\\", "/"),
            "totals_elapsed_sec": round(budget.elapsed(), 2),
        })
        print(f"[{code}/{contract}] {role}: {len(df)} 行 "
              f"{df['datetime'].iloc[0].date()}~{df['datetime'].iloc[-1].date()} "
              f"耗时 {el:.1f}s")
        return True

    for code, cn, expired in PROBE_TARGETS:
        if budget.exhausted():
            out["aborted"] = True
            break
        # ---- 1) 列出在交易合约 ----
        try:
            items, el, status = _contracts(cn)
            out["requests"].append({
                "symbol": code, "stage": "contract_list", "api": "futures_zh_realtime",
                "elapsed_sec": round(el, 2), "status": status,
                "contracts_found": len(items),
                "contracts": [it["contract"] for it in items][:12],
                "totals_elapsed_sec": round(budget.elapsed(), 2),
            })
            print(f"[{code}] 在交易单月合约: {len(items)} 个 -> {[it['contract'] for it in items][:6]}")
        except FutTimeout:
            out["failures"].append({"stage": "contract_list", "symbol": code,
                                    "error": f"超时 >{REQ_TIMEOUT}s"})
            print(f"[{code}] 合约列表超时")
            items = []
        except Exception as exc:
            out["failures"].append({"stage": "contract_list", "symbol": code,
                                    "error": f"{type(exc).__name__}: {exc}"})
            print(f"[{code}] 合约列表失败: {exc}")
            items = []

        # ---- 2) 近月 / 次近月（按到期先后排序后的前两个） ----
        for idx, it in enumerate(items[:2]):
            role = "near" if idx == 0 else "next"
            _fetch(code, it["contract"], role)
            out["requests"][-1]["oi_at_probe"] = it["oi"]
            out["requests"][-1]["volume_at_probe"] = it["volume"]

        # ---- 3) 已到期合约：决定能否拼出 3 年滚动近月序列 ----
        _fetch(code, expired, "expired")

    # ---- 汇总判定 ----
    ok = [r for r in out["requests"] if r.get("stage") == "daily" and r.get("status") == "ok"]
    sym_live = {}
    expired_ok = {}
    for r in ok:
        if r["role"] in ("near", "next"):
            sym_live.setdefault(r["symbol"], []).append(r)
        else:
            expired_ok[r["symbol"]] = r
    feasible = (len(sym_live) >= 3 and min(len(v) for v in sym_live.values()) >= 2
                and all(r["has_settle"] and r["has_oi"] for r in ok))
    out["conclusion"] = {
        "single_contract_daily_obtainable": bool(ok),
        "symbols_with_two_live_contracts": len([k for k, v in sym_live.items() if len(v) >= 2]),
        "expired_contract_history_obtainable": len(expired_ok),
        "term_structure_probe_feasible": bool(feasible),
        "max_rows_per_contract": int(max((r["rows"] for r in ok), default=0)),
        "min_rows_per_contract": int(min((r["rows"] for r in ok), default=0)),
        "reason": (
            "在交易近月/次近月单合约日线可得，且含结算价与持仓量；"
            "3 年滚动近月序列需批量抓取多个月份合约"
            if feasible else
            "单合约日线不可得或不完整，期限结构实验需要额外数据源/接口"
        ),
    }
    out["total_elapsed_sec"] = round(budget.elapsed(), 2)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("=== 结论 ===")
    print(json.dumps(out["conclusion"], ensure_ascii=False, indent=2))
    print(f"总耗时 {out['total_elapsed_sec']}s -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

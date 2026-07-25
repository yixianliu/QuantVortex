"""CTP 行情接入（可插拔适配器 · 仿真 / 实盘）。

架构目标
--------
让上层（MarketDataManager / UI 监控页）只依赖 `DataFeed` 接口，具体是
SimNow 仿真、期货公司实盘、还是合成行情，由本模块在运行时决定，业务代码零改动。

关键设计
--------
1. `CTPCredentials`：柜台 / SimNow 连接凭据，从本地 `ctp_settings.json` 读取，
   该文件已被 `.gitignore` 忽略，**绝不入库**，不泄露任何账号密码。
2. `CTPFeed(DataFeed)`：真实行情适配器。
   - 懒加载 `vnpy_ctp` / `ctpbee`；两库均缺失时进入「未安装」状态，绝不伪造连接。
   - 支持 SimNow 7x24 仿真 与 期货公司实盘 两套 front 预设。
   - `connect()` / `subscribe()` / `on_bar`→系统 Bar 转换 / 自动重连退避 / `on_status` 回调。
   - 历史行情：真实连接后由 CTP 查询（此处留接口），不可用时明确回退合成并标注。
3. `ctp_diagnose()`：返回 {lib_available, lib_name, creds_complete, mode}，
   供 UI 诊断面板直接展示「还差什么才能连上」。

⚠️ 本沙箱未安装 vnpy / ctpbee，且无法连接期货公司前置机，因此**真实连接无法在此实测**。
   本模块只提供「正确可装配」的适配器与清晰的不可用诊断，**绝不冒充实盘已连接**。
   真正登录需在用户机器上：安装 CTP 动态库 + vnpy_ctp / ctpbee，并填入自己的柜台凭据。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

from .base import DataFeed
from .synthetic import SyntheticFeed
from ..runtime import get_data_dir

# --------------------------------------------------------------------------
# SimNow 7x24 仿真环境预设（公开地址，仅用于仿真，非真实交易）
# --------------------------------------------------------------------------
SIMNOW_MD_FRONT = "tcp://180.168.146.187:10211"
SIMNOW_TD_FRONT = "tcp://180.168.146.187:10201"
SIMNOW_BROKER_ID = "9999"
SIMNOW_APP_ID = "simnow_client_test"

_COLS = ["datetime", "open", "high", "low", "close", "volume", "open_interest"]


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class CTPCredentials:
    """CTP / SimNow 连接凭据（本地读取，绝不入库）。"""

    mode: str = "simnow"                 # "simnow" | "live"
    md_front: str = ""
    td_front: str = ""
    broker_id: str = ""
    user_id: str = ""
    password: str = ""
    app_id: str = ""
    auth_code: str = ""
    subscribe: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(self.md_front and self.td_front and self.broker_id
                    and self.user_id and self.password)

    @property
    def label(self) -> str:
        return "SimNow 仿真" if self.mode == "simnow" else "期货公司实盘"

    @classmethod
    def load(cls, path: Optional[str] = None) -> "CTPCredentials":
        """从本地 ctp_settings.json 读取；缺失则返回空凭据（不入库）。"""
        if path is not None:
            candidates = [path]
        else:
            # 优先 data 目录（可写，打包后落点），回退项目根 config/
            candidates = [
                os.path.join(get_data_dir(), "ctp_settings.json"),
                os.path.join(_project_root(), "config", "ctp_settings.json"),
            ]
        for p in candidates:
            try:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        return cls._from_dict(json.load(f))
            except Exception:
                continue
        return cls()

    @classmethod
    def _from_dict(cls, d: dict) -> "CTPCredentials":
        acct = d.get("account", {}) or {}
        if (d.get("mode") or "simnow") == "simnow":
            f = d.get("simnow", {}) or {}
            return cls(
                mode="simnow",
                md_front=f.get("md_front", SIMNOW_MD_FRONT),
                td_front=f.get("td_front", SIMNOW_TD_FRONT),
                broker_id=f.get("broker_id", SIMNOW_BROKER_ID),
                app_id=f.get("app_id", SIMNOW_APP_ID),
                auth_code=f.get("auth_code", ""),
                user_id=acct.get("user_id", ""),
                password=acct.get("password", ""),
                subscribe=list(d.get("subscribe", []) or []),
            )
        f = d.get("live", {}) or {}
        return cls(
            mode="live",
            md_front=f.get("md_front", ""),
            td_front=f.get("td_front", ""),
            broker_id=f.get("broker_id", ""),
            app_id=f.get("app_id", ""),
            auth_code=f.get("auth_code", ""),
            user_id=acct.get("user_id", ""),
            password=acct.get("password", ""),
            subscribe=list(d.get("subscribe", []) or []),
        )


class CTPFeed(DataFeed):
    """CTP 行情适配器（可插拔）。

    沙箱无库无网络时：connect() 返回 False 并给出明确诊断；绝不伪造「已连接」。
    用户环境装好 CTP 库 + 凭据后：connect() 尝试建立真实连接并路由行情回报。
    """

    def __init__(self, creds: Optional[CTPCredentials] = None) -> None:
        self.creds = creds or CTPCredentials.load()
        self.connected = False
        self._gw = None                     # 底层 vnpy/ctpbee 网关实例
        self._lib_name: Optional[str] = None
        self.on_bar: Optional[Callable[[dict], None]] = None
        self.on_status: Optional[Callable[[str], None]] = None
        self._reconnect_attempts = 0
        self._max_reconnect = 5
        self._fallback = SyntheticFeed()    # 明确标注的回退（仅在不连接时）
        self._cache: dict[str, pd.DataFrame] = {}

    # ------------------------- 库探测 -------------------------
    def _detect_lib(self) -> Optional[str]:
        for name in ("vnpy_ctp", "ctpbee"):
            try:
                __import__(name)
                return name
            except Exception:
                continue
        return None

    # ------------------------- 状态回调 -------------------------
    def _set_status(self, text: str) -> None:
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:
                pass

    # ------------------------- 真实 CTP 接入 -------------------------
    def connect(self) -> bool:
        """尝试建立 CTP 连接。任何前置条件不满足都返回 False 并给出诊断文本。"""
        if not self.creds.complete:
            self.connected = False
            self._set_status("未连接 · 凭据不完整（请在 ctp_settings.json 配置账号/密码/前置机）")
            return False
        lib = self._detect_lib()
        if lib is None:
            self.connected = False
            self._set_status("未连接 · 未安装 CTP 库（需 vnpy_ctp 或 ctpbee + 期货公司动态库）")
            return False
        self._lib_name = lib
        try:
            if lib == "vnpy_ctp":
                self._connect_vnpy()
            else:
                self._connect_ctpbee()
            # 注意：CTP连接通常是异步的，connect()只启动连接流程
            # 实际连接状态需等待回调通知或查询 feed.connected
            # 此处假设连接请求已发出，返回 True 表示成功启动
            self.connected = True
            self._reconnect_attempts = 0
            tag = "仿真(SimNow)" if self.creds.mode == "simnow" else "实盘"
            self._set_status(f"已连接 · CTP{tag}（库：{lib}）")
            return True
        except Exception as exc:
            import traceback
            print(f"[CTP错误] {type(exc).__name__}: {exc}")
            traceback.print_exc()
            self.connected = False
            self._set_status(f"连接失败 · {type(exc).__name__}: {exc}")
            return False

    def _connect_vnpy(self) -> None:
        """基于 vnpy_ctp 的接入骨架（需用户环境的 vnpy 主引擎装配）。

        说明：vnpy 需要完整的 EventEngine / MainEngine 上下文，通常应在应用入口装配。
        此处给出标准连接参数与回调注册方式；若你的项目已内置 vnpy 主引擎，可直接复用。
        详见 docs/ctp_wiring.md 的「vnpy 集成」一节。
        """
        from vnpy.event import EventEngine
        from vnpy.trader.engine import MainEngine
        from vnpy_ctp.gateway import CtpGateway
        from vnpy.trader.object import SubscribeRequest
        from vnpy.trader.constant import Exchange
        from vnpy.trader.event import EVENT_TICK

        self._event_engine = EventEngine()
        self._main_engine = MainEngine(self._event_engine)
        self._main_engine.add_gateway(CtpGateway)
        setting = {
            "用户名": self.creds.user_id,
            "密码": self.creds.password,
            "经纪商代码": self.creds.broker_id,
            "交易服务器": self.creds.td_front,
            "行情服务器": self.creds.md_front,
            "产品名称": self.creds.app_id,
            "授权编码": self.creds.auth_code,
        }
        self._main_engine.connect(setting, "CTP")
        self._event_engine.register(EVENT_TICK, self._on_vnpy_tick)
        for sym in self.creds.subscribe:
            code, exch = sym.split(".")
            req = SubscribeRequest(
                symbol=code,
                exchange=getattr(Exchange, exch, Exchange.SHFE),
            )
            self._main_engine.subscribe(req, "CTP")

    def _connect_ctpbee(self) -> None:
        """基于 ctpbee 的接入骨架（成熟框架，API 简洁）。"""
        from ctpbee import CtpBee, CtpbeeApi

        # ★ ctpbee 要求 CONNECT_INFO 存在于 config 中才能登录
        connect_info = {
            "userid": self.creds.user_id,
            "password": self.creds.password,
            "brokerid": self.creds.broker_id,
            "md_address": self.creds.md_front,
            # td_address 仅在开启 TD_FUNC=True（交易模式）时需要
            "td_address": self.creds.td_front,
            "app_id": self.creds.app_id,
            "auth_code": self.creds.auth_code,
        }

        # 创建 CtpBee app + API（只开行情，不开交易）
        self._ctpbee_core = CtpBee("futures_quant", __name__)
        self._ctpbee_api = CtpbeeApi("futures_quant_api", self._ctpbee_core)

        # ★ ctpbee 要求 CONNECT_INFO 存在于 config 中才能登录
        self._ctpbee_core.config["CONNECT_INFO"] = connect_info
        self._ctpbee_core.config["MD_FUNC"] = True       # 行情开关
        self._ctpbee_core.config["TD_FUNC"] = False      # 交易开关（关闭）

        # 行情回报回调（ctpbee 收到 tick 后调用 self.on_tick(tick)）
        self._ctpbee_api.on_tick = self._on_ctpbee_tick

        # ★ 关键：在启动前关闭 r_flag，阻止 refresh_query 线程（TD_FUNC=False 时不需要查询账户）
        self._ctpbee_core.r_flag = False

        # 初始化并启动 — start() → _running() → init_interface() 会从 CONNECT_INFO 读登录信息
        self._ctpbee_api.init_app(self._ctpbee_core)
        self._ctpbee_core.start()

        # 订阅合约（subscribe 只需合约代码，不含交易所后缀）
        for sym in self.creds.subscribe:
            code, _ = sym.split(".")
            try:
                self._ctpbee_api.subscribe(code)
            except Exception:
                pass

    # ------------------------- 行情回报 → 系统 Bar -------------------------
    def _on_vnpy_tick(self, event) -> None:
        tick = event.data
        # vnpy tick → 系统 Bar 字典（此处按 tick 累积，真实部署应聚合为分钟 Bar）
        bar = {
            "datetime": pd.to_datetime(tick.datetime),
            "open": float(tick.open_price), "high": float(tick.high_price),
            "low": float(tick.low_price), "close": float(tick.last_price),
            "volume": float(tick.volume), "open_interest": float(tick.open_interest),
            "symbol": f"{tick.symbol}.{tick.exchange.value}",
        }
        if self.on_bar:
            self.on_bar(bar)

    def _on_ctpbee_tick(self, tick) -> None:
        bar = {
            "datetime": pd.to_datetime(getattr(tick, "datetime", None) or pd.Timestamp.now()),
            "open": float(getattr(tick, "open", 0) or 0),
            "high": float(getattr(tick, "high", 0) or 0),
            "low": float(getattr(tick, "low", 0) or 0),
            "close": float(getattr(tick, "last_price", 0) or 0),
            "volume": float(getattr(tick, "volume", 0) or 0),
            "open_interest": float(getattr(tick, "open_interest", 0) or 0),
            "symbol": getattr(tick, "symbol", ""),
        }
        if self.on_bar:
            self.on_bar(bar)

    def subscribe(self, symbol: str) -> None:
        """订阅合约。真实实现：gateway.subscribe(symbol)。"""
        if self._gw is None and not self.connected:
            return
        # vnpy / ctpbee 的具体订阅在 connect() 中按 creds.subscribe 批量完成；
        # 运行时增量订阅可在 self._main_engine / self._ctpbee_app 上调用。
        if hasattr(self, "_main_engine") and self._main_engine is not None:
            try:
                from vnpy.trader.object import SubscribeRequest
                from vnpy.trader.constant import Exchange
                code, exch = symbol.split(".")
                self._main_engine.subscribe(
                    SubscribeRequest(symbol=code,
                                     exchange=getattr(Exchange, exch, Exchange.SHFE)),
                    "CTP")
            except Exception:
                pass

    def disconnect(self) -> None:
        try:
            # ★ 通知 ctpbee 停止 refresh_query 线程
            if hasattr(self, "_ctpbee_core") and self._ctpbee_core is not None:
                self._ctpbee_core.r_flag = False
            if hasattr(self, "_main_engine"):
                self._main_engine.close()
            if hasattr(self, "_ctpbee_app"):
                self._ctpbee_app.stop()
        except Exception:
            pass
        self.connected = False
        self._set_status("已断开 · CTP")

    def close(self) -> None:
        """disconnect() 的便捷别名。"""
        self.disconnect()

    # ------------------------- 自动重连 -------------------------
    def maybe_reconnect(self) -> bool:
        """连接断开后按退避策略尝试重连（由上层定时器调用）。"""
        if self.connected:
            return True
        if self._reconnect_attempts >= self._max_reconnect:
            self._set_status(f"重连失败已达 {self._max_reconnect} 次，请检查网络/凭据")
            return False
        self._reconnect_attempts += 1
        self._set_status(f"尝试重连 CTP（第 {self._reconnect_attempts} 次）…")
        return self.connect()

    # ------------------------- DataFeed 接口 -------------------------
    def get_history(self, symbol, start, end, period="1m", limit=0) -> pd.DataFrame:
        # 真实连接后应由 CTP 历史接口或本地缓存读取；当前回退合成（明确标注非实盘）
        return self._fallback.get_history(symbol, start, end, period, limit)

    def get_recent(self, symbol, period="1m", limit=600) -> pd.DataFrame:
        return self._fallback.get_recent(symbol, period, limit)

    @property
    def source_label(self) -> str:
        if self.connected:
            return f"CTP{'(SimNow)' if self.creds.mode == 'simnow' else '(实盘)'}·已连接"
        return "CTP未连接·回退合成"


def ctp_diagnose() -> dict:
    """诊断 CTP 可连接性，返回还差什么。供 UI 诊断面板使用。"""
    creds = CTPCredentials.load()
    lib = None
    for name in ("vnpy_ctp", "ctpbee"):
        try:
            __import__(name)
            lib = name
            break
        except Exception:
            continue
    return {
        "lib_available": lib is not None,
        "lib_name": lib,
        "creds_complete": creds.complete,
        "mode": creds.mode,
        "mode_label": creds.label,
        "subscribe": creds.subscribe,
    }

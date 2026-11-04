"""TqSdk（快期 / SimNow）真实行情适配器。

本模块只做一件事：把 TqSdk 的 K 线接口适配成项目既有的 ``DataFeed`` 契约，
并沿用 ``futures_quant/data/base.py`` 的 provenance 约定。**它不生成任何合成
行情**：库缺失、凭据缺失、连接失败、区间无数据、周期不支持，一律抛出具名
异常（见下方错误分类），由调用方显式处理。

支持的周期与合约
----------------
- 周期：日线（``D``）、1 / 5 / 15 / 30 分钟；
- 合约：
    * 主力连续：``KQ.m@SHFE.rb``，或简写 ``rb`` / ``rb0`` / ``rb.SHFE``；
    * 单合约：``SHFE.rb2611``，或简写 ``rb2611`` / ``rb2611.SHFE``。

凭据读取顺序（绝不写入源码 / 仓库）
-----------------------------------
1. 构造参数 ``user`` / ``password``（测试或调用方显式传入）；
2. 环境变量 ``TQ_USER`` / ``TQ_PASSWORD``（另兼容 ``TQSDK_USER`` /
   ``TQSDK_PASSWORD``、``QV_TQ_USER`` / ``QV_TQ_PASSWORD``）；
3. 本地未跟踪文件 ``tqsdk_settings.json``（``data/`` 或 ``config/`` 下），
   形如 ``{"user": "...", "password": "..."}``；该文件已在 ``.gitignore``
   中忽略，**不会入库**。

错误分类（全部继承 ``TqSdkFeedError``）
--------------------------------------
    NotInstalledError       未安装 tqsdk            → pip install tqsdk
    MissingCredentialsError 未配置账号              → 设置 TQ_USER / TQ_PASSWORD
    ConnectFailedError      初始化/取数调用失败     → 检查网络、账号权限、模拟环境
    NoDataError             区间内没有 K 线          → 换合约/周期或确认交易时段
    UnsupportedPeriodError  周期不在白名单          → 改用 D/1m/5m/15m/30m
    InvalidSymbolError      合约代码无法解析        → 用 SHFE.rb2611 / KQ.m@SHFE.rb

注意：``TqApi`` 是长连接对象，本适配器懒初始化，必须在退出前调用 ``close()``
（``MarketDataManager.disconnect()`` / 应用退出时已接线），否则会残留连接线程。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

import pandas as pd

from .base import DataFeed, attach_provenance, register_feed
from ..runtime import app_base_dir, get_config_dir, get_data_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 错误分类
# ---------------------------------------------------------------------------
class TqSdkFeedError(RuntimeError):
    """TqSdk 适配器错误基类；``kind`` 供 UI / 日志做稳定分类。"""

    kind = "TqSdkError"
    default_hint = ""

    def __init__(self, message: str, hint: str = "") -> None:
        """初始化相关对象。

        参数:
            message: 具体错误描述（含合约/周期等上下文）
            hint: 可执行的下一步建议
        """
        super().__init__(message)
        self.message = str(message)
        self.hint = hint or self.default_hint

    @property
    def user_message(self) -> str:
        """面向界面的完整文案（错误 + 下一步）。"""
        return self.message + (f"（下一步：{self.hint}）" if self.hint else "")


class NotInstalledError(TqSdkFeedError):
    """当前环境未安装 tqsdk。"""

    kind = "NotInstalled"
    default_hint = "执行 pip install tqsdk 后重启程序"


class MissingCredentialsError(TqSdkFeedError):
    """未找到 TqSdk / SimNow 账号凭据。"""

    kind = "MissingCredentials"
    default_hint = ("设置环境变量 TQ_USER / TQ_PASSWORD，"
                    "或写入本地未跟踪文件 config/tqsdk_settings.json（不要提交到仓库）")


class ConnectFailedError(TqSdkFeedError):
    """TqSdk 初始化或取数调用失败（网络 / 账号权限 / 服务端异常）。"""

    kind = "ConnectFailed"
    default_hint = ("检查网络与账号是否可用；SimNow 账号请确认已开通并处于交易时段，"
                    "或改用 tqsdk 的模拟账号试连")


class NoDataError(TqSdkFeedError):
    """请求的合约/周期/区间没有返回任何 K 线。"""

    kind = "NoData"
    default_hint = "确认合约代码与周期正确；非交易时段可能暂无当日 K 线，可扩大时间区间重试"


class UnsupportedPeriodError(TqSdkFeedError):
    """周期不在 TqSdk 适配器白名单内。"""

    kind = "UnsupportedPeriod"
    default_hint = "改用 D / 1m / 5m / 15m / 30m，或在配置中切换其它数据源"


class InvalidSymbolError(TqSdkFeedError):
    """合约代码无法解析为 TqSdk 代码。"""

    kind = "InvalidSymbol"
    default_hint = "使用带交易所的代码，如 SHFE.rb2611、KQ.m@SHFE.rb，或简写 rb2611"


# ---------------------------------------------------------------------------
# 合约代码规范化
# ---------------------------------------------------------------------------
_EXCHANGES = {"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"}

#: 品种 → (交易所, TqSdk 规范大小写)。覆盖项目常用品种；未知品种要求显式带交易所。
_PRODUCTS: dict[str, tuple[str, str]] = {
    # 上期所
    "RB": ("SHFE", "rb"), "HC": ("SHFE", "hc"), "CU": ("SHFE", "cu"),
    "AL": ("SHFE", "al"), "ZN": ("SHFE", "zn"), "NI": ("SHFE", "ni"),
    "SN": ("SHFE", "sn"), "PB": ("SHFE", "pb"), "SS": ("SHFE", "ss"),
    "AU": ("SHFE", "au"), "AG": ("SHFE", "ag"), "FU": ("SHFE", "fu"),
    "BU": ("SHFE", "bu"), "SP": ("SHFE", "sp"), "RU": ("SHFE", "ru"),
    "BR": ("SHFE", "br"),
    # 大商所
    "I": ("DCE", "i"), "J": ("DCE", "j"), "JM": ("DCE", "jm"),
    "M": ("DCE", "m"), "Y": ("DCE", "y"), "P": ("DCE", "p"),
    "C": ("DCE", "c"), "CS": ("DCE", "cs"), "A": ("DCE", "a"),
    "B": ("DCE", "b"), "EG": ("DCE", "eg"), "EB": ("DCE", "eb"),
    "PG": ("DCE", "pg"), "LH": ("DCE", "lh"), "JD": ("DCE", "jd"),
    "FB": ("DCE", "fb"), "BB": ("DCE", "bb"), "RR": ("DCE", "rr"),
    # 郑商所（TqSdk 代码大写）
    "TA": ("CZCE", "TA"), "MA": ("CZCE", "MA"), "SR": ("CZCE", "SR"),
    "CF": ("CZCE", "CF"), "OI": ("CZCE", "OI"), "FG": ("CZCE", "FG"),
    "SA": ("CZCE", "SA"), "UR": ("CZCE", "UR"), "PF": ("CZCE", "PF"),
    "PK": ("CZCE", "PK"), "AP": ("CZCE", "AP"), "CJ": ("CZCE", "CJ"),
    "RM": ("CZCE", "RM"), "ZC": ("CZCE", "ZC"), "SM": ("CZCE", "SM"),
    "SF": ("CZCE", "SF"), "SH": ("CZCE", "SH"), "PX": ("CZCE", "PX"),
    "PR": ("CZCE", "PR"),
    # 中金所
    "IF": ("CFFEX", "IF"), "IH": ("CFFEX", "IH"), "IC": ("CFFEX", "IC"),
    "IM": ("CFFEX", "IM"), "T": ("CFFEX", "T"), "TF": ("CFFEX", "TF"),
    "TS": ("CFFEX", "TS"), "TL": ("CFFEX", "TL"),
    # 能源中心
    "SC": ("INE", "sc"), "LU": ("INE", "lu"), "NR": ("INE", "nr"),
    "BC": ("INE", "bc"), "EC": ("INE", "ec"),
    # 广期所
    "SI": ("GFEX", "SI"), "LC": ("GFEX", "LC"), "PS": ("GFEX", "PS"),
}

_CONTRACT_RE = re.compile(r"([A-Za-z]+)(\d*)")


def _qualified_tq_symbol(code_part: str, exchange: str) -> str:
    """把「品种+月份」拼成 TqSdk 代码；无月份或月份为 0 视为主力连续。"""
    m = _CONTRACT_RE.fullmatch(str(code_part or "").strip())
    if not m:
        raise InvalidSymbolError(
            f"无法解析合约代码 {code_part!r}", hint="示例：SHFE.rb2611 / KQ.m@SHFE.rb")
    raw_product, digits = m.group(1), m.group(2)
    info = _PRODUCTS.get(raw_product.upper())
    if info is None:
        raise InvalidSymbolError(
            f"未识别品种 {raw_product!r}（交易所 {exchange}）",
            hint="请使用带交易所的完整代码，如 SHFE.rb2611 或 KQ.m@SHFE.rb")
    _, canonical = info
    if digits in ("", "0"):
        return f"KQ.m@{exchange}.{canonical}"
    return f"{exchange}.{canonical}{digits}"


def to_tq_symbol(symbol: str) -> str:
    """项目风格合约代码 → TqSdk 代码。

    识别的写法：
        - 原样透传：``KQ.m@SHFE.rb`` / 含 ``@`` 的字符串；
        - 带交易所前置：``SHFE.rb2611``；
        - 项目风格：``rb2611.SHFE`` / ``rb.SHFE``；
        - 简写：``rb2611`` / ``rb``（视为主力连续）/ ``rb0``。

    无法解析时抛出 ``InvalidSymbolError``（绝不猜测一个可能错位的合约）。
    """
    s = str(symbol or "").strip()
    if not s:
        raise InvalidSymbolError("合约代码为空", hint="请选择或输入一个合约代码")
    if "@" in s or s.upper().startswith("KQ."):
        return s
    if "." in s:
        left, right = s.split(".", 1)
        if left.upper() in _EXCHANGES:
            return _qualified_tq_symbol(right, left.upper())
        if right.upper() in _EXCHANGES:
            return _qualified_tq_symbol(left, right.upper())
        raise InvalidSymbolError(
            f"无法解析合约代码 {s!r}",
            hint="交易所前缀应为 SHFE/DCE/CZCE/CFFEX/INE/GFEX")
    m = _CONTRACT_RE.fullmatch(s)
    if not m:
        raise InvalidSymbolError(f"无法解析合约代码 {s!r}")
    info = _PRODUCTS.get(m.group(1).upper())
    if info is None:
        raise InvalidSymbolError(
            f"未识别品种 {m.group(1)!r}",
            hint="请使用带交易所的完整代码，如 SHFE.rb2611 或 KQ.m@SHFE.rb")
    exchange, _ = info
    return _qualified_tq_symbol(s, exchange)


# ---------------------------------------------------------------------------
# 周期映射
# ---------------------------------------------------------------------------
#: TqSdk 周期白名单：周期键 → (规范名, duration_seconds)。
_PERIOD_MAP: dict[str, tuple[str, int]] = {
    "d": ("D", 86400),
    "1d": ("D", 86400),
    "day": ("D", 86400),
    "1m": ("1m", 60),
    "1min": ("1m", 60),
    "5m": ("5m", 300),
    "5min": ("5m", 300),
    "15m": ("15m", 900),
    "15min": ("15m", 900),
    "30m": ("30m", 1800),
    "30min": ("30m", 1800),
}


def normalize_period(period: str) -> tuple[str, int]:
    """周期字符串 → (规范名, TqSdk duration_seconds)；不支持时抛具名异常。"""
    raw = str(period or "D").strip().lower()
    hit = _PERIOD_MAP.get(raw)
    if hit is None:
        raise UnsupportedPeriodError(
            f"TqSdk 适配器不支持周期 {period!r}（仅支持 D / 1m / 5m / 15m / 30m）")
    return hit


# ---------------------------------------------------------------------------
# 凭据
# ---------------------------------------------------------------------------
_ENV_USER_ALIASES = ("TQ_USER", "TQSDK_USER", "QV_TQ_USER")
_ENV_PASS_ALIASES = ("TQ_PASSWORD", "TQSDK_PASSWORD", "QV_TQ_PASSWORD")
_CREDS_FILENAME = "tqsdk_settings.json"


def _creds_candidates(path: Optional[str]) -> list[str]:
    """本地凭据文件候选路径（前者优先）。

    相对路径同时按「程序基准目录」和「当前工作目录」解析，避免从任意目录
    启动打包程序时找不到 config/tqsdk_settings.json。
    """
    if path:
        if os.path.isabs(path):
            return [path]
        return [os.path.join(app_base_dir(), path), path]
    return [
        os.path.join(get_data_dir(), _CREDS_FILENAME),
        os.path.join(get_config_dir(), _CREDS_FILENAME),
    ]


@dataclass(frozen=True)
class TqSdkCredentials:
    """TqSdk / SimNow 账号凭据（只读，来源可追溯）。"""

    user: str = ""
    password: str = ""
    origin: str = ""          # "env" / "file:<path>" / ""

    @property
    def complete(self) -> bool:
        """用户名与密码是否齐全。"""
        return bool(self.user and self.password)

    @classmethod
    def load(
        cls,
        user_env: str = "TQ_USER",
        password_env: str = "TQ_PASSWORD",
        path: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> "TqSdkCredentials":
        """按「环境变量 → 本地未跟踪文件」顺序读取凭据；缺失返回空凭据。"""
        env = os.environ if env is None else env
        user = str(env.get(user_env) or "").strip()
        password = str(env.get(password_env) or "").strip()
        if not user:
            user = next((str(env.get(k) or "").strip()
                         for k in _ENV_USER_ALIASES if env.get(k)), "")
        if not password:
            password = next((str(env.get(k) or "").strip()
                             for k in _ENV_PASS_ALIASES if env.get(k)), "")
        if user and password:
            return cls(user, password, "env")

        for fp in _creds_candidates(path):
            try:
                if not os.path.exists(fp):
                    continue
                with open(fp, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if not isinstance(data, dict):
                    continue
                acct = data.get("account", {}) or {}
                u = str(data.get("user") or data.get("user_id")
                        or acct.get("user") or acct.get("user_id") or "").strip()
                p = str(data.get("password") or acct.get("password") or "").strip()
                if u and p:
                    return cls(u, p, f"file:{fp}")
            except Exception as exc:  # noqa: BLE001 - 凭据文件损坏不应中断读取
                logger.warning("TqSdk 凭据文件读取失败 %s: %s", fp, exc)
        return cls()


def tqsdk_diagnose(path: Optional[str] = None) -> dict:
    """只读诊断（不联网、不创建连接），供 UI 展示「还差什么才能连上」。"""
    installed, version = False, ""
    try:
        import tqsdk  # noqa: F401 - 仅探测可导入性
        installed = True
        version = str(getattr(tqsdk, "__version__", "") or "")
    except Exception:  # noqa: BLE001
        pass
    creds = TqSdkCredentials.load(path=path)
    return {
        "installed": installed,
        "version": version,
        "creds_complete": creds.complete,
        "creds_origin": creds.origin,
    }


# ---------------------------------------------------------------------------
# 时间戳
# ---------------------------------------------------------------------------
def _bar_datetime(series: pd.Series) -> pd.Series:
    """TqSdk 时间戳 → 项目时间口径（北京时间的 naive datetime）。

    TqSdk 的 ``datetime`` 是「以北京时间为基准的纳秒计数」，直接按 ns 解析
    会整体早 8 小时（例如 09:00 的夜盘/日盘棒变 01:00），因此数值型需 +8h；
    测试桩或旧版接口返回真实 datetime 时则原样转换。
    """
    if pd.api.types.is_numeric_dtype(series):
        return (pd.to_datetime(series.astype("int64"), unit="ns")
                + pd.Timedelta(hours=8))
    return pd.to_datetime(series)


_REQUIRED_COLUMNS = ("datetime", "open", "high", "low", "close",
                     "volume", "open_interest")
_BAR_COLUMNS = list(_REQUIRED_COLUMNS)


# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------
class TqSdkFeed(DataFeed):
    """TqSdk 真实行情源（日线 / 分钟线，主力连续与单合约）。"""

    source_label = "TqSdk 实盘行情"

    def __init__(
        self,
        user: str = "",
        password: str = "",
        user_env: str = "TQ_USER",
        password_env: str = "TQ_PASSWORD",
        creds_path: Optional[str] = None,
        api_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        """初始化相关对象（不联网、不建连，真正的连接发生在首次取数）。

        参数:
            user / password: 显式凭据（优先级最高，便于测试或上层注入）
            user_env / password_env: 环境变量名（可在 settings.json 中覆盖）
            creds_path: 本地凭据文件路径；None 时按 data/ → config/ 顺序探测
            api_factory: 测试注入用的 TqApi 工厂（返回带 get_kline_* 方法的对象）
        """
        self._user = str(user or "").strip()
        self._password = str(password or "").strip()
        self._user_env = user_env
        self._password_env = password_env
        self._creds_path = creds_path
        self._api_factory = api_factory
        self._api: Any = None
        self._lock = threading.RLock()
        #: 与其它 feed 对齐的可读属性（TqSdk 不做缓存回放，连接失败直接抛错）
        self.is_stale: bool = False
        self.history_real: bool = True

    # ------------------------- 凭据 / 连接 -------------------------
    def credentials(self) -> TqSdkCredentials:
        """返回当前生效的凭据（显式参数优先，其次 env → 本地文件）。"""
        if self._user and self._password:
            return TqSdkCredentials(self._user, self._password, "explicit")
        return TqSdkCredentials.load(
            user_env=self._user_env, password_env=self._password_env,
            path=self._creds_path)

    def _ensure_api(self) -> Any:
        """懒初始化 TqApi；失败按类型抛出，绝不返回一个「假连接」。"""
        if self._api is not None:
            return self._api

        # 测试注入路径：跳过库/凭据检查，直接使用调用方提供的对象
        if self._api_factory is not None:
            try:
                self._api = self._api_factory()
            except TqSdkFeedError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ConnectFailedError(
                    f"TqSdk 连接失败：{type(exc).__name__}: {exc}") from exc
            return self._api

        try:
            from tqsdk import TqApi, TqAuth
        except Exception as exc:  # noqa: BLE001 - ImportError / 依赖 DLL 缺失等
            raise NotInstalledError(
                f"未安装 tqsdk（{type(exc).__name__}: {exc}）") from exc

        creds = self.credentials()
        if not creds.complete:
            raise MissingCredentialsError(
                "未找到 TqSdk / SimNow 账号：环境变量 TQ_USER / TQ_PASSWORD 为空，"
                f"且本地未找到可用的 {_CREDS_FILENAME}")

        try:
            self._api = TqApi(auth=TqAuth(creds.user, creds.password), web_gui=False)
        except Exception as exc:  # noqa: BLE001
            raise ConnectFailedError(
                f"TqSdk 初始化失败：{type(exc).__name__}: {exc}") from exc
        logger.info("TqSdk 已建立连接（凭据来源：%s）", creds.origin or "unknown")
        return self._api

    def close(self) -> None:
        """关闭底层 TqApi（幂等；未连接时为安全空操作）。"""
        with self._lock:
            api, self._api = self._api, None
            if api is None:
                return
            closer = getattr(api, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception as exc:  # noqa: BLE001 - 关闭失败只记录
                    logger.debug("TqSdk close() 异常：%s", exc)

    def __enter__(self) -> "TqSdkFeed":
        """支持 with 语法，保证退出时释放连接。"""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """退出上下文时关闭连接。"""
        self.close()

    # ------------------------- 取数 -------------------------
    def get_history(
        self, symbol: str, start: str, end: str,
        period: str = "1m", limit: int = 0,
    ) -> pd.DataFrame:
        """获取历史 K 线（列：datetime/open/high/low/close/volume/open_interest）。

        ``start`` / ``end`` 为 None 时按「最近 limit 根」取（``get_recent`` 走此路径）。
        无数据抛 ``NoDataError``；任何失败都不返回合成行情。
        """
        period_key, duration = normalize_period(period)
        tq_symbol = to_tq_symbol(symbol)

        with self._lock:
            raw = self._fetch(tq_symbol, duration, start, end, limit)
            df = self._normalize(raw)
            df = self._filter_range(df, start, end)
            if limit and len(df) > int(limit):
                df = df.tail(int(limit))
            df = df.reset_index(drop=True)
            if df.empty:
                raise NoDataError(
                    f"TqSdk 未返回 {tq_symbol} 的 {period_key} K 线"
                    f"（区间 {start or '-'} ~ {end or '-'}）")
            as_of = df["datetime"].iloc[-1]
            return attach_provenance(
                df, "tqsdk", is_synthetic=False, is_stale=False,
                as_of=as_of, note="")

    def get_recent(self, symbol: str, period: str = "D",
                   limit: int = 600) -> pd.DataFrame:
        """取最近 limit 根 K 线（与其它 feed 的 get_recent 契约一致）。"""
        return self.get_history(symbol, None, None, period=period, limit=limit)

    # ------------------------- 内部 -------------------------
    def _fetch(self, tq_symbol: str, duration: int,
               start, end, limit: int) -> Any:
        """调用 TqSdk 取原始 K 线（范围取数与最近取数两条路径）。"""
        api = self._ensure_api()
        try:
            if (start is not None or end is not None) and hasattr(
                    api, "get_kline_data_series"):
                start_dt = pd.to_datetime(start).to_pydatetime() if start else None
                end_dt = pd.to_datetime(end).to_pydatetime() if end else None
                return api.get_kline_data_series(
                    symbol=tq_symbol, duration_seconds=duration,
                    start_dt=start_dt, end_dt=end_dt)
            # 无范围取数：最近 limit 根；有范围但接口不支持 range 时：取足够长的窗口
            if limit and int(limit) > 0:
                n = int(limit)
            else:
                n = 200 if (start is None and end is None) else 8000
            n = max(1, min(n, 8964))
            return api.get_kline_serial(tq_symbol, duration, data_length=n)
        except TqSdkFeedError:
            raise
        except Exception as exc:  # noqa: BLE001 - 网络 / 权限 / 服务端异常统一归类
            raise ConnectFailedError(
                f"TqSdk 取数失败（{tq_symbol}，周期 {duration}s）："
                f"{type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _normalize(raw: Any) -> pd.DataFrame:
        """把 TqSdk 原始表规范为 bar schema（缺失列补 0，保留 settle）。"""
        if raw is None:
            return pd.DataFrame(columns=_BAR_COLUMNS)
        df = raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return pd.DataFrame(columns=_BAR_COLUMNS)
        # 仅价格与时间戳是硬性字段；成交量/持仓量缺失时补 0（TqSdk 部分品种无 OI）
        essential = ("datetime", "open", "high", "low", "close")
        missing = [c for c in essential if c not in df.columns]
        if missing:
            raise ConnectFailedError(
                f"TqSdk 返回数据缺少字段：{', '.join(missing)}")
        df["datetime"] = _bar_datetime(df["datetime"])
        cols = list(_BAR_COLUMNS)
        if "settle" in df.columns:
            cols.append("settle")
        elif "settlement" in df.columns:
            df = df.rename(columns={"settlement": "settle"})
            cols.append("settle")
        df = df[[c for c in cols if c in df.columns]]
        for c in _BAR_COLUMNS:
            if c not in df.columns:
                df[c] = 0.0
        df = (df.sort_values("datetime")
                .drop_duplicates(subset="datetime", keep="last")
                .reset_index(drop=True))
        return df

    @staticmethod
    def _filter_range(df: pd.DataFrame, start, end) -> pd.DataFrame:
        """按区间过滤；``end`` 只给日期时按当日收盘（含）处理。"""
        if df.empty:
            return df
        out = df
        if start:
            out = out[out["datetime"] >= pd.to_datetime(start)]
        if end:
            end_ts = pd.to_datetime(end)
            if len(str(end).strip()) <= 10:      # 仅日期：视为当日 23:59:59
                end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            out = out[out["datetime"] <= end_ts]
        return out.reset_index(drop=True)


# 导入即注册：Config 中 data.source = "tqsdk" 时由 MarketDataManager 识别
register_feed("tqsdk", lambda **kwargs: TqSdkFeed(**kwargs))

__all__ = [
    "TqSdkFeed", "TqSdkCredentials", "TqSdkFeedError",
    "NotInstalledError", "MissingCredentialsError", "ConnectFailedError",
    "NoDataError", "UnsupportedPeriodError", "InvalidSymbolError",
    "normalize_period", "to_tq_symbol", "tqsdk_diagnose",
]

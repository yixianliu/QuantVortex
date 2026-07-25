"""期货品种 AI 辅助预测模块（api 文件夹，与 agnes-2.0-flash.py 同风格）。

设计目标：
    1. 以统一接口对「指定期货品种的历史行情」做 AI 辅助分析与预测；
    2. 优先调用大模型（兼容百度千帆 / Agnes 的 Chat Completions 接口，
       请求体结构见同目录 `function call（第二次请求）.txt`）；
    3. 当无网络 / 未配置 API Key / 未安装 requests 时，自动降级到本地
       统计预测引擎（futures_quant.analytics.Predictor），保证模块在任何
       环境都能跑通、可被回测与 UI 复用；
    4. 输出结构固定（AIAnalysisResult / to_dict），UI 与回测报告可直接消费。

调用方式（与同目录脚本一致）：
    python api/futures_ai_predict.py

重要声明：
    本模块所有「预测 / 分析」均为模型输出（统计外推或大模型基于历史特征的
    判断），**绝非确定性预测，更不构成任何投资建议**。实盘决策须结合自身判断
    与风险管理。大模型接口需要你自己的 API Key，仓库不含任何私密信息。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Sequence


# ----------------------------------------------------------------------------
# 路径：把项目根目录加入 sys.path，便于独立脚本直接 import futures_quant
# ----------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ----------------------------------------------------------------------------
# 配置（与同目录千帆 / Agnes 示例保持一致；通过环境变量覆盖）
# ----------------------------------------------------------------------------
DEFAULT_API_URL = os.environ.get(
    "FUTURES_AI_API_URL", "https://qianfan.baidubce.com/v2/chat/completions")
DEFAULT_MODEL = os.environ.get("FUTURES_AI_MODEL", "deepseek-v3.1-250821")
DEFAULT_API_KEY = os.environ.get("FUTURES_AI_API_KEY", "")


# ----------------------------------------------------------------------------
# 结果结构（固定数据格式，供 UI / 报告消费）
# ----------------------------------------------------------------------------
@dataclass
class AIAnalysisResult:
    """指定期货品种的 AI 辅助分析结果。

    Attributes:
        symbol:        合约代码（如 "rb.SHFE"）。
        direction:     方向研判（看多 / 看空 / 中性）。
        confidence:    置信度（0~1）。
        last_price:    当前最新价。
        target_price:  期末预测中枢价。
        support:       近期支撑。
        resistance:    近期阻力。
        forecast:      逐期预测中枢（与 dates 等长）。
        upper:         情景区间上沿。
        lower:         情景区间下沿。
        dates:         预测期标签。
        key_indicators:关键指标字典（MA / RSI / ATR / 波动率 / 趋势描述等）。
        narrative:     AI 文本分析结论（中文）。
        source:        "llm" 表示大模型生成；"local_model" 表示本地统计引擎。
    """

    symbol: str
    direction: str
    confidence: float
    last_price: float
    target_price: float
    support: float
    resistance: float
    forecast: List[float] = field(default_factory=list)
    upper: List[float] = field(default_factory=list)
    lower: List[float] = field(default_factory=list)
    dates: List[str] = field(default_factory=list)
    key_indicators: Dict[str, Any] = field(default_factory=dict)
    narrative: str = ""
    source: str = "local_model"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def pretty(self) -> str:
        lines = [
            f"合约：{self.symbol}　来源：{self.source}",
            f"方向研判：{self.direction}　置信度：{self.confidence:.0%}",
            f"最新价：{self.last_price:,.2f}　预测中枢：{self.target_price:,.2f}",
            f"支撑：{self.support:,.2f}　阻力：{self.resistance:,.2f}",
            "-" * 48,
            "关键指标：",
        ]
        for k, v in self.key_indicators.items():
            lines.append(f"  · {k}: {v}")
        lines.append("-" * 48)
        lines.append("AI 分析结论：")
        lines.append(self.narrative)
        lines.append("⚠️ 以上为模型输出，非确定性预测，不构成投资建议。")
        return "\n".join(lines)


# ----------------------------------------------------------------------------
# 工具：把行情 DataFrame / 列表规整为统一字段
# ----------------------------------------------------------------------------
def _normalize_bars(bars: Any) -> List[Dict[str, float]]:
    """支持 pandas.DataFrame 或 list[dict]，输出统一字段列表。

    需要字段：datetime, open, high, low, close, volume（可选）。
    """
    if hasattr(bars, "to_dict"):  # DataFrame
        rows = bars.to_dict(orient="records")
    else:
        rows = list(bars)
    out = []
    for r in rows:
        out.append({
            "datetime": str(r.get("datetime", "")),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r.get("volume", 0.0) or 0.0),
        })
    return out


# ----------------------------------------------------------------------------
# 大模型客户端（与同目录千帆 / Agnes 请求体结构一致）
# ----------------------------------------------------------------------------
def _call_llm(prompt: str, api_url: str, api_key: str, model: str,
              timeout: int = 30) -> Optional[str]:
    """调用 Chat Completions 接口，返回 assistant 文本；失败返回 None。

    请求体结构与同目录 `function call（第二次请求）.txt` 一致：
    { model, messages:[{role:system},{role:user}], stream:false }。
    """
    try:
        import requests  # 可选依赖：未安装时直接走本地降级
    except Exception:
        return None
    if not api_key:
        return None
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system",
             "content": "你是一名严谨的期货量化分析师，只基于给定数据做技术性研判，"
                        "不提供任何投资建议，输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    })
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        resp = requests.request("POST", api_url, headers=headers,
                                data=payload, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从模型文本中稳健地解析 JSON（容错花括号范围）。"""
    if not text:
        return None
    s = text.find("{")
    e = text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return None
    try:
        return json.loads(text[s:e + 1])
    except Exception:
        return None


def _build_prompt(symbol: str, bars: List[Dict[str, float]],
                  horizon: int, lookback: int) -> str:
    """构造给大模型的行情摘要 + 结构化输出要求。"""
    window = bars[-lookback:] if lookback else bars
    recent = window[-min(30, len(window)):]
    lines = [f"期货品种：{symbol}", f"近 {len(window)} 根 K 线，最近 {len(recent)} 根明细："]
    for b in recent:
        lines.append(
            f"  {b['datetime']} O={b['open']:.2f} H={b['high']:.2f} "
            f"L={b['low']:.2f} C={b['close']:.2f} V={b['volume']:.0f}")
    lines.append(
        f"请基于以上数据预测未来 {horizon} 根 K 线的走势，"
        "并严格输出如下 JSON（不要任何额外解释）：\n"
        "{\n"
        '  "direction": "看多" | "看空" | "中性",\n'
        '  "confidence": 0.0~1.0,\n'
        '  "target_price": 数值,\n'
        '  "support": 数值,\n'
        '  "resistance": 数值,\n'
        '  "key_indicators": {"趋势": "...", "动能": "..."},\n'
        '  "narrative": "不超过 120 字的中文技术面分析结论"\n'
        "}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 本地统计引擎降级（复用 futures_quant.analytics.Predictor）
# ----------------------------------------------------------------------------
def _local_analyze(symbol: str, bars: List[Dict[str, float]],
                   horizon: int, lookback: int) -> AIAnalysisResult:
    from futures_quant.analytics import Predictor  # 延迟导入，避免无谓依赖

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    dts = [b["datetime"] for b in bars]
    lb = min(lookback, len(bars))
    res = Predictor().predict(
        closes[-lb:], highs[-lb:], lows[-lb:], dts[-lb:],
        horizon=horizon, lookback=lb, freq="1min")

    # 统一方向词表：看涨/看跌/震荡 → 看多/看空/中性
    _dir_map = {"看涨": "看多", "看跌": "看空", "震荡": "中性"}
    direction = _dir_map.get(res.direction, "中性")

    narrative = (
        f"基于近 {lb} 根 K 线的统计外推：方向【{res.direction}】"
        f"（趋势强度 {res.trend_strength:+.2f}）。\n"
        f"均线：{res.metrics.get('ma_alignment')}（快 "
        f"{res.metrics.get('ma_fast')} / 慢 {res.metrics.get('ma_slow')}）；"
        f"RSI {res.metrics.get('rsi')}；ATR {res.metrics.get('atr')}；"
        f"波动率 {res.metrics.get('volatility_pct')}%。\n"
        f"期末预测中枢 {res.target_price:,.2f}（较当前 "
        f"{(res.target_price / res.last_price - 1) * 100:+.2f}%）。"
    )
    return AIAnalysisResult(
        symbol=symbol, direction=direction, confidence=res.confidence,
        last_price=res.last_price, target_price=res.target_price,
        support=res.support, resistance=res.resistance,
        forecast=res.forecast, upper=res.upper, lower=res.lower,
        dates=res.dates, key_indicators=res.metrics, narrative=narrative,
        source="local_model",
    )


# ----------------------------------------------------------------------------
# 主入口类
# ----------------------------------------------------------------------------
class FuturesAIAnalyst:
    """期货品种 AI 辅助分析器（统一接口）。

    用法：
        analyst = FuturesAIAnalyst()                       # 自动：有 Key 走 LLM，否则本地
        res = analyst.analyze("rb.SHFE", df, horizon=20)  # df 含 OHLCV
        print(res.pretty())
    """

    def __init__(self, api_url: str = DEFAULT_API_URL,
                 api_key: str = DEFAULT_API_KEY,
                 model: str = DEFAULT_MODEL) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def analyze(self, symbol: str, bars: Any,
                horizon: int = 20, lookback: int = 120,
                provider: str = "auto", timeout: int = 30) -> AIAnalysisResult:
        """对指定期货品种做 AI 辅助分析。

        Args:
            symbol:   合约代码。
            bars:     DataFrame 或 list[dict]，需含 open/high/low/close（volume 可选）。
            horizon:  预测期数。
            lookback: 回看根数。
            provider: "auto"（默认，有 Key+requests 走 llm，否则 local）/
                      "llm"（强制大模型）/ "local"（强制本地统计引擎）。
            timeout:  LLM 请求超时（秒）。

        Returns:
            AIAnalysisResult
        """
        norm = _normalize_bars(bars)
        if len(norm) < 3:
            raise ValueError("历史数据不足，无法分析（至少需要 3 根 K 线）")

        use_llm = provider in ("llm", "auto")
        if provider == "local":
            use_llm = False

        # 本地统计引擎始终计算（提供可绘制的预测路径）
        local = _local_analyze(symbol, norm, horizon, lookback)

        if not use_llm:
            return local

        # 尝试大模型
        prompt = _build_prompt(symbol, norm, horizon, lookback)
        text = _call_llm(prompt, self.api_url, self.api_key, self.model, timeout)
        parsed = _extract_json(text) if text else None
        if not parsed:
            # 大模型不可用 / 解析失败 → 降级本地
            return local

        try:
            direction = str(parsed.get("direction", local.direction))
            if direction not in ("看多", "看空", "中性"):
                direction = local.direction
            confidence = float(parsed.get("confidence", local.confidence))
            confidence = max(0.0, min(1.0, confidence))
            target = float(parsed.get("target_price", local.target_price))
            support = float(parsed.get("support", local.support))
            resistance = float(parsed.get("resistance", local.resistance))
            ki = parsed.get("key_indicators", local.key_indicators)
            if not isinstance(ki, dict):
                ki = local.key_indicators
            narrative = str(parsed.get("narrative", "")).strip()
            if not narrative:
                narrative = local.narrative
        except Exception:
            return local

        return AIAnalysisResult(
            symbol=symbol, direction=direction, confidence=confidence,
            last_price=local.last_price, target_price=target,
            support=support, resistance=resistance,
            forecast=local.forecast, upper=local.upper, lower=local.lower,
            dates=local.dates, key_indicators=ki,
            narrative=narrative, source="llm",
        )


# ----------------------------------------------------------------------------
# 独立运行入口（与同目录脚本风格一致）
# ----------------------------------------------------------------------------
def main() -> None:
    from futures_quant.data.synthetic import generate_bars

    print("=== 期货品种 AI 辅助预测模块演示 ===\n")
    analyst = FuturesAIAnalyst()
    modes = {"螺纹钢rb": "trend", "白银ag": "range", "沪铜cu": "mixed"}
    for name, mode in modes.items():
        df = generate_bars(symbol=f"{name}.SHFE", mode=mode, n=300, seed=7)
        res = analyst.analyze(name + ".SHFE", df, horizon=20, lookback=120)
        # 不变量自校验
        assert res.forecast and len(res.forecast) == len(res.upper) == len(res.lower)
        assert res.direction in ("看多", "看空", "中性")
        for lo, fc, hi in zip(res.lower, res.forecast, res.upper):
            assert lo <= fc + 1e-6 <= hi + 1e-6, "置信带顺序错误"
            assert lo > 0 and fc > 0 and hi > 0, "出现非正价格"
        assert 0.0 <= res.confidence <= 1.0
        print(f"--- {name}（来源：{res.source}）---")
        print(res.pretty())
        print()

    # 强制本地引擎验证
    local_only = FuturesAIAnalyst().analyze(
        "rb.SHFE", generate_bars(symbol="rb.SHFE", mode="trend", n=200, seed=3),
        horizon=15, provider="local")
    print(f"[OK] 强制本地引擎：方向={local_only.direction} "
          f"目标={local_only.target_price:,.2f} 置信度={local_only.confidence:.0%}")
    print("\n全部自校验通过 ✅")


if __name__ == "__main__":
    main()

"""M3.5 事件总线验收：
- EventBus 独立实例 publish/subscribe 基础契约；
- 业务集成：LinkageBus（预测⇄回测调参画像状态服务）对外事件经 core.events.bus 广播，
  UI 订阅者经事件总线收到 prediction.created / backtest.completed / prediction.hit。
"""
from __future__ import annotations
import sys, os
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from futures_quant.core.events import EventBus
from futures_quant.core.events import bus as EVENTBUS
from futures_quant.ai.linkage_bus import BUS as LINKAGE_BUS


def test_events():
    bus = EventBus()
    received = []
    def handler(payload):
        received.append(payload)
    bus.subscribe("backtest.completed", handler)
    bus.publish("backtest.completed", {"symbol":"rb"})
    assert received == [{"symbol":"rb"}]
    print("test_events.py 全绿")


def test_eventbus_wiring():
    """业务事件经 core.events.bus 广播，订阅者按 topic 收到。"""
    got = []
    EVENTBUS.subscribe("backtest.completed", lambda p: got.append(("backtest", p.get("symbol"))))
    EVENTBUS.subscribe("prediction.created", lambda p: got.append(("prediction", p.get("symbol"))))
    EVENTBUS.subscribe("prediction.hit", lambda p: got.append(("hit", p.get("symbol"))))
    # LinkageBus 对外事件发射应广播到全局总线
    LINKAGE_BUS.push_backtest_result("rb", {"a": 1}, {"sharpe": 1.2})
    LINKAGE_BUS.push_prediction("au", {"bias": 0.3})
    LINKAGE_BUS.record_hit("au", True)
    assert ("backtest", "rb") in got, "缺失 backtest.completed"
    assert ("prediction", "au") in got, "缺失 prediction.created"
    assert ("hit", "au") in got, "缺失 prediction.hit"
    print("test_events.py 事件总线广播链路全绿")


if __name__ == "__main__":
    test_events()
    test_eventbus_wiring()

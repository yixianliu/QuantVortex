"""核心层通用异常定义（M4-06：异步框架统一）。

设计约束：
    中断语义需要同时被「UI 层（``futures_quant.ui.pages.Worker``）」与「引擎层
    （``futures_quant.backtest.backtester.Backtester``）」识别。若把异常定义在 UI 包内，
    引擎就必须反向依赖 UI，违反分层。因此统一在 core 层定义，UI 层仅做再导出。

约定：
    长任务在执行循环内定期调用 ``should_abort()``（由调用方注入）；一旦返回 True，
    即抛出 ``InterruptionError``，由 ``Worker.run`` 捕获并转为 ``interrupted`` 信号，
    UI 据此恢复按钮态（不发 ``finished``，避免半截结果被当成功处理）。
"""
from __future__ import annotations


class InterruptionError(Exception):
    """协作式中断：长任务被用户/页面关闭请求中止时抛出。

    与 ``KeyboardInterrupt`` 类似，属于**控制流**而非错误：调用方不应把它当成
    失败上报给用户（不弹错误框），只需恢复界面可交互状态。
    """


class TimeoutError_(Exception):  # noqa: N818 - 名称需与内置 TimeoutError 区分
    """预留：长任务超时（M4-06⑤ 由 ``Worker`` 的 timeout_ms 触发）。

    当前 ``Worker`` 超时走的是「发 timeout 信号 + terminate」路径，不抛本异常；
    保留类型以便后续引擎侧需要自行实现软超时时使用。
    """


__all__ = ["InterruptionError", "TimeoutError_"]

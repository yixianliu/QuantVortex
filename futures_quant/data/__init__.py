"""数据层包。

导入本包即注册可插拔数据源（阶段 5：TqSdk / SimNow）。
只注册工厂，不导入 tqsdk 本体，因此未安装 tqsdk 也不会阻塞程序启动。
"""
from .tqsdk_feed import TqSdkFeed  # noqa: F401  # 副作用：register_feed("tqsdk", ...)

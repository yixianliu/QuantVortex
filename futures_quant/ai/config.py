"""AI 模型配置管理器。

提供：
    1. 统一的配置读取/写入接口（基于 ConfigManager + 点分路径）；
    2. 配置热更新（修改后调用 apply() 可立即生效，无需重启）；
    3. 配置状态摘要（供 UI 展示，不含敏感值）。

配置结构（写入 user_settings.json）：
    ai.api_key   Agnes AI API 密钥（用户填写，不落盘）
    ai.timeout   请求超时秒数

双模式安全约定（2026-08）：
    调试运行（python main.py）：
        - 密钥可从环境变量 QV_AGNES_API_KEY 注入
        - UI 对话框填写密钥，仅内存持有
        - 密钥永不写入 user_settings.json

    打包运行（FuturesQuant.exe）：
        - 启动时自动清除 user_settings.json 中的 ai.api_key 字段
        - 强制从环境变量 QV_AGNES_API_KEY 读取，不存在则不可用
        - UI 对话框仅用于展示状态，不用于填写密钥（隐藏输入框）
        - 密钥不持久化，进程退出即销毁
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

from ..runtime import is_frozen
from ..storage.config_manager import ConfigManager

logger = logging.getLogger(__name__)


AI_SECTION = "ai"

# 环境变量中的 API 密钥（调试/打包双模式通用入口）
_ENV_KEY = "QV_AGNES_API_KEY"

# 默认值（与 config/settings.json 中的 ai.* 保持一致）
DEFAULTS = {
    "ai.timeout": 30,
    "ai.model": "agnes-3.0-flash",
    "ai.max_tokens": 1024,
    "ai.temperature": 0.3,
}


class AIConfig:
    """AI 模型配置管理器（线程安全）。

    注意：
        - 调试模式：API 密钥仅内存持有，不从磁盘读取/写入
        - 打包模式：启动时强制清除 ai.api_key 持久化字段，仅从环境变量读取
    """

    def __init__(self, config: Optional[ConfigManager] = None) -> None:
        """初始化相关对象。
        
            参数:
                config: Optional[ConfigManager]"""
        self._config = config
        self._api_key: str | None = None
        # M7-05：当前密钥是否来自环境变量（区分 key_source 的 env/memory）
        self._key_from_env = False
        self._callbacks: list[callable] = []
        self._lock = threading.Lock()
        self._frozen = is_frozen()
        # M3-08 ⑥：无 ConfigManager 时的「进程内默认值」副本。
        # 旧实现 `set()` 直接改模块级 DEFAULTS → 一次 set 会**永久污染全局默认值**，
        # 影响之后新建的每一个 AIConfig 实例（含单例重建）。改为实例级副本。
        self._local_defaults: dict[str, Any] = dict(DEFAULTS)

        # 打包模式：启动时清除持久化的 api_key
        if self._frozen:
            self._purge_api_key_from_config()

        # 初始化密钥来源（环境变量 > UI 内存）
        self._refresh_key_from_env()

    # ------------------------------------------------------------------
    # 读取接口
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        """读取配置值（点分路径或 ai.* 前缀）。"""
        # 兼容 ai.timeout 和 timeout 两种写法
        # M3-08 ⑥：必须判 `"ai."` 前缀 —— 只判 `"ai"` 会把 `ai_foo` 这类键
        # 误认为已带前缀，导致读到一个根本不存在的配置项。
        full = (key if key.startswith(AI_SECTION + ".")
                else f"{AI_SECTION}.{key}")
        if self._config is None:
            # 进程内副本按**完整键**存储，与 DEFAULTS 口径一致
            return self._local_defaults.get(full, DEFAULTS.get(full, default))
        return self._config.get(full, DEFAULTS.get(full, default))

    def get_all(self) -> dict[str, Any]:
        """返回当前所有 AI 配置（不含默认值的部分）。"""
        if self._config is None:
            return dict(self._local_defaults)
        # M3-08 ⑥：原实现连跑两遍**完全相同的** for 循环，第二遍（"显式覆盖"）
        # 把第一遍的结果逐键覆盖成同一个值 —— 整段是死代码，删除。
        # 保留第一遍语义：与默认值相同的项返回 None（对应 docstring「不含默认值的部分」）。
        result: dict[str, Any] = {}
        for key, default in DEFAULTS.items():
            val = self._config.get(key)
            result[key] = val if val != default else None
        return result

    # ------------------------------------------------------------------
    # 写入接口（注意：不写入 api_key）
    # ------------------------------------------------------------------
    def set(self, key: str, value: Any) -> None:
        """设置配置值并持久化（api_key 除外）。"""
        if key == "api_key":
            # API 密钥不持久化
            with self._lock:
                self._api_key = str(value) if value else None
            return
        # M3-08 ⑥：前缀补全提到分支之前，保证有无 ConfigManager 时键口径一致
        key = (key if key.startswith(AI_SECTION + ".")
               else f"{AI_SECTION}.{key}")
        if self._config is None:
            # 改实例副本，不再污染模块级 DEFAULTS
            self._local_defaults[key] = value
            return
        self._config.set(key, value)
        self._config.save()

    def save(self) -> bool:
        """强制落盘当前配置（不含密钥）。"""
        if self._config is None:
            return True
        return self._config.save()

    # ------------------------------------------------------------------
    # API 密钥管理
    # ------------------------------------------------------------------
    def set_api_key(self, key: str) -> None:
        """设置 API 密钥（仅内存，不落盘）。

        调试模式：UI 填写密钥时调用
        打包模式：UI 填写密钥，仅内存持有（不落盘）
        """
        with self._lock:
            self._api_key = key.strip() if key else None
            # UI 显式输入/清除 → 覆盖环境变量来源标记（M7-05 key_source）
            self._key_from_env = False

    def get_api_key(self) -> str | None:
        """获取 API 密钥（仅内存）。
        
        返回优先级：内存持有（UI配置） > 环境变量 > None
        
        说明：
        - 首选从内存中的 UI 配置获取（用户明确设置，优先级最高）
        - 其次从环境变量读取（兼容旧配置、打包模式备选）
        - 最后返回 None（未配置）
        """
        with self._lock:
            # 首选内存中的 UI 配置（优先级最高，明确由用户设置）
            if self._api_key:
                return self._api_key
            # 其次从环境变量读取（兼容旧配置、打包模式备选）
            return self._env_key_value()

    def key_source(self) -> str:
        """返回当前生效密钥的来源（M7-05 诊断页用，不含密钥值）。

        返回:
            ``"memory"``：本次会话由 UI 输入（优先级最高）
            ``"env"``：来自环境变量 QV_AGNES_API_KEY
            ``"none"``：未配置
        """
        with self._lock:
            if self._api_key:
                return "env" if self._key_from_env else "memory"
        return "env" if self._env_key_value() else "none"

    def _env_key_value(self) -> str | None:
        """从环境变量读取密钥。"""
        val = os.environ.get(_ENV_KEY, "").strip()
        return val if val else None

    def _refresh_key_from_env(self) -> None:
        """刷新密钥：优先使用环境变量，其次保留内存中的值。"""
        env_key = self._env_key_value()
        if env_key:
            with self._lock:
                self._api_key = env_key
                self._key_from_env = True  # M7-05：记录来源

    # ------------------------------------------------------------------
    # 打包模式专用：清除持久化的 api_key
    # ------------------------------------------------------------------
    def _purge_api_key_from_config(self) -> None:
        """打包模式下启动时强制清除 user_settings.json 中的 ai.api_key。

        确保即使上次调试运行时填入了密钥，打包后也自动清除。
        """
        if self._config is None:
            return
        # 删除 ai.api_key 字段（只删字段，保留其他配置）
        raw = self._config.as_dict()
        ai_section = raw.get(AI_SECTION, {})
        if "api_key" in ai_section:
            del ai_section["api_key"]
            raw[AI_SECTION] = ai_section
            # 写回 config（用 set 会触发 save，这里直接操作底层更简洁）
            self._config.set(f"{AI_SECTION}.api_key", None)
            self._config.save()
            logger.info("[安全] 打包模式：已清除 ai.api_key 持久化字段")

    # ------------------------------------------------------------------
    # 热更新
    # ------------------------------------------------------------------
    def apply(self) -> None:
        """将配置应用到 AgnesLLMClient 单例（热更新，无需重启）。"""
        from ..ai.llm_client import reload_from_config, get_client
        # 1. 先同步非密钥参数（超时、模型名、max_tokens、temperature）
        reload_from_config(self._config)
        # 2. 再同步 API 密钥：使用 get_api_key() 保证优先级（环境变量 > 内存 > None）
        #    这在打包模式下尤为重要：环境变量 QV_AGNES_API_KEY 为最高优先级
        client = get_client()
        client.api_key = self.get_api_key()
        # 3. 触发回调
        with self._lock:
            for cb in list(self._callbacks):
                try:
                    cb()
                except Exception:
                    pass

    def on_changed(self, callback: callable) -> None:
        """注册热更新回调。"""
        with self._lock:
            self._callbacks.append(callback)

    # ------------------------------------------------------------------
    # 状态摘要
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """返回 API 可用性摘要（不含密钥）。"""
        from ..ai.llm_client import api_status, get_client
        c = get_client()
        return {
            **api_status(),
            "configured_base": True,  # 固定为 Agnes AI
            "api_key_set": bool(self.get_api_key()),
            "mode": "frozen" if self._frozen else "debug",
            "timeout": self.get("timeout", 30),
            "model": self.get("model", "agnes-3.0-flash"),
            "max_tokens": self.get("max_tokens", 1024),
            "temperature": self.get("temperature", 0.3),
        }

    def reset_to_defaults(self) -> None:
        """恢复所有 AI 配置到默认值（清除密钥）。"""
        with self._lock:
            self._api_key = None
        if self._config is None:
            return
        for key in DEFAULTS:
            self._config.set(key, None)
        self._config.save()
        self.apply()


# 模块级单例
_instance: Optional[AIConfig] = None
_instance_lock = threading.Lock()


def get_ai_config(config: Optional[ConfigManager] = None) -> AIConfig:
    """获取 AI 配置单例（线程安全）。"""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = AIConfig(config)
        return _instance

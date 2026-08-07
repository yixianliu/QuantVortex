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

import os
import threading
from typing import Any, Optional

from ..runtime import is_frozen
from ..storage.config_manager import ConfigManager


AI_SECTION = "ai"

# 环境变量中的 API 密钥（调试/打包双模式通用入口）
_ENV_KEY = "QV_AGNES_API_KEY"

# 默认值（与 config/settings.json 中的 ai.* 保持一致）
DEFAULTS = {
    "ai.timeout": 30,
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
        self._callbacks: list[callable] = []
        self._lock = threading.Lock()
        self._frozen = is_frozen()

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
        if self._config is None:
            return DEFAULTS.get(key, default)
        # 兼容 ai.timeout 和 timeout 两种写法
        full = f"{AI_SECTION}.{key}" if not key.startswith(AI_SECTION) else key
        return self._config.get(full, DEFAULTS.get(full, default))

    def get_all(self) -> dict[str, Any]:
        """返回当前所有 AI 配置（不含默认值的部分）。"""
        if self._config is None:
            return {k: v for k, v in DEFAULTS.items()}
        result = {}
        for key, default in DEFAULTS.items():
            val = self._config.get(key)
            result[key] = val if val != default else None
        # 显式覆盖
        for key, default in DEFAULTS.items():
            val = self._config.get(key)
            if val is not None:
                result[key] = val
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
        if self._config is None:
            DEFAULTS[key] = value
            return
        key = f"{AI_SECTION}.{key}" if not key.startswith(AI_SECTION) else key
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
        打包模式：此方法被忽略，密钥只能从环境变量注入
        """
        if self._frozen:
            return  # 打包模式不接受手动设置的密钥
        with self._lock:
            self._api_key = key.strip() if key else None

    def get_api_key(self) -> str | None:
        """获取 API 密钥（仅内存）。

        返回优先级：环境变量 > 内存持有 > None
        """
        with self._lock:
            return self._api_key or self._env_key_value()

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
            print(f"[安全] 打包模式：已清除 ai.api_key 持久化字段")

    # ------------------------------------------------------------------
    # 热更新
    # ------------------------------------------------------------------
    def apply(self) -> None:
        """将配置应用到 AgnesLLMClient 单例（热更新，无需重启）。"""
        from ..ai.llm_client import reload_from_config
        reload_from_config(self._config)
        # 同时更新内存中的密钥
        with self._lock:
            key = self._api_key
        # 重新设置到客户端
        from ..ai.llm_client import get_client
        client = get_client()
        client.api_key = key
        # 触发回调
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

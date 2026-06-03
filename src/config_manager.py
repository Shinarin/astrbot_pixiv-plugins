# ============================================================================
# config_manager.py — 插件配置管理（轻量包装 AstrBotConfig）
# ============================================================================
# 从 _conf_schema.json + AstrBot WebUI 获取配置，不再自行管理持久化。
# AstrBot 会自动：
#   1. 读取 _conf_schema.json 在 WebUI 生成设置表单
#   2. 将用户修改保存到 data/config/<plugin>_config.json
#   3. 在插件构造时通过 config: AstrBotConfig 参数注入
#
# ConfigManager 现在只是一个轻量包装，提供：
#   - 类型安全的 get/set 方法
#   - 默认值回退
#   - 兼容旧的 config_mgr.get("key") 调用方式
# ============================================================================

from typing import Any

# 默认配置值（当 AstrBotConfig 中缺少某键时使用）
DEFAULT_CONFIG = {
    "pixiv_refresh_token": "",
    "r18_mode": "safe",
    "r18_admin_id": "",
    "tag_blacklist": "futa",
    "global_dedup_limit": 100,
    "session_dedup_limit": 20,
    "search_max_results": 10,
    "max_retry_count": 3,
    "llm_provider_id": "",
    "tag_enrichment_enabled": True,
    "min_bookmarks": 50,
    "humanized_reply_enabled": True,
    "show_image_info": {
        "show_title": True,
        "show_author": True,
        "show_bookmarks": True,
        "show_tags": True,
        "show_link": True,
    },
    "image_quality": "large",
    "search_sort": "popular_desc",
    "search_max_pages": 10,
    "max_images_per_request": 3,
}


class ConfigManager:
    """
    配置管理器 —— 包装 AstrBot 注入的 AstrBotConfig 字典。

    AstrBot 通过 _conf_schema.json → WebUI → AstrBotConfig 自动管理配置。
    此类仅提供便捷的 get/set 方法和默认值回退。
    """

    def __init__(self, astrbot_config: dict = None) -> None:
        self._config = astrbot_config if astrbot_config is not None else {}

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项，优先 AstrBot 配置 → DEFAULT_CONFIG → default。"""
        if key in self._config:
            return self._config[key]
        if key in DEFAULT_CONFIG:
            return DEFAULT_CONFIG[key]
        return default

    def set(self, key: str, value: Any) -> None:
        """设置配置项（仅内存，持久化由 AstrBot 的 config.save_config() 负责）。"""
        self._config[key] = value

    def get_all(self) -> dict:
        """获取所有配置的合并视图。"""
        result = dict(DEFAULT_CONFIG)
        result.update(self._config)
        return result

    @property
    def r18_mode(self) -> str:
        """R18 模式: "safe" | "off" | "r18_only"。"""
        return self.get("r18_mode", "safe")

    @property
    def is_r18_filtering(self) -> bool:
        """是否正在过滤 R18（safe 模式）。"""
        return self.r18_mode == "safe"

    @property
    def is_r18_only(self) -> bool:
        """是否只看 R18。"""
        return self.r18_mode == "r18_only"

    @property
    def is_token_configured(self) -> bool:
        """Pixiv refresh_token 是否已配置。"""
        return bool(self.get("pixiv_refresh_token", "").strip())

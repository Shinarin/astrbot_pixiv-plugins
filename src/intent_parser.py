# ============================================================================
# intent_parser.py — LLM 意图分类器（LLM 优先架构）
# ============================================================================
# 本模块是插件的核心智能组件。所有非 /pixiv 指令的自然语言消息，
# 都会交由 LLM 分析意图，而非依赖关键词匹配。
#
# 设计原则:
#   1. LLM 优先 — 默认通过 LLM 判断用户意图，不做关键词绕过
#   2. 指令直通 — /pixiv id|tag|r18 指令不经 LLM，直接解析
#   3. 上下文感知 — 在反问流程中，LLM 能结合上一轮对话理解用户
#   4. 安全回退 — LLM 不可用时，回退到关键词匹配（降级方案）
#
# 意图分类流程:
#   /pixiv 指令 → 直接路由（不调 LLM）
#   其他消息   → LLM 分类 → 6 种意图之一
#
# 支持的意图类型:
#   FIND_BY_ID         — 按作品 ID 搜索
#   FIND_BY_TAG        — 按标签搜索
#   TOGGLE_R18         — 切换 R18 过滤
#   HELP               — 查看帮助
#   UNKNOWN            — 无法判断（触发反问）
#   NOT_IMAGE_REQUEST  — 非图片请求（透传给 AstrBot）
# ============================================================================

import json
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from astrbot.api import logger


class IntentType(Enum):
    """用户意图类型枚举。"""
    FIND_BY_ID = auto()
    FIND_BY_TAG = auto()
    TOGGLE_R18 = auto()
    HELP = auto()
    UNKNOWN = auto()
    NOT_IMAGE_REQUEST = auto()


@dataclass
class IntentResult:
    """意图分类结果。"""
    intent_type: IntentType = IntentType.NOT_IMAGE_REQUEST
    params: dict = field(default_factory=dict)
    confidence: float = 0.0
    raw_message: str = ""


# ============================================================================
# LLM Prompt 模板
# ============================================================================

# 意图分类 prompt —— 让 LLM 作为唯一的意图分析器
# 设计要点:
#   - 明确区分"图片请求"和"普通聊天"
#   - 对模糊请求输出 UNKNOWN（而不是强行猜测）
#   - 提取参数时保留用户原文（特别是标签搜索）
INTENT_CLASSIFY_PROMPT = """你是 Pixiv 插画搜索插件的意图分析器。
你的任务是判断用户消息是否与 Pixiv 图片搜索有关，并提取关键参数。

## 意图定义

### FIND_BY_ID — 按作品ID查图
用户明确要查找某个 Pixiv 作品 ID。
关键词: "id", "作品", "编号", "这个图" + 数字ID, Pixiv URL
示例: "找id 12345678"、"帮我查作品119293921"、"https://www.pixiv.net/artworks/12345678"

### FIND_BY_TAG — 按标签/关键词搜图
用户想搜索某类图片，给出了主题/角色/风格等关键词。
关键词: 任何具体的搜索词，不需要包含"图"字。
示例: "找nikke的图"、"有没有原神的插画"、"想看风景"、"来张猫耳少女"、"オリジナル"

### TOGGLE_R18 — 切换R18过滤
用户想开启或关闭成人内容过滤。
示例: "关掉R18过滤"、"开启成人内容"、"r18 off"

### HELP — 查看帮助
用户不知道怎么用，或者问功能相关的问题。
示例: "怎么用"、"有什么功能"、"帮助"

### UNKNOWN — 图片相关但意图模糊
用户提到了"图"、"图片"但没给具体内容，或者只说"来一张"、"发个图"。
这种情况下你需要输出 UNKNOWN，让系统反问用户。
示例: "来张图"、"发个图片"、"有没有好图"

### NOT_IMAGE_REQUEST — 与图片无关
用户消息跟 Pixiv 搜图没有任何关系，是正常的聊天内容。
示例: "你好"、"今天天气怎么样"、"帮我写代码"、"谢谢"、"吃饭了吗"

## 重要规则
1. 标签搜索(FIND_BY_TAG)是最常见的意图。
2. 参数 "tag" 应保留用户的原始搜索意图词。
3. **参数 "count"** 表示用户想要的图片数量：
   - "来张"/"一张"/"找张" → count=1
   - "两张"/"来两张" → count=2
   - "多张"/"几张"/"一些"/"来点" → count=0（表示使用默认值）
   - 未提及数量 → count=1
4. 如果无法确定意图，输出 UNKNOWN。
5. 纯聊天消息输出 NOT_IMAGE_REQUEST。

## 输出格式
{"intent": "<意图类型>", "params": {}, "confidence": <0.0-1.0>}

## 示例
用户: "有没有猫耳少女的图"
{"intent": "FIND_BY_TAG", "params": {"tag": "猫耳少女", "count": 1}, "confidence": 0.9}

用户: "来两张nikke的"
{"intent": "FIND_BY_TAG", "params": {"tag": "nikke", "count": 2}, "confidence": 0.9}

用户: "来多张原神的图"
{"intent": "FIND_BY_TAG", "params": {"tag": "原神", "count": 0}, "confidence": 0.9}

用户: "关掉R18"
{"intent": "TOGGLE_R18", "params": {"enable": false}, "confidence": 0.95}

用户: "来张图"
{"intent": "UNKNOWN", "params": {}, "confidence": 0.3}

用户: "今天吃什么"
{"intent": "NOT_IMAGE_REQUEST", "params": {}, "confidence": 0.95}

用户: "怎么用"
{"intent": "HELP", "params": {}, "confidence": 0.95}

用户: "有没有风景画"
{"intent": "FIND_BY_TAG", "params": {"tag": "風景"}, "confidence": 0.9}

现在分析以下用户消息（只返回 JSON，不要其他文字）：
"""
# 标签富化 prompt —— 将中文描述转为 Pixiv 常用标签
TAG_ENRICH_PROMPT = """你是 Pixiv 标签专家。将用户的中文搜索需求翻译为最适合在 Pixiv 上搜索的标签。

## 规则
1. Pixiv 以日文标签为主，英文标签为辅，中文标签很少
2. 角色名优先用日文原名（如"灰姑娘"→"アナキオール"）
3. 作品名保留最通用的写法
4. 输出 2-3 个标签，按搜索命中率从高到低排列
5. 只返回 JSON 数组，不要其他文字

## 示例
用户搜索: "灰姑娘" (NIKKE游戏)
["アナキオール", "NIKKE Cinderella", "灰姑娘"]

用户搜索: "初音未来"
["初音ミク", "Hatsune Miku", "VOCALOID"]

用户搜索: "猫耳少女"
["猫耳", "猫耳少女", "nekomimi"]

用户搜索: "风景"
["風景", "landscape", "景色"]

用户搜索: "nikke"
["NIKKE", "ニケ", "勝利の女神NIKKE"]

现在转换以下搜索词（只返回 JSON 数组）：
"""

# 反问生成 prompt
HUMANIZED_SEARCH_PROMPT = """你是 Pixiv 插画搜索助手。用户正在等待搜索结果，你需要用自然、拟人的语气告诉他们正在搜索什么。

## 规则
- 用日常对话的语气，不要说"正在搜索标签xxx"
- 像人类一样表达"我帮你找找xxx的图"
- 简短，不超过30字
- 用中文

用户请求: "{user_query}"
搜索关键词: "{search_tags}"

请生成一句拟人化的搜索提示："""
CLARIFY_PROMPT = """你是 Pixiv 图片搜索助手。用户表达了一个模糊的图片请求，你需要友好地反问以明确需求。

## 规则
- 引导用户说出搜索关键词/标签
- 简短、自然，不超过40字
- 给1-2个具体例子提示用户
- 用中文

用户说: "{user_message}"
请生成反问："""


# ============================================================================
# IntentParser
# ============================================================================

class IntentParser:
    """
    LLM 优先的意图分类器。

    默认通过 LLM 分析每条消息的意图。
    /pixiv 指令直接路由，不经过 LLM。
    仅在 LLM 不可用时回退到关键词匹配。
    """

    # 回退用关键词（仅 LLM 不可用时使用）
    _FALLBACK_IMAGE_KW = [
        "图", "图片", "插画", "pixiv", "イラスト", "illust",
        "来张", "找", "搜", "看看",
    ]

    # 正则
    _PIXIV_ID_RE = re.compile(r'\b(\d{6,10})\b')
    _PIXIV_CMD_RE = re.compile(r'/pixiv\s+(id|tag|r18|help|config)', re.IGNORECASE)

    def __init__(self, config_mgr, context=None) -> None:
        """
        Args:
            config_mgr: ConfigManager 实例。
            context:    AstrBot Context（用于 llm_generate 调用独立 LLM）。
        """
        self._config = config_mgr
        self._context = context
        self._persona_prompt: str | None = None

    # ==================================================================
    # 主入口
    # ==================================================================

    async def parse(
        self, message: str, session_id: str, event=None
    ) -> IntentResult:
        """
        解析用户消息意图 —— LLM 优先。

        流程:
          1. /pixiv 指令 → 直接路由
          2. LLM 分类（主要方式）
          3. LLM 不可用 → 关键词回退
        """
        message = message.strip()
        result = IntentResult(raw_message=message)

        if not message:
            result.intent_type = IntentType.NOT_IMAGE_REQUEST
            return result

        # ---- Step 1: /pixiv 显式指令 → 不经 LLM ----
        if self._PIXIV_CMD_RE.search(message):
            return self._parse_command(message, result)

        # ---- Step 2: LLM 分类（主要通路）----
        if event is not None:
            try:
                llm_result = await self._llm_classify(message, event)
                if llm_result is not None:
                    logger.info(
                        f"[pixiv:intent] LLM → {llm_result.intent_type.name} "
                        f"(conf={llm_result.confidence:.2f})"
                    )
                    return llm_result
            except Exception as e:
                logger.warning(f"[pixiv:intent] LLM 分类异常: {e}")

        # ---- Step 3: 回退（LLM 不可用时）----
        logger.warning("[pixiv:intent] LLM 不可用，使用关键词回退")
        return self._fallback_match(message, result)

    # ==================================================================
    # /pixiv 指令解析（不调 LLM）
    # ==================================================================

    def _parse_command(self, message: str, result: IntentResult) -> IntentResult:
        parts = message.split(maxsplit=3)

        if len(parts) < 2:
            result.intent_type = IntentType.HELP
            result.confidence = 1.0
            return result

        cmd = parts[1].lower()

        if cmd == "id" and len(parts) >= 3:
            illust_id = self._extract_illust_id(parts[2])
            if illust_id:
                result.intent_type = IntentType.FIND_BY_ID
                result.params = {"illust_id": illust_id}
                result.confidence = 1.0
            else:
                result.intent_type = IntentType.UNKNOWN
                result.confidence = 0.5

        elif cmd == "tag" and len(parts) >= 3:
            result.intent_type = IntentType.FIND_BY_TAG
            result.params = {"tag": parts[2]}
            result.confidence = 1.0

        elif cmd == "r18" and len(parts) >= 3:
            val = parts[2].lower()
            if val in ("on", "开", "开启", "启用", "true", "1"):
                result.intent_type = IntentType.TOGGLE_R18
                result.params = {"enable": False}
                result.confidence = 1.0
            elif val in ("off", "关", "关闭", "禁用", "false", "0"):
                result.intent_type = IntentType.TOGGLE_R18
                result.params = {"enable": True}
                result.confidence = 1.0

        elif cmd in ("help", "帮助"):
            result.intent_type = IntentType.HELP
            result.confidence = 1.0

        elif cmd == "config":
            result.intent_type = IntentType.UNKNOWN
            result.confidence = 1.0  # 由 main.py 的 cmd_pixiv_config 处理

        else:
            result.intent_type = IntentType.HELP
            result.confidence = 0.8

        return result

    # ==================================================================
    # LLM 分类（核心通路）
    # ==================================================================

    async def _llm_classify(self, message: str, event) -> Optional[IntentResult]:
        """调用 LLM 分析意图。优先用插件专用 LLM，否则用默认。"""
        prompt = INTENT_CLASSIFY_PROMPT + f"\n用户消息: {message}"
        response_text = await self._call_llm(
            prompt=prompt,
            system_prompt="你是精确的意图分类器。只返回JSON，不要任何其他内容。",
        )
        if not response_text:
            return None
        try:
            json_str = self._extract_json(response_text)
            data = json.loads(json_str)
            return self._dict_to_result(data, message)
        except json.JSONDecodeError as e:
            logger.warning(f"[pixiv:intent] LLM JSON 解析失败: {e}")
            return None

    # ==================================================================
    # 角色智能解析（含联网搜索）
    # ==================================================================

    # 角色解析 prompt —— 识别游戏/作品 + 角色名，判断是否需要联网搜索
    CHARACTER_RESOLVE_PROMPT = """你是二次元角色识别专家。分析用户的搜索意图，提取游戏/作品名和角色名。

## 输出格式
{"game": "游戏/作品名（没有则为空字符串）", "character": "角色名（没有则为空字符串）", "need_web_search": false, "note": "简短说明"}

## 规则
1. 如果能确定角色属于哪个游戏/作品，填写 game 字段。
2. 如果角色名是中文昵称/简称（如"尼可"、"胡桃"），填写你知道的日文原名到 character。
3. need_web_search: 如果你**不确定**这个角色是谁、属于哪个作品、或不确定角色的日文名，设为 true。
4. 对于热门角色（原神、崩铁、FGO、NIKKE 等知名游戏角色），你通常能直接识别，need_web_search 应为 false。
5. 对于非常冷门、新出、或你完全不知道的角色，need_web_search 应为 true。

## 示例
用户搜索: "原神角色天使尼可"
{"game": "原神", "character": "ニコ", "need_web_search": false, "note": "原神角色，日文名ニコ（天使のニコ）"}

用户搜索: "nikke灰姑娘"
{"game": "NIKKE", "character": "アナキオール", "need_web_search": false, "note": "NIKKE角色灰姑娘，日文名アナキオール"}

用户搜索: "猫耳少女"
{"game": "", "character": "", "need_web_search": false, "note": "通用标签，非特定角色"}

用户搜索: "xxx2025新番女主"
{"game": "", "character": "xxx", "need_web_search": true, "note": "不确定这个角色，需要联网确认"}

现在分析以下搜索词（只返回 JSON）：
"""

    async def resolve_search_intent(self, user_tag: str, umo: str = "") -> dict:
        """
        解析用户搜索意图：识别游戏/作品 + 角色名，必要时联网搜索。

        流程：
          1. LLM 初步识别 → 提取 game/character + 是否需要联网
          2. 若 need_web_search=true → 调用 AstrBot 内置联网搜索确认角色
          3. 合并结果，返回 {"game": ..., "character": ..., "resolved": bool}

        Args:
            user_tag: 用户原始搜索词。

        Returns:
            {"game": str, "character": str, "resolved": bool, "note": str}
        """
        result = {"game": "", "character": "", "resolved": False, "note": ""}

        # ---- Step 1: LLM 初步识别 ----
        prompt = self.CHARACTER_RESOLVE_PROMPT + f"\n用户搜索: {user_tag}"
        response_text = await self._call_llm(
            prompt=prompt,
            system_prompt="你是二次元角色识别专家。只返回 JSON，不要其他内容。",
        )
        if response_text:
            try:
                json_str = self._extract_json(response_text)
                data = json.loads(json_str)
                result["game"] = data.get("game", "")
                result["character"] = data.get("character", "")
                result["note"] = data.get("note", "")
                need_web = data.get("need_web_search", False)

                if not need_web and result["character"]:
                    result["resolved"] = True
                    logger.info(
                        f"[pixiv:intent] 🎯 角色识别: game='{result['game']}', "
                        f"character='{result['character']}' → {result['note']}"
                    )
                    return result

                if need_web:
                    logger.info(
                        f"[pixiv:intent] 🔍 LLM 不确定角色，尝试联网搜索: "
                        f"'{user_tag}' → {result.get('note', '')}"
                    )
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"[pixiv:intent] 角色解析 JSON 失败: {e}")

        # ---- Step 2: 联网搜索确认角色 ----
        try:
            resolved = await self._web_search_character(user_tag, umo)
            if resolved:
                result["game"] = resolved.get("game", result["game"])
                result["character"] = resolved.get("character", result["character"])
                result["resolved"] = True
                result["note"] = resolved.get("note", "联网搜索确认")
                logger.info(
                    f"[pixiv:intent] 🌐 联网搜索完成: game='{result['game']}', "
                    f"character='{result['character']}'"
                )
        except Exception as e:
            logger.warning(f"[pixiv:intent] 联网搜索失败: {e}")

        return result

    async def _web_search_character(self, user_tag: str, umo: str = "") -> dict | None:
        """
        使用 AstrBot 内置联网搜索工具查找角色信息。

        通过 LLM + web_search tool 组合：让 LLM 搜索角色信息并提取关键字段。

        Returns:
            {"game": str, "character": str, "note": str} 或 None。
        """
        if not self._context:
            return None

        # 获取 AstrBot 内置 web_search 工具
        # 照搬 AstrBot 源码 _apply_web_search_tools 的做法：
        #   读会话配置 websearch_provider → 映射工具类 → get_builtin_tool()
        tool_manager = self._context.get_llm_tool_manager()

        # 读取当前会话的 provider_settings（需 umo 获取正确的会话配置）
        cfg = self._context.get_config(umo=umo) if umo else self._context.get_config()
        prov_settings = cfg.get("provider_settings", {})
        provider = prov_settings.get("websearch_provider", "tavily")

        from astrbot.core.tools.web_search_tools import (
            BaiduWebSearchTool,
            BochaWebSearchTool,
            BraveWebSearchTool,
            FirecrawlWebSearchTool,
            TavilyWebSearchTool,
        )
        tool_class_map = {
            "tavily": TavilyWebSearchTool,
            "bocha": BochaWebSearchTool,
            "brave": BraveWebSearchTool,
            "baidu_ai_search": BaiduWebSearchTool,
            "firecrawl": FirecrawlWebSearchTool,
        }
        tool_cls = tool_class_map.get(provider)
        web_tool = tool_manager.get_builtin_tool(tool_cls) if tool_cls else None

        if web_tool:
            logger.info(
                f"[pixiv:intent] 🌐 使用联网工具: {web_tool.name} "
                f"(provider={provider})"
            )
        else:
            logger.info(
                f"[pixiv:intent] 🌐 无可用联网搜索工具 "
                f"(provider={provider or '未配置'})，跳过"
            )
            return None

        # 构建 tool_set 并调用 LLM
        try:
            from astrbot.api import ToolSet
            tool_set = ToolSet()
            tool_set.add_tool(web_tool)

            search_prompt = (
                f"请搜索「{user_tag}」是哪个游戏/动漫作品的哪个角色。\n"
                f"找到后，请用工具搜索确认角色的日文原名。\n"
                f"最后用 JSON 回复: "
                f'{{"game": "作品名", "character": "日文角色名", "note": "来源说明"}}'
            )

            providers = self._context.get_all_providers()
            provider_id = self._config.get("llm_provider_id", "")
            if not provider_id and providers:
                provider_id = providers[0].meta().id

            resp = await self._context.llm_generate(
                chat_provider_id=provider_id,
                prompt=search_prompt,
                system_prompt="你是二次元角色搜索专家。使用搜索工具查找角色信息，只返回 JSON。",
                tools=tool_set,
            )
            text = resp.completion_text.strip() if hasattr(resp, 'completion_text') else ""
            if text:
                json_str = self._extract_json(text)
                return json.loads(json_str)
        except Exception as e:
            logger.warning(f"[pixiv:intent] 联网搜索调用失败: {e}")

        return None

    # ==================================================================
    # 标签富化
    # ==================================================================

    async def enrich_tags(self, user_tag: str) -> list[str]:
        """
        将用户的中文搜索词转换为 Pixiv 常用标签（日文/英文）。

        用 LLM 生成 2-3 个 Pixiv 上最可能找到高质量结果的搜索标签。
        返回按优先级排序的标签列表。

        Args:
            user_tag: 用户原始搜索词（如 "灰姑娘"、"猫耳少女"）。

        Returns:
            标签列表（如 ["アナキオール", "NIKKE Cinderella", "灰姑娘"]）。
            如果 LLM 不可用或关闭了标签富化，返回 [user_tag]。
        """
        if not self._config.get("tag_enrichment_enabled", True):
            return [user_tag]

        prompt = TAG_ENRICH_PROMPT + f"\n用户搜索: {user_tag}"
        response_text = await self._call_llm(
            prompt=prompt,
            system_prompt="你是 Pixiv 标签专家。只返回 JSON 数组，不要其他内容。",
        )
        if not response_text:
            return [user_tag]

        try:
            json_str = self._extract_json(response_text)
            tags = json.loads(json_str)
            if isinstance(tags, list) and len(tags) > 0:
                # 确保原始标签也在列表中（作为兜底）
                if user_tag not in tags:
                    tags.append(user_tag)
                logger.info(f"[pixiv:intent] 标签富化: '{user_tag}' → {tags}")
                return tags
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[pixiv:intent] 标签富化 JSON 解析失败: {e}")

        return [user_tag]

    # ==================================================================
    # 统一 LLM 调用
    # ==================================================================

    async def _call_llm(self, prompt: str, system_prompt: str = "") -> str | None:
        """
        调用 LLM，优先使用插件专用 LLM（llm_provider_id），否则用 AstrBot 默认。

        Returns:
            LLM 响应文本，或 None。
        """
        provider_id = self._config.get("llm_provider_id", "")

        # ---- 优先使用插件专用 LLM ----
        if provider_id and self._context:
            try:
                resp = await self._context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=system_prompt,
                )
                return resp.completion_text
            except Exception as e:
                logger.warning(
                    f"[pixiv:intent] 专用 LLM({provider_id}) 调用失败: {e}，"
                    f"回退到默认 LLM"
                )

        # ---- 回退: 使用 AstrBot 默认 LLM ----
        if self._context:
            try:
                # 获取默认 provider ID（AstrBot v4.5+ 要求必传 chat_provider_id）
                providers = self._context.get_all_providers()
                default_id = providers[0].meta().id if providers else ""
                resp = await self._context.llm_generate(
                    chat_provider_id=default_id,
                    prompt=prompt,
                    system_prompt=system_prompt,
                )
                return resp.completion_text
            except Exception as e:
                logger.warning(
                    f"[pixiv:intent] 默认 LLM 调用失败: {e}"
                )

        logger.debug("[pixiv:intent] LLM 不可用（无 context）")
        return None

    # ==================================================================
    # 回退分类（LLM 不可用时）
    # ==================================================================

    def _fallback_match(self, message: str, result: IntentResult) -> IntentResult:
        """关键词回退 —— 仅 LLM 不可用时作为降级方案。"""
        msg_lower = message.lower()

        # 检测 ID
        id_match = self._PIXIV_ID_RE.search(message)
        if id_match and any(kw in msg_lower for kw in ["id", "编号", "作品"]):
            result.intent_type = IntentType.FIND_BY_ID
            result.params = {"illust_id": int(id_match.group(1))}
            result.confidence = 0.7
            return result

        # 检测 R18
        if any(kw in msg_lower for kw in ["r18", "成人", "过滤", "色图", "涩图"]):
            result.intent_type = IntentType.TOGGLE_R18
            result.confidence = 0.7
            return result

        # 图片相关
        if any(kw in msg_lower for kw in self._FALLBACK_IMAGE_KW):
            tag = self._extract_tag(message)
            if tag:
                result.intent_type = IntentType.FIND_BY_TAG
                result.params = {"tag": tag}
                result.confidence = 0.5
            else:
                result.intent_type = IntentType.UNKNOWN
                result.confidence = 0.2
        else:
            result.intent_type = IntentType.NOT_IMAGE_REQUEST

        return result

    # ==================================================================
    # 反问生成
    # ==================================================================

    async def generate_clarification(self, message: str, event=None) -> str:
        """为模糊图片请求生成反问。"""
        prompt = CLARIFY_PROMPT + f"\n用户说: {message}\n请生成反问："
        response = await self._call_llm(
            prompt=prompt,
            system_prompt=self._persona_prompt or "你是友好的 Pixiv 搜索助手，用中文简短反问。",
        )
        if response and len(response.strip()) >= 3:
            return response.strip()

        import random
        defaults = [
            "请问想搜什么主题呢？比如「猫耳」「风景」「初音未来」~",
            "想找什么样的图？告诉我关键词吧！",
        ]
        return random.choice(defaults)

    # ==================================================================
    # 拟人化搜索回复
    # ==================================================================

    async def generate_search_reply(self, user_query: str, search_tags: list[str]) -> str:
        """生成拟人化搜索提示。"""
        prompt = HUMANIZED_SEARCH_PROMPT.format(
            user_query=user_query, search_tags=", ".join(search_tags),
        )
        response = await self._call_llm(
            prompt=prompt,
            system_prompt=self._persona_prompt or "你是友好的 Pixiv 搜索助手，用中文简短回复。",
        )
        if response and len(response.strip()) >= 3:
            return response.strip()
        return f"🔍 帮你找找 {search_tags[0] if search_tags else user_query} 的图~"

    # ==================================================================
    # 注入人格提示词（由 main.py 调用）
    # ==================================================================

    def set_persona(self, persona_prompt: str | None) -> None:
        """设置当前会话的人格提示词。"""
        self._persona_prompt = persona_prompt

    def _extract_illust_id(self, text: str) -> Optional[int]:
        text = text.replace("https://www.pixiv.net/artworks/", "")
        text = text.replace("pixiv.net/artworks/", "")
        match = self._PIXIV_ID_RE.search(text)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_tag(message: str) -> Optional[str]:
        """从自然语言中提取搜索标签。"""
        # 噪声词按长度降序排列，避免短词先匹配破坏长词
        noise = [
            "pixiv的", "Pixiv的", "的图片", "来一张",
            "有没有", "pixiv", "Pixiv", "插画",
            "我想看", "一张", "一个", "一些",
            "来张", "给张", "的图", "图片",
            "搜索", "帮我", "看看", "想要",
            "有吗", "找", "搜", "图", "求",
        ]
        tag = message
        for w in noise:
            tag = tag.replace(w, "")
        tag = re.sub(r'[，。！？、；：""''（）【】《》\s]+', ' ', tag).strip()
        # 过滤残留的短噪声字（"的"、"吗"等），但保留有意义的单字标签
        short_noise = {"的", "吗", "呢", "吧", "啊", "呀"}
        words = [w for w in tag.split() if w not in short_noise]
        tag = " ".join(words)
        return tag if len(tag) >= 1 else None

    @staticmethod
    def _extract_json(text: str) -> str:
        """从 LLM 响应中提取 JSON。"""
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if m:
            return m.group(1)
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return m.group(0)
        return text

    @staticmethod
    def _dict_to_result(data: dict, raw_message: str) -> IntentResult:
        result = IntentResult(raw_message=raw_message)
        intent_str = data.get("intent", "NOT_IMAGE_REQUEST")
        result.confidence = float(data.get("confidence", 0.0))

        mapping = {
            "FIND_BY_ID": IntentType.FIND_BY_ID,
            "FIND_BY_TAG": IntentType.FIND_BY_TAG,
            "TOGGLE_R18": IntentType.TOGGLE_R18,
            "HELP": IntentType.HELP,
            "UNKNOWN": IntentType.UNKNOWN,
            "NOT_IMAGE_REQUEST": IntentType.NOT_IMAGE_REQUEST,
        }
        result.intent_type = mapping.get(intent_str, IntentType.NOT_IMAGE_REQUEST)

        params = data.get("params", {})
        if isinstance(params, dict):
            result.params = params

        return result

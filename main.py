# ============================================================================
# astrbot_pixiv-plugins — 插件入口 (main.py)
# ============================================================================
# Pixiv 图片检索插件，支持指令和自然语言两种交互方式。
#
# 设置方式：AstrBot WebUI → 插件管理 → astrbot_pixiv-plugins → 设置
#   （基于 _conf_schema.json 自动生成设置表单，无需手动输指令配置）
#
# 触发条件：私聊直接触发，群聊需 @机器人。
# ============================================================================

import asyncio
import os
import re
import sys
from typing import Optional

# 确保插件目录在 Python 搜索路径中，使 src/ 子模块可被导入
_plugin_dir = os.path.dirname(os.path.abspath(__file__))
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.event.filter import CustomFilter
from astrbot.api.star import Context, Star
from astrbot.api import logger


# ---------------------------------------------------------------------------
# 自定义消息过滤器 —— 决定哪些消息进入自然语言处理流程
# ---------------------------------------------------------------------------

class PixivMessageFilter(CustomFilter):
    """
    拦截所有消息，私聊全部通过，群聊仅 @机器人 的消息通过。
    具体意图分类由 handler 内部完成。
    """

    def __init__(self, raise_error: bool = False):
        super().__init__(raise_error=raise_error)

    def filter(self, event: AstrMessageEvent, cfg) -> bool:
        """
        判断消息是否应被拦截处理。

        Returns:
            True: 消息进入 natural_language_handler 处理
            False: 消息被忽略
        """
        message = event.message_str.strip()
        if not message:
            return False

        # 跳过 /pixiv 显式指令（由 command 处理器单独处理）
        if message.startswith("/pixiv") or message.startswith("/PIXIV"):
            return False

        # 私聊：全部通过
        if event.is_private_chat():
            return True

        # 群聊：必须 @机器人
        if event.is_at_or_wake_command:
            return True

        return False


class AstrBotPixivPlugin(Star):
    """
    AstrBot Pixiv 图片检索插件主类。

    通过 AstrBot 的 filter 装饰器注册命令和消息拦截器。
    config 参数由 AstrBot 自动注入（基于 _conf_schema.json）。
    """

    def __init__(self, context: Context, config: dict = None) -> None:
        """
        Args:
            context: AstrBot 上下文对象。
            config:  AstrBot 注入的配置字典（AstrBotConfig），
                     基于 _conf_schema.json 由 WebUI 管理。
        """
        super().__init__(context)

        # 子模块实例（在 initialize() 中初始化）
        self.pixiv_client = None
        self.dedup_mgr = None
        self.config_mgr = None
        self.conv_state = None
        self.intent_parser = None

        # 保存原始 config 引用（供 R18 切换时持久化）
        self._raw_config = config

        self._cleanup_task: Optional[asyncio.Task] = None

    # ==================================================================
    # 生命周期
    # ==================================================================

    async def initialize(self) -> None:
        logger.info("=" * 50)
        logger.info("[pixiv] 🎨 astrbot_pixiv-plugins 正在初始化...")
        logger.info("=" * 50)

        from src.config_manager import ConfigManager
        from src.pixiv_client import PixivClient
        from src.dedup_manager import DedupManager
        from src.conversation_state import ConversationStateManager
        from src.intent_parser import IntentParser

        # 1. 配置管理器（包装 AstrBotConfig）
        self.config_mgr = ConfigManager(self._raw_config)

        # 2. Pixiv 客户端
        self.pixiv_client = PixivClient(self.config_mgr)
        refresh_token = self.config_mgr.get("pixiv_refresh_token")
        if refresh_token:
            try:
                await self.pixiv_client.login(refresh_token)
                logger.info("[pixiv] ✅ Pixiv API 登录成功")
                # 诊断: 测试 API 连通性
                test_result = await self.pixiv_client.test_connection()
                if test_result.get("ok"):
                    logger.info(
                        f"[pixiv] ✅ API 连通性正常, "
                        f"排行榜样本数={test_result.get('sample_count')}, "
                        f"样本ID={test_result.get('sample_id')}"
                    )
                else:
                    logger.warning(
                        f"[pixiv] ⚠️ API 连通性异常: {test_result.get('error')}"
                    )
            except Exception as e:
                logger.warning(f"[pixiv] ⚠️ Pixiv API 登录失败: {e}")
        else:
            logger.warning("[pixiv] ⚠️ 未配置 pixiv_refresh_token")
            logger.warning("[pixiv] 请在 WebUI 插件设置页面配置 refresh_token")

        # 3. 去重管理器
        self.dedup_mgr = DedupManager(self.context, self.config_mgr)
        await self.dedup_mgr.initialize()

        # 4. 对话状态机
        self.conv_state = ConversationStateManager()

        # 5. 意图解析器（传入 context 以支持独立 LLM 调用）
        self.intent_parser = IntentParser(self.config_mgr, self.context)

        # 6. 注册 LLM Tools
        self._register_llm_tools()

        # 7. 超时清理
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info("[pixiv] ✅ 插件初始化完成！")
        logger.info("[pixiv] 设置: WebUI → 插件 → astrbot_pixiv-plugins → 设置")
        logger.info("[pixiv] 指令: /pixiv id|tag|r18|help")
        logger.info("=" * 50)

    async def terminate(self) -> None:
        logger.info("[pixiv] 插件正在终止...")
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        if self.pixiv_client:
            await self.pixiv_client.close()
        if self.dedup_mgr:
            self.dedup_mgr.close()
        if self.conv_state:
            self.conv_state.clear_all()
        logger.info("[pixiv] ✅ 插件已终止")

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(60)
                if self.conv_state:
                    await self.conv_state.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[pixiv] 清理循环异常: {e}")

    # ==================================================================
    # LLM Tool 注册
    # ==================================================================

    def _register_llm_tools(self) -> None:
        try:
            self.context.register_llm_tool(
                name="pixiv_search_by_id",
                func_args=["illust_id"],
                desc="按 Pixiv 作品 ID 搜索插画。illust_id 为数字 ID。",
                func_obj=self._tool_search_by_id,
            )
            self.context.register_llm_tool(
                name="pixiv_search_by_tag",
                func_args=["tag"],
                desc="按标签/关键词搜索 Pixiv 插画。tag 为搜索关键词。",
                func_obj=self._tool_search_by_tag,
            )
            self.context.register_llm_tool(
                name="pixiv_toggle_r18",
                func_args=["enable"],
                desc="开启或关闭 Pixiv R18 内容过滤。enable=true 表示过滤。",
                func_obj=self._tool_toggle_r18,
            )
            logger.info("[pixiv] ✅ 已注册 3 个 LLM Tools")
        except Exception as e:
            logger.warning(f"[pixiv] LLM Tool 注册失败: {e}")

    def _tool_search_by_id(self, illust_id: int) -> str:
        return f"[pixiv] 请使用 /pixiv id {illust_id} 指令来搜索该作品"

    def _tool_search_by_tag(self, tag: str) -> str:
        return f"[pixiv] 请使用 /pixiv tag {tag} 指令来搜索相关作品"

    def _tool_toggle_r18(self, enable: bool) -> str:
        action = "开启" if enable else "关闭"
        return f"[pixiv] R18 过滤已{action}"

    # ==================================================================
    # /pixiv 命令组
    # ==================================================================

    @filter.command_group("pixiv")
    def pixiv_group(self):
        pass

    # ------------------------------------------------------------------
    # /pixiv id <illust_id>
    # ------------------------------------------------------------------

    @pixiv_group.command("id")
    async def cmd_pixiv_id(self, event: AstrMessageEvent, illust_id: str = ""):
        """按 Pixiv 作品 ID 搜索插画。"""
        if not self.pixiv_client or not self.pixiv_client.is_logged_in:
            yield event.plain_result(
                "⚠️ Pixiv 未登录。请在 WebUI 插件设置页面配置 refresh_token。"
            )
            return

        illust_id_int = self.intent_parser._extract_illust_id(
            illust_id if illust_id else event.message_str
        )
        if not illust_id_int:
            yield event.plain_result("❌ 请提供有效的作品 ID。\n示例: /pixiv id 12345678")
            return

        yield event.plain_result(f"🔍 正在查找作品 ID: {illust_id_int} ...")

        try:
            info = await self.pixiv_client.search_by_id(illust_id_int)
            if info is None:
                yield event.plain_result(f"❌ 作品 ID {illust_id_int} 不存在或已被删除。")
                return

            r18_mode = self.config_mgr.r18_mode
            if r18_mode == "safe" and info.is_r18:
                yield event.plain_result(
                    f"⚠️ 该作品为 R18 内容，当前已开启 R18 过滤。\n"
                    f"如需查看，请在 WebUI 设置中关闭 R18 过滤，或使用 /pixiv r18 off"
                )
                return

            # 下载图片（按质量设置选择 URL）
            quality = self.config_mgr.get("image_quality", "large")
            dl_url = info.get_image_url_for_quality(quality)
            image_bytes = await self.pixiv_client.download_image(dl_url)
            if image_bytes is None:
                yield event.plain_result(f"❌ 图片下载失败，请稍后重试。\n{info.page_url}")
                return

            session_id = event.get_session_id()
            self.dedup_mgr.mark_sent(info.illust_id, session_id)

            img_path = self._save_temp_image(image_bytes, info.illust_id)
            info_cfg = self.config_mgr.get("show_image_info", {})
            result = event.make_result()
            result.file_image(img_path)
            msg = info.to_message_text(info_cfg)
            if msg:
                result.message(msg)
            yield result

        except Exception as e:
            logger.error(f"[pixiv] cmd_pixiv_id 错误: {e}", exc_info=True)
            yield event.plain_result(f"❌ 搜索失败: {e}")

    # ------------------------------------------------------------------
    # /pixiv tag <tag>
    # ------------------------------------------------------------------

    @pixiv_group.command("tag")
    async def cmd_pixiv_tag(self, event: AstrMessageEvent, tag: str = "", count: int = 1):
        """按标签搜索 Pixiv 插画，支持多张。"""
        await self._search_and_send_images(event, tag, count)

    # ------------------------------------------------------------------
    # /pixiv r18 <on|off>
    # ------------------------------------------------------------------

    @pixiv_group.command("r18")
    async def cmd_pixiv_r18(self, event: AstrMessageEvent, action: str = ""):
        """R18 模式: safe / off / r18_only（切换需管理员权限）。"""
        action_lower = action.lower().strip() if action else ""
        mode_labels = {"safe": "过滤 R18（全年龄）🔒", "off": "关闭过滤（全部）🔓", "r18_only": "只看 R18 ⚠️"}
        current = self.config_mgr.r18_mode

        # 查看模式：任何人可看
        if not action_lower:
            yield event.plain_result(
                f"📋 当前 R18 模式: {mode_labels.get(current, current)}\n"
                f"切换: /pixiv r18 safe / off / r18_only"
            )
            return

        # 切换模式：需要管理员权限
        admin_id = self.config_mgr.get("r18_admin_id", "").strip()
        sender_id = event.get_sender_id()
        if admin_id and str(sender_id) != admin_id:
            yield event.plain_result("⛔ 只有插件管理员才能切换 R18 模式。")
            return

        if action_lower in ("safe", "过滤", "开启"):
            self.config_mgr.set("r18_mode", "safe")
            await self._save_config()
            yield event.plain_result("🔒 已切换为「过滤 R18」模式。")
        elif action_lower in ("off", "关闭", "全部"):
            self.config_mgr.set("r18_mode", "off")
            await self._save_config()
            yield event.plain_result("🔓 已切换为「关闭过滤」模式。")
        elif action_lower in ("r18_only", "仅r18", "只看r18"):
            self.config_mgr.set("r18_mode", "r18_only")
            await self._save_config()
            yield event.plain_result("⚠️ 已切换为「只看 R18」模式。")
        else:
            yield event.plain_result(
                f"❌ 无效参数「{action}」。\n"
                f"• /pixiv r18 safe    — 过滤 R18\n"
                f"• /pixiv r18 off     — 关闭过滤\n"
                f"• /pixiv r18 r18_only — 只看 R18"
            )

    # ------------------------------------------------------------------
    # /pixiv test — 诊断 API 连通性
    # ------------------------------------------------------------------

    @pixiv_group.command("test")
    async def cmd_pixiv_test(self, event: AstrMessageEvent):
        """测试 Pixiv API 连通性。"""
        if not self.pixiv_client or not self.pixiv_client.is_logged_in:
            yield event.plain_result("⚠️ 未登录，无法测试。")
            return
        yield event.plain_result("🔍 正在测试 Pixiv API 连通性...")
        test = await self.pixiv_client.test_connection()
        if test.get("ok"):
            yield event.plain_result(
                f"✅ API 正常！\n"
                f"排行榜样本: {test.get('sample_count')} 个\n"
                f"样本作品ID: {test.get('sample_id')}"
            )
        else:
            yield event.plain_result(f"❌ API 异常: {test.get('error')}")

    # ------------------------------------------------------------------
    # /pixiv help
    # ------------------------------------------------------------------

    @pixiv_group.command("help")
    async def cmd_pixiv_help(self, event: AstrMessageEvent):
        """显示帮助信息。"""
        help_text = (
            "🎨 **Pixiv 图片检索插件 使用帮助**\n\n"
            "**指令列表:**\n"
            "• `/pixiv id <作品ID>` — 按作品 ID 搜索\n"
            "  例: `/pixiv id 12345678`\n\n"
            "• `/pixiv tag <标签>` — 按标签搜索\n"
            "  例: `/pixiv tag 猫耳少女`\n\n"
            "• `/pixiv r18 <safe/off/r18_only>` — R18 模式切换\n"
            "  例: `/pixiv r18 off` 关闭过滤\n\n"
            "• `/pixiv help` — 显示本帮助\n\n"
            "**⚙️ 设置方式:**\n"
            "WebUI → 插件管理 → astrbot_pixiv-plugins → 设置\n"
            "包括: Pixiv Token、R18 过滤、去重数量等\n\n"
            "**自然语言:**\n"
            "也可以直接说「找一张猫娘的图」自动搜索\n"
            "⚠️ 群聊中需 @我 才能触发"
        )
        yield event.plain_result(help_text)

    # ------------------------------------------------------------------
    # /pixiv config — 仅查看（设置请用 WebUI）
    # ------------------------------------------------------------------

    @pixiv_group.command("config")
    async def cmd_pixiv_config(self, event: AstrMessageEvent):
        """查看当前配置（只读）。如需修改请使用 WebUI 设置页面。"""
        all_config = self.config_mgr.get_all()
        lines = [
            "📋 **当前配置（只读）**",
            "💡 修改设置请前往: WebUI → 插件 → astrbot_pixiv-plugins → 设置",
            "",
        ]
        for k, v in all_config.items():
            if "token" in k and v:
                display_v = str(v)[:8] + "****" + str(v)[-4:] if len(str(v)) > 12 else "****"
            else:
                display_v = v
            lines.append(f"• `{k}` = {display_v}")
        yield event.plain_result("\n".join(lines))

    # ==================================================================
    # 自然语言消息拦截器
    # ==================================================================

    @filter.custom_filter(PixivMessageFilter)
    async def natural_language_handler(self, event: AstrMessageEvent):
        """自然语言消息处理器。由 PixivMessageFilter 预过滤。"""
        message = event.message_str.strip()
        if not message:
            return

        # 群聊消息去除 @前缀
        if not event.is_private_chat():
            message = self._clean_at_prefix(message)
        if not message.strip():
            return

        # 跳过 pixiv 指令（已被 command handler 处理，避免重复执行）
        if message.startswith("pixiv ") or message.startswith("/pixiv"):
            event.continue_event()
            return

        session_id = event.get_session_id()

        if self.conv_state.is_waiting(session_id):
            async for r in self._handle_clarification_response(message, session_id, event):
                yield r
            return

        from src.intent_parser import IntentType

        intent_result = await self.intent_parser.parse(
            message=message, session_id=session_id, event=event,
        )
        logger.info(
            f"[pixiv] 意图: {intent_result.intent_type.name} "
            f"(conf={intent_result.confidence:.2f}) msg=\"{message[:40]}\""
        )

        intent_type = intent_result.intent_type
        if intent_type == IntentType.FIND_BY_ID:
            async for r in self._nl_find_by_id(intent_result, event, session_id):
                yield r
            event.stop_event()
        elif intent_type == IntentType.FIND_BY_TAG:
            async for r in self._nl_find_by_tag(intent_result, event, session_id):
                yield r
            event.stop_event()
        elif intent_type == IntentType.TOGGLE_R18:
            async for r in self._nl_toggle_r18(intent_result, event):
                yield r
            event.stop_event()
        elif intent_type == IntentType.HELP:
            async for r in self.cmd_pixiv_help(event):
                yield r
            event.stop_event()
        elif intent_type == IntentType.UNKNOWN:
            async for r in self._nl_unknown(message, session_id, event):
                yield r
            event.stop_event()
        else:
            # 非图片请求 → 清除插件空结果，原话交给 AstrBot
            event.clear_result()
            event.continue_event()

    # ==================================================================
    # 自然语言子处理
    # ==================================================================

    async def _nl_find_by_id(self, intent_result, event, session_id):
        illust_id = intent_result.params.get("illust_id")
        if not illust_id:
            await self.conv_state.set_waiting(session_id, intent_result.raw_message)
            yield event.plain_result("🤔 您想找哪个作品呢？请提供作品 ID（纯数字）。")
            return
        async for r in self.cmd_pixiv_id(event, str(illust_id)):
            yield r

    async def _nl_find_by_tag(self, intent_result, event, session_id):
        """自然语言 → 按标签搜索。"""
        tag = intent_result.params.get("tag")
        if not tag:
            clarification = await self.intent_parser.generate_clarification(
                intent_result.raw_message, event
            )
            await self.conv_state.set_waiting(session_id, intent_result.raw_message)
            yield event.plain_result(f"🤔 {clarification}")
            return
        raw_count = intent_result.params.get("count", 0)
        max_n = self.config_mgr.get("max_images_per_request", 3)
        count = max_n if raw_count <= 0 else min(raw_count, max_n)
        async for r in self._search_and_send_images(event, tag, count):
            yield r

    async def _nl_toggle_r18(self, intent_result, event):
        enable = intent_result.params.get("enable")
        action = "on" if enable else "off"
        async for r in self.cmd_pixiv_r18(event, action):
            yield r

    async def _nl_unknown(self, message, session_id, event):
        clarification = await self.intent_parser.generate_clarification(message, event)
        await self.conv_state.set_waiting(session_id, message)
        yield event.plain_result(f"🤔 {clarification}")

    async def _handle_clarification_response(self, message, session_id, event):
        from src.intent_parser import IntentType

        intent_result = await self.intent_parser.parse(
            message=message, session_id=session_id, event=event,
        )
        if intent_result.intent_type in (
            IntentType.FIND_BY_ID, IntentType.FIND_BY_TAG,
            IntentType.TOGGLE_R18, IntentType.HELP,
        ):
            await self.conv_state.clear(session_id)
            if intent_result.intent_type == IntentType.FIND_BY_ID:
                async for r in self._nl_find_by_id(intent_result, event, session_id):
                    yield r
            elif intent_result.intent_type == IntentType.FIND_BY_TAG:
                async for r in self._nl_find_by_tag(intent_result, event, session_id):
                    yield r
            elif intent_result.intent_type == IntentType.TOGGLE_R18:
                async for r in self._nl_toggle_r18(intent_result, event):
                    yield r
            elif intent_result.intent_type == IntentType.HELP:
                async for r in self.cmd_pixiv_help(event):
                    yield r
        else:
            await self.conv_state.clear(session_id)
            yield event.plain_result(
                "😔 抱歉，仍然无法理解您的需求。\n\n"
                "请使用以下明确指令：\n"
                "• `/pixiv id <作品ID>` — 按 ID 搜索\n"
                "• `/pixiv tag <标签>` — 按标签搜索\n"
                "• `/pixiv help` — 查看帮助"
            )

    # ==================================================================
    # 核心: 按标签搜索并发送多张图片
    # ==================================================================

    async def _search_and_send_images(
        self, event: AstrMessageEvent, tag: str, count: int = 1
    ):
        """
        搜索并发送指定数量的图片。

        Args:
            event: 消息事件。
            tag:   用户原始搜索标签。
            count: 需要的图片数量（不超过 max_images_per_request）。
        """
        if not self.pixiv_client or not self.pixiv_client.is_logged_in:
            yield event.plain_result(
                "⚠️ Pixiv 未登录。请在 WebUI 插件设置页面配置 refresh_token。"
            )
            return

        if not tag:
            yield event.plain_result("❌ 请提供搜索标签。")
            return

        r18_mode = self.config_mgr.r18_mode
        session_id = event.get_session_id()
        max_n = self.config_mgr.get("max_images_per_request", 3)
        count = max(1, min(count, max_n))

        # 标签富化
        enriched_tags = await self.intent_parser.enrich_tags(tag)

        # 拟人化搜索提示
        if count > 1:
            hint = f"帮你找 {count} 张 {tag} 的图~"
        else:
            hint = f"帮你找找 {tag} 的图~"
        if self.config_mgr.get("humanized_reply_enabled", True):
            # 注入当前 AstrBot 人格提示词，让回复带有人格风味
            await self._inject_persona(event)
            reply = await self.intent_parser.generate_search_reply(tag, enriched_tags)
            # 如果 LLM 返回了数量信息，保留它
            if "张" not in reply and count > 1:
                reply = hint
        else:
            reply = hint
        yield event.plain_result(reply)

        sent = 0
        for i in range(count):
            try:
                info = await self.pixiv_client.search_by_tags(
                    tags=enriched_tags, session_id=session_id,
                    dedup_mgr=self.dedup_mgr, r18_mode=r18_mode,
                )
                if info is None:
                    if sent == 0:
                        yield event.plain_result(f"😔 没找到 {tag} 相关的图，换个关键词试试？")
                    else:
                        yield event.plain_result(f"（共找到 {sent} 张，没有更多了）")
                    return

                quality = self.config_mgr.get("image_quality", "large")
                dl_url = info.get_image_url_for_quality(quality)
                image_bytes = await self.pixiv_client.download_image(dl_url)
                if image_bytes is None:
                    continue

                self.dedup_mgr.mark_sent(info.illust_id, session_id)
                img_path = self._save_temp_image(image_bytes, info.illust_id)
                info_cfg = self.config_mgr.get("show_image_info", {})
                result = event.make_result()
                result.file_image(img_path)
                msg = info.to_message_text(info_cfg)
                if count > 1 and msg:
                    msg = f"({sent + 1}/{count})\n{msg}"
                if msg:
                    result.message(msg)
                yield result
                sent += 1

            except Exception as e:
                logger.error(f"[pixiv] _search_and_send_images 第{i}张异常: {e}")
                continue

    # ==================================================================
    # 工具方法
    # ==================================================================

    async def _save_config(self) -> None:
        """持久化配置。"""
        try:
            if hasattr(self._raw_config, 'save_config'):
                self._raw_config.save_config()
                logger.debug("[pixiv] 配置已保存 (save_config)")
            elif hasattr(self._raw_config, 'save'):
                self._raw_config.save()
                logger.debug("[pixiv] 配置已保存 (save)")
            else:
                logger.warning("[pixiv] 无法保存配置: _raw_config 无 save 方法")
        except Exception as e:
            logger.warning(f"[pixiv] 配置保存失败: {e}")

    async def _inject_persona(self, event: AstrMessageEvent) -> None:
        """
        从 AstrBot 获取当前会话的人格提示词，注入到 intent_parser，
        使 LLM 生成的拟人化回复带有人格风味。
        """
        try:
            persona_mgr = self.context.persona_manager
            persona = await persona_mgr.get_default_persona_v3(
                umo=event.unified_msg_origin
            )
            prompt = persona.get("prompt", "") if persona else ""
            if prompt:
                # 加上指示：按此人格风格回复
                self.intent_parser.set_persona(
                    f"请严格按以下人格设定来组织你的回复语气和风格：\n{prompt}"
                )
                logger.debug("[pixiv] 人格提示词已注入")
            else:
                self.intent_parser.set_persona(None)
        except Exception as e:
            logger.debug(f"[pixiv] 获取人格失败（非关键）: {e}")
            self.intent_parser.set_persona(None)

    @staticmethod
    def _clean_at_prefix(message: str) -> str:
        message = re.sub(r'\[CQ:at[^\]]*\]', '', message).strip()
        message = re.sub(r'^@\S+\s*', '', message).strip()
        return message

    @staticmethod
    def _save_temp_image(image_bytes: bytes, illust_id: int) -> str:
        """将图片 bytes 保存为临时文件，返回文件路径。"""
        import tempfile
        # 尝试从 bytes 头判断文件格式
        ext = ".jpg"
        if image_bytes[:4] == b'\x89PNG':
            ext = ".png"
        elif image_bytes[:4] == b'GIF8':
            ext = ".gif"
        tmp = tempfile.NamedTemporaryFile(
            suffix=ext, prefix=f"pixiv_{illust_id}_", delete=False
        )
        tmp.write(image_bytes)
        tmp.close()
        return tmp.name

    # ==================================================================
    # 错误处理
    # ==================================================================

    @filter.on_plugin_error()
    async def on_error(self, event, plugin_name, handler_name, error, traceback_text):
        if plugin_name != "astrbot_pixiv-plugins":
            return
        logger.error(f"[pixiv] 异常 | handler={handler_name} | error={error}\n{traceback_text}")
        if self.conv_state:
            await self.conv_state.clear(event.get_session_id())

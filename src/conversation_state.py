# ============================================================================
# conversation_state.py — 对话状态机
# ============================================================================
# 管理用户与插件的对话状态，实现"反问1次后终止"的交互流程。
#
# 状态流转:
#   IDLE ──(用户发来模糊指令)──▶ WAITING_CLARIFICATION
#   WAITING_CLARIFICATION ──(用户回复)──▶
#       ├── 回复清晰 → 执行操作 → IDLE
#       └── 回复仍不清晰 → 回复终止提示 → IDLE
#
# 特性:
#   - 超时自动清理: 5 分钟无活动自动回到 IDLE
#   - 每个会话独立状态: 不同群聊/私聊互不干扰
#   - 线程安全: 使用 asyncio.Lock 保护状态操作
#
# 使用示例:
#   state_mgr = ConversationStateManager()
#   # 用户发送模糊指令
#   state_mgr.set_waiting(session_id, "给我一张图")
#   # 用户回复
#   if state_mgr.is_waiting(session_id):
#       orig_query = state_mgr.get_original_query(session_id)
#       # 尝试解析回复...
#       state_mgr.clear(session_id)
# ============================================================================

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from astrbot.api import logger


class ConversationState(Enum):
    """对话状态枚举。"""
    IDLE = auto()                   # 空闲，无进行中的对话
    WAITING_CLARIFICATION = auto()  # 等待用户澄清意图


@dataclass
class SessionState:
    """
    单个会话的状态数据。

    Attributes:
        state:           当前状态。
        original_query:  触发反问的原始消息。
        clarify_count:   已反问次数。
        timestamp:       状态创建时间（用于超时判断）。
    """
    state: ConversationState = ConversationState.IDLE
    original_query: str = ""
    clarify_count: int = 0
    timestamp: float = field(default_factory=time.monotonic)


class ConversationStateManager:
    """
    对话状态管理器。

    管理多个会话的状态，提供状态查询、设置和超时清理功能。
    每个会话（由 session_id 标识）独立维护状态。

    线程安全: 所有状态修改操作由 asyncio.Lock 保护。
    """

    # 状态超时时间（秒）—— 5 分钟无交互自动清除
    STATE_TIMEOUT = 300.0

    # 最大反问次数
    MAX_CLARIFY_COUNT = 1

    def __init__(self) -> None:
        """初始化状态管理器。"""
        self._sessions: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()
        logger.debug("[pixiv:state] 对话状态管理器已创建")

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def is_waiting(self, session_id: str) -> bool:
        """
        检查指定会话是否处于"等待用户澄清"状态。

        本方法为只读查询，超时清理由 cleanup_expired() 统一负责，
        避免在查询路径中无锁修改共享状态。

        Args:
            session_id: 会话 ID。

        Returns:
            True 表示正在等待用户回复。
        """
        state = self._sessions.get(session_id)
        if state is None:
            return False

        # 检查超时（仅判断，不修改——由 cleanup_expired 统一清理）
        if self._is_timed_out(state):
            return False

        return state.state == ConversationState.WAITING_CLARIFICATION

    def get_original_query(self, session_id: str) -> str:
        """
        获取触发反问的原始消息。

        Args:
            session_id: 会话 ID。

        Returns:
            原始消息文本；如果不在等待状态，返回空字符串。
        """
        state = self._sessions.get(session_id)
        if state and state.state == ConversationState.WAITING_CLARIFICATION:
            return state.original_query
        return ""

    def get_clarify_count(self, session_id: str) -> int:
        """
        获取已反问次数。

        Args:
            session_id: 会话 ID。

        Returns:
            反问次数；不在等待状态时返回 0。
        """
        state = self._sessions.get(session_id)
        if state:
            return state.clarify_count
        return 0

    # ------------------------------------------------------------------
    # 状态设置
    # ------------------------------------------------------------------

    async def set_waiting(self, session_id: str, original_query: str) -> None:
        """
        将指定会话设为"等待用户澄清"状态。

        Args:
            session_id:      会话 ID。
            original_query:  触发反问的原始消息内容。
        """
        async with self._lock:
            state = self._sessions.get(session_id, SessionState())
            state.state = ConversationState.WAITING_CLARIFICATION
            state.original_query = original_query
            state.clarify_count += 1
            state.timestamp = time.monotonic()
            self._sessions[session_id] = state
            logger.info(
                f"[pixiv:state] 会话 {session_id} 进入等待澄清状态 "
                f"(第 {state.clarify_count} 次)"
            )

    async def clear(self, session_id: str) -> None:
        """
        清除指定会话的状态，回到 IDLE。

        Args:
            session_id: 会话 ID。
        """
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.debug(f"[pixiv:state] 会话 {session_id} 状态已清除")

    # ------------------------------------------------------------------
    # 超时与清理
    # ------------------------------------------------------------------

    async def cleanup_expired(self) -> int:
        """
        清理所有超时的会话状态。

        Returns:
            清理的会话数量。
        """
        async with self._lock:
            expired = [
                sid for sid, state in self._sessions.items()
                if self._is_timed_out(state)
            ]
            for sid in expired:
                del self._sessions[sid]
            if expired:
                logger.info(
                    f"[pixiv:state] 清理 {len(expired)} 个超时会话: {expired}"
                )
            return len(expired)

    def clear_all(self) -> None:
        """清除所有会话状态（插件卸载时调用）。"""
        count = len(self._sessions)
        self._sessions.clear()
        logger.info(f"[pixiv:state] 已清除全部 {count} 个会话状态")

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _is_timed_out(state: SessionState) -> bool:
        """
        检查会话状态是否已超时。

        Args:
            state: 会话状态对象。

        Returns:
            True 表示已超时。
        """
        return time.monotonic() - state.timestamp > ConversationStateManager.STATE_TIMEOUT

# ============================================================================
# dedup_manager.py — 已发送图片去重管理器（使用独立 sqlite3）
# ============================================================================
# 负责记录和查询已发送的 Pixiv 作品 ID，避免短期内重复发送。
#
# 去重策略（双层）:
#   1. 全局去重: 最近 N 张（默认100），跨会话生效
#   2. 会话去重: 每会话最近 M 张（默认20），仅当前会话生效
#
# 存储: 插件自己的 SQLite 数据库文件（data/pixiv_dedup.db）
#       使用标准 sqlite3 模块，简单可靠，不依赖 AstrBot 内部 DB API
# ============================================================================

import os
import sqlite3
import time
from threading import Lock

from astrbot.api import logger


class DedupManager:
    """
    已发送图片去重管理器。

    使用独立的 sqlite3 数据库文件存储已发送记录。
    所有操作均为同步（sqlite3 不支持异步），但操作极快（微秒级）。
    """

    TABLE_GLOBAL = "pixiv_sent_global"
    TABLE_SESSION = "pixiv_sent_session"

    def __init__(self, context, config_mgr) -> None:
        self._config = config_mgr
        # 数据库文件存储在插件目录下的 data/ 中
        plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(plugin_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        self._db_path = os.path.join(data_dir, "pixiv_dedup.db")
        self._conn: sqlite3.Connection | None = None
        self._lock = Lock()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """初始化数据库连接并建表。"""
        try:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._create_tables()
            self._cleanup_all()
            logger.info(f"[pixiv:dedup] 去重数据库就绪: {self._db_path}")
        except Exception as e:
            logger.error(f"[pixiv:dedup] 初始化失败: {e}")
            raise

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # 建表
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """创建去重记录表。"""
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.TABLE_GLOBAL} (
                illust_id INTEGER PRIMARY KEY,
                sent_at TEXT NOT NULL
            )
        """)
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.TABLE_SESSION} (
                session_id TEXT NOT NULL,
                illust_id INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (session_id, illust_id)
            )
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # 去重查询
    # ------------------------------------------------------------------

    def is_duplicate(self, illust_id: int, session_id: str) -> bool:
        """检查作品是否已在全局或当前会话中发送过。"""
        with self._lock:
            row = self._conn.execute(
                f"SELECT 1 FROM {self.TABLE_GLOBAL} WHERE illust_id = ?",
                (illust_id,),
            ).fetchone()
            if row:
                return True

            row = self._conn.execute(
                f"SELECT 1 FROM {self.TABLE_SESSION} WHERE session_id = ? AND illust_id = ?",
                (session_id, illust_id),
            ).fetchone()
            return row is not None

    # ------------------------------------------------------------------
    # 标记已发送
    # ------------------------------------------------------------------

    def mark_sent(self, illust_id: int, session_id: str) -> None:
        """标记作品已发送。"""
        now = self._now_iso()
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO {self.TABLE_GLOBAL} (illust_id, sent_at) VALUES (?, ?)",
                (illust_id, now),
            )
            self._conn.execute(
                f"INSERT OR REPLACE INTO {self.TABLE_SESSION} (session_id, illust_id, sent_at) VALUES (?, ?, ?)",
                (session_id, illust_id, now),
            )
            self._conn.commit()
        # 清理（不需要锁住查询操作）
        self._cleanup_global()
        self._cleanup_session(session_id)

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    def _cleanup_global(self) -> None:
        """清理全局表中超限的旧记录。"""
        limit = self._config.get("global_dedup_limit", 100)
        with self._lock:
            self._conn.execute(f"""
                DELETE FROM {self.TABLE_GLOBAL}
                WHERE illust_id NOT IN (
                    SELECT illust_id FROM {self.TABLE_GLOBAL}
                    ORDER BY sent_at DESC LIMIT ?
                )
            """, (limit,))
            self._conn.commit()

    def _cleanup_session(self, session_id: str) -> None:
        """清理指定会话中超限的旧记录。"""
        limit = self._config.get("session_dedup_limit", 20)
        with self._lock:
            self._conn.execute(f"""
                DELETE FROM {self.TABLE_SESSION}
                WHERE session_id = ? AND illust_id NOT IN (
                    SELECT illust_id FROM {self.TABLE_SESSION}
                    WHERE session_id = ? ORDER BY sent_at DESC LIMIT ?
                )
            """, (session_id, session_id, limit))
            self._conn.commit()

    def _cleanup_all(self) -> None:
        """初始化时清理所有超限记录。"""
        self._cleanup_global()
        rows = self._conn.execute(
            f"SELECT DISTINCT session_id FROM {self.TABLE_SESSION}"
        ).fetchall()
        for (sid,) in rows:
            self._cleanup_session(sid)

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """获取去重统计信息。"""
        global_count = self._conn.execute(
            f"SELECT COUNT(*) FROM {self.TABLE_GLOBAL}"
        ).fetchone()[0]
        session_count = self._conn.execute(
            f"SELECT COUNT(*) FROM {self.TABLE_SESSION}"
        ).fetchone()[0]
        return {
            "global_sent_count": global_count,
            "session_sent_count": session_count,
            "global_limit": self._config.get("global_dedup_limit", 100),
            "session_limit": self._config.get("session_dedup_limit", 20),
        }

    @staticmethod
    def _now_iso() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

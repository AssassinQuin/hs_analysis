# -*- coding: utf-8 -*-
"""hsreplay_updater.py — HSReplay 卡组数据库更新器

从 HSReplay API 获取最新卡组数据并存储到 SQLite 缓存中，
用于贝叶斯对手模型进行卡组原型推断。

功能:
- 获取 HSReplay 原型 API 数据 (https://hsreplay.net/api/v1/archetypes/)
- 从 deck_codes.txt 构建卡组数据库（当 API 不可用时的回退方案）
- 存储卡牌统计数据（胜率、使用率、留牌率）
- 定期更新（每 24 小时）
- 在 PyQt5 QThread 中运行

使用现有 analysis.data.fetch_hsreplay 基础设施。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 尝试导入 PyQt5（可选）
_HAS_PYQT5 = False
_QThread = None
_pyqtSignal = None

try:
    from PyQt5.QtCore import QThread, pyqtSignal
    _HAS_PYQT5 = True
    _QThread = QThread
    _pyqtSignal = pyqtSignal
except ImportError:
    pass


if _HAS_PYQT5:
    class HSReplayUpdater(QThread):
        """后台线程，定期更新 HSReplay 卡组数据。

        信号:
            update_finished(dict)  — 更新完成，包含统计信息
            update_error(str)      — 更新失败，包含错误信息
            update_started()       — 更新开始
        """

        update_finished = _pyqtSignal(dict)
        update_error = _pyqtSignal(str)
        update_started = _pyqtSignal()

        def __init__(
            self,
            update_interval_hours: float = 24.0,
            parent=None,
        ):
            super().__init__(parent)
            self._update_interval = update_interval_hours
            self._running = False
            self._last_update: Optional[datetime] = None

            # 确定数据库路径
            try:
                from analysis.config import HSREPLAY_CACHE_DB
                self._db_path = str(HSREPLAY_CACHE_DB)
            except ImportError:
                self._db_path = str(
                    Path(__file__).resolve().parent.parent
                    / "card_data" / "240397" / "hsreplay_cache.db"
                )

        def run(self):
            """线程主循环。"""
            self._running = True

            # 启动时立即检查并更新
            self._check_and_update()

            # 定期更新循环
            while self._running:
                # 等待更新间隔（可中断）
                wait_seconds = self._update_interval * 3600
                elapsed = 0
                while self._running and elapsed < wait_seconds:
                    self.msleep(1000)
                    elapsed += 1

                if self._running:
                    self._check_and_update()

        def stop(self):
            """停止更新线程。"""
            self._running = False
            self.wait(3000)

        def force_update(self):
            """强制立即更新。"""
            self._last_update = None
            self._check_and_update()

        def _check_and_update(self):
            """检查是否需要更新并执行。"""
            if self._should_update():
                self._do_update()

        def _should_update(self) -> bool:
            """判断是否需要更新。"""
            if self._last_update is None:
                if not os.path.exists(self._db_path):
                    return True
                try:
                    conn = sqlite3.connect(self._db_path)
                    try:
                        row = conn.execute(
                            "SELECT MAX(fetch_date) FROM meta_decks"
                        ).fetchone()
                        if row and row[0]:
                            last_date = datetime.strptime(row[0], "%Y-%m-%d")
                            self._last_update = last_date
                            hours_since = (datetime.now() - last_date).total_seconds() / 3600
                            if hours_since < self._update_interval:
                                return False
                        else:
                            return True
                    finally:
                        conn.close()
                except Exception:
                    return True

            hours_since = (datetime.now() - self._last_update).total_seconds() / 3600
            return hours_since >= self._update_interval

        def _do_update(self):
            """执行更新操作。"""
            self.update_started.emit()
            logger.info("开始更新 HSReplay 数据...")

            try:
                from analysis.data.fetch_hsreplay import (
                    init_db,
                    fetch_archetypes,
                    store_meta_decks,
                    store_card_stats,
                    generate_card_stats_from_v2,
                    fetch_card_stats_api,
                    extract_api_card_stats,
                    cleanup_old_data,
                    get_meta_decks,
                )
            except ImportError as e:
                msg = f"无法导入 fetch_hsreplay 模块: {e}"
                logger.error(msg)
                self.update_error.emit(msg)
                return

            try:
                conn = init_db(self._db_path)
                try:
                    archetypes = fetch_archetypes()
                    archetype_count = 0
                    if archetypes:
                        archetype_count = store_meta_decks(conn, archetypes)
                    else:
                        try:
                            from analysis.data.fetch_hsreplay import build_archetype_db_from_deck_codes
                            archetype_count = build_archetype_db_from_deck_codes(conn)
                        except Exception:
                            pass

                    decks = get_meta_decks(conn)
                    if not decks:
                        try:
                            from analysis.data.fetch_hsreplay import build_archetype_db_from_deck_codes
                            archetype_count = build_archetype_db_from_deck_codes(conn)
                        except Exception:
                            pass

                    card_stat_count = 0
                    api_cards = fetch_card_stats_api()
                    if api_cards:
                        records = extract_api_card_stats(api_cards)
                        card_stat_count = store_card_stats(conn, records)
                    else:
                        records = generate_card_stats_from_v2(archetypes or [])
                        card_stat_count = store_card_stats(conn, records)

                    cleanup_old_data(conn)
                    self._last_update = datetime.now()

                    result = {
                        "archetype_count": archetype_count,
                        "card_stat_count": card_stat_count,
                        "timestamp": self._last_update.isoformat(),
                    }
                    self.update_finished.emit(result)

                finally:
                    conn.close()

            except Exception as e:
                msg = f"HSReplay 数据更新失败: {e}"
                logger.exception(msg)
                self.update_error.emit(msg)

else:
    # 没有 PyQt5 时，提供纯 Python 的 HSReplayUpdater
    class HSReplayUpdater:
        """纯 Python 版本的 HSReplay 更新器（不需要 PyQt5）。

        使用 threading.Thread 替代 QThread。
        """

        def __init__(
            self,
            update_interval_hours: float = 24.0,
        ):
            self._update_interval = update_interval_hours
            self._running = False
            self._last_update: Optional[datetime] = None
            self._thread: Optional[threading.Thread] = None

            try:
                from analysis.config import HSREPLAY_CACHE_DB
                self._db_path = str(HSREPLAY_CACHE_DB)
            except ImportError:
                self._db_path = str(
                    Path(__file__).resolve().parent.parent
                    / "card_data" / "240397" / "hsreplay_cache.db"
                )

            # 回调
            self.on_update_finished = None
            self.on_update_error = None
            self.on_update_started = None

        def start(self):
            """启动更新线程。"""
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

        def _run_loop(self):
            """线程主循环。"""
            self._check_and_update()
            while self._running:
                import time
                time.sleep(self._update_interval * 3600)
                if self._running:
                    self._check_and_update()

        def stop(self):
            """停止更新线程。"""
            self._running = False

        def force_update(self):
            """强制立即更新。"""
            self._last_update = None
            self._check_and_update()

        def _check_and_update(self):
            """检查是否需要更新并执行。"""
            if self._should_update():
                self._do_update()

        def _should_update(self) -> bool:
            """判断是否需要更新。"""
            if self._last_update is None:
                if not os.path.exists(self._db_path):
                    return True
                try:
                    conn = sqlite3.connect(self._db_path)
                    try:
                        row = conn.execute(
                            "SELECT MAX(fetch_date) FROM meta_decks"
                        ).fetchone()
                        if row and row[0]:
                            last_date = datetime.strptime(row[0], "%Y-%m-%d")
                            self._last_update = last_date
                            hours_since = (datetime.now() - last_date).total_seconds() / 3600
                            if hours_since < self._update_interval:
                                return False
                        else:
                            return True
                    finally:
                        conn.close()
                except Exception:
                    return True
            hours_since = (datetime.now() - self._last_update).total_seconds() / 3600
            return hours_since >= self._update_interval

        def _do_update(self):
            """执行更新操作。"""
            if self.on_update_started:
                self.on_update_started()
            logger.info("开始更新 HSReplay 数据...")

            try:
                from analysis.data.fetch_hsreplay import (
                    init_db, fetch_archetypes, store_meta_decks,
                    store_card_stats, generate_card_stats_from_v2,
                    fetch_card_stats_api, extract_api_card_stats,
                    cleanup_old_data, get_meta_decks,
                )
            except ImportError as e:
                msg = f"无法导入 fetch_hsreplay 模块: {e}"
                logger.error(msg)
                if self.on_update_error:
                    self.on_update_error(msg)
                return

            try:
                conn = init_db(self._db_path)
                try:
                    archetypes = fetch_archetypes()
                    archetype_count = 0
                    if archetypes:
                        archetype_count = store_meta_decks(conn, archetypes)
                    else:
                        try:
                            from analysis.data.fetch_hsreplay import build_archetype_db_from_deck_codes
                            archetype_count = build_archetype_db_from_deck_codes(conn)
                        except Exception:
                            pass

                    decks = get_meta_decks(conn)
                    if not decks:
                        try:
                            from analysis.data.fetch_hsreplay import build_archetype_db_from_deck_codes
                            archetype_count = build_archetype_db_from_deck_codes(conn)
                        except Exception:
                            pass

                    card_stat_count = 0
                    api_cards = fetch_card_stats_api()
                    if api_cards:
                        records = extract_api_card_stats(api_cards)
                        card_stat_count = store_card_stats(conn, records)
                    else:
                        records = generate_card_stats_from_v2(archetypes or [])
                        card_stat_count = store_card_stats(conn, records)

                    cleanup_old_data(conn)
                    self._last_update = datetime.now()

                    result = {
                        "archetype_count": archetype_count,
                        "card_stat_count": card_stat_count,
                        "timestamp": self._last_update.isoformat(),
                    }
                    if self.on_update_finished:
                        self.on_update_finished(result)

                finally:
                    conn.close()

            except Exception as e:
                msg = f"HSReplay 数据更新失败: {e}"
                logger.exception(msg)
                if self.on_update_error:
                    self.on_update_error(msg)


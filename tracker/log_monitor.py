# -*- coding: utf-8 -*-
"""log_monitor.py — 实时 Power.log 监控器

监控炉石传说 Power.log 文件变化，增量读取新行并喂入 GameTracker。
自动检测游戏开始/结束、回合切换，并将事件桥接到 GlobalTracker。

支持两种运行模式:
1. PyQt5 QThread 模式（需要 PyQt5，用于实时叠加窗口）
2. 纯 Python 模式（不需要 PyQt5，用于离线分析/验证）

特性:
- 自动检测炉石传说日志目录 (Windows: %LOCALAPPDATA%\\Blizzard\\Hearthstone\\Logs)
- 支持 watchdog 或轮询两种监控模式
- 日志轮转检测（炉石重启时 Power.log 会被截断）
- 增量行读取，避免内存溢出
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional, Callable, Dict, List

from dataclasses import dataclass

from analysis.watcher.game_tracker import GameTracker, EntityCache
from analysis.watcher.global_tracker import GlobalTracker
from analysis.constants.hs_enums import (
    ZONE_PLAY, ZONE_DECK, ZONE_HAND, ZONE_GRAVEYARD,
    ZONE_SETASIDE, ZONE_SECRET,
    CT_HERO, CT_MINION, CT_SPELL, CT_ENCHANTMENT,
    CT_WEAPON, CT_HERO_POWER, CT_LOCATION,
    ZONE_NAME_MAP, CARDTYPE_NAME_MAP,
)
from analysis.utils.hero_class import class_to_cn
from analysis.utils.player_name import normalize_player_name
from hearthstone.enums import GameTag, Zone, CardType

logger = logging.getLogger(__name__)

# 尝试导入 PyQt5（可选）
_HAS_PYQT5 = False
_QThread = None
_pyqtSignal = None
_QMutex = None

try:
    from PyQt5.QtCore import QThread, pyqtSignal, QMutex
    _HAS_PYQT5 = True
    _QThread = QThread
    _pyqtSignal = pyqtSignal
    _QMutex = QMutex
except ImportError:
    pass


# ── 日志目录自动检测 ──────────────────────────────────────────

def find_hearthstone_log_dir() -> Optional[Path]:
    """自动检测炉石传说日志目录。

    搜索顺序:
    1. %LOCALAPPDATA%\\Blizzard\\Hearthstone\\Logs (标准位置)
    2. 项目根目录下的 Power.log
    3. 项目根目录下的 Hearthstone_* 子目录

    Returns:
        Path 对象或 None
    """
    # 1. Windows 标准位置
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        hs_log = Path(local_app) / "Blizzard" / "Hearthstone" / "Logs"
        if (hs_log / "Power.log").exists():
            return hs_log

    # 2. 项目根目录
    try:
        from analysis.config import PROJECT_ROOT
        project_root = Path(PROJECT_ROOT)
    except ImportError:
        project_root = Path(__file__).resolve().parent.parent

    # 直接 Power.log
    if (project_root / "Power.log").exists():
        return project_root

    # 带时间戳的子目录
    candidates = []
    try:
        for child in project_root.iterdir():
            if child.is_dir() and child.name.startswith("Hearthstone_"):
                if (child / "Power.log").exists():
                    candidates.append(child)
    except OSError:
        pass

    if candidates:
        # 选择最新的
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]

    return None


def find_power_log_path() -> Optional[Path]:
    """查找 Power.log 文件路径。

    Returns:
        Power.log 的 Path 对象或 None
    """
    log_dir = find_hearthstone_log_dir()
    if log_dir is None:
        return None

    power_log = log_dir / "Power.log"
    if power_log.exists():
        return power_log
    return None


# ── Zone/CardType 字符串→整数转换（单一数据源：hs_enums） ─────

# 补充 hs_enums 中未覆盖的额外映射项
_ZONE_MAP = {
    "INVALID": 0,
}
# 合并 hs_enums 中的权威映射
_ZONE_MAP.update(ZONE_NAME_MAP)
# REMOVEDFROMGAME 权威值为 8（来自 hs_enums）
_ZONE_MAP["REMOVEDFROMGAME"] = 8

_CARD_TYPE_MAP = {
    "INVALID": 0, "GAME": 1, "PLAYER": 2, "ITEM": 8,
}
_CARD_TYPE_MAP.update(CARDTYPE_NAME_MAP)


def _safe_int(val, default: int = 0) -> int:
    """安全地将值转换为整数，失败时返回默认值。"""
    if isinstance(val, int):
        return val
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _zone_to_int(zone_val) -> int:
    """将 Zone 值转换为整数（支持字符串如 "PLAY" 和整数如 1）。"""
    if isinstance(zone_val, int):
        return zone_val
    if isinstance(zone_val, str):
        return _ZONE_MAP.get(zone_val.upper(), 0)
    return _safe_int(zone_val)


def _card_type_to_int(ct_val) -> int:
    """将 CardType 值转换为整数（支持字符串如 "MINION" 和整数如 4）。"""
    if isinstance(ct_val, int):
        return ct_val
    if isinstance(ct_val, str):
        return _CARD_TYPE_MAP.get(ct_val.upper(), 0)
    return _safe_int(ct_val)


# ── 提取实体字段的统一数据结构 ────────────────────────────

@dataclass
class EntityFields:
    """从 entity_cache 条目中提取的实体关键字段。"""
    controller: int
    zone: int
    card_type: int
    cost: int
    is_coin_tag: bool
    card_id: str


def _extract_entity_fields(ent_data: dict) -> EntityFields:
    """从 entity_cache 的实体字典中提取并解析所有关键字段。

    消除了 _bridge_entities_to_global_tracker、_bridge_new_entities、
    _parse_tag_change_zone 三处重复的字段解析代码。
    """
    tags = ent_data.get("tags", {})
    return EntityFields(
        controller=_safe_int(tags.get(GameTag.CONTROLLER, 0)),
        zone=_zone_to_int(tags.get(GameTag.ZONE, 0)),
        card_type=_card_type_to_int(tags.get(GameTag.CARDTYPE, 0)),
        cost=_safe_int(tags.get(GameTag.COST, 0)),
        is_coin_tag=bool(tags.get(GameTag.COIN_CARD, 0) == 1),
        card_id=ent_data.get("card_id", ""),
    )


# ── 游戏生命周期状态机 ────────────────────────────────────

from enum import Enum, auto

class GameLifecycle(Enum):
    """游戏生命周期状态，替代 _game_started_emitted / _game_started_with_classes 标志对。

    IDLE:     未在游戏中
    STARTING: 游戏开始，但职业信息尚未就绪
    READY:    游戏开始且职业信息完整
    ENDED:    游戏结束
    """
    IDLE = auto()
    STARTING = auto()
    READY = auto()
    ENDED = auto()


# ── 核心日志解析器（不依赖 PyQt5） ─────────────────────────────

class CoreLogMonitor:
    """核心日志监控器（不依赖 PyQt5）。

    提供完整的日志解析和游戏状态追踪功能，
    可以独立运行或嵌入到 QThread 中。

    用法::

        monitor = CoreLogMonitor()
        monitor.load_existing_log("/path/to/Power.log")
        state = monitor.build_state_dict()
    """

    def __init__(
        self,
        log_path: Optional[str | Path] = None,
        poll_interval: float = 0.1,
    ):
        self._log_path = Path(log_path) if log_path else None
        self._poll_interval = poll_interval
        self._running = False

        # 核心解析器
        self.game_tracker = GameTracker()
        self.global_tracker = GlobalTracker()

        # 回调
        self.on_game_started: Optional[Callable[[dict], None]] = None
        self.on_game_ended: Optional[Callable[[], None]] = None
        self.on_turn_changed: Optional[Callable[[int], None]] = None
        self.on_state_updated: Optional[Callable[[dict], None]] = None
        self.on_log_error: Optional[Callable[[str], None]] = None

        # 上次通知时间（节流）
        self._last_notify_time = 0.0
        self._notify_interval = 0.1  # 100ms = 10 FPS

        # 文件位置追踪
        self._file_pos = 0
        self._file_ino = 0

        # 增量实体桥接追踪
        self._bridged_entities: set = set()  # 已桥接到 GlobalTracker 的 entity_id 集合

        # 实体区域快照 (entity_id → zone_int)，用于 diff 检测区域变化
        self._last_known_zones: Dict[int, int] = {}

        # 实体 card_id 快照 (entity_id → card_id)，用于检测 ChangeEntity 变形和窥探揭示
        self._last_known_card_ids: Dict[int, str] = {}

        # FIRST_PLAYER 检测标记
        self._first_player_detected: bool = False

        # 玩家名称追踪 (PlayerID → name)
        self._player_names: Dict[int, str] = {}  # player_id → player_name
        self._re_player_name = re.compile(r"PlayerID=(\d+),\s*PlayerName=(.+)")

        # 已知我方玩家名称（跨游戏持久化）
        # 一旦通过 AI_TAG / BattleTag 等正确识别我方名称后，后续游戏直接用此名称匹配
        # 避免 PvP 双方都有 BattleTag 时默认 my_idx=0 导致 50% 概率反转
        self._our_known_name: str = ""

        # 游戏生命周期状态（替代 _game_started_emitted 标志对）
        self._game_lifecycle = GameLifecycle.IDLE

        # 初始追赶标记：启动/日志轮转后读取已有数据时抑制事件回调
        # 避免「读到旧日志的 game_start + game_end → UI 闪烁」问题
        self._catching_up: bool = False

    @property
    def log_path(self) -> Optional[Path]:
        return self._log_path

    @log_path.setter
    def log_path(self, value: Optional[str | Path]):
        self._log_path = Path(value) if value else None

    def auto_detect_log_path(self) -> bool:
        """自动检测 Power.log 路径。"""
        path = find_power_log_path()
        if path:
            self._log_path = path
            logger.info("自动检测到 Power.log: %s", path)
            return True
        else:
            logger.warning("未找到 Power.log")
            return False

    def run_poll_loop(self):
        """轮询主循环（阻塞）。"""
        self._running = True

        if self._log_path is None:
            self.auto_detect_log_path()

        if self._log_path is None:
            if self.on_log_error:
                self.on_log_error("未找到 Power.log 文件")
            return

        logger.info("开始监控: %s", self._log_path)

        while self._running:
            try:
                self._poll_file()
            except Exception as e:
                if self.on_log_error:
                    self.on_log_error(f"日志解析错误: {e}")
                logger.exception("日志解析错误")

            time.sleep(self._poll_interval)

    def stop(self):
        """停止监控。"""
        self._running = False

    def _poll_file(self):
        """轮询文件变化。"""
        if self._log_path is None or not self._log_path.exists():
            if self._log_path is None:
                self.auto_detect_log_path()
            return

        try:
            stat = self._log_path.stat()
        except OSError:
            return

        current_ino = stat.st_ino
        current_size = stat.st_size

        if current_ino != self._file_ino or current_size < self._file_pos:
            self._file_pos = 0
            self._file_ino = current_ino
            logger.info("检测到日志轮转，重置读取位置及追踪状态")
            # 日志轮转意味着新 session 开始，需清空残留状态
            # 避免旧游戏的实体泄漏到新 session
            self._bridged_entities.clear()
            self._last_known_zones.clear()
            self._last_known_card_ids.clear()
            self._first_player_detected = False
            self._player_names.clear()
            self._game_lifecycle = GameLifecycle.IDLE
            self.game_tracker.reset()
            # 保存当前 controller，因为 on_game_start 会重置为 0
            # 日志轮转后如果新日志中有继续的游戏数据，需要先保留 controller
            old_our = self.global_tracker.our_controller
            old_opp = self.global_tracker.opp_controller
            self.global_tracker.on_game_start()
            # 如果有已知 controller，恢复它们（等待真正的 game_start 重新设置）
            if old_our and old_opp:
                self.global_tracker.set_controllers(old_our, old_opp)
            # 标记为追赶模式：读取已有日志时不触发 UI 事件
            self._catching_up = True

        if current_size <= self._file_pos:
            return

        try:
            with open(self._log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._file_pos)
                new_text = f.read()
                self._file_pos = f.tell()
        except (OSError, IOError):
            return

        if not new_text:
            return

        lines = new_text.splitlines()
        self._process_lines(lines)

        # 追赶模式结束：如果之前是首次读取旧日志，现在处理完毕
        # 检查当前游戏状态，若仍在游戏中则正常触发 game_start
        if self._catching_up:
            self._catching_up = False
            if self.game_tracker.in_game:
                # 旧日志中有一局正在进行中的游戏 → 补触发生命周期
                logger.info("追赶完毕，检测到进行中的游戏，补触发 game_start")
                self._on_game_start()
            else:
                # 旧日志中的游戏已结束 → 不触发任何事件，静默等待新游戏
                logger.info("追赶完毕，旧游戏已结束，静默等待新游戏")

    def _process_lines(self, lines: list[str]):
        """处理新行，喂入 GameTracker 并分发事件。

        追赶模式(_catching_up=True)时，仍然将所有行喂入 GameTracker
        以维护正确的内部状态（game_count、in_game 等），但跳过
        UI 事件回调，避免读到旧日志的 game_start + game_end
        导致 UI 闪烁「游戏开始 → 立即结束」。
        """
        for line in lines:
            if not line.strip():
                continue

            # 解析 PlayerName 行（在 DebugPrintGame() 中）
            self._parse_player_name_line(line)

            event = self.game_tracker.feed_line(line)
            if event is None:
                continue

            if self._catching_up:
                # 追赶模式：只更新内部状态，不触发 UI 事件
                # 但仍需维护桥接状态，以便追赶结束后状态正确
                if event == "game_start":
                    self._bridged_entities.clear()
                    self._last_known_zones.clear()
                    self._last_known_card_ids.clear()
                    self._first_player_detected = False
                    # 不再清空 _player_names — 同 _on_game_start 理由
                continue

            if event == "game_start":
                self._on_game_start()
            elif event == "game_end":
                self._on_game_end()
            elif event == "turn_start":
                self._on_turn_start()
            elif event == "action":
                now = time.time()
                if now - self._last_notify_time >= self._notify_interval:
                    self._notify_state_update()
                    self._last_notify_time = now

        # 处理完一批行后，从 entity_cache diff 检测区域变化和 FIRST_PLAYER
        # 追赶模式下也需要桥接实体，以便追赶结束后状态正确
        self._detect_zone_changes_from_cache()
        self._detect_first_player_from_cache()
        # 检查是否需要更新玩家信息（追赶模式下也执行，以便恢复正确状态）
        self._try_enrich_player_info()

    def _detect_my_idx(self, players, saved_our_controller: int = 0) -> int:
        """确定哪个玩家是本地玩家（我方）。

        判定规则（按优先级）:
          0. 已知我方名称匹配：_our_known_name 与玩家名精确匹配
          1. AI_MAKES_DECISIONS_FOR_PLAYER 标签：AI 玩家标签=1，我方=0
          2. 从 _player_names 匹配：名字含 '#' 的 BattleTag 用户是本地玩家
             当双方都有 '#' 时，用 saved_our_controller（上局 controller）匹配
          3. 从 hslog player.name 匹配：名字含 '#' 的是本地玩家
          4. 都不含 '#' 时默认 players[0] 为我方

        Args:
            players: hslog 导出的玩家实体列表（按 EntityID 排序）
            saved_our_controller: 上局的我方 controller（0 表示无历史记录）

        Returns:
            我方在 players 列表中的索引 (0 或 1)
        """
        my_idx = 0
        if len(players) < 2:
            return my_idx

        n0 = getattr(players[0], 'name', '') or ''
        n1 = getattr(players[1], 'name', '') or ''

        # 最高优先级: 已知我方名称匹配（跨游戏持久化）
        # 一旦从任何方式正确识别过，后续游戏直接用名称匹配
        if self._our_known_name:
            norm_known = normalize_player_name(self._our_known_name)
            norm_n0 = normalize_player_name(n0)
            norm_n1 = normalize_player_name(n1)
            if norm_known and norm_n0 and norm_known == norm_n0:
                logger.debug("玩家检测(KNOWN_NAME): 我方=players[0] (name=%s)", n0)
                return 0
            if norm_known and norm_n1 and norm_known == norm_n1:
                logger.debug("玩家检测(KNOWN_NAME): 我方=players[1] (name=%s)", n1)
                return 1

        # 优先级次高: AI_MAKES_DECISIONS_FOR_PLAYER 标签
        # AI 玩家此标签=1，我方(人类)此标签=0或不存在
        try:
            ai0 = players[0].tags.get(GameTag.AI_MAKES_DECISIONS_FOR_PLAYER, 0)
            ai1 = players[1].tags.get(GameTag.AI_MAKES_DECISIONS_FOR_PLAYER, 0)
            if ai0 and not ai1:
                # players[0] 是 AI → 我方是 players[1]
                my_idx = 1
                logger.debug("玩家检测(AI_TAG): 我方=players[%d] (name=%s), AI=players[%d] (name=%s)",
                             my_idx, n1, 1 - my_idx, n0)
                return my_idx
            elif ai1 and not ai0:
                # players[1] 是 AI → 我方是 players[0]
                my_idx = 0
                logger.debug("玩家检测(AI_TAG): 我方=players[%d] (name=%s), AI=players[%d] (name=%s)",
                             my_idx, n0, 1 - my_idx, n1)
                return my_idx
            # 两个都是 AI 或都不是 → 继续后续判断
        except (AttributeError, TypeError):
            pass

        # 第二优先: 从 _player_names 匹配（从 DebugPrintGame() 解析的玩家名）
        if self._player_names:
            pid0 = 0
            pid1 = 0
            try:
                pid0 = players[0].tags.get(GameTag.PLAYER_ID, 0)
                pid1 = players[1].tags.get(GameTag.PLAYER_ID, 0)
            except (AttributeError, TypeError):
                pass
            name0 = self._player_names.get(pid0, '')
            name1 = self._player_names.get(pid1, '')

            has_tag0 = bool(name0 and '#' in name0 and name0 != 'UNKNOWN HUMAN PLAYER')
            has_tag1 = bool(name1 and '#' in name1 and name1 != 'UNKNOWN HUMAN PLAYER')

            if has_tag0 and has_tag1:
                # 双方都有 BattleTag：用上局 controller 匹配
                # saved_our_controller 是 on_game_start 之前保存的值，
                # 不受 global_tracker.on_game_start() 重置为 0 的影响
                try:
                    c0 = players[0].tags.get(GameTag.CONTROLLER, 0)
                    c1 = players[1].tags.get(GameTag.CONTROLLER, 0)
                    if saved_our_controller and c0 == saved_our_controller:
                        my_idx = 0
                        self._our_known_name = name0
                    elif saved_our_controller and c1 == saved_our_controller:
                        my_idx = 1
                        self._our_known_name = name1
                    else:
                        # 首次游戏 / 无法匹配：用 FIRST_PLAYER 验证
                        # 检测 entity_cache 中的 FIRST_PLAYER 标签
                        first_pid = self._detect_first_player_pid()
                        if first_pid:
                            # FIRST_PLAYER 的 PlayerID 对应的玩家 → 先手
                            # 在炉石中，先手玩家拿到先手优势但后手拿硬币
                            # 先手玩家的 PlayerID 可能是 1 或 2（不固定）
                            # 这里仅做日志记录，不改变 my_idx（需要更多信息）
                            logger.debug("玩家检测(FIRST_PLAYER辅助): first_player PID=%d, 默认 my_idx=0",
                                         first_pid)
                        my_idx = 0
                except Exception:
                    my_idx = 0
                logger.debug("玩家检测(_player_names, dual BattleTag): 我方=players[%d] name=%s, saved_ctrl=%d",
                             my_idx, [name0, name1][my_idx], saved_our_controller)
                return my_idx

            if has_tag1:
                my_idx = 1
                self._our_known_name = name1
                logger.debug("玩家检测(_player_names): 我方=players[%d] name=%s, 对手=players[%d] name=%s",
                             my_idx, name1, 1 - my_idx, name0)
                return my_idx
            if has_tag0:
                my_idx = 0
                self._our_known_name = name0
                logger.debug("玩家检测(_player_names): 我方=players[%d] name=%s, 对手=players[%d] name=%s",
                             my_idx, name0, 1 - my_idx, name1)
                return my_idx

        # 第三优先: 使用 hslog player.name
        has_tag0 = '#' in n0 and n0 != 'UNKNOWN HUMAN PLAYER'
        has_tag1 = '#' in n1 and n1 != 'UNKNOWN HUMAN PLAYER'
        if has_tag1 and not has_tag0:
            my_idx = 1

        logger.debug("玩家检测(fallback): 我方=players[%d], n0=%r, n1=%r", my_idx, n0, n1)
        return my_idx

    def _detect_first_player_pid(self) -> Optional[int]:
        """从 entity_cache 检测先手玩家的 PlayerID。

        遍历 entity_cache 查找带有 FIRST_PLAYER=1 标签的 Player 实体，
        返回其 PlayerID。如果未找到则返回 None。
        """
        from hearthstone.enums import CardType
        ec = self.game_tracker.entity_cache
        for entity_id, ent_data in ec.items():
            tags = ent_data.get("tags", {})
            card_type = tags.get(GameTag.CARDTYPE, 0)
            if card_type != CardType.PLAYER.value:
                continue
            if tags.get(GameTag.FIRST_PLAYER, 0) == 1:
                try:
                    return int(tags.get(GameTag.PLAYER_ID, 0))
                except (ValueError, TypeError):
                    pass
        return None

    def _parse_player_name_line(self, line: str):
        """从 DebugPrintGame() 行中解析 PlayerID 和 PlayerName。

        格式: PlayerID=N, PlayerName=NAME
        例如: PlayerID=2, PlayerName=湫然#51704
        """
        if 'PlayerName=' not in line:
            return
        m = self._re_player_name.search(line)
        if m:
            pid = int(m.group(1))
            name = m.group(2).strip()
            self._player_names[pid] = name
            logger.debug("解析到玩家名: PlayerID=%d, Name=%s", pid, name)

    def _detect_zone_changes_from_cache(self):
        """从 entity_cache diff 检测区域变化和卡牌变形，并桥接到 GlobalTracker。

        替代原先的正则匹配 TAG_CHANGE 方案：hslog 的 GameTracker.feed_line()
        已将 TAG_CHANGE 事件处理并更新到 entity_cache，我们只需 diff cache
        中的 ZONE 值即可检测区域变化，无需重复解析日志行。

        同时检测 card_id 变化（ChangeEntity 事件），例如腐蚀升级、变形术等。
        """
        ec = self.game_tracker.entity_cache
        for entity_id, ent_data in ec.items():
            new_zone = _zone_to_int(ent_data.get("tags", {}).get(GameTag.ZONE, 0))
            old_zone = self._last_known_zones.get(entity_id)
            new_card_id = ent_data.get("card_id", "")
            old_card_id = self._last_known_card_ids.get(entity_id, "")

            # 检测卡牌变形（ChangeEntity）：已桥接实体的 card_id 发生变化
            if (entity_id in self._bridged_entities
                    and old_card_id and new_card_id
                    and old_card_id != new_card_id):
                fields = _extract_entity_fields(ent_data)
                self.global_tracker.on_card_transformed(
                    entity_id=entity_id,
                    old_card_id=old_card_id,
                    new_card_id=new_card_id,
                    controller=fields.controller,
                    zone=new_zone,
                )

            # 更新卡牌ID快照
            if new_card_id:
                self._last_known_card_ids[entity_id] = new_card_id

            # 区域变化检测：对所有实体执行（含已桥接实体）
            # 已桥接实体的后续区域变化（如 HAND→PLAY、PLAY→GRAVEYARD）
            # 必须桥接到 GlobalTracker，否则对手出牌/随从死亡等关键事件丢失
            # _entity_played_set 防止 on_show_entity + on_zone_change 双重记录出牌
            if old_zone is not None and old_zone != new_zone:
                fields = _extract_entity_fields(ent_data)
                self.global_tracker.on_zone_change(
                    entity_id=entity_id,
                    controller=fields.controller,
                    old_zone=old_zone,
                    new_zone=new_zone,
                    card_id=fields.card_id,
                    card_type=fields.card_type,
                )

            # 更新快照（zone=0 也记录，避免首次变化被静默忽略）
            # zone=0 表示 INVALID/未分配区域，但实体后续会变到有效区域
            self._last_known_zones[entity_id] = new_zone

    def _detect_first_player_from_cache(self):
        """从 entity_cache 检测 FIRST_PLAYER 标签并桥接到 GlobalTracker。

        替代原先的正则匹配 TAG_CHANGE FIRST_PLAYER 方案：hslog 在处理
        TAG_CHANGE 行时会将 FIRST_PLAYER 标签存入 entity_cache，
        我们直接从 cache 中查询即可。
        """
        if self._first_player_detected:
            return

        ec = self.game_tracker.entity_cache
        for entity_id, ent_data in ec.items():
            tags = ent_data.get("tags", {})
            if tags.get(GameTag.FIRST_PLAYER, 0) == 1:
                controller = _safe_int(tags.get(GameTag.CONTROLLER, 0))
                our_ctrl = self.global_tracker.our_controller
                opp_ctrl = self.global_tracker.opp_controller

                if our_ctrl == 0 and opp_ctrl == 0:
                    # controller 尚未设置，等待下次检测
                    return

                is_our_first = (controller == our_ctrl)
                self.global_tracker.on_first_player(is_our_first)
                self._first_player_detected = True

                who = "我方先手" if is_our_first else "对手先手"
                logger.info("FIRST_PLAYER 检测: entity_id=%d, controller=%d → %s",
                             entity_id, controller, who)
                return

    # ── 游戏生命周期 ──────────────────────────────────────────

    def _enrich_player_info_core(self, re_bridge: bool = True, re_emit: bool = True):
        """核心玩家信息补充逻辑（合并原 _try_enrich_player_info 和 _enrich_player_info）。

        从 hslog EntityTreeExporter 提取玩家信息（controller、职业、牌库计数）。
        当 controller 被修正时，可选择是否重新桥接所有实体。

        Args:
            re_bridge: controller 变化时是否重新桥接所有实体
            re_emit: 职业信息更新后是否重新发送 game_started 信号

        Returns:
            (our_controller, opp_controller) 或 None（失败时）
        """
        try:
            game = self.game_tracker.export_entities()
            if game is None or not hasattr(game, 'players') or len(game.players) < 2:
                return None

            players = list(game.players)
            # 传入当前 global_tracker 的 our_controller 作为 saved 值，
            # 与 _on_game_start 中的逻辑一致
            my_idx = self._detect_my_idx(
                players,
                saved_our_controller=self.global_tracker.our_controller,
            )
            our_player = players[my_idx]
            opp_player = players[1 - my_idx]

            our_controller = our_player.tags.get(GameTag.CONTROLLER, my_idx + 1)
            opp_controller = opp_player.tags.get(GameTag.CONTROLLER, 2 - my_idx)

            old_our = self.global_tracker.our_controller
            old_opp = self.global_tracker.opp_controller

            # 如果 controller 被修正，需要重新桥接所有实体
            if old_our != our_controller or old_opp != opp_controller:
                self._handle_controller_correction(
                    old_our, our_controller, old_opp, opp_controller,
                    re_bridge=re_bridge,
                )
            else:
                self.global_tracker.set_controllers(our_controller, opp_controller)

            # 从对手的实体中检测职业
            from analysis.watcher.game_log_parser import _get_hero_card_id
            for player, attr in [(opp_player, 'opp_hero_class'), (our_player, 'player_hero_class')]:
                hero_id = _get_hero_card_id(player)
                if hero_id:
                    meta = self.global_tracker._card_metadata(hero_id)
                    cls = meta.get('cardClass', '')
                    if cls:
                        setattr(self.global_tracker.state, attr, cls)

            # 更新牌库/武器/地点计数
            self._refresh_opp_counts(opp_player)

            return our_controller, opp_controller

        except Exception as e:
            logger.debug("补充玩家信息失败: %s", e)
            return None

    def _try_enrich_player_info(self):
        """实时模式下的玩家信息补充（有节流，只在信息不完整时执行）。

        在 _process_lines() 和 _notify_state_update() 中调用。
        当信息补全后，将游戏生命周期推进到 READY 并重新发送 game_started 信号。
        """
        state = self.global_tracker.state
        # 如果已进入 READY 状态，信息已完整，无需补充
        if self._game_lifecycle == GameLifecycle.READY:
            return

        result = self._enrich_player_info_core(re_bridge=True, re_emit=True)
        if result is None:
            return

        our_controller, opp_controller = result
        state = self.global_tracker.state

        # 检查职业信息是否补全
        if state.player_hero_class and state.opp_hero_class:
            if self._game_lifecycle == GameLifecycle.STARTING:
                # 从 STARTING → READY，发送最终 game_started
                self._game_lifecycle = GameLifecycle.READY
                self._emit_game_started(our_controller, opp_controller)

    def _handle_controller_correction(self, old_our, new_our, old_opp, new_opp,
                                       re_bridge: bool = True):
        """处理 controller 修正（提取自多处重复逻辑）。

        当检测到 controller 值变化时，重置 GlobalTracker 状态并重新桥接实体。
        """
        logger.info("Controller 修正: our %d→%d, opp %d→%d",
                    old_our, new_our, old_opp, new_opp)
        if re_bridge:
            self.global_tracker.on_game_start()
            self.global_tracker.set_controllers(new_our, new_opp)
            self._bridged_entities.clear()
            self._bridge_entities_to_global_tracker()
            self._bridge_new_entities()
        else:
            self.global_tracker.set_controllers(new_our, new_opp)

    def _refresh_opp_counts(self, opp_player):
        """统一更新对手牌库/手牌/武器/地点计数（消除 4 处重复代码块）。"""
        opp_entities = list(opp_player.entities)
        gt = self.global_tracker
        gt.count_opp_deck(opp_entities)
        gt.count_opp_hand(opp_entities)
        gt.update_opp_weapon(opp_entities)
        gt.update_opp_locations(opp_entities)

    def _emit_game_started(self, our_controller: int, opp_controller: int):
        """构建并发送 game_started 信号（消除 _on_game_start 和 _try_enrich_player_info 中的重复构建代码）。"""
        state = self.global_tracker.state
        info = {
            "player_class": class_to_cn(state.player_hero_class) if state.player_hero_class else "未知",
            "opp_class": class_to_cn(state.opp_hero_class) if state.opp_hero_class else "未知",
            "player_class_en": state.player_hero_class or "UNKNOWN",
            "opp_class_en": state.opp_hero_class or "UNKNOWN",
            "turn": self.game_tracker.get_current_turn(),
            "our_controller": our_controller,
            "opp_controller": opp_controller,
        }
        if self.on_game_started:
            self.on_game_started(info)

    def _on_game_start(self):
        """游戏开始事件处理。"""
        logger.info("游戏开始")

        # 保存上局 controller 值（在重置之前），用于玩家身份检测。
        # 关键修复：global_tracker.on_game_start() 会将 controller 重置为 0，
        # 导致 _detect_my_idx 在 PvP 双方都有 BattleTag 时无法匹配，
        # 默认 my_idx=0 导致 50% 概率把对手识别为"我方"。
        saved_our_controller = self.global_tracker.our_controller
        saved_opp_controller = self.global_tracker.opp_controller

        # 重置增量桥接追踪
        self._bridged_entities.clear()
        self._last_known_zones.clear()
        self._last_known_card_ids.clear()
        self._first_player_detected = False
        # 注意：不再清空 _player_names — DebugPrintGame() 的 PlayerName 行
        # 可能在 CREATE_GAME 之前就已解析，清空会丢失当前游戏的有效信息。
        # _player_names 在日志轮转时清空（line 355）。
        self._game_lifecycle = GameLifecycle.STARTING

        # 重置 GlobalTracker 状态（清空旧游戏数据）
        self.global_tracker.on_game_start()

        # 尝试获取初始 controller 分配
        our_controller = 1
        opp_controller = 2
        try:
            exporter = self.game_tracker.export_entities()
            if exporter is not None and hasattr(exporter, 'players') and len(exporter.players) >= 2:
                players = list(exporter.players)
                # 传入上局 controller 用于匹配（解决 PvP 双 BattleTag 识别问题）
                my_idx = self._detect_my_idx(players, saved_our_controller=saved_our_controller)
                our_controller = players[my_idx].tags.get(GameTag.CONTROLLER, my_idx + 1)
                opp_controller = players[1 - my_idx].tags.get(GameTag.CONTROLLER, 2 - my_idx)
                logger.info("玩家检测: 我方=players[%d](controller=%d), 对手=players[%d](controller=%d), saved_ctrl=(%d,%d)",
                            my_idx, our_controller, 1 - my_idx, opp_controller,
                            saved_our_controller, saved_opp_controller)
                # 保存我方名称用于后续游戏识别（跨游戏持久化）
                our_name = getattr(players[my_idx], 'name', '') or ''
                if our_name and '#' in our_name and our_name != 'UNKNOWN HUMAN PLAYER':
                    self._our_known_name = our_name
                    logger.debug("保存我方名称: %s (从 hslog player.name)", our_name)
        except Exception as e:
            logger.debug("检测玩家 controller 失败: %s", e)

        self.global_tracker.set_controllers(our_controller, opp_controller)

        # 在桥接之前尝试补充玩家信息，确定最终 controller
        # 避免先桥接后发现 controller 不对，需要重置再重新桥接的问题
        enriched = self._enrich_player_info_core(re_bridge=False, re_emit=False)
        if enriched is not None:
            our_controller, opp_controller = enriched
            self.global_tracker.set_controllers(our_controller, opp_controller)

        # 桥接实体事件到 GlobalTracker（在 controller 确定之后）
        self._bridge_entities_to_global_tracker()
        self._bridge_new_entities()

        # 不在此处设置 _game_lifecycle = READY，
        # 让 _try_enrich_player_info 处理完整的生命周期转换。
        # 这样即使初始检测有误，后续 _player_names 填充后仍可修正。

        self._notify_state_update()

    def _on_game_end(self):
        """游戏结束事件处理。保存最终快照用于验证。"""
        logger.info("游戏结束")
        self._game_lifecycle = GameLifecycle.ENDED
        # 在结束前保存最终状态快照
        self._final_state = self.build_state_dict()
        if self.on_game_ended:
            self.on_game_ended()
        # 重置 GlobalTracker 状态，避免下局开始前 overlay 显示旧游戏数据
        self.global_tracker.on_game_start()
        # 重置增量桥接追踪
        self._bridged_entities.clear()
        self._last_known_zones.clear()
        self._last_known_card_ids.clear()
        self._first_player_detected = False
        # 结束回调完成后重置为 IDLE
        self._game_lifecycle = GameLifecycle.IDLE

    def _on_turn_start(self):
        """回合开始事件处理。"""
        turn = self.game_tracker.get_current_turn()
        logger.info("回合 %d 开始", turn)
        self.global_tracker.on_turn_change(turn)
        if self.on_turn_changed:
            self.on_turn_changed(turn)
        self._notify_state_update()

    def _notify_state_update(self):
        """通知 UI 更新游戏状态。"""
        # 先桥接新实体，确保 GlobalTracker 状态最新
        self._bridge_new_entities()
        # 如果职业信息不完整，尝试补充
        self._try_enrich_player_info()
        state = self.build_state_dict()
        if self.on_state_updated:
            self.on_state_updated(state)

    def build_state_dict(self) -> dict:
        """构建游戏状态字典用于 UI 展示。"""
        # 确保所有新实体已桥接
        self._bridge_new_entities()

        gt_state = self.global_tracker.state
        gt = self.global_tracker

        opp_hand_count = gt_state.opp_hand_count
        opp_deck_count = gt_state.opp_deck_remaining

        bayesian = gt.get_bayesian_state()
        secret_report = gt.get_secret_report()
        known_hand = gt.get_opp_known_hand()
        card_breakdown = gt.get_opp_card_breakdown()

        return {
            "in_game": self.game_tracker.in_game,
            "turn": self.game_tracker.get_current_turn(),
            "step": self.game_tracker.get_step(),
            "player_class": class_to_cn(gt_state.player_hero_class) if gt_state.player_hero_class else "未知",
            "opp_class": class_to_cn(gt_state.opp_hero_class) if gt_state.opp_hero_class else "未知",
            "player_class_en": gt_state.player_hero_class or "UNKNOWN",
            "opp_class_en": gt_state.opp_hero_class or "UNKNOWN",
            "opp_hand_count": opp_hand_count,
            "opp_deck_count": opp_deck_count,
            "opp_initial_deck_size": gt_state.opp_initial_deck_size,
            "opp_secrets": list(gt_state.opp_secrets),
            "opp_weapon": gt_state.opp_weapon,
            "opp_weapon_atk": gt_state.opp_weapon_atk,
            "opp_weapon_durability": gt_state.opp_weapon_durability,
            "opp_locations": list(gt_state.opp_locations),
            "opp_corpses": gt_state.opp_corpses,
            "opp_herald_count": gt_state.opp_herald_count,
            "player_corpses": gt_state.player_corpses,
            "player_hand_count": gt_state.player_hand_count,
            "player_deck_count": gt_state.player_deck_remaining,
            "player_initial_deck_size": gt_state.player_initial_deck_size,
            "player_weapon": gt_state.player_weapon,
            "player_weapon_atk": gt_state.player_weapon_atk,
            "player_weapon_durability": gt_state.player_weapon_durability,
            "player_locations": list(gt_state.player_locations),
            "player_board_minions": list(gt_state.player_board_minions),
            "opp_board_minions": list(gt_state.opp_board_minions),
            "opp_shuffled_into_deck": list(gt_state.opp_shuffled_into_deck),
            "is_first_player": gt_state.is_first_player,
            "coin_used": gt_state.coin_used,
            "opp_hand_hold": dict(gt_state.opp_hand_hold_since),
            # ── 对手可用法力推断 ──
            # 从回合数估算：基础法力 = min(turn, 10)
            # 后手硬币已单独追踪，此处不额外加1
            "available_mana": min(self.game_tracker.get_current_turn(), 10),
            # ── 对手本回合打出的卡牌（用于计算已花费法力） ──
            "opp_cards_played_this_turn": list(gt_state.cards_played_this_turn_opp),
            "known_hand": [(eid, cid) for eid, cid in known_hand],
            "known_cards": [
                {
                    "card_id": kc.card_id,
                    "turn_seen": kc.turn_seen,
                    "source": kc.source.value if hasattr(kc.source, "value") else str(kc.source),
                    "card_type": kc.card_type,
                    "cost": kc.cost,
                    "race": kc.race,
                    "spell_school": kc.spell_school,
                    "conditional_evidence": kc.conditional_evidence,
                    "effect_triggered": kc.effect_triggered,
                }
                for kc in gt_state.opp_known_cards
            ],
            "generated_cards": list(gt_state.opp_generated_seen),
            "graveyard": list(gt_state.opp_graveyard_seen),
            "peeked_deck_cards": list(gt_state.opp_peeked_deck_cards),
            "hand_transforms": list(gt_state.opp_hand_transforms),
            "discarded_cards": list(gt_state.opp_discarded_cards),
            "hand_type_constraints": list(gt_state.opp_hand_type_constraints),
            "confirmed_hand_cards": list(gt_state.opp_confirmed_hand_cards),
            "bayesian": bayesian,
            "secret_report": secret_report,
            "card_breakdown": card_breakdown,
            "player_stats": {
                "minions_played": gt_state.player_stats.minions_played,
                "spells_played": gt_state.player_stats.spells_played,
                "fatigue_damage": gt_state.player_stats.fatigue_damage,
                "overload_next": gt_state.player_stats.overload_next,
            },
            "opp_stats": {
                "minions_played": gt_state.opp_stats.minions_played,
                "spells_played": gt_state.opp_stats.spells_played,
                "weapons_played": gt_state.opp_stats.weapons_played,
                "heroes_played": gt_state.opp_stats.heroes_played,
                "locations_played": gt_state.opp_stats.locations_played,
                "generated_cards_played": gt_state.opp_stats.generated_cards_played,
                "deck_cards_played": gt_state.opp_stats.deck_cards_played,
                "fatigue_damage": gt_state.opp_stats.fatigue_damage,
                "overload_next": gt_state.opp_stats.overload_next,
                "cards_drawn": gt_state.opp_stats.cards_drawn,
                "cards_milled": gt_state.opp_stats.cards_milled,
            },
            # ── 信息揭示追踪数据 ──
            "reveal_info": {
                "known_deck_cards": dict(gt_state.opp_known_deck_cards),
                "known_hand_types": [
                    {
                        "entity_id": ht.get("entity_id", 0),
                        "turn": ht.get("turn", 0),
                        "race": ht.get("race", ""),
                        "spell_school": ht.get("spell_school", ""),
                        "search_type": ht.get("search_type", ""),
                    }
                    for ht in gt_state.opp_known_hand_types
                ],
                "revealed_hand_cards": [
                    {
                        "card_id": rec.card_id,
                        "reveal_type": rec.reveal_type.value if hasattr(rec.reveal_type, "value") else str(rec.reveal_type),
                        "turn": rec.turn,
                        "entity_id": rec.entity_id,
                        "details": rec.details,
                    }
                    for rec in gt_state.opp_revealed_hand_cards
                ],
                "revealed_deck_cards": [
                    {
                        "card_id": rec.card_id,
                        "reveal_type": rec.reveal_type.value if hasattr(rec.reveal_type, "value") else str(rec.reveal_type),
                        "turn": rec.turn,
                        "entity_id": rec.entity_id,
                        "details": rec.details,
                    }
                    for rec in gt_state.opp_revealed_deck_cards
                ],
                "transform_events": [
                    {
                        "card_id": rec.card_id,
                        "source_card_id": rec.source_card_id,
                        "reveal_type": rec.reveal_type.value if hasattr(rec.reveal_type, "value") else str(rec.reveal_type),
                        "turn": rec.turn,
                        "entity_id": rec.entity_id,
                        "details": rec.details,
                    }
                    for rec in gt_state.opp_transform_events
                ],
                "tutor_evidence": [
                    {
                        "card_id": rec.card_id,
                        "reveal_type": rec.reveal_type.value if hasattr(rec.reveal_type, "value") else str(rec.reveal_type),
                        "turn": rec.turn,
                        "entity_id": rec.entity_id,
                        "details": rec.details,
                    }
                    for rec in gt_state.opp_tutor_evidence
                ],
                "deck_insert_events": [
                    {
                        "card_id": rec.card_id,
                        "reveal_type": rec.reveal_type.value if hasattr(rec.reveal_type, "value") else str(rec.reveal_type),
                        "turn": rec.turn,
                        "entity_id": rec.entity_id,
                        "details": rec.details,
                    }
                    for rec in gt_state.opp_deck_insert_events
                ],
                "entity_transforms": {
                    str(eid): f"{old}→{new}"
                    for eid, (old, new) in gt_state.opp_entity_transforms.items()
                },
            },
        }

    def _bridge_entities_to_global_tracker(self):
        """将 GameTracker 中已解析的实体桥接到 GlobalTracker。

        从 entity_cache 中读取实体信息，调用 GlobalTracker 的
        on_full_entity / on_show_entity / on_zone_change 方法。
        委托给 _bridge_single_entity 统一处理。
        """
        ec = self.game_tracker.entity_cache

        for entity_id, ent_data in ec.items():
            self._bridge_single_entity(entity_id, ent_data)

        # 更新牌库计数
        self._refresh_opp_counts_from_exporter()

    def _bridge_single_entity(self, entity_id: int, ent_data: dict) -> bool:
        """桥接单个实体到 GlobalTracker（统一桥接逻辑）。

        合并了 _bridge_entities_to_global_tracker 和 _bridge_new_entities 中
        重复的实体桥接逻辑，包括：
        - 字段提取
        - on_full_entity / on_show_entity 调用
        - DECK 区域特殊处理
        - 已桥接标记和区域追踪

        Returns:
            True 如果实体被成功处理（新实体），False 如果跳过
        """
        gt = self.global_tracker
        fields = _extract_entity_fields(ent_data)

        # P0 #3: 使用 _last_known_zones 中的区域作为 on_full_entity 的初始区域
        # 如果实体在桥接之前已经发生过区域变化，应使用最早记录的区域
        initial_zone = self._last_known_zones.get(entity_id, fields.zone)

        # P1 #5: 对手 DECK 实体即使没有 card_id 也需要调用 on_full_entity
        # 以确保 opp_initial_deck_size 正确计数
        is_opp_deck_no_cardid = (
            not fields.card_id
            and fields.controller == gt.opp_controller
            and fields.zone == ZONE_DECK
        )

        if fields.card_id or is_opp_deck_no_cardid:
            # 先调用 on_full_entity（记录实体出生 + 检测硬币 + 牌库计数）
            gt.on_full_entity(
                entity_id=entity_id,
                card_id=fields.card_id or "",
                controller=fields.controller,
                zone=initial_zone,  # P0 #3: 使用最初记录的区域
                card_type=fields.card_type,
                cost=fields.cost,
                is_coin_tag=fields.is_coin_tag,
            )

            # P1 #8: 只为对手非 DECK 区域的实体调用 on_show_entity
            # DECK 区域始终可见的实体（FULL_ENTITY with card_id）不是"揭示"事件，
            # 不应创建虚假的窥探记录
            # 只有当实体从隐藏变为可见（如 DECK 中无 cardid 的实体获得 cardid）
            # 或者对手实体不在 DECK 区域时，才调用 on_show_entity
            if fields.card_id:
                is_opp = (fields.controller == gt.opp_controller)
                if not is_opp or fields.zone != ZONE_DECK:
                    # 对手非 DECK 区域 或 我方实体 → 调用 on_show_entity
                    gt.on_show_entity(
                        entity_id=entity_id,
                        card_id=fields.card_id,
                        controller=fields.controller,
                        zone=fields.zone,
                        card_type=fields.card_type,
                        cost=fields.cost,
                        is_coin_tag=fields.is_coin_tag,
                    )

            # 记录区域和初始 card_id，用于后续 ChangeEntity 变形和窥探揭示检测
            self._last_known_zones[entity_id] = fields.zone
            self._last_known_card_ids[entity_id] = fields.card_id or ""

            # 标记为已桥接
            self._bridged_entities.add(entity_id)
        else:
            # 无 card_id 的非对手 DECK 实体：只在 DECK 区域或 ENCHANTMENT 时标记已桥接
            # DECK 中的暗牌可能后续通过窥探效果获得 card_id，
            # 此时 _bridge_new_entities 的 card_id diff 会检测到并 dispatch on_show_entity
            # 非 DECK 区域的实体可能后续通过 SHOW_ENTITY 获得 card_id，
            # 不标记为已桥接以便后续重新处理
            # ENCHANTMENT 类型的无 card_id 实体（附魔）需要标记已桥接，
            # 避免无限重复处理
            if fields.zone == ZONE_DECK or fields.card_type == CT_ENCHANTMENT:
                self._bridged_entities.add(entity_id)
            # 记录区域和 card_id（空）
            self._last_known_zones[entity_id] = fields.zone
            self._last_known_card_ids[entity_id] = ""

        return True

    def _refresh_opp_counts_from_exporter(self):
        """从 hslog exporter 获取对手玩家并更新计数（提取自多个调用点）。"""
        try:
            game = self.game_tracker.current_game
            if game is None:
                return
            exporter = self.game_tracker.export_entities()
            if exporter is None:
                return
            players = list(exporter.players)
            if len(players) < 2:
                return
            my_idx = self._detect_my_idx(players)
            opp_player = players[1 - my_idx]
            self._refresh_opp_counts(opp_player)
        except Exception as e:
            logger.debug("更新对手计数失败: %s", e)

    def _bridge_new_entities(self):
        """增量桥接：将 entity_cache 中尚未桥接的新实体转发到 GlobalTracker。

        每次调用只处理自上次桥接以来新增的实体，避免重复处理。
        这确保了对手打出的牌、区域变化等事件能实时反映到 GlobalTracker，
        从而驱动贝叶斯推断和手牌预测。

        对于已桥接的实体，如果其区域发生了变化（TAG_CHANGE 更新了 cache），
        也会桥接 zone_change 事件到 GlobalTracker。
        """
        ec = self.game_tracker.entity_cache

        new_count = 0
        for entity_id, ent_data in ec.items():
            if entity_id in self._bridged_entities:
                # 已桥接的实体——检查区域或 card_id 是否变化
                fields = _extract_entity_fields(ent_data)
                old_zone = self._last_known_zones.get(entity_id)
                if old_zone is not None and old_zone != fields.zone:
                    # 区域变化，桥接到 GlobalTracker
                    self.global_tracker.on_zone_change(
                        entity_id=entity_id,
                        controller=fields.controller,
                        old_zone=old_zone,
                        new_zone=fields.zone,
                        card_id=fields.card_id,
                        card_type=fields.card_type,
                    )
                    self._last_known_zones[entity_id] = fields.zone
                # 检测 DECK 区域实体新获得 card_id（窥探揭示效果）
                # 这类实体之前已在 DECK 中桥接，但当时没有 card_id
                old_card_id = self._last_known_card_ids.get(entity_id)
                if fields.card_id and old_card_id != fields.card_id:
                    self.global_tracker.on_show_entity(
                        entity_id=entity_id,
                        card_id=fields.card_id,
                        controller=fields.controller,
                        zone=fields.zone,
                        card_type=fields.card_type,
                        cost=fields.cost,
                        is_coin_tag=fields.is_coin_tag,
                    )
                    self._last_known_card_ids[entity_id] = fields.card_id
                elif not fields.card_id and old_card_id is None:
                    # 首次记录无 card_id 的实体
                    self._last_known_card_ids[entity_id] = ""
                continue

            # 使用统一的单实体桥接方法
            if self._bridge_single_entity(entity_id, ent_data):
                new_count += 1

        # 更新牌库/手牌计数（如果有新实体）
        if new_count > 0:
            self._refresh_opp_counts_from_exporter()

        if new_count > 0:
            logger.debug("增量桥接: %d 个新实体", new_count)

    def load_existing_log(self, path: str | Path):
        """加载已有的 Power.log 文件（用于验证/离线模式）。

        逐行喂入以实时桥接实体到 GlobalTracker。

        Args:
            path: Power.log 文件路径
        """
        path = Path(path)
        if not path.exists():
            logger.error("文件不存在: %s", path)
            return

        logger.info("加载已有日志: %s", path)

        # 使用 _process_lines 逐行处理，确保实时桥接
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            self._process_lines([line.rstrip("\n") for line in lines])
        except Exception as e:
            logger.error("加载日志失败: %s", e)

        # 补充：使用统一的核心方法提取完整玩家信息
        old_our_ctrl = self.global_tracker.our_controller
        old_opp_ctrl = self.global_tracker.opp_controller
        # 离线模式：使用核心方法但不重新发送信号
        self._enrich_player_info_core(re_bridge=True, re_emit=False)

        # 如果 controller 被修正了，_enrich_player_info_core 内部已处理重新桥接
        new_our_ctrl = self.global_tracker.our_controller
        new_opp_ctrl = self.global_tracker.opp_controller
        if old_our_ctrl == new_our_ctrl and old_opp_ctrl == new_opp_ctrl:
            self._bridge_new_entities()

        logger.info("日志加载完成")

    # _enrich_player_info 已被 _enrich_player_info_core 替代
    # 保留方法名作为兼容别名，避免外部调用点报错
    def _enrich_player_info(self, log_path: str):
        """兼容方法：委托给 _enrich_player_info_core。"""
        self._enrich_player_info_core(re_bridge=True, re_emit=False)


# ── PyQt5 QThread 包装器 ─────────────────────────────────────

if _HAS_PYQT5:
    class LogMonitor(QThread):
        """PyQt5 后台线程，监控 Power.log 并解析游戏事件。

        信号:
            game_started(dict)     — 游戏开始
            game_ended()           — 游戏结束
            turn_changed(int)      — 回合切换
            state_updated(dict)    — 游戏状态更新（最多 10 FPS）
            log_error(str)         — 日志解析错误
        """

        game_started = _pyqtSignal(dict)
        game_ended = _pyqtSignal()
        turn_changed = _pyqtSignal(int)
        state_updated = _pyqtSignal(dict)
        log_error = _pyqtSignal(str)

        def __init__(
            self,
            log_path: Optional[str | Path] = None,
            poll_interval: float = 0.1,
            parent=None,
        ):
            super().__init__(parent)
            self._core = CoreLogMonitor(log_path, poll_interval)

            # 桥接回调到信号
            self._core.on_game_started = self.game_started.emit
            self._core.on_game_ended = self.game_ended.emit
            self._core.on_turn_changed = self.turn_changed.emit
            self._core.on_state_updated = self.state_updated.emit
            self._core.on_log_error = self.log_error.emit

        @property
        def game_tracker(self):
            return self._core.game_tracker

        @property
        def global_tracker(self):
            return self._core.global_tracker

        @property
        def log_path(self):
            return self._core.log_path

        @log_path.setter
        def log_path(self, value):
            self._core.log_path = value

        def auto_detect_log_path(self):
            return self._core.auto_detect_log_path()

        def run(self):
            self._core.run_poll_loop()

        def stop(self):
            self._core.stop()
            self.wait(3000)

        def build_state_dict(self):
            return self._core.build_state_dict()

        def load_existing_log(self, path):
            self._core.load_existing_log(path)

        def _on_game_start(self):
            self._core._on_game_start()

else:
    # 没有 PyQt5 时，LogMonitor 就是 CoreLogMonitor
    LogMonitor = CoreLogMonitor

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

from analysis.watcher.game_tracker import GameTracker, EntityCache
from analysis.watcher.global_tracker import GlobalTracker
from analysis.constants.hs_enums import (
    ZONE_PLAY, ZONE_DECK, ZONE_HAND, ZONE_GRAVEYARD,
    ZONE_SETASIDE, ZONE_SECRET,
    CT_HERO, CT_MINION, CT_SPELL, CT_ENCHANTMENT,
    CT_WEAPON, CT_HERO_POWER, CT_LOCATION,
)
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


# ── Zone/CardType 字符串→整数转换 ──────────────────────────────

_ZONE_MAP = {
    "INVALID": 0, "PLAY": 1, "DECK": 2, "HAND": 3,
    "GRAVEYARD": 4, "REMOVEDFROMGAME": 5, "SETASIDE": 6,
    "SECRET": 7,
}

_CARD_TYPE_MAP = {
    "INVALID": 0, "GAME": 1, "PLAYER": 2, "HERO": 3,
    "MINION": 4, "SPELL": 5, "ENCHANTMENT": 6, "WEAPON": 7,
    "ITEM": 8, "LOCATION": 39, "HERO_POWER": 10,
}


def _zone_to_int(zone_val) -> int:
    """将 Zone 值转换为整数（支持字符串如 "PLAY" 和整数如 1）。"""
    if isinstance(zone_val, int):
        return zone_val
    if isinstance(zone_val, str):
        return _ZONE_MAP.get(zone_val.upper(), 0)
    try:
        return int(zone_val)
    except (ValueError, TypeError):
        return 0


def _card_type_to_int(ct_val) -> int:
    """将 CardType 值转换为整数（支持字符串如 "MINION" 和整数如 4）。"""
    if isinstance(ct_val, int):
        return ct_val
    if isinstance(ct_val, str):
        return _CARD_TYPE_MAP.get(ct_val.upper(), 0)
    try:
        return int(ct_val)
    except (ValueError, TypeError):
        return 0


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
            logger.info("检测到日志轮转，重置读取位置")

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

    def _process_lines(self, lines: list[str]):
        """处理新行，喂入 GameTracker 并分发事件。"""
        for line in lines:
            if not line.strip():
                continue

            event = self.game_tracker.feed_line(line)
            if event is None:
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

    def _detect_my_idx(self, players) -> int:
        """确定哪个玩家是本地玩家（我方）。

        判定规则:
          1. 名字包含 '#' 的是 BattleTag 用户（本地玩家）
          2. 名字为 'UNKNOWN HUMAN PLAYER' 的是 AI
          3. 都不含 '#' 时默认 players[0] 为我方

        Returns:
            我方在 players 列表中的索引 (0 或 1)
        """
        my_idx = 0
        if len(players) >= 2:
            n0 = getattr(players[0], 'name', '') or ''
            n1 = getattr(players[1], 'name', '') or ''
            if '#' in n1 and ('#' not in n0 or n0 == 'UNKNOWN HUMAN PLAYER'):
                my_idx = 1
        return my_idx

    def _on_game_start(self):
        """游戏开始事件处理。"""
        logger.info("游戏开始")

        # 重置增量桥接追踪
        self._bridged_entities.clear()

        game = self.game_tracker.current_game
        our_controller = 1
        opp_controller = 2

        if game is not None:
            try:
                players = list(game.players)
                if len(players) >= 2:
                    my_idx = self._detect_my_idx(players)
                    our_controller = players[my_idx].tags.get(GameTag.CONTROLLER, my_idx + 1)
                    opp_controller = players[1 - my_idx].tags.get(GameTag.CONTROLLER, 2 - my_idx)
                    logger.info("玩家检测: 我方=players[%d](controller=%d), 对手=players[%d](controller=%d)",
                                my_idx, our_controller, 1 - my_idx, opp_controller)
            except Exception as e:
                logger.debug("检测玩家 controller 失败: %s", e)

        self.global_tracker.on_game_start()
        self.global_tracker.set_controllers(our_controller, opp_controller)

        # 桥接实体事件到 GlobalTracker
        self._bridge_entities_to_global_tracker()

        # 增量桥接：扫描 entity_cache 中尚未桥接的新实体
        self._bridge_new_entities()

        state = self.global_tracker.state
        from analysis.utils.hero_class import class_to_cn

        info = {
            "player_class": class_to_cn(state.player_hero_class) if state.player_hero_class else "未知",
            "opp_class": class_to_cn(state.opp_hero_class) if state.opp_hero_class else "未知",
            "player_class_en": state.player_hero_class or "UNKNOWN",
            "opp_class_en": state.opp_hero_class or "UNKNOWN",
            "turn": 0,
            "our_controller": our_controller,
            "opp_controller": opp_controller,
        }

        if self.on_game_started:
            self.on_game_started(info)
        self._notify_state_update()

    def _on_game_end(self):
        """游戏结束事件处理。保存最终快照用于验证。"""
        logger.info("游戏结束")
        # 在结束前保存最终状态快照
        self._final_state = self.build_state_dict()
        if self.on_game_ended:
            self.on_game_ended()

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
        state = self.build_state_dict()
        if self.on_state_updated:
            self.on_state_updated(state)

    def build_state_dict(self) -> dict:
        """构建游戏状态字典用于 UI 展示。"""
        # 确保所有新实体已桥接
        self._bridge_new_entities()

        gt_state = self.global_tracker.state
        gt = self.global_tracker

        opp_hand_count = gt_state.opp_hand_count or len(gt_state.opp_hand_card_ids)
        opp_deck_count = gt_state.opp_deck_remaining

        bayesian = gt.get_bayesian_state()
        secret_report = gt.get_secret_report()
        known_hand = gt.get_opp_known_hand()
        card_breakdown = gt.get_opp_card_breakdown()

        from analysis.utils.hero_class import class_to_cn

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
            "is_first_player": gt_state.is_first_player,
            "coin_used": gt_state.coin_used,
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
        }

    def _bridge_entities_to_global_tracker(self):
        """将 GameTracker 中已解析的实体桥接到 GlobalTracker。

        从 entity_cache 中读取实体信息，调用 GlobalTracker 的
        on_full_entity / on_show_entity / on_zone_change 方法。
        """
        ec = self.game_tracker.entity_cache
        gt = self.global_tracker

        for entity_id, ent_data in ec._entities.items():
            card_id = ent_data.get("card_id", "")
            tags = ent_data.get("tags", {})

            controller = tags.get(GameTag.CONTROLLER, 0)
            if not isinstance(controller, int):
                try:
                    controller = int(controller)
                except (ValueError, TypeError):
                    controller = 0

            zone = _zone_to_int(tags.get(GameTag.ZONE, 0))
            card_type = _card_type_to_int(tags.get(GameTag.CARDTYPE, 0))

            cost = tags.get(GameTag.COST, 0)
            if not isinstance(cost, int):
                try:
                    cost = int(cost)
                except (ValueError, TypeError):
                    cost = 0

            if card_id:
                gt.on_full_entity(
                    entity_id=entity_id,
                    card_id=card_id,
                    controller=controller,
                    zone=zone,
                    card_type=card_type,
                    cost=cost,
                )
                # 如果不是DECK区域（即已揭示的牌），也调用 on_show_entity
                if zone != ZONE_DECK:
                    gt.on_show_entity(
                        entity_id=entity_id,
                        card_id=card_id,
                        controller=controller,
                        zone=zone,
                        card_type=card_type,
                        cost=cost,
                    )

        # 更新牌库计数
        game = self.game_tracker.current_game
        if game is not None:
            try:
                exporter = self.game_tracker.export_entities()
                if exporter is not None:
                    players = list(exporter.players)
                    if len(players) >= 2:
                        my_idx = self._detect_my_idx(players)
                        opp_player = players[1 - my_idx]
                        our_player = players[my_idx]
                        opp_entities = list(opp_player.entities)
                        our_entities = list(our_player.entities)

                        gt.count_opp_deck(opp_entities)
                        gt.count_opp_hand(opp_entities)
                        gt.update_opp_weapon(opp_entities)
                        gt.update_opp_locations(opp_entities)
            except Exception as e:
                logger.debug("桥接实体到 GlobalTracker 失败: %s", e)

    def _bridge_new_entities(self):
        """增量桥接：将 entity_cache 中尚未桥接的新实体转发到 GlobalTracker。

        每次调用只处理自上次桥接以来新增的实体，避免重复处理。
        这确保了对手打出的牌、区域变化等事件能实时反映到 GlobalTracker，
        从而驱动贝叶斯推断和手牌预测。
        """
        ec = self.game_tracker.entity_cache
        gt = self.global_tracker

        new_count = 0
        for entity_id, ent_data in ec._entities.items():
            if entity_id in self._bridged_entities:
                continue

            card_id = ent_data.get("card_id", "")
            tags = ent_data.get("tags", {})

            # 解析关键字段
            controller = tags.get(GameTag.CONTROLLER, 0)
            if not isinstance(controller, int):
                try:
                    controller = int(controller)
                except (ValueError, TypeError):
                    controller = 0

            zone = _zone_to_int(tags.get(GameTag.ZONE, 0))
            card_type = _card_type_to_int(tags.get(GameTag.CARDTYPE, 0))

            cost = tags.get(GameTag.COST, 0)
            if not isinstance(cost, int):
                try:
                    cost = int(cost)
                except (ValueError, TypeError):
                    cost = 0

            if card_id:
                # 对手实体的 SHOW_ENTITY 桥接（最关键的路径）
                is_opp = (controller == gt.opp_controller)

                # 先调用 on_full_entity（记录实体出生）
                gt.on_full_entity(
                    entity_id=entity_id,
                    card_id=card_id,
                    controller=controller,
                    zone=zone,
                    card_type=card_type,
                    cost=cost,
                )

                # 如果实体不在 DECK 区域（已揭示的牌），也调用 on_show_entity
                if zone != ZONE_DECK:
                    gt.on_show_entity(
                        entity_id=entity_id,
                        card_id=card_id,
                        controller=controller,
                        zone=zone,
                        card_type=card_type,
                        cost=cost,
                    )

                # 检测区域变化（如果之前已桥接过且区域不同）
                # 这处理 TAG_CHANGE 引起的区域迁移

            self._bridged_entities.add(entity_id)
            new_count += 1

        # 更新牌库/手牌计数（如果有新实体）
        if new_count > 0:
            try:
                game = self.game_tracker.current_game
                if game is not None:
                    exporter = self.game_tracker.export_entities()
                    if exporter is not None:
                        players = list(exporter.players)
                        if len(players) >= 2:
                            my_idx = self._detect_my_idx(players)
                            opp_player = players[1 - my_idx]
                            opp_entities = list(opp_player.entities)
                            gt.count_opp_deck(opp_entities)
                            gt.count_opp_hand(opp_entities)
                            gt.update_opp_weapon(opp_entities)
                            gt.update_opp_locations(opp_entities)
            except Exception as e:
                logger.debug("增量桥接更新计数失败: %s", e)

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

        # 补充：使用 game_log_parser 提取完整玩家信息
        old_our_ctrl = self.global_tracker.our_controller
        old_opp_ctrl = self.global_tracker.opp_controller
        self._enrich_player_info(str(path))

        # 如果 controller 被修正了，需要重新桥接所有实体
        new_our_ctrl = self.global_tracker.our_controller
        new_opp_ctrl = self.global_tracker.opp_controller
        if old_our_ctrl != new_our_ctrl or old_opp_ctrl != new_opp_ctrl:
            logger.info("Controller 修正: our %d→%d, opp %d→%d — 重新桥接所有实体",
                        old_our_ctrl, new_our_ctrl, old_opp_ctrl, new_opp_ctrl)
            # 重置 GlobalTracker 状态并重新桥接
            self.global_tracker.on_game_start()
            self.global_tracker.set_controllers(new_our_ctrl, new_opp_ctrl)
            self._bridged_entities.clear()
            self._bridge_entities_to_global_tracker()
            self._bridge_new_entities()
        else:
            self._bridge_new_entities()

        logger.info("日志加载完成")

    def _enrich_player_info(self, log_path: str):
        """从 Power.log 提取完整的玩家信息（职业、controller等）。

        GameTracker 的 entity_cache 只解析实体标签，
        而 hslog 的 EntityTreeExporter 能提供更完整的玩家信息。
        """
        try:
            game = self.game_tracker.export_entities()
            if game is None or not hasattr(game, 'players') or len(game.players) < 2:
                return

            from hearthstone.enums import GameTag
            players = list(game.players)

            # 使用统一的玩家检测逻辑
            my_idx = self._detect_my_idx(players)
            our_player = players[my_idx]
            opp_player = players[1 - my_idx]

            our_controller = our_player.tags.get(GameTag.CONTROLLER, my_idx + 1)
            opp_controller = opp_player.tags.get(GameTag.CONTROLLER, 2 - my_idx)
            self.global_tracker.set_controllers(our_controller, opp_controller)

            # 从对手的实体中检测职业
            from analysis.watcher.game_log_parser import _get_hero_card_id
            opp_hero_id = _get_hero_card_id(opp_player)
            if opp_hero_id:
                meta = self.global_tracker._card_metadata(opp_hero_id)
                opp_class = meta.get('cardClass', '')
                if opp_class:
                    self.global_tracker.state.opp_hero_class = opp_class

            our_hero_id = _get_hero_card_id(our_player)
            if our_hero_id:
                meta = self.global_tracker._card_metadata(our_hero_id)
                our_class = meta.get('cardClass', '')
                if our_class:
                    self.global_tracker.state.player_hero_class = our_class

            # 更新牌库/武器/地点计数
            opp_entities = list(opp_player.entities)
            self.global_tracker.count_opp_deck(opp_entities)
            self.global_tracker.count_opp_hand(opp_entities)
            self.global_tracker.update_opp_weapon(opp_entities)
            self.global_tracker.update_opp_locations(opp_entities)

        except Exception as e:
            logger.debug("提取玩家信息失败: %s", e)


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

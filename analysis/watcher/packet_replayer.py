"""packet_replayer.py — 基于 hslog 的 Power.log 回放 + RHEA 分析引擎

用 hslog 库替代正则解析，修复:
- Zone/CardType 枚举值 (GRAVEYARD=4, LOCATION=39)
- FIRST_PLAYER 双方检测 (不再假设我方先手)
- 英雄职业从 CLASS 标签读取
- 武器从 CardType.WEAPON 提取
- 生命吸取 (Lifesteal) 正确设置
- 随从按 ZONE_POSITION 排序
- can_attack 检查 CANT_ATTACK
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hearthstone.enums import (
    CardClass, CardType, GameTag, PlayState, Step,
    Zone, BlockType,
)
from hslog import LogParser
from hslog import packets

from analysis.models.card import Card
from analysis.data.card_roles import RoleTag, classify_card_roles
from analysis.data.card_effects import get_effects
from analysis.data.card_index import get_index
from analysis.search.game_state import (
    GameState, HeroState, ManaState,
    Minion, OpponentState, Weapon,
)
from analysis.search.keywords import KeywordSet
from analysis.search.mechanics_state import MechanicsState
from analysis.search.discover import generate_discover_pool
from analysis.search.discover import _parse_discover_constraint
from analysis.search.engine.models.probability_panel import compute_panel
from analysis.search.engine.models.discover_model import DiscoverModel
from analysis.search.engine.models.draw_model import DrawModel
from analysis.search.rhea_engine import Action, RHEAEngine, enumerate_legal_actions
from analysis.watcher.global_tracker import CardSource, GlobalTracker
from analysis.utils.player_name import (
    normalize_player_name, is_anonymous_name, name_matches, ANON_DISPLAY,
)

_PLAYABLE_CLASSES = {
    "DEATHKNIGHT", "DEMONHUNTER", "DRUID", "HUNTER", "MAGE",
    "PALADIN", "PRIEST", "ROGUE", "SHAMAN", "WARLOCK", "WARRIOR",
}


# ─── 数据类 ───────────────────────────────────────────────────────────

@dataclass
class Entity:
    """轻量级实体，跟踪标签变更"""
    id: int = 0
    card_id: str = ""
    controller: int = 0        # player_id
    zone: int = 0              # Zone enum value
    zone_position: int = 0
    card_type: int = 0         # CardType enum value
    cost: int = 0
    atk: int = 0
    health: int = 0
    armor: int = 0
    exhausted: bool = False
    taunt: bool = False
    divine_shield: bool = False
    charge: bool = False
    rush: bool = False
    windfury: bool = False
    stealth: bool = False
    poisonous: bool = False
    lifesteal: bool = False
    frozen: bool = False
    reborn: bool = False
    immune: bool = False
    cant_attack: bool = False
    spell_power: int = 0


@dataclass
class PlayerState:
    """玩家资源状态"""
    resources: int = 0
    resources_used: int = 0
    overload_locked: int = 0
    temp_resources: int = 0
    max_mana: int = 0
    name: str = ""


@dataclass
class TurnDecision:
    """回合决策结果"""
    turn_number: int = 0
    player_name: str = ""
    is_our_turn: bool = True
    # --- 时间 ---
    timestamp: str = ""
    elapsed_ms: float = 0.0
    # --- 我方 ---
    hero_hp: int = 30
    hero_armor: int = 0
    hero_class: str = ""
    mana_available: int = 0
    mana_max: int = 0
    mana_used: int = 0
    overload_locked: int = 0
    temp_mana: int = 0
    board_count: int = 0
    hand_count: int = 0
    hand_cards: List[str] = field(default_factory=list)
    board_minions: List[str] = field(default_factory=list)
    deck_remaining: int = 0
    # --- 对手 ---
    opp_hero_hp: int = 30
    opp_hero_armor: int = 0
    opp_hero_class: str = ""
    opp_board_count: int = 0
    opp_board_minions: List[str] = field(default_factory=list)
    opp_hand_count: int = 0
    opp_deck_remaining: int = 0
    opp_known_hand_cards: List[str] = field(default_factory=list)
    # 对手已打出牌分类
    opp_deck_cards_played: List[str] = field(default_factory=list)     # 牌库牌（已打出）
    opp_generated_cards_played: List[str] = field(default_factory=list) # 衍生牌（已打出）
    opp_card_type_counts: Dict[str, int] = field(default_factory=dict) # 卡牌类型统计
    opp_generated_played: int = 0
    opp_secrets: List[str] = field(default_factory=list)
    # 对手卡组推理
    opp_archetype_name: Optional[str] = None
    opp_archetype_confidence: float = 0.0
    opp_top_archetypes: List[tuple] = field(default_factory=list)  # [(name, prob)]
    opp_playstyle: str = "unknown"  # aggro/control/combo/midrange
    opp_secret_report: Dict = field(default_factory=dict)  # secret probability report
    # --- 全局 ---
    player_global_stats: Optional[Dict] = None
    # --- 合法动作 ---
    legal_action_count: int = 0
    legal_actions: List[str] = field(default_factory=list)
    # --- RHEA ---
    rhea_best_score: float = 0.0
    rhea_best_actions: List[str] = field(default_factory=list)
    rhea_generations: int = 0
    rhea_elapsed_ms: float = 0.0
    # --- 评估 ---
    decision_quality: str = ""
    decision_score: float = 0.0
    lethal_available: bool = False
    lethal_executed: bool = False
    # --- 日志 ---
    summary_lines: List[str] = field(default_factory=list)
    effect_pool_reports: List[Dict[str, Any]] = field(default_factory=list)


# ─── 主类 ─────────────────────────────────────────────────────────────

class PacketReplayer:
    """基于 hslog 的 Power.log 回放分析器"""

    def __init__(
        self,
        log_dir: str = "logs",
        player_name: str = "",
        engine_params: Optional[Dict] = None,
    ):
        self.log_dir = log_dir
        self.player_name = player_name
        self.engine_params = engine_params or {}

        # --- 状态 ---
        self.entities: Dict[int, Entity] = {}
        self.players: Dict[int, PlayerState] = {}      # player_id → PlayerState
        self.controller_map: Dict[int, int] = {}         # entity_id → player_id
        self.decisions: List[TurnDecision] = []

        # 玩家映射
        self._player_entity_to_pid: Dict[int, int] = {}  # player entity_id → player_id
        self._player_name_map: Dict[str, int] = {}        # name → player_id
        self._our_player_id: int = 0
        self._opp_player_id: int = 0
        self._opp_name: str = ""

        # 回合 / 先手
        self.game_turn: int = 0
        self._we_are_first: Optional[bool] = None
        self._game_count: int = 0
        self._game_entity_id: int = 0

        # 英雄职业
        self._player_hero_class: str = "UNKNOWN"
        self._opp_hero_class: str = "UNKNOWN"

        # 全局追踪
        self.global_tracker = GlobalTracker()

        # 日志 & 缓存
        self._card_name_cache: Dict[str, str] = {}
        self._discover_pool_cache: Dict[str, List[Card]] = {}
        self._setup_loggers()

    # ─── 公共接口 ──────────────────────────────────────────────────

    def replay_file(self, path: str) -> List[TurnDecision]:
        """解析并回放 Power.log，返回每回合决策"""
        self._card_name_cache = self._load_card_names()
        self.global_tracker.on_game_start()
        parser = LogParser()
        parse_errors = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    parser.read_line(line)
                except Exception:
                    parse_errors += 1
        if self._main_logger and parse_errors:
            self._main_logger.info(f"⚠️ hslog 解析跳过 {parse_errors} 个异常行")
        for game_tree in parser.games:
            self._game_count += 1
            self._process_game(game_tree)
        self._save_summary()
        return self.decisions

    # ─── hslog 解析层 ──────────────────────────────────────────────

    def _process_game(self, packet_tree) -> None:
        """处理单个对局的所有 packet"""
        # Reset per-game state
        self.entities.clear()
        self.players.clear()
        self.controller_map.clear()
        self.game_turn = 0
        self._we_are_first = None
        self._last_processed_turn = 0
        self._player_hero_class = "UNKNOWN"
        self._opp_hero_class = "UNKNOWN"
        self._player_entity_to_pid.clear()
        self._player_name_map.clear()
        self._game_entity_id = 0
        self._our_player_id = 0
        self._opp_player_id = 0
        self._opp_name = ""
        self.global_tracker.on_game_start()

        if self._main_logger:
            self._main_logger.info("=" * 70)
            self._main_logger.info("🎮 新对局开始")
            self._main_logger.info("=" * 70)

        _FILTER = {
            packets.CreateGame, packets.FullEntity, packets.ShowEntity,
            packets.TagChange, packets.ChangeEntity, packets.HideEntity,
        }
        for packet in packet_tree.recursive_iter():
            if type(packet) in _FILTER:
                self._process_packet(packet)

    def _process_packet(self, packet) -> None:
        """按 packet 类型分发"""
        if isinstance(packet, packets.CreateGame):
            self._handle_create_game(packet)
        elif isinstance(packet, packets.FullEntity):
            self._handle_full_entity(packet)
        elif isinstance(packet, packets.ShowEntity):
            self._handle_show_entity(packet)
        elif isinstance(packet, packets.TagChange):
            self._handle_tag_change(packet)
        elif isinstance(packet, packets.ChangeEntity):
            entity_id = self._resolve_id(packet.entity)
            if entity_id in self.entities:
                if packet.card_id:
                    self.entities[entity_id].card_id = packet.card_id
                for tag, value in packet.tags:
                    self._apply_tag(self.entities[entity_id], tag, value)
        elif isinstance(packet, packets.HideEntity):
            entity_id = self._resolve_id(packet.entity)
            if entity_id in self.entities:
                old_zone = self.entities[entity_id].zone
                self.entities[entity_id].zone = packet.zone
                self.global_tracker.on_zone_change(
                    entity_id=entity_id,
                    controller=self.entities[entity_id].controller,
                    old_zone=old_zone,
                    new_zone=packet.zone,
                    card_id=self.entities[entity_id].card_id,
                    card_type=self.entities[entity_id].card_type,
                )

    def _handle_create_game(self, packet) -> None:
        """处理 CREATE_GAME — 初始化玩家映射"""
        self._game_entity_id = self._resolve_id(packet.entity)
        for player in packet.players:
            pid = player.player_id
            if hasattr(player.entity, 'name'):
                eid = getattr(player.entity, 'entity_id', player.entity)
                raw_name = getattr(player.entity, 'name', "") or ""
            else:
                eid = player.entity
                raw_name = player.name or ""

            name = normalize_player_name(raw_name)

            self._player_entity_to_pid[eid] = pid
            self._player_name_map[name or raw_name] = pid

            self.players[pid] = PlayerState(name=name or ANON_DISPLAY)

            for tag, value in player.tags:
                if tag == GameTag.RESOURCES:
                    self.players[pid].resources = value
                elif tag == GameTag.MAXRESOURCES:
                    self.players[pid].max_mana = value
                elif tag == GameTag.RESOURCES_USED:
                    self.players[pid].resources_used = value
                elif tag == GameTag.OVERLOAD_LOCKED:
                    self.players[pid].overload_locked = value
                elif tag == GameTag.TEMP_RESOURCES:
                    self.players[pid].temp_resources = value

            if self.player_name and name_matches(name, self.player_name):
                self._our_player_id = pid
            elif name and not is_anonymous_name(name):
                if not self.player_name:
                    self.player_name = name
                if name_matches(name, self.player_name):
                    self._our_player_id = pid
                else:
                    self._opp_player_id = pid
                    self._opp_name = name
            elif name or raw_name:
                self._opp_player_id = pid
                self._opp_name = name or ANON_DISPLAY

        if self._our_player_id and self._opp_player_id:
            self.global_tracker.set_controllers(
                self._our_player_id, self._opp_player_id
            )

        if self._main_logger and self._our_player_id:
            our = self.players.get(self._our_player_id)
            opp = self.players.get(self._opp_player_id)
            if our:
                self._main_logger.info(
                    f"🎮 我方: {our.name} (PlayerID={self._our_player_id})"
                )
            if opp:
                self._main_logger.info(
                    f"🎮 对手: {opp.name} (PlayerID={self._opp_player_id})"
                )

    def _handle_full_entity(self, packet) -> None:
        """处理 FULL_ENTITY — 创建/更新实体"""
        eid = self._resolve_id(packet.entity)
        cid = packet.card_id or ""

        if eid not in self.entities:
            self.entities[eid] = Entity(id=eid, card_id=cid)
        elif cid:
            self.entities[eid].card_id = cid

        entity = self.entities[eid]
        for tag, value in packet.tags:
            self._apply_tag(entity, tag, value)

        # Detect hero class from CLASS tag on hero entities
        if entity.card_type == CardType.HERO and entity.controller in (self._our_player_id, self._opp_player_id):
            for tag, value in packet.tags:
                if tag == GameTag.CLASS:
                    try:
                        cls_name = CardClass(value).name
                    except (ValueError, KeyError):
                        cls_name = str(value)
                    if entity.controller == self._our_player_id:
                        self._player_hero_class = cls_name
                    else:
                        self._opp_hero_class = cls_name
                    break

        # Notify global tracker
        self.global_tracker.on_full_entity(
            entity_id=eid, card_id=cid,
            controller=entity.controller, zone=entity.zone,
            card_type=entity.card_type, cost=entity.cost,
        )

    def _handle_show_entity(self, packet) -> None:
        """处理 SHOW_ENTITY — 卡牌揭示"""
        eid = self._resolve_id(packet.entity)
        cid = packet.card_id or ""

        if eid not in self.entities:
            self.entities[eid] = Entity(id=eid, card_id=cid)
        else:
            self.entities[eid].card_id = cid

        entity = self.entities[eid]
        for tag, value in packet.tags:
            self._apply_tag(entity, tag, value)

        # Detect hero class from CLASS tag on revealed hero entities
        if entity.card_type == CardType.HERO and entity.controller in (self._our_player_id, self._opp_player_id):
            for tag, value in packet.tags:
                if tag == GameTag.CLASS:
                    try:
                        cls_name = CardClass(value).name
                    except (ValueError, KeyError):
                        cls_name = str(value)
                    if entity.controller == self._our_player_id:
                        self._player_hero_class = cls_name
                    else:
                        self._opp_hero_class = cls_name
                    break

        self.global_tracker.on_show_entity(
            entity_id=eid, card_id=cid,
            controller=entity.controller, zone=entity.zone,
            card_type=entity.card_type, cost=entity.cost,
        )

    def _handle_tag_change(self, packet) -> None:
        """处理 TAG_CHANGE — 标签变更 + 决策点检测"""
        tag = packet.tag
        value = packet.value
        eid = self._resolve_id(packet.entity)

        # ── Game-level tags (STEP, TURN have entity=1 game entity) ──
        if tag == GameTag.STEP:
            step = Step(value)
            if step == Step.MAIN_ACTION:
                self._check_decision_point()
            return

        if tag == GameTag.TURN:
            if eid == self._game_entity_id:
                old_turn = self.game_turn
                self.game_turn = value
                if old_turn != value:
                    self.global_tracker.on_turn_change(value)
            return

        if tag == GameTag.FIRST_PLAYER:
            # entity is the player entity that IS the first player
            first_pid = self._player_entity_to_pid.get(eid, 0)
            if first_pid > 0 and self._our_player_id > 0:
                self._we_are_first = (first_pid == self._our_player_id)
                self.global_tracker.set_controllers(
                    self._our_player_id, self._opp_player_id
                )
                self.global_tracker.on_first_player(bool(self._we_are_first))
                if self._main_logger:
                    who = "我方先手" if self._we_are_first else "对手先手"
                    self._main_logger.info(f"🪙 {who}")
            return

        # ── Player entity tags (RESOURCES, etc.) ──
        if eid in self._player_entity_to_pid:
            pid = self._player_entity_to_pid[eid]
            ps = self.players.get(pid)
            if ps:
                if tag == GameTag.RESOURCES:
                    ps.resources = value
                elif tag == GameTag.RESOURCES_USED:
                    ps.resources_used = value
                elif tag == GameTag.MAXRESOURCES:
                    ps.max_mana = value
                elif tag == GameTag.OVERLOAD_LOCKED:
                    ps.overload_locked = value
                elif tag == GameTag.TEMP_RESOURCES:
                    ps.temp_resources = value
                elif tag == GameTag.OVERLOAD_OWED:
                    self.global_tracker.on_overload_change(pid, value)
            return

        # ── Card/Minion entity tags ──
        if eid in self.entities:
            entity = self.entities[eid]
            old_zone = entity.zone
            self._apply_tag(entity, tag, value)

            # Zone change notification
            if tag == GameTag.ZONE and old_zone != entity.zone:
                self.global_tracker.on_zone_change(
                    entity_id=eid,
                    controller=entity.controller,
                    old_zone=old_zone,
                    new_zone=entity.zone,
                    card_id=entity.card_id,
                    card_type=entity.card_type,
                )

    def _resolve_id(self, entity_ref) -> int:
        """解析 hslog entity reference → int (可能是 PlayerReference 或 int)"""
        if entity_ref is None:
            return 0
        if isinstance(entity_ref, int):
            return entity_ref
        if hasattr(entity_ref, 'entity_id'):
            return entity_ref.entity_id
        try:
            return int(entity_ref)
        except (TypeError, ValueError):
            return 0

    def _apply_tag(self, entity: Entity, tag, value: int) -> None:
        """将单个标签应用到实体"""
        TAG_MAP = {
            GameTag.ZONE: "zone",
            GameTag.CONTROLLER: "controller",
            GameTag.CARDTYPE: "card_type",
            GameTag.COST: "cost",
            GameTag.ATK: "atk",
            GameTag.HEALTH: "health",
            GameTag.ARMOR: "armor",
            GameTag.ZONE_POSITION: "zone_position",
            GameTag.SPELLPOWER: "spell_power",
        }
        BOOL_MAP = {
            GameTag.EXHAUSTED: "exhausted",
            GameTag.TAUNT: "taunt",
            GameTag.DIVINE_SHIELD: "divine_shield",
            GameTag.CHARGE: "charge",
            GameTag.RUSH: "rush",
            GameTag.WINDFURY: "windfury",
            GameTag.STEALTH: "stealth",
            GameTag.POISONOUS: "poisonous",
            GameTag.LIFESTEAL: "lifesteal",
            GameTag.FROZEN: "frozen",
            GameTag.REBORN: "reborn",
            GameTag.IMMUNE: "immune",
            GameTag.CANT_ATTACK: "cant_attack",
        }

        if tag in TAG_MAP:
            setattr(entity, TAG_MAP[tag], value)
        elif tag in BOOL_MAP:
            setattr(entity, BOOL_MAP[tag], bool(value))

    def _check_decision_point(self) -> None:
        """检测当前 MAIN_ACTION 是否为我方回合，触发分析

        每个 game_turn 可能触发两次 MAIN_ACTION (GameState + PowerTaskList)。
        只处理每 turn 的第一次。
        """
        # Deduplicate: skip if we already processed this turn
        if hasattr(self, '_last_processed_turn') and self._last_processed_turn == self.game_turn:
            return
        self._last_processed_turn = self.game_turn

        if self._we_are_first is None:
            is_our_turn = (self.game_turn % 2 == 1)
        else:
            if self._we_are_first:
                is_our_turn = (self.game_turn % 2 == 1)
            else:
                is_our_turn = (self.game_turn % 2 == 0)

        if is_our_turn:
            self._analyze_decision_point()
        else:
            self._collect_opponent_turn_info()

    # ─── 决策分析 (业务逻辑) ───────────────────────────────────────

    def _analyze_decision_point(self) -> None:
        """我方 MAIN_ACTION 决策点：构建 GameState → RHEA 分析"""
        try:
            # Player lookup — already resolved at CREATE_GAME time
            our_player = self.players.get(self._our_player_id)
            opp_player = self.players.get(self._opp_player_id)

            if not our_player:
                self._error_logger.error(f"无法找到我方玩家 (player_id={self._our_player_id})")
                return

            # Extract player entities
            our_entities = []
            opp_entities = []

            for entity_id, entity in self.entities.items():
                if entity.controller == self._our_player_id:
                    our_entities.append(entity)
                elif entity.controller == self._opp_player_id:
                    opp_entities.append(entity)

            # Extract hero HP/armor
            our_hero_hp = 30
            our_hero_armor = 0
            opp_hero_hp = 30
            opp_hero_armor = 0

            for entity in our_entities:
                if entity.card_type == CardType.HERO:
                    our_hero_hp = entity.health
                    our_hero_armor = entity.armor
                elif entity.card_type == CardType.MINION:
                    pass  # minions on board

            for entity in opp_entities:
                if entity.card_type == CardType.HERO:
                    opp_hero_hp = entity.health
                    opp_hero_armor = entity.armor

            # Extract board minions
            our_board = []
            opp_board = []

            for entity in our_entities:
                if entity.zone == Zone.PLAY and entity.card_type == CardType.MINION:
                    keywords = []
                    if entity.taunt: keywords.append("嘲讽")
                    if entity.divine_shield: keywords.append("圣盾")
                    if entity.charge: keywords.append("冲锋")
                    if entity.rush: keywords.append("突袭")
                    if entity.windfury: keywords.append("风怒")
                    if entity.stealth: keywords.append("潜行")
                    if entity.poisonous: keywords.append("剧毒")
                    if entity.frozen: keywords.append("冻结")
                    if entity.reborn: keywords.append("亡语")

                    our_board.append({
                        'name': self._card_name(entity.card_id),
                        'atk': entity.atk,
                        'health': entity.health,
                        'keywords': keywords,
                    })

            for entity in opp_entities:
                if entity.zone == Zone.PLAY and entity.card_type == CardType.MINION:
                    opp_board.append({
                        'name': self._card_name(entity.card_id),
                        'atk': entity.atk,
                        'health': entity.health,
                        'keywords': [],
                    })

            # Extract hand cards
            our_hand = []

            for entity in our_entities:
                if entity.zone == Zone.HAND:
                    if entity.card_type == CardType.MINION:
                        type_str = "随从"
                    elif entity.card_type == CardType.SPELL:
                        type_str = "法术"
                    elif entity.card_type == CardType.WEAPON:
                        type_str = "武器"
                    elif entity.card_type == CardType.HERO:
                        type_str = "英雄牌"
                    elif entity.card_type == CardType.LOCATION:
                        type_str = "地点"
                    elif entity.card_type == CardType.HERO_POWER:
                        type_str = "英雄技能"
                    else:
                        type_str = "未知"

                    our_hand.append({
                        'name': self._card_name(entity.card_id),
                        'cost': entity.cost,
                        'type': type_str,
                    })

            # Extract mana state
            # NOTE: STEP=MAIN_ACTION may fire BEFORE RESOURCES_USED is reset to 0
            # for the new turn.  At a decision point (MAIN_ACTION) no mana has been
            # spent yet this turn, so any resources_used > 0 is stale from last turn.
            mana_max = our_player.resources
            mana_used = our_player.resources_used
            mana_temp = our_player.temp_resources
            mana_overload = our_player.overload_locked
            if mana_used > 0:
                mana_used = 0  # reset stale value from previous turn
            mana_available = max(0, mana_max - mana_used - mana_overload + mana_temp)

            # Count opponent board
            opp_board_count = 0
            for entity in opp_entities:
                if entity.zone == Zone.PLAY and entity.card_type == CardType.MINION:
                    opp_board_count += 1

            # Count opponent deck / hand
            opp_deck_remaining = self.global_tracker.count_opp_deck(opp_entities)
            opp_hand_count = self.global_tracker.get_opp_hand_count(opp_entities)

            # Update opponent weapon/location tracking
            self.global_tracker.update_opp_weapon(opp_entities)
            self.global_tracker.update_opp_locations(opp_entities)

            # Build summary
            summary = {
                'turn_number': self.game_turn,
                'player_name': self.player_name,
                'player_turn': len([d for d in self.decisions if d.turn_number == self.game_turn]) + 1,
                'hero_hp': our_hero_hp,
                'hero_armor': our_hero_armor,
                'mana_max': mana_max,
                'mana_available': mana_available,
                'mana_used': mana_used,
                'mana_temp': mana_temp,
                'mana_overload': mana_overload,
                'board_count': len(our_board),
                'hand_count': len(our_hand),
                'hand_cards': our_hand[:8],
                'board_minions': our_board[:6],
                'opp_hero_hp': opp_hero_hp,
                'opp_hero_armor': opp_hero_armor,
                'opp_board_count': opp_board_count,
                'opp_hand_count': opp_hand_count,
                'opp_deck_remaining': opp_deck_remaining,
                'opp_known_hand': self.global_tracker.get_opp_known_hand(),
                'opp_generated_count': len(self.global_tracker.state.opp_generated_seen),
            }

            # Build mana detail parts for display
            mana_parts = [f"法力 {mana_available}/{mana_max}"]
            if mana_overload > 0:
                mana_parts.append(f"锁定{mana_overload}")
            if mana_temp > 0:
                mana_parts.append(f"临时{mana_temp}")
            # Show overload owed (next turn lock)
            overload_next = self.global_tracker.state.player_stats.overload_next
            if overload_next > 0:
                mana_parts.append(f"下回合锁{overload_next}")
            mana_detail = " | ".join(mana_parts)

            self._main_logger.info("=" * 70)
            self._main_logger.info(f"🎯 回合 {self.game_turn} ({self.player_name})")
            self._main_logger.info("=" * 70)
            self._main_logger.info(f"状态: 英雄 HP={our_hero_hp}/{30} 护甲={our_hero_armor} | "
                             f"{mana_detail} | "
                             f"场面 {len(our_board)}随从 | 手牌 {len(our_hand)}张")
            self._main_logger.info(f"  场面:")
            for i, m in enumerate(our_board[:6], 1):
                kw = f" ({' '.join(m['keywords'])})" if m['keywords'] else ""
                self._main_logger.info(f"    [{i}] {m['name']} {m['atk']}/{m['health']}{kw}")
            self._main_logger.info(f"  手牌:")
            if not our_hand:
                self._main_logger.info(f"    (空 — 卡牌可能在本决策点后加入)")
            for i, c in enumerate(our_hand[:8], 1):
                self._main_logger.info(f"    [{i}] {c['name']} ({c['cost']}费·{c['type']})")
            self._main_logger.info(f"对手: HP={opp_hero_hp} 护甲={opp_hero_armor} | "
                             f"场面 {opp_board_count}随从 | 手牌 {opp_hand_count}张 | "
                             f"牌库 {opp_deck_remaining}张")

            # Log opponent card intelligence
            opp_breakdown = self.global_tracker.get_opp_card_breakdown(self._card_name)
            if opp_breakdown["known_hand"]:
                self._main_logger.info(f"  对手已知手牌: {', '.join(opp_breakdown['known_hand'])}")
            if opp_breakdown["deck_cards_played"]:
                self._main_logger.info(f"  对手牌库牌: {', '.join(opp_breakdown['deck_cards_played'])}")
            if opp_breakdown["generated_cards_played"]:
                self._main_logger.info(f"  对手衍生牌: {', '.join(opp_breakdown['generated_cards_played'])}")
            tc = opp_breakdown["type_counts"]
            type_parts = [f"{k}{v}" for k, v in tc.items() if v > 0]
            if type_parts:
                self._main_logger.info(f"  对手出牌类型: {' '.join(type_parts)}")

            # Log opponent secrets
            if self.global_tracker.state.opp_secrets:
                sec_str = ", ".join(self._card_name(cid)
                                    for cid in self.global_tracker.state.opp_secrets)
                self._main_logger.info(f"  对手奥秘: {sec_str}")

            # Log Bayesian archetype inference
            bayesian = self.global_tracker.get_bayesian_state()
            if bayesian["archetype_name"]:
                self._main_logger.info(
                    f"  对手卡组: {bayesian['archetype_name']} "
                    f"(置信度={bayesian['deck_confidence']:.1%})")
            elif bayesian["top_decks"]:
                top_str = ", ".join(
                    f"{name}({prob:.1%})" for _, name, prob in bayesian["top_decks"][:3]
                )
                self._main_logger.info(f"  对手可能卡组: {top_str}")

            # Secret probability report
            secret_report = self.global_tracker.get_secret_report()
            if secret_report.get("active_secrets", 0) > 0:
                summary = secret_report.get("summary", "")
                attack_risk = secret_report.get("attack_risk", "0.00")
                spell_risk = secret_report.get("spell_risk", "0.00")
                self._main_logger.info(f"  对手奥秘风险: 攻击={attack_risk}, 施法={spell_risk}, {summary}")

            # Build GameState
            game_state = self._build_game_state()

            if not game_state or not game_state.hero:
                self._error_logger.error(f"无法构建 GameState")
                return

            # Enumerate legal actions
            legal_actions = enumerate_legal_actions(game_state)

            # Count action types
            action_breakdown = {}
            for action in legal_actions:
                action_breakdown[action.action_type] = action_breakdown.get(action.action_type, 0) + 1

            # Build action descriptions
            action_descriptions = []
            for i, action in enumerate(legal_actions[:15]):
                desc = action.describe(game_state)
                action_descriptions.append(f"  {i+1:2d}. {desc}")

            self._main_logger.info(f"⚖️ 合法动作: {len(legal_actions)} 个")
            for desc in action_descriptions:
                self._main_logger.info(desc)

            # Run RHEA
            self._main_logger.info("")
            self._main_logger.info("🔍 运行 RHEA 分析...")
            t0 = time.perf_counter()

            try:
                rhea_engine = RHEAEngine(**self.engine_params)
                search_result = rhea_engine.search(game_state)

                t1 = time.perf_counter()
                rhea_time_ms = (t1 - t0) * 1000.0

                # Evaluate decision quality
                decision_quality, decision_score = self._evaluate_decision(
                    game_state=game_state,
                    best_actions=search_result.best_chromosome,
                    best_score=search_result.best_fitness,
                    legal_actions=legal_actions,
                )
                effect_pool_reports = self._analyze_effect_pools(game_state)
                discover_pool = self._get_standard_discover_pool(self._player_hero_class)
                opp_hand_prior = self._estimate_opponent_hand_role_priors(opp_hand_count)
                prob_panel = compute_panel(
                    game_state,
                    discover_pool=discover_pool,
                    opp_hand_roles=opp_hand_prior,
                )
                probability_lines = self._build_effect_probability_lines(
                    game_state, effect_pool_reports, min_prob=0.05
                )
                if prob_panel.opp_threat_ev is not None:
                    probability_lines.extend(prob_panel.opp_threat_ev.format_lines())
                deck_model_line = (
                    f"牌库建模: 已知{getattr(game_state, 'deck_model_known', 0)} / "
                    f"补全{getattr(game_state, 'deck_model_inferred', 0)} / "
                    f"剩余{game_state.deck_remaining}"
                )
                opp_prior_line = self._format_opp_hand_prior_line(opp_hand_prior)
                if not probability_lines:
                    probability_lines = ["当前手牌无 发现/随机/抉择/抽牌 可计算效果"]

                # Log results
                self._decision_logger.info("=" * 70)
                self._decision_logger.info(f"回合 {self.game_turn} ({self.player_name})")
                self._decision_logger.info("=" * 70)
                self._decision_logger.info(f"状态: 英雄 HP={our_hero_hp}/{30} 护甲={our_hero_armor} | "
                                      f"{mana_detail} | "
                                      f"场面 {len(our_board)}随从 | 手牌 {len(our_hand)}张")
                self._decision_logger.info(f"对手: HP={opp_hero_hp} | 场面 {opp_board_count}随从")
                self._decision_logger.info(f"合法动作: {len(legal_actions)} 个 {action_breakdown}")

                for desc in action_descriptions:
                    self._decision_logger.info(desc)

                self._decision_logger.info("")
                self._decision_logger.info(f"RHEA 搜索: {rhea_time_ms:.1f}ms, {search_result.generations_run} 代")
                self._decision_logger.info(f"最佳适应度: {search_result.best_fitness:+.2f}")

                self._decision_logger.info("")
                self._decision_logger.info("最佳序列:")
                for i, action in enumerate(search_result.best_chromosome):
                    self._decision_logger.info(f"  {i+1}. {action.describe(game_state)}")

                self._decision_logger.info("")
                self._decision_logger.info("抉择期望(命中率>=5%):")
                self._decision_logger.info(f"  {deck_model_line}")
                for line in probability_lines:
                    self._decision_logger.info(f"  {line}")
                self._decision_logger.info(f"  {opp_prior_line}")
                if effect_pool_reports:
                    self._decision_logger.info("")
                    self._decision_logger.info("效果池分析(发现/随机获得):")
                    for report in effect_pool_reports:
                        self._decision_logger.info(
                            f"  [{report['effect_kind']}] {report['card_name']} "
                            f"| 池大小={report['pool_size']} | 约束={report['constraint']}"
                        )
                        for line in report.get("probability_lines", []):
                            self._decision_logger.info(f"    {line}")

                self._decision_logger.info("")
                self._decision_logger.info(f"抉择分析: {decision_quality}")
                self._decision_logger.info("=" * 70)

                # Store decision
                decision = TurnDecision(
                    turn_number=self.game_turn,
                    player_name=self.player_name,
                    is_our_turn=True,
                    hero_hp=our_hero_hp,
                    hero_armor=our_hero_armor,
                    hero_class=self._player_hero_class,
                    mana_available=mana_available,
                    mana_max=mana_max,
                    mana_used=mana_used,
                    overload_locked=mana_overload,
                    temp_mana=mana_temp,
                    board_count=len(our_board),
                    hand_count=len(our_hand),
                    hand_cards=[f"{c['name']}({c['cost']}费·{c['type']})" for c in our_hand[:8]],
                    board_minions=[f"{m['name']} {m['atk']}/{m['health']}" for m in our_board[:6]],
                    deck_remaining=0,
                    opp_hero_hp=opp_hero_hp,
                    opp_hero_armor=opp_hero_armor,
                    opp_hero_class=self._opp_hero_class,
                    opp_board_count=opp_board_count,
                    opp_board_minions=[f"{m['name']} {m['atk']}/{m['health']}" for m in opp_board[:7]],
                    opp_hand_count=opp_hand_count,
                    opp_deck_remaining=opp_deck_remaining,
                    opp_known_hand_cards=opp_breakdown["known_hand"],
                    opp_deck_cards_played=opp_breakdown["deck_cards_played"],
                    opp_generated_cards_played=opp_breakdown["generated_cards_played"],
                    opp_card_type_counts=opp_breakdown["type_counts"],
                    opp_generated_played=opp_breakdown["total_generated"],
                    opp_secrets=[self._card_name(cid) for cid in self.global_tracker.state.opp_secrets],
                    # Bayesian archetype inference
                    opp_archetype_name=bayesian.get("archetype_name"),
                    opp_archetype_confidence=bayesian.get("deck_confidence", 0.0),
                    opp_top_archetypes=[(name, prob) for _, name, prob in bayesian.get("top_decks", [])],
                    opp_playstyle=bayesian.get("playstyle", "unknown"),
                    opp_secret_report=secret_report if secret_report.get("active_secrets", 0) > 0 else {},
                    player_global_stats=self.global_tracker.player_summary_str(self._card_name),
                    legal_action_count=len(legal_actions),
                    legal_actions=[a.describe(game_state) for a in legal_actions[:15]],
                    rhea_best_score=search_result.best_fitness,
                    rhea_best_actions=[action.describe(game_state) for action in search_result.best_chromosome],
                    rhea_generations=search_result.generations_run,
                    rhea_elapsed_ms=rhea_time_ms,
                    decision_quality=decision_quality,
                    decision_score=decision_score,
                    summary_lines=[deck_model_line] + probability_lines + [opp_prior_line],
                    effect_pool_reports=effect_pool_reports,
                )
                self.decisions.append(decision)

            except Exception as e:
                self._error_logger.error(f"RHEA 搜索失败: {e}", exc_info=True)
                self.decisions.append(TurnDecision(
                    turn_number=self.game_turn,
                    player_name=self.player_name,
                    is_our_turn=True,
                    hero_hp=our_hero_hp,
                    hero_armor=our_hero_armor,
                    hero_class=self._player_hero_class,
                    mana_available=mana_available,
                    mana_max=mana_max,
                    mana_used=mana_used,
                    overload_locked=mana_overload,
                    temp_mana=mana_temp,
                    board_count=len(our_board),
                    hand_count=len(our_hand),
                    opp_hero_hp=opp_hero_hp,
                    opp_hero_armor=opp_hero_armor,
                    opp_hero_class=self._opp_hero_class,
                    opp_board_count=opp_board_count,
                    opp_hand_count=opp_hand_count,
                    opp_deck_remaining=opp_deck_remaining,
                    opp_secrets=[self._card_name(cid) for cid in self.global_tracker.state.opp_secrets],
                    legal_action_count=len(legal_actions),
                    legal_actions=[a.describe(game_state) for a in legal_actions[:15]],
                    rhea_best_score=0.0,
                    rhea_best_actions=[],
                    rhea_generations=0,
                    rhea_elapsed_ms=0.0,
                    decision_quality="❌ 错误",
                    decision_score=0.0,
                ))

        except Exception as e:
            self._error_logger.error(f"分析回合 {self.game_turn} 时出错: {e}", exc_info=True)

    def _build_game_state(self) -> Optional[GameState]:
        """从 Entity dict 构建 GameState (修复 weapon/hero_class/lifesteal/sort)"""
        try:
            our_pid = self._our_player_id
            opp_pid = self._opp_player_id

            # ── Partition entities ──
            our_entities = [e for e in self.entities.values() if e.controller == our_pid]
            opp_entities = [e for e in self.entities.values() if e.controller == opp_pid]

            # ── Extract hero ──
            our_hero = None
            for entity in our_entities:
                if entity.card_type == CardType.HERO:
                    our_hero = entity
                    break
            if our_hero is None:
                return None

            # ── Extract our weapon ──
            our_weapon = None
            for entity in our_entities:
                if entity.zone == Zone.PLAY and entity.card_type == CardType.WEAPON:
                    our_weapon = Weapon(
                        attack=entity.atk,
                        health=entity.health,
                        name=self._card_name(entity.card_id) or "",
                    )
                    break

            # ── Mana ──
            our_player = self.players.get(our_pid)
            if not our_player:
                return None
            max_mana = our_player.resources
            resources_used = our_player.resources_used
            # Same staleness fix: at decision point no mana spent yet
            if resources_used > 0:
                resources_used = 0
            temp = our_player.temp_resources
            overloaded = our_player.overload_locked
            available = max(0, max_mana - resources_used - overloaded + temp)

            # ── Our board (sorted by zone_position) ──
            board_minions = [
                e for e in our_entities
                if e.zone == Zone.PLAY and e.card_type == CardType.MINION
            ]
            board_minions.sort(key=lambda e: e.zone_position)

            board: List[Minion] = []
            for entity in board_minions:
                minion = Minion(
                    attack=entity.atk,
                    health=entity.health,
                    max_health=entity.health,
                    cost=entity.cost,
                    has_taunt=entity.taunt,
                    has_stealth=entity.stealth,
                    has_windfury=entity.windfury,
                    has_rush=entity.rush,
                    has_charge=entity.charge,
                    has_poisonous=entity.poisonous,
                    has_lifesteal=entity.lifesteal,
                    has_reborn=entity.reborn,
                    has_immune=entity.immune,
                    frozen_until_next_turn=entity.frozen,
                    has_divine_shield=entity.divine_shield,
                    cant_attack=entity.cant_attack or entity.exhausted,
                    name=self._card_name(entity.card_id) or "",
                    can_attack=not entity.exhausted and not entity.cant_attack,
                )
                minion.keywords = KeywordSet.from_minion(minion)
                board.append(minion)

            # ── Our hand ──
            _CT_MAP = {
                CardType.MINION: "MINION",
                CardType.SPELL: "SPELL",
                CardType.WEAPON: "WEAPON",
                CardType.HERO: "HERO",
                CardType.LOCATION: "LOCATION",
                CardType.HERO_POWER: "HERO_POWER",
            }

            hand: List[Card] = []
            try:
                from analysis.data.hsdb import get_db
                card_db = get_db()
            except ImportError:
                card_db = None
            for entity in our_entities:
                if entity.zone == Zone.HAND:
                    ct = _CT_MAP.get(entity.card_type, "MINION")
                    card_obj = None
                    if card_db and entity.card_id:
                        raw = card_db.get_card(entity.card_id)
                        if raw:
                            card_obj = Card.from_hsdb_dict(raw)
                    if card_obj is None:
                        card_obj = Card(
                            dbf_id=0,
                            name=self._card_name(entity.card_id) or "",
                            cost=entity.cost,
                            card_type=ct,
                        )
                    hand.append(card_obj)

            # ── Our hero state ──
            hero = HeroState(
                hp=our_hero.health,
                max_hp=our_hero.health,
                armor=our_hero.armor,
                weapon=our_weapon,
                hero_class=self._player_hero_class,
            )

            # ── Mana state ──
            overload_next = self.global_tracker.state.player_stats.overload_next
            mana = ManaState(
                max_mana=max_mana,
                available=available,
                overloaded=overloaded,
                overload_next=overload_next,
            )

            # ── Opponent hero ──
            opp_hero = None
            for entity in opp_entities:
                if entity.card_type == CardType.HERO:
                    opp_hero = entity
                    break

            # ── Opponent weapon ──
            opp_weapon = None
            for entity in opp_entities:
                if entity.zone == Zone.PLAY and entity.card_type == CardType.WEAPON:
                    opp_weapon = Weapon(
                        attack=entity.atk,
                        health=entity.health,
                        name=self._card_name(entity.card_id) or "",
                    )
                    break

            # ── Opponent board (sorted by zone_position) ──
            opp_board_minions = [
                e for e in opp_entities
                if e.zone == Zone.PLAY and e.card_type == CardType.MINION
            ]
            opp_board_minions.sort(key=lambda e: e.zone_position)

            opp_board: List[Minion] = []
            for entity in opp_board_minions:
                minion = Minion(
                    attack=entity.atk,
                    health=entity.health,
                    max_health=entity.health,
                    cost=entity.cost,
                    has_taunt=entity.taunt,
                    has_stealth=entity.stealth,
                    has_windfury=entity.windfury,
                    has_rush=entity.rush,
                    has_charge=entity.charge,
                    has_poisonous=entity.poisonous,
                    has_lifesteal=entity.lifesteal,
                    has_reborn=entity.reborn,
                    has_immune=entity.immune,
                    frozen_until_next_turn=entity.frozen,
                    has_divine_shield=entity.divine_shield,
                    cant_attack=entity.cant_attack or entity.exhausted,
                    name=self._card_name(entity.card_id) or "",
                    can_attack=not entity.exhausted and not entity.cant_attack,
                )
                minion.keywords = KeywordSet.from_minion(minion)
                opp_board.append(minion)

            # ── Deck remaining ──
            deck_remaining = sum(1 for e in our_entities if e.zone == Zone.DECK)
            opp_deck_remaining = self.global_tracker.count_opp_deck(opp_entities)
            deck_list: List[Card] = []
            known_deck_cards = 0
            for entity in our_entities:
                if entity.zone != Zone.DECK:
                    continue
                ct = _CT_MAP.get(entity.card_type, "MINION")
                card_obj = None
                if card_db and entity.card_id:
                    raw = card_db.get_card(entity.card_id)
                    if raw:
                        card_obj = Card.from_hsdb_dict(raw)
                        known_deck_cards += 1
                if card_obj is None and entity.card_id:
                    card_obj = Card(
                        dbf_id=0,
                        name=self._card_name(entity.card_id) or "",
                        cost=entity.cost,
                        card_type=ct,
                    )
                if card_obj is not None:
                    deck_list.append(card_obj)

            inferred_deck_cards = 0
            if deck_remaining > len(deck_list):
                need = deck_remaining - len(deck_list)
                exclude_ids = set()
                for entity in our_entities:
                    if entity.card_id and entity.zone != Zone.DECK:
                        exclude_ids.add(entity.card_id)
                for c in deck_list:
                    cid = getattr(c, "card_id", None)
                    if cid:
                        exclude_ids.add(cid)
                inferred = self._infer_unknown_deck_cards(
                    hero_class=self._player_hero_class,
                    need_count=need,
                    exclude_card_ids=exclude_ids,
                )
                inferred_deck_cards = len(inferred)
                deck_list.extend(inferred)

            # ── Build GameState ──
            game_state = GameState(
                turn_number=self.game_turn,
                hero=hero,
                mana=mana,
                board=board,
                hand=hand,
                deck_list=deck_list,
                deck_remaining=deck_remaining,
                opponent=OpponentState(
                    hero=HeroState(
                        hp=opp_hero.health if opp_hero else 30,
                        max_hp=opp_hero.health if opp_hero else 30,
                        armor=opp_hero.armor if opp_hero else 0,
                        weapon=opp_weapon,
                        hero_class=self._opp_hero_class,
                    ),
                    board=opp_board,
                    hand_count=len([e for e in opp_entities if e.zone == Zone.HAND]),
                    deck_remaining=opp_deck_remaining,
                    opp_known_cards=[
                        {"card_id": kc.card_id, "turn_seen": kc.turn_seen,
                         "source": kc.source.value, "card_type": kc.card_type}
                        for kc in self.global_tracker.state.opp_known_cards
                    ],
                    opp_generated_count=len(self.global_tracker.state.opp_generated_seen),
                    opp_secrets_triggered=[
                        {"card_id": kc.card_id, "turn_seen": kc.turn_seen}
                        for kc in self.global_tracker.state.opp_secrets_triggered
                    ],
                    secrets=list(self.global_tracker.state.opp_secrets),
                ),
            )
            game_state.deck_model_known = known_deck_cards
            game_state.deck_model_inferred = inferred_deck_cards

            # Populate Bayesian inference state
            bayesian = self.global_tracker.get_bayesian_state()
            game_state.opponent.locked_deck_id = bayesian["locked_deck_id"]
            game_state.opponent.deck_confidence = bayesian["deck_confidence"]

            # Populate mechanics from global tracker
            game_state._mechanics = MechanicsState.from_global_state(self.global_tracker.state)

            return game_state

        except Exception as e:
            if self._error_logger:
                self._error_logger.error(f"构建 GameState 失败: {e}", exc_info=True)
            return None

    def _get_standard_discover_pool(self, hero_class: str) -> List[Card]:
        hc = (hero_class or "").upper()
        if not hc or hc == "UNKNOWN":
            return []

        cached = self._discover_pool_cache.get(hc)
        if cached is not None:
            return cached

        cards: List[Card] = []
        try:
            raw_pool = generate_discover_pool(hc, use_wild_pool=False)
            for raw in raw_pool:
                try:
                    cards.append(Card.from_hsdb_dict(raw))
                except (TypeError, KeyError, ValueError):
                    continue
        except Exception:
            cards = []

        self._discover_pool_cache[hc] = cards
        return cards

    def _analyze_effect_pools(self, state: GameState) -> List[Dict[str, Any]]:
        reports: List[Dict[str, Any]] = []
        hand = state.hand or []
        discover_model = DiscoverModel()
        for idx, card in enumerate(hand):
            text = getattr(card, "text", "") or ""
            if not text:
                continue
            specs = self._extract_effect_specs(text)
            if not specs:
                continue
            for spec in specs:
                if spec["pool_mode"] == "choose":
                    choose_probs = {
                        self._role_label(role): 1.0
                        for role in classify_card_roles(card)
                    }
                    report = {
                        "hand_index": idx,
                        "card_name": card.name,
                        "card_text": text,
                        "effect_kind": spec["effect_kind"],
                        "constraint": spec["constraint_text"],
                        "pool_mode": spec["pool_mode"],
                        "pool_size": 0,
                        "pool_cards": [],
                        "pool_role_probabilities": choose_probs,
                        "offer_role_probabilities": {},
                        "probability_lines": self._format_role_probability_lines(choose_probs, {}),
                    }
                    reports.append(report)
                    continue

                pool = self._build_effect_pool(state.hero.hero_class, spec)
                if not pool:
                    continue

                pool_probs = self._calc_role_probabilities(pool)
                offer_probs = {}
                if spec["pool_mode"] == "discover":
                    offer_probs = self._calc_role_offer_probabilities(discover_model, pool)

                report = {
                    "hand_index": idx,
                    "card_name": card.name,
                    "card_text": text,
                    "effect_kind": spec["effect_kind"],
                    "constraint": spec["constraint_text"],
                    "pool_mode": spec["pool_mode"],
                    "pool_size": len(pool),
                    "pool_cards": [c.name for c in pool],
                    "pool_role_probabilities": pool_probs,
                    "offer_role_probabilities": offer_probs,
                    "probability_lines": self._format_role_probability_lines(pool_probs, offer_probs),
                }
                reports.append(report)
        return reports

    def _extract_effect_specs(self, text: str) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        tl = text.lower()
        from_past_only = ("来自过去" in text or "from the past" in tl)

        class_mode = "own_or_neutral"
        if (
            "其他职业" in text
            or "另一职业" in text
            or "other class" in tl
            or "another class" in tl
        ):
            class_mode = "other"
        elif (
            "本职业" in text
            or "你的职业" in text
            or "your class" in tl
        ):
            class_mode = "own_only"
        elif "不限" in text or "any class" in tl:
            class_mode = "unrestricted"

        if "发现" in text or "discover" in tl:
            c = _parse_discover_constraint(text)
            specs.append(
                {
                    "effect_kind": "发现",
                    "pool_mode": "discover",
                    "card_type": c.get("card_type"),
                    "race": c.get("race"),
                    "use_wild_pool": from_past_only,
                    "from_past_only": from_past_only,
                    "class_mode": class_mode,
                    "constraint_text": (
                        f"type={c.get('card_type') or 'ANY'}, race={c.get('race') or 'ANY'}, "
                        f"class_mode={class_mode}, from_past_only={from_past_only}"
                    ),
                }
            )

        is_random_gain = ("随机" in text or "random" in tl) and (
            "获得" in text
            or "加入" in text
            or "置入" in text
            or "add a random" in tl
        )
        if is_random_gain:
            c = _parse_discover_constraint(text)
            random_class_mode = "unrestricted"
            if (
                "其他职业" in text
                or "另一职业" in text
                or "other class" in tl
                or "another class" in tl
            ):
                random_class_mode = "other"
            elif (
                "本职业" in text
                or "你的职业" in text
                or "your class" in tl
            ):
                random_class_mode = "own_only"
            specs.append(
                {
                    "effect_kind": "随机获得",
                    "pool_mode": "random",
                    "card_type": c.get("card_type"),
                    "race": c.get("race"),
                    "use_wild_pool": from_past_only,
                    "from_past_only": from_past_only,
                    "class_mode": random_class_mode,
                    "constraint_text": (
                        f"type={c.get('card_type') or 'ANY'}, race={c.get('race') or 'ANY'}, "
                        f"class_mode={random_class_mode}, from_past_only={from_past_only}"
                    ),
                }
            )

        if "抉择" in text or "choose one" in tl:
            specs.append(
                {
                    "effect_kind": "抉择",
                    "pool_mode": "choose",
                    "card_type": None,
                    "race": None,
                    "use_wild_pool": False,
                    "from_past_only": False,
                    "class_mode": "unrestricted",
                    "constraint_text": "choose_one",
                }
            )

        dedup: Dict[Tuple, Dict[str, Any]] = {}
        for spec in specs:
            key = (
                spec["effect_kind"],
                spec.get("pool_mode"),
                spec.get("card_type"),
                spec.get("race"),
                spec.get("use_wild_pool"),
                spec.get("from_past_only"),
                spec.get("class_mode"),
            )
            dedup[key] = spec
        return list(dedup.values())

    def _build_effect_probability_lines(
        self,
        state: GameState,
        reports: List[Dict[str, Any]],
        min_prob: float = 0.05,
    ) -> List[str]:
        lines: List[str] = []
        draw_model = DrawModel()

        # 抽牌效果：仅按当前手牌中真正有抽牌效果的卡计算
        for card in state.hand or []:
            effects = get_effects(card)
            n_draw = int(getattr(effects, "draw", 0) or 0)
            if n_draw <= 0:
                continue
            clear = min(
                1.0,
                draw_model.draw_role_probability(state, RoleTag.REMOVAL_SINGLE, n_draws=n_draw)
                + draw_model.draw_role_probability(state, RoleTag.REMOVAL_AOE, n_draws=n_draw),
            )
            heal = draw_model.draw_role_probability(state, RoleTag.HEAL, n_draws=n_draw)
            board = draw_model.draw_role_probability(state, RoleTag.TEMPO_BOARD, n_draws=n_draw)
            burst = draw_model.draw_role_probability(state, RoleTag.BURST_DAMAGE, n_draws=n_draw)
            parts = []
            if clear >= min_prob:
                parts.append(f"解场={clear:.0%}")
            if heal >= min_prob:
                parts.append(f"回血={heal:.0%}")
            if board >= min_prob:
                parts.append(f"战场={board:.0%}")
            if burst >= min_prob:
                parts.append(f"直伤={burst:.0%}")
            if parts:
                lines.append(f"抽牌[{card.name}]({n_draw}抽): " + ", ".join(parts))

        # 发现/随机/抉择：按当前手牌效果池报告输出
        for report in reports:
            effect_kind = report.get("effect_kind", "")
            grouped = self._compress_role_probs(
                report.get("offer_role_probabilities") or report.get("pool_role_probabilities") or {}
            )
            parts = [f"{k}={v:.0%}" for k, v in grouped.items() if v >= min_prob]
            if not parts:
                continue
            label = f"{effect_kind}[{report.get('card_name', '未知')}]"
            if effect_kind == "发现":
                lines.append(f"{label}(3选1): " + ", ".join(parts))
            elif effect_kind == "随机获得":
                lines.append(f"{label}(池内): " + ", ".join(parts))
            elif effect_kind == "抉择":
                lines.append(f"{label}(可控): " + ", ".join(parts))
            else:
                lines.append(f"{label}: " + ", ".join(parts))

        if not lines:
            unknown_text = sum(1 for c in (state.hand or []) if not (getattr(c, "text", "") or ""))
            if unknown_text > 0:
                lines.append(f"效果概率: 手牌文本未知 {unknown_text} 张，无法解析 发现/随机/抉择/抽牌")

        return lines

    def _compress_role_probs(self, probs: Dict[str, float]) -> Dict[str, float]:
        grouped = {"解场": 0.0, "回血": 0.0, "战场": 0.0, "直伤": 0.0}
        for name, p in probs.items():
            if "解场" in name:
                grouped["解场"] += p
            elif "回血" in name:
                grouped["回血"] += p
            elif "直伤" in name:
                grouped["直伤"] += p
            elif name in ("战场", "防御嘲讽", "增益"):
                grouped["战场"] += p
        return {k: min(1.0, v) for k, v in grouped.items() if v > 0}

    def _build_effect_pool(self, hero_class: str, spec: Dict[str, Any]) -> List[Card]:
        hc = (hero_class or "").upper()
        if not hc or hc == "UNKNOWN":
            return []

        card_type = spec.get("card_type")
        race = spec.get("race")
        use_wild_pool = bool(spec.get("use_wild_pool"))
        from_past_only = bool(spec.get("from_past_only"))
        class_mode = spec.get("class_mode", "unrestricted")
        mode = spec.get("pool_mode")
        pool_cards: List[Card] = []

        try:
            if mode == "discover":
                if class_mode == "own_or_neutral":
                    raw_pool = generate_discover_pool(
                        hc,
                        card_type=card_type,
                        race=race,
                        use_wild_pool=use_wild_pool,
                        from_past_only=from_past_only,
                    )
                else:
                    idx = get_index()
                    raw_pool = self._query_pool_with_past_filter(
                        idx,
                        card_type=card_type,
                        race=race,
                        use_wild_pool=use_wild_pool,
                        from_past_only=from_past_only,
                    )
                    raw_pool = self._apply_class_mode(raw_pool, hc, class_mode)
                    # 发现池不包含英雄和地点
                    raw_pool = [
                        c for c in raw_pool
                        if c.get("type", "") not in ("HERO", "LOCATION")
                    ]
            else:
                idx = get_index()
                raw_pool = self._query_pool_with_past_filter(
                    idx,
                    card_type=card_type,
                    race=race,
                    use_wild_pool=use_wild_pool,
                    from_past_only=from_past_only,
                )
                raw_pool = self._apply_class_mode(raw_pool, hc, class_mode)

            for raw in raw_pool:
                try:
                    pool_cards.append(Card.from_hsdb_dict(raw))
                except (TypeError, KeyError, ValueError):
                    continue
        except Exception:
            return []

        return pool_cards

    def _query_pool_with_past_filter(
        self,
        idx,
        *,
        card_type: Optional[str] = None,
        race: Optional[str] = None,
        use_wild_pool: bool = False,
        from_past_only: bool = False,
    ) -> List[Dict[str, Any]]:
        if from_past_only:
            wild_pool = idx.get_pool(card_type=card_type, format="wild")
            std_pool = idx.get_pool(card_type=card_type, format="standard")
            std_dbf = {c.get("dbfId") for c in std_pool if c.get("dbfId") is not None}
            raw_pool = [c for c in wild_pool if c.get("dbfId") not in std_dbf]
        else:
            fmt = "wild" if use_wild_pool else "standard"
            raw_pool = idx.get_pool(card_type=card_type, format=fmt)
        if race:
            raw_pool = [c for c in raw_pool if race in (c.get("race", "") or "")]
        return raw_pool

    def _apply_class_mode(
        self,
        raw_pool: List[Dict[str, Any]],
        hero_class: str,
        class_mode: str,
    ) -> List[Dict[str, Any]]:
        if class_mode == "own_or_neutral":
            return [c for c in raw_pool if c.get("cardClass") in (hero_class, "NEUTRAL")]
        if class_mode == "own_only":
            return [c for c in raw_pool if c.get("cardClass") == hero_class]
        if class_mode == "other":
            return [
                c for c in raw_pool
                if c.get("cardClass") in _PLAYABLE_CLASSES and c.get("cardClass") != hero_class
            ]
        return raw_pool

    def _infer_unknown_deck_cards(
        self,
        hero_class: str,
        need_count: int,
        exclude_card_ids: set | None = None,
    ) -> List[Card]:
        if need_count <= 0:
            return []
        hc = (hero_class or "").upper()
        if not hc or hc == "UNKNOWN":
            return []

        try:
            idx = get_index()
            candidates = idx.get_pool(format="standard")
            candidates = [
                c for c in candidates
                if c.get("cardClass") in (hc, "NEUTRAL")
                and c.get("type", "") != "HERO"
            ]
            if exclude_card_ids:
                candidates = [
                    c for c in candidates
                    if c.get("id", "") not in exclude_card_ids
                ]
            if not candidates:
                return []

            candidates = sorted(candidates, key=lambda c: c.get("dbfId", 0))
            out: List[Card] = []
            i = 0
            n = len(candidates)
            while len(out) < need_count and n > 0:
                raw = candidates[i % n]
                try:
                    out.append(Card.from_hsdb_dict(raw))
                except (TypeError, KeyError, ValueError):
                    pass
                i += 1
                if i > need_count * 3:
                    break
            return out[:need_count]
        except Exception:
            return []

    def _calc_role_probabilities(self, pool: List[Card]) -> Dict[str, float]:
        total = len(pool)
        if total <= 0:
            return {}
        counts: Dict[RoleTag, int] = {r: 0 for r in RoleTag}
        for card in pool:
            roles = classify_card_roles(card)
            for role in roles:
                counts[role] += 1
        probs: Dict[str, float] = {}
        for role, count in counts.items():
            if count > 0:
                probs[self._role_label(role)] = count / total
        return probs

    def _calc_role_offer_probabilities(
        self, model: DiscoverModel, pool: List[Card],
    ) -> Dict[str, float]:
        probs: Dict[str, float] = {}
        for role in RoleTag:
            p = model.discover_role_offer_prob(pool, role, offer_size=3)
            if p > 0:
                probs[self._role_label(role)] = p
        return probs

    def _format_role_probability_lines(
        self,
        pool_probs: Dict[str, float],
        offer_probs: Dict[str, float],
    ) -> List[str]:
        def _fmt(d: Dict[str, float]) -> str:
            items = sorted(d.items(), key=lambda kv: kv[1], reverse=True)
            return ", ".join([f"{name}={p:.1%}" for name, p in items])

        lines: List[str] = []
        if pool_probs:
            lines.append(f"池内分类占比: {_fmt(pool_probs)}")
        if offer_probs:
            lines.append(f"三选一命中率: {_fmt(offer_probs)}")
        return lines

    def _role_label(self, role: RoleTag) -> str:
        labels = {
            RoleTag.REMOVAL_SINGLE: "解场单体",
            RoleTag.REMOVAL_AOE: "解场群体",
            RoleTag.HEAL: "回血",
            RoleTag.TEMPO_BOARD: "战场",
            RoleTag.CARD_DRAW: "抽牌",
            RoleTag.BURST_DAMAGE: "直伤",
            RoleTag.TAUNT_DEFENSE: "防御嘲讽",
            RoleTag.BUFF: "增益",
            RoleTag.UTILITY: "功能",
        }
        return labels.get(role, role.name)

    def _estimate_opponent_hand_role_priors(self, opp_hand_count: int) -> Dict[str, float]:
        """Estimate opponent hand role distribution from known hand + Bayesian predictions."""
        weights: Dict[str, float] = {}
        total_weight = 0.0
        try:
            from analysis.data.hsdb import get_db
            db = get_db()
        except ImportError:
            db = None

        # 1) Known hand cards observed in HAND zone
        if db is not None:
            for _, card_id in self.global_tracker.get_opp_known_hand():
                raw = db.get_card(card_id)
                if not raw:
                    continue
                try:
                    card = Card.from_hsdb_dict(raw)
                except (TypeError, KeyError, ValueError):
                    continue
                roles = classify_card_roles(card)
                if not roles:
                    continue
                w = 1.0 / len(roles)
                for role in roles:
                    name = self._role_label(role)
                    weights[name] = weights.get(name, 0.0) + w
                    total_weight += w

        # 2) Bayesian predicted-next cards (weighted by posterior probability)
        bayesian = self.global_tracker.get_bayesian_state()
        preds = bayesian.get("predicted_next", []) or []
        if db is not None:
            for pred in preds:
                dbf = pred.get("dbfId")
                if dbf is None:
                    continue
                raw = db.get_by_dbf(int(dbf))
                if not raw:
                    continue
                p = float(pred.get("probability", 0.0) or 0.0)
                if p <= 0:
                    continue
                try:
                    card = Card.from_hsdb_dict(raw)
                except (TypeError, KeyError, ValueError):
                    continue
                roles = classify_card_roles(card)
                if not roles:
                    continue
                w = p / len(roles)
                for role in roles:
                    name = self._role_label(role)
                    weights[name] = weights.get(name, 0.0) + w
                    total_weight += w

        if total_weight <= 0.0:
            return {}
        priors = {k: v / total_weight for k, v in weights.items()}
        # Keep top 5 role priors for readability
        ranked = sorted(priors.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return dict(ranked)

    def _format_opp_hand_prior_line(self, priors: Dict[str, float]) -> str:
        if not priors:
            return "对手手牌类型先验: 数据不足"
        parts = [f"{k}={v:.1%}" for k, v in priors.items()]
        return "对手手牌类型先验: " + ", ".join(parts)

    def _evaluate_decision(
        self, game_state: GameState, best_actions: List[Action],
        best_score: float, legal_actions: List[Action],
    ) -> Tuple[str, float]:
        """多因子决策评估 → (rating_str, score)

        Multi-factor evaluation:
        1. Lethal detection (RHEA score >= 5000 = lethal found)
        2. Mana efficiency
        3. Board control assessment
        4. Action diversity analysis
        5. RHEA score interpretation
        6. Health pressure
        """
        reasons: List[str] = []
        positive_reasons: List[str] = []

        # Extract state from game_state (no summary param)
        mana_available = game_state.mana.available
        mana_max = game_state.mana.max_mana
        mana_used = mana_max - mana_available
        rhea_score = best_score
        opp_hp = game_state.opponent.hero.hp if game_state.opponent and game_state.opponent.hero else 30
        opp_armor = game_state.opponent.hero.armor if game_state.opponent and game_state.opponent.hero else 0
        our_hp = game_state.hero.hp if game_state.hero else 30
        board_count = len(game_state.board)
        hand_count = len(game_state.hand)

        # 1. Lethal detection
        is_lethal = rhea_score >= 5000
        if is_lethal:
            total_atk = sum(m.attack for m in game_state.board)
            reasons.append(
                f"致命检测! 场攻={total_atk} vs 对手HP={opp_hp}+{opp_armor}护甲, "
                f"RHEA找到斩杀方案 (分数={rhea_score:.1f})"
            )

        # 2. Mana efficiency (only evaluate if not lethal)
        if not is_lethal and mana_max > 0:
            spent = mana_max - mana_available
            if mana_available == 0 and spent == mana_max:
                positive_reasons.append(f"法力完美利用: {spent}/{mana_max}")
            elif mana_available > 0 and spent > 0:
                if mana_available <= 1:
                    positive_reasons.append(f"法力利用充分: 用{spent}/{mana_max}, 仅剩{mana_available}")
                elif mana_available > mana_max * 0.5:
                    reasons.append(
                        f"法力剩余较多: {mana_available}/{mana_max} 未使用 "
                        f"(浪费{mana_available}费)"
                    )
                else:
                    positive_reasons.append(f"法力利用合理: 用{spent}/{mana_max}")
            elif spent == 0 and hand_count > 0:
                reasons.append(
                    f"未使用任何法力 ({mana_available}/{mana_max}), "
                    f"手牌有{hand_count}张可用"
                )

        # 3. Board control assessment
        if not is_lethal:
            opp_board_count = len(game_state.opponent.board) if game_state.opponent else 0

            if board_count == 0 and opp_board_count > 0:
                reasons.append(f"场面劣势: 我方0随从 vs 对方{opp_board_count}随从")
            elif board_count > opp_board_count + 2:
                positive_reasons.append(f"场面优势: {board_count} vs {opp_board_count}随从")
            elif opp_board_count > board_count + 2:
                reasons.append(f"场面落后: {board_count} vs {opp_board_count}随从, 考虑清场")

        # 4. Action diversity
        if legal_actions:
            action_types = set()
            for a in legal_actions:
                action_types.add(a.action_type)

            if len(action_types) <= 2 and hand_count > 3:
                reasons.append(
                    f"可用操作较少 ({len(action_types)}种), "
                    f"但手牌{hand_count}张 — 可能是费用不匹配"
                )
            elif len(action_types) >= 4:
                positive_reasons.append(f"策略选择丰富: {len(action_types)}种操作可选")

        # 5. RHEA score interpretation (non-lethal context)
        if not is_lethal and rhea_score != 0.0:
            if rhea_score > 50:
                positive_reasons.append(f"RHEA评估积极 (分数={rhea_score:.1f})")
            elif rhea_score < -50:
                reasons.append(f"RHEA评估消极 (分数={rhea_score:.1f}), 局势不利")
            elif abs(rhea_score) <= 10:
                positive_reasons.append(f"局势平稳 (RHEA分数={rhea_score:.1f})")

        # 6. Health pressure
        if not is_lethal:
            if our_hp <= 10:
                reasons.append(f"血量危险: HP={our_hp}, 需要优先防守")
            elif opp_hp <= 15 and board_count > 0:
                positive_reasons.append(f"对手血量低 (HP={opp_hp}), 有进攻压力")

        # Determine rating
        has_issues = len(reasons) > 0
        has_positives = len(positive_reasons) > 0

        if is_lethal:
            rating = "致命"
        elif not has_issues and has_positives:
            rating = "合理"
        elif has_issues and has_positives:
            rating = "次优"
        elif has_issues and not has_positives:
            if len(reasons) >= 3:
                rating = "错误"
            else:
                rating = "次优"
        else:
            rating = "合理"

        # Compute numeric score (0.0 to 1.0)
        if is_lethal:
            score = 1.0
        else:
            score = 0.5
            score += len(positive_reasons) * 0.1
            score -= len(reasons) * 0.1
            if rhea_score > 50:
                score += 0.1
            elif rhea_score < -50:
                score -= 0.1
            score = max(0.0, min(1.0, score))

        # Log reasons
        all_reasons = reasons + [f"✓ {r}" for r in positive_reasons]
        for reason in all_reasons:
            self._decision_logger.info(f"  - {reason}")

        return (rating, score)

    def _collect_opponent_turn_info(self) -> None:
        """收集对手回合信息 (不再跳过)"""
        try:
            if not self._opp_player_id:
                return

            # Collect opponent entities
            opp_entities = [e for e in self.entities.values()
                           if e.controller == self._opp_player_id]
            our_entities = [e for e in self.entities.values()
                           if e.controller == self._our_player_id]

            # Opponent hero
            opp_hero_hp = 30
            opp_hero_armor = 0
            for entity in opp_entities:
                if entity.card_type == CardType.HERO:
                    opp_hero_hp = entity.health
                    opp_hero_armor = entity.armor
                    break

            # Opponent board
            opp_board = []
            for entity in opp_entities:
                if entity.zone == Zone.PLAY and entity.card_type == CardType.MINION:
                    opp_board.append({
                        'name': self._card_name(entity.card_id),
                        'atk': entity.atk,
                        'health': entity.health,
                    })

            # Opponent hand count & deck
            opp_hand_count = self.global_tracker.get_opp_hand_count(opp_entities)
            opp_deck_remaining = self.global_tracker.count_opp_deck(opp_entities)

            # Update opponent weapon/location tracking
            self.global_tracker.update_opp_weapon(opp_entities)
            self.global_tracker.update_opp_locations(opp_entities)

            # Log opponent turn info
            self._main_logger.info(
                f"📋 对手回合 {self.game_turn}: "
                f"HP={opp_hero_hp} 护甲={opp_hero_armor} "
                f"职业={self._opp_hero_class} | "
                f"场面 {len(opp_board)}随从 | "
                f"手牌 {opp_hand_count}张 | "
                f"牌库 {opp_deck_remaining}张"
            )

            # Log opponent board minions if any
            if opp_board:
                for i, m in enumerate(opp_board[:7], 1):
                    self._main_logger.info(
                        f"    对手随从[{i}]: {m['name']} {m['atk']}/{m['health']}"
                    )

            # Log opponent card intelligence
            opp_breakdown = self.global_tracker.get_opp_card_breakdown(self._card_name)
            if opp_breakdown["known_hand"]:
                self._main_logger.info(f"    对手已知手牌: {', '.join(opp_breakdown['known_hand'])}")
            if opp_breakdown["deck_cards_played"]:
                self._main_logger.info(f"    对手牌库牌: {', '.join(opp_breakdown['deck_cards_played'])}")
            if opp_breakdown["generated_cards_played"]:
                self._main_logger.info(f"    对手衍生牌: {', '.join(opp_breakdown['generated_cards_played'])}")
            tc = opp_breakdown["type_counts"]
            type_parts = [f"{k}{v}" for k, v in tc.items() if v > 0]
            if type_parts:
                self._main_logger.info(f"    对手出牌类型: {' '.join(type_parts)}")

            # Log opponent secrets
            if self.global_tracker.state.opp_secrets:
                sec_str = ", ".join(
                    self._card_name(cid) for cid in self.global_tracker.state.opp_secrets
                )
                self._main_logger.info(f"    对手奥秘: {sec_str}")

            # Log opponent weapon
            if self.global_tracker.state.opp_weapon:
                w = self.global_tracker.state.opp_weapon
                self._main_logger.info(
                    f"    对手武器: {self._card_name(w)} "
                    f"{self.global_tracker.state.opp_weapon_atk}/"
                    f"{self.global_tracker.state.opp_weapon_durability}"
                )

            # Log opponent locations
            for loc_cid in self.global_tracker.state.opp_locations:
                self._main_logger.info(
                    f"    对手地标: {self._card_name(loc_cid)}"
                )

            # Build structured opponent turn decision (for first-turn visibility & downstream analysis)
            our_hero_hp = 30
            our_hero_armor = 0
            for entity in our_entities:
                if entity.card_type == CardType.HERO:
                    our_hero_hp = entity.health
                    our_hero_armor = entity.armor
                    break

            opp_hand_prior = self._estimate_opponent_hand_role_priors(opp_hand_count)
            opp_prior_line = self._format_opp_hand_prior_line(opp_hand_prior)
            self.decisions.append(TurnDecision(
                turn_number=self.game_turn,
                player_name=self.player_name,
                is_our_turn=False,
                hero_hp=our_hero_hp,
                hero_armor=our_hero_armor,
                hero_class=self._player_hero_class,
                mana_available=0,
                mana_max=0,
                board_count=0,
                hand_count=0,
                opp_hero_hp=opp_hero_hp,
                opp_hero_armor=opp_hero_armor,
                opp_hero_class=self._opp_hero_class,
                opp_board_count=len(opp_board),
                opp_board_minions=[f"{m['name']} {m['atk']}/{m['health']}" for m in opp_board[:7]],
                opp_hand_count=opp_hand_count,
                opp_deck_remaining=opp_deck_remaining,
                opp_known_hand_cards=opp_breakdown["known_hand"],
                opp_deck_cards_played=opp_breakdown["deck_cards_played"],
                opp_generated_cards_played=opp_breakdown["generated_cards_played"],
                opp_card_type_counts=opp_breakdown["type_counts"],
                opp_generated_played=opp_breakdown["total_generated"],
                summary_lines=[opp_prior_line],
            ))

        except Exception as e:
            self._error_logger.error(
                f"收集对手回合 {self.game_turn} 信息时出错: {e}", exc_info=True
            )

    # ─── 辅助方法 ─────────────────────────────────────────────────

    def _card_name(self, card_id: str) -> str:
        """card_id → 中文名"""
        if not card_id:
            return "未知"
        return self._card_name_cache.get(card_id, card_id)

    def _load_card_names(self) -> Dict[str, str]:
        """加载卡牌名称映射 (zhCN + standard + wild + HSCardDB)"""
        name_map: Dict[str, str] = {}

        for path in [
            Path("card_data/240397/zhCN/cards.json"),
            Path("card_data/240397/zhCN/cards.collectible.json"),
            Path("card_data/240397/unified_standard.json"),
            Path("card_data/240397/unified_wild.json"),
        ]:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        for card in data:
                            cid = card.get("id", "")
                            name = card.get("name", "") or card.get("zhName", "")
                            if cid and name:
                                name_map[cid] = name
                    elif isinstance(data, dict):
                        # unified format might be different
                        pass
                except (OSError, json.JSONDecodeError):
                    pass

        # Also try HSCardDB for non-collectible (token) cards
        try:
            from analysis.data.hsdb import get_db
            db = get_db()
            for cid, card_data in db._cards.items():
                if cid and cid not in name_map:
                    name = card_data.get("name", "") or card_data.get("englishName", "")
                    if name:
                        name_map[cid] = name
        except ImportError:
            pass

        return name_map

    def _save_summary(self) -> None:
        """保存 JSON 摘要"""
        ts = time.strftime("%Y%m%d_%H%M%S")
        log_path = Path(self.log_dir)
        summary_path = log_path / f"game_summary_{ts}.json"

        summary = {
            "player_name": self.player_name,
            "num_decisions": len(self.decisions),
            "decisions": [{
                'turn_number': d.turn_number,
                'player_name': d.player_name,
                'is_our_turn': d.is_our_turn,
                'hero_hp': d.hero_hp,
                'hero_armor': d.hero_armor,
                'hero_class': d.hero_class,
                'mana_available': d.mana_available,
                'mana_max': d.mana_max,
                'mana_used': d.mana_used,
                'overload_locked': d.overload_locked,
                'temp_mana': d.temp_mana,
                'board_count': d.board_count,
                'hand_count': d.hand_count,
                'hand_cards': d.hand_cards,
                'board_minions': d.board_minions,
                'deck_remaining': d.deck_remaining,
                'opp_hero_hp': d.opp_hero_hp,
                'opp_hero_armor': d.opp_hero_armor,
                'opp_hero_class': d.opp_hero_class,
                'opp_board_count': d.opp_board_count,
                'opp_board_minions': d.opp_board_minions,
                'opp_hand_count': d.opp_hand_count,
                'opp_deck_remaining': d.opp_deck_remaining,
                'opp_known_hand_cards': d.opp_known_hand_cards,
                'opp_deck_cards_played': d.opp_deck_cards_played,
                'opp_generated_cards_played': d.opp_generated_cards_played,
                'opp_card_type_counts': d.opp_card_type_counts,
                'opp_generated_played': d.opp_generated_played,
                'opp_secrets': d.opp_secrets,
                'opp_archetype_name': d.opp_archetype_name,
                'opp_archetype_confidence': d.opp_archetype_confidence,
                'opp_top_archetypes': d.opp_top_archetypes,
                'opp_playstyle': d.opp_playstyle,
                'opp_secret_risk': d.opp_secret_report,
                'player_global_stats': d.player_global_stats,
                'legal_action_count': d.legal_action_count,
                'legal_actions': d.legal_actions,
                'rhea_best_score': d.rhea_best_score,
                'rhea_best_actions': d.rhea_best_actions,
                'rhea_generations': d.rhea_generations,
                'rhea_elapsed_ms': d.rhea_elapsed_ms,
                'decision_quality': d.decision_quality,
                'decision_score': d.decision_score,
                'lethal_available': d.lethal_available,
                'lethal_executed': d.lethal_executed,
                'summary_lines': d.summary_lines,
                'effect_pool_reports': d.effect_pool_reports,
            } for d in self.decisions],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        if self._main_logger:
            self._main_logger.info(f"保存摘要: {summary_path}")

    def _setup_loggers(self) -> None:
        """配置日志"""
        ts = time.strftime("%Y%m%d_%H%M%S")
        log_path = Path(self.log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        # Main replay log — everything
        self._main_logger = logging.getLogger(f"packet_replay.main.{ts}")
        fh = logging.FileHandler(log_path / f"replay_{ts}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        self._main_logger.addHandler(fh)
        self._main_logger.setLevel(logging.DEBUG)

        # Decisions log — per-turn analysis
        self._decision_logger = logging.getLogger(f"packet_replay.decisions.{ts}")
        fh2 = logging.FileHandler(log_path / f"decisions_{ts}.log", encoding="utf-8")
        fh2.setFormatter(logging.Formatter("%(message)s"))
        self._decision_logger.addHandler(fh2)
        self._decision_logger.setLevel(logging.INFO)

        # Errors log
        self._error_logger = logging.getLogger(f"packet_replay.errors.{ts}")
        fh3 = logging.FileHandler(log_path / f"errors_{ts}.log", encoding="utf-8")
        fh3.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        self._error_logger.addHandler(fh3)
        self._error_logger.setLevel(logging.WARNING)

    # 日志器
    _main_logger: Any = None
    _decision_logger: Any = None
    _error_logger: Any = None

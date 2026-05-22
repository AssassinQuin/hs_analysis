# -*- coding: utf-8 -*-
"""powerlog_game_state_builder.py — 从 Power.log 实时数据构建完整的 GameState

将 CoreLogMonitor 的 entity_cache 和 GlobalTracker 的状态
转换为搜索树使用的 GameState 对象，使 MCTS 对手手牌模拟
可以基于真实游戏状态而非简化近似。

核心思路：
    entity_cache 包含所有实体的标签快照（攻击力、血量、区域、关键词等），
    GlobalTracker 维护了对手层面的聚合状态（手牌数、牌库数、场攻随从等）。
    两者互补：entity_cache 提供细粒度实体数据，GlobalTracker 提供
    对手层面的推断和汇总数据。

    构建 GameState 时：
    - 我方信息：主要从 entity_cache 提取（因为我们能看到自己的手牌/场面）
    - 对手信息：主要从 GlobalTracker 提取（因为我们只能看到对手的场面和推断数据）
    - 共同信息（如英雄状态、法力）：从 entity_cache 的玩家实体标签中提取

用法::

    builder = PowerLogGameStateBuilder()
    game_state = builder.build_from_tracker(log_monitor, our_controller, opp_controller)
    # game_state 可直接用于 MCTS 搜索引擎

    # 对手视角构建（用于 MCTS 对手手牌模拟）
    opp_state = builder.build_opponent_game_state(
        log_monitor, opp_hand_cards, our_controller, opp_controller
    )
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any

from hearthstone.enums import GameTag, Zone, CardType

from analysis.card.engine.state import (
    GameState,
    HeroState,
    ManaState,
    Minion,
    OpponentState,
    Weapon,
)
from analysis.card.models.card import Card
from analysis.card.abilities.keywords import KeywordSet

logger = logging.getLogger(__name__)


# ── CardType 枚举值到字符串的映射 ─────────────────────────────────

_CARD_TYPE_STR: Dict[int, str] = {
    CardType.MINION.value: "MINION",
    CardType.SPELL.value: "SPELL",
    CardType.WEAPON.value: "WEAPON",
    CardType.HERO.value: "HERO",
    CardType.HERO_POWER.value: "HERO_POWER",
    CardType.LOCATION.value: "LOCATION",
    CardType.ENCHANTMENT.value: "ENCHANTMENT",
    CardType.PLAYER.value: "PLAYER",
    CardType.GAME.value: "GAME",
    CardType.ITEM.value: "ITEM",
}


def _safe_int(val: Any, default: int = 0) -> int:
    """安全地将值转换为整数，失败时返回默认值。"""
    if isinstance(val, int):
        return val
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _card_type_to_str(card_type_val: Any) -> str:
    """将 CardType 标签值转换为大写字符串。

    Args:
        card_type_val: GameTag.CARDTYPE 的值（int 或枚举）

    Returns:
        大写类型字符串，如 "MINION"、"SPELL" 等
    """
    if isinstance(card_type_val, CardType):
        return card_type_val.name
    val = _safe_int(card_type_val, 0)
    return _CARD_TYPE_STR.get(val, "")


# ── 核心：PowerLogGameStateBuilder ──────────────────────────────────


class PowerLogGameStateBuilder:
    """从 Power.log 实时数据构建完整的 GameState。

    将 CoreLogMonitor 的 entity_cache 和 GlobalTracker 的状态
    转换为搜索树使用的 GameState 对象。

    数据来源优先级：
    1. entity_cache：提供精确的实体标签（攻击力、血量、关键词等）
    2. GlobalTracker.state：提供对手层面的聚合数据（手牌数、牌库数等）
    3. CardDB：提供卡牌的种族、法术学派等元数据

    用法::

        builder = PowerLogGameStateBuilder()
        game_state = builder.build_from_tracker(log_monitor, our_controller, opp_controller)
        # game_state 可直接用于 MCTS 搜索引擎
    """

    def __init__(self):
        self._card_db = None
        # v5优化：缓存对手 GameState 的基础组件（除手牌外）
        # MCTS 为每个世界调用 build_opponent_game_state，但只有手牌不同
        # 缓存 key = (entity_cache_version, our_ctrl, opp_ctrl)
        self._opp_base_cache_key = None
        self._opp_base_cache = None  # 缓存的 GameState 基础组件

    # ── 延迟加载卡牌数据库 ────────────────────────────────────

    def _ensure_card_db(self):
        """延迟加载 CardDB，用于查询卡牌元数据（种族、法术学派等）。"""
        if self._card_db is None:
            try:
                from analysis.card.data.card_data import get_db
                self._card_db = get_db()
            except Exception as e:
                logger.warning("无法加载卡牌数据库: %s", e)

    def _get_card_meta(self, card_id: str) -> Dict:
        """从卡牌数据库获取卡牌元数据。

        Args:
            card_id: 卡牌ID，如 "EX1_001"

        Returns:
            卡牌元数据字典，包含 name, race, spellSchool 等。
            查询失败时返回空字典。
        """
        self._ensure_card_db()
        if self._card_db is None or not card_id:
            return {}
        card_data = self._card_db.get_card(card_id)
        return card_data if card_data else {}

    # ── 主入口：从我方视角构建 GameState ──────────────────────

    def build_from_tracker(
        self,
        log_monitor,
        our_controller: int,
        opp_controller: int,
    ) -> GameState:
        """从 CoreLogMonitor 构建完整的 GameState（我方视角）。

        这是主要的构建入口。从 entity_cache 提取所有实体的精确标签，
        从 GlobalTracker 提取对手推断状态，合并为一个完整的 GameState。

        Args:
            log_monitor: CoreLogMonitor 实例，包含 entity_cache 和 global_tracker
            our_controller: 我方控制器 ID（1 或 2）
            opp_controller: 对手控制器 ID（1 或 2）

        Returns:
            GameState 实例，可直接用于 MCTS 搜索引擎
        """
        entity_cache = log_monitor.game_tracker.entity_cache
        global_tracker = log_monitor.global_tracker
        gt_state = global_tracker.state

        # 1. 提取英雄状态
        our_hero = self._extract_hero_state(entity_cache, our_controller)
        opp_hero = self._extract_hero_state(entity_cache, opp_controller)

        # 2. 提取法力状态
        our_mana = self._extract_mana_state(entity_cache, our_controller)

        # 3. 提取我方场面随从
        our_board = self._extract_board_minions(
            entity_cache, our_controller, owner="friendly"
        )

        # 4. 提取我方手牌
        our_hand = self._extract_hand_cards(entity_cache, our_controller)

        # 5. 构建对手状态（从 GlobalTracker）
        opponent = self._build_opp_state_from_global_tracker(global_tracker)

        # 用 entity_cache 的精确数据覆写对手英雄状态（如果有的话）
        if opp_hero.hp > 0:
            opponent.hero = opp_hero

        # 6. 提取我方武器
        our_weapon = self._extract_weapon(entity_cache, our_controller)
        if our_weapon is not None:
            our_hero.weapon = our_weapon

        # 7. 提取地点
        our_locations = self._extract_locations(
            entity_cache, our_controller
        )

        # 8. 提取回合数
        turn_number = gt_state.current_turn or log_monitor.game_tracker.get_current_turn()

        # 9. 提取我方牌库剩余
        deck_remaining = gt_state.player_deck_remaining

        # 10. 构建 GameState
        game_state = GameState(
            hero=our_hero,
            mana=our_mana,
            board=our_board,
            locations=our_locations,
            hand=our_hand,
            deck_remaining=deck_remaining,
            opponent=opponent,
            turn_number=turn_number,
            # 机制状态
            corpses=gt_state.player_corpses,
            herald_count=gt_state.player_herald_count,
            active_quests=list(gt_state.player_quests) if gt_state.player_quests else [],
            fatigue_damage=gt_state.player_stats.fatigue_damage,
        )

        return game_state

    # ── 对手视角构建（用于 MCTS 对手手牌模拟）──────────────────

    def build_opponent_game_state(
        self,
        log_monitor,
        opp_hand_cards: List[Card],
        our_controller: int,
        opp_controller: int,
    ) -> GameState:
        """从对手视角构建 GameState（用于 MCTS 对手手牌模拟）。

        在 MCTS 对手手牌模拟中，我们需要从对手的视角构建 GameState：
        - 对手变成"玩家"（hero、mana、board、hand 都是对手的）
        - 我们变成"对手"（opponent 字段是我们的场面）
        - 对手的手牌使用传入的 opp_hand_cards（贝叶斯采样的假设手牌）

        这种视角翻转使得搜索引擎可以：
        1. 枚举对手的合法动作（打出哪些手牌、攻击谁等）
        2. 模拟对手的决策过程
        3. 与实际观测的对手行为比较，验证手牌假设

        Args:
            log_monitor: CoreLogMonitor 实例
            opp_hand_cards: 假设的对手手牌（Card 对象列表，由贝叶斯采样生成）
            our_controller: 我方控制器 ID
            opp_controller: 对手控制器 ID

        Returns:
            GameState 实例，从对手视角构建，hand 为传入的 opp_hand_cards
        """
        entity_cache = log_monitor.game_tracker.entity_cache
        global_tracker = log_monitor.global_tracker
        gt_state = global_tracker.state

        # v5优化：缓存基础组件（所有世界共享除手牌外的状态）
        cache_key = (id(entity_cache), our_controller, opp_controller)
        if self._opp_base_cache_key == cache_key and self._opp_base_cache is not None:
            # 从缓存快速重建——只需替换手牌
            base = self._opp_base_cache
            game_state = GameState(
                hero=base['hero'],        # 共享引用（不修改）
                mana=base['mana'],
                board=base['board'],
                locations=base['locations'],
                hand=list(opp_hand_cards),  # 每个世界独立的副本
                deck_remaining=base['deck_remaining'],
                opponent=base['opponent'],
                turn_number=base['turn_number'],
                corpses=base['corpses'],
                herald_count=base['herald_count'],
                active_quests=list(base['active_quests']) if base['active_quests'] else [],
                fatigue_damage=base['fatigue_damage'],
            )
            return game_state

        # ── 首次构建（缓存未命中）：完整提取所有组件 ──
        # 1. 对手视角：对手是"玩家"
        opp_hero = self._extract_hero_state(entity_cache, opp_controller)
        our_hero_as_opp = self._extract_hero_state(entity_cache, our_controller)

        # 2. 对手法力（从 entity_cache 提取对手的玩家标签）
        opp_mana = self._extract_mana_state(entity_cache, opp_controller)
        # 如果无法从 entity_cache 获取法力，基于回合数估算
        turn_number = gt_state.current_turn or log_monitor.game_tracker.get_current_turn()
        if opp_mana.max_mana <= 0 and turn_number > 0:
            estimated_mana = min(10, turn_number)
            opp_mana = ManaState(
                available=estimated_mana,
                max_mana=estimated_mana,
            )

        # 3. 对手场面随从 → 变成"玩家"的 board
        opp_board = self._extract_board_minions(
            entity_cache, opp_controller, owner="friendly"
        )
        # 同时从 GlobalTracker 补充更丰富的随从数据
        gt_opp_board = self._build_opp_minions_from_tracker(global_tracker)
        if gt_opp_board and not opp_board:
            opp_board = gt_opp_board

        # 4. 对手手牌 = 传入的假设手牌
        opp_hand = list(opp_hand_cards)

        # 5. 我方场面 → 变成"对手"的 board
        our_board = self._extract_board_minions(
            entity_cache, our_controller, owner="enemy"
        )

        # 6. 构建我方作为对手的状态
        our_as_opponent = OpponentState(
            hero=our_hero_as_opp,
            board=our_board,
            hand_count=gt_state.player_hand_count,
            deck_remaining=gt_state.player_deck_remaining,
        )

        # 7. 对手武器
        opp_weapon = self._extract_weapon(entity_cache, opp_controller)
        if opp_weapon is not None:
            opp_hero.weapon = opp_weapon
        elif gt_state.opp_weapon:
            # 回退到 GlobalTracker 的武器数据
            opp_hero.weapon = Weapon(
                attack=gt_state.opp_weapon_atk,
                health=gt_state.opp_weapon_durability,
                name=gt_state.opp_weapon,
            )

        # 8. 对手地点
        opp_locations = self._extract_locations(entity_cache, opp_controller)

        # 9. 构建 GameState（对手视角）
        game_state = GameState(
            hero=opp_hero,
            mana=opp_mana,
            board=opp_board,
            locations=opp_locations,
            hand=opp_hand,
            deck_remaining=gt_state.opp_deck_remaining,
            opponent=our_as_opponent,
            turn_number=turn_number,
            # 对手的机制状态
            corpses=gt_state.opp_corpses,
            herald_count=gt_state.opp_herald_count,
            active_quests=list(gt_state.opp_quests) if gt_state.opp_quests else [],
            fatigue_damage=gt_state.opp_stats.fatigue_damage,
        )

        # v5优化：缓存基础组件供后续世界复用（只替换 hand）
        self._opp_base_cache_key = cache_key
        self._opp_base_cache = {
            'hero': opp_hero,
            'mana': opp_mana,
            'board': opp_board,
            'locations': opp_locations,
            'deck_remaining': gt_state.opp_deck_remaining,
            'opponent': our_as_opponent,
            'turn_number': turn_number,
            'corpses': gt_state.opp_corpses,
            'herald_count': gt_state.opp_herald_count,
            'active_quests': list(gt_state.opp_quests) if gt_state.opp_quests else [],
            'fatigue_damage': gt_state.opp_stats.fatigue_damage,
        }

        return game_state

    # ── 辅助方法：从 entity_cache 提取实体 ─────────────────────

    def _extract_hero_state(
        self,
        entity_cache,
        controller: int,
    ) -> HeroState:
        """从 entity_cache 提取英雄状态。

        遍历 entity_cache 查找匹配 controller 的 HERO 类型实体，
        提取 HP、护甲、职业等信息。

        Args:
            entity_cache: EntityCache 实例（支持 .items() 迭代）
            controller: 控制者 ID

        Returns:
            HeroState 实例
        """
        hero_state = HeroState()

        for entity_id, ent_data in entity_cache.items():
            tags = ent_data.get("tags", {})

            # 检查控制器
            ent_controller = _safe_int(tags.get(GameTag.CONTROLLER, 0))
            if ent_controller != controller:
                continue

            # 检查类型是否为 HERO
            card_type = _safe_int(tags.get(GameTag.CARDTYPE, 0))
            if card_type != CardType.HERO.value:
                continue

            # 检查是否在场上
            zone = _safe_int(tags.get(GameTag.ZONE, 0))
            if zone != Zone.PLAY.value:
                continue

            # 提取英雄属性
            hero_state.hp = max(0, _safe_int(tags.get(GameTag.HEALTH, 30)))
            hero_state.max_hp = max(1, _safe_int(tags.get(GameTag.HEALTH, 30)))
            hero_state.armor = _safe_int(tags.get(GameTag.ARMOR, 0))
            hero_state.is_immune = bool(tags.get(GameTag.IMMUNE, 0))

            # 从卡牌数据库获取职业信息
            card_id = ent_data.get("card_id", "")
            if card_id:
                meta = self._get_card_meta(card_id)
                hero_state.hero_class = meta.get("cardClass", "")

            # 英雄技能已使用标记
            # 英雄技能使用状态：HEROPOWER_ACTIVATIONS_THIS_TURN > 0 表示本回合使用过
            hero_power_activations = _safe_int(tags.get(GameTag.HEROPOWER_ACTIVATIONS_THIS_TURN, 0))
            hero_state.hero_power_used = hero_power_activations > 0

            # 英雄技能费用：COST 标签在 HERO_POWER 类型实体上存储
            # 此处为 HERO 实体，不直接存储英雄技能费用，保持默认值 2

            # 只取第一个匹配的 HERO（正常情况每方只有一个）
            break

        return hero_state

    def _extract_mana_state(
        self,
        entity_cache,
        controller: int,
    ) -> ManaState:
        """从 entity_cache 提取法力状态。

        法力信息存储在 PLAYER 类型的实体上（而非 HERO）。
        遍历 entity_cache 查找匹配 controller 的 PLAYER 实体。

        Args:
            entity_cache: EntityCache 实例
            controller: 控制者 ID

        Returns:
            ManaState 实例
        """
        mana_state = ManaState()

        for entity_id, ent_data in entity_cache.items():
            tags = ent_data.get("tags", {})

            # 检查控制器
            ent_controller = _safe_int(tags.get(GameTag.CONTROLLER, 0))
            if ent_controller != controller:
                continue

            # PLAYER 类型实体包含法力信息
            card_type = _safe_int(tags.get(GameTag.CARDTYPE, 0))
            if card_type != CardType.PLAYER.value:
                continue

            # 提取法力值
            mana_state.available = _safe_int(tags.get(GameTag.RESOURCES, 0))
            mana_state.max_mana = _safe_int(tags.get(GameTag.MAXRESOURCES, 0))
            mana_state.overloaded = _safe_int(tags.get(GameTag.OVERLOAD_OWED, 0))
            mana_state.overload_next = _safe_int(tags.get(GameTag.OVERLOAD_LOCKED, 0))

            # 只取第一个匹配的 PLAYER
            break

        return mana_state

    def _extract_board_minions(
        self,
        entity_cache,
        controller: int,
        owner: str = "friendly",
    ) -> List[Minion]:
        """从 entity_cache 提取场上随从列表。

        遍历 entity_cache 查找满足以下条件的实体：
        - ZONE = PLAY
        - CARDTYPE = MINION
        - CONTROLLER = 指定 controller

        Args:
            entity_cache: EntityCache 实例
            controller: 控制者 ID
            owner: 随从归属，"friendly" 或 "enemy"

        Returns:
            Minion 对象列表，按出场位置（entity_id）排序
        """
        minions: List[Minion] = []

        for entity_id, ent_data in entity_cache.items():
            tags = ent_data.get("tags", {})

            # 检查控制器
            ent_controller = _safe_int(tags.get(GameTag.CONTROLLER, 0))
            if ent_controller != controller:
                continue

            # 检查区域为场上
            zone = _safe_int(tags.get(GameTag.ZONE, 0))
            if zone != Zone.PLAY.value:
                continue

            # 检查类型为随从
            card_type = _safe_int(tags.get(GameTag.CARDTYPE, 0))
            if card_type != CardType.MINION.value:
                continue

            # 构建随从
            minion = self._extract_minion_from_entity(ent_data, self._card_db)
            minion.owner = owner
            minions.append(minion)

        # 按 entity_id 排序（保持场面位置顺序）
        # 注意：炉石中随从的场面位置由 ZONE_POSITION 标签决定
        # 但 entity_id 通常也是递增的，这里用 entity_id 作为简单排序
        return minions

    def _extract_hand_cards(
        self,
        entity_cache,
        controller: int,
    ) -> List[Card]:
        """从 entity_cache 提取手牌列表。

        遍历 entity_cache 查找满足以下条件的实体：
        - ZONE = HAND
        - CONTROLLER = 指定 controller

        手牌只能看到自己的，对手手牌不可见。

        Args:
            entity_cache: EntityCache 实例
            controller: 控制者 ID（应为我方）

        Returns:
            Card 对象列表
        """
        hand_cards: List[Card] = []

        for entity_id, ent_data in entity_cache.items():
            tags = ent_data.get("tags", {})

            # 检查控制器
            ent_controller = _safe_int(tags.get(GameTag.CONTROLLER, 0))
            if ent_controller != controller:
                continue

            # 检查区域为手牌
            zone = _safe_int(tags.get(GameTag.ZONE, 0))
            if zone != Zone.HAND.value:
                continue

            # 构建卡牌
            card = self._extract_card_from_entity(ent_data, self._card_db)
            hand_cards.append(card)

        return hand_cards

    def _extract_weapon(
        self,
        entity_cache,
        controller: int,
    ) -> Optional[Weapon]:
        """从 entity_cache 提取已装备的武器。

        遍历 entity_cache 查找满足以下条件的实体：
        - ZONE = PLAY
        - CARDTYPE = WEAPON
        - CONTROLLER = 指定 controller

        Args:
            entity_cache: EntityCache 实例
            controller: 控制者 ID

        Returns:
            Weapon 实例，无武器时返回 None
        """
        for entity_id, ent_data in entity_cache.items():
            tags = ent_data.get("tags", {})

            # 检查控制器
            ent_controller = _safe_int(tags.get(GameTag.CONTROLLER, 0))
            if ent_controller != controller:
                continue

            # 检查区域为场上
            zone = _safe_int(tags.get(GameTag.ZONE, 0))
            if zone != Zone.PLAY.value:
                continue

            # 检查类型为武器
            card_type = _safe_int(tags.get(GameTag.CARDTYPE, 0))
            if card_type != CardType.WEAPON.value:
                continue

            # 提取武器属性
            attack = _safe_int(tags.get(GameTag.ATK, 0))
            durability = _safe_int(tags.get(GameTag.DURABILITY, 0))
            card_id = ent_data.get("card_id", "")
            name = ""

            if card_id:
                meta = self._get_card_meta(card_id)
                name = meta.get("name", "")

            return Weapon(
                attack=attack,
                health=durability,  # Weapon.health 存储耐久度
                name=name or card_id,
            )

        return None

    def _extract_locations(
        self,
        entity_cache,
        controller: int,
    ) -> list:
        """从 entity_cache 提取地点列表。

        遍历 entity_cache 查找满足以下条件的实体：
        - ZONE = PLAY
        - CARDTYPE = LOCATION
        - CONTROLLER = 指定 controller

        Args:
            entity_cache: EntityCache 实例
            controller: 控制者 ID

        Returns:
            地点字典列表，每个包含 card_id、name、durability 等信息
        """
        locations = []

        for entity_id, ent_data in entity_cache.items():
            tags = ent_data.get("tags", {})

            # 检查控制器
            ent_controller = _safe_int(tags.get(GameTag.CONTROLLER, 0))
            if ent_controller != controller:
                continue

            # 检查区域为场上
            zone = _safe_int(tags.get(GameTag.ZONE, 0))
            if zone != Zone.PLAY.value:
                continue

            # 检查类型为地点
            card_type = _safe_int(tags.get(GameTag.CARDTYPE, 0))
            if card_type != CardType.LOCATION.value:
                continue

            card_id = ent_data.get("card_id", "")
            name = ""
            if card_id:
                meta = self._get_card_meta(card_id)
                name = meta.get("name", "")

            locations.append({
                "card_id": card_id,
                "name": name,
                "durability": _safe_int(tags.get(GameTag.DURABILITY, 0)),
                "attack": _safe_int(tags.get(GameTag.ATK, 0)),
            })

        return locations

    # ── 核心：从 entity_cache 条目构建 Minion ──────────────────

    def _extract_minion_from_entity(
        self,
        entity_data: Dict,
        card_db=None,
    ) -> Minion:
        """从 entity_cache 条目构建 Minion 对象。

        entity_cache 中的每个实体条目格式为：
        {"card_id": str, "tags": {GameTag: value}}

        此方法从 tags 中提取随从的属性和关键词标记，
        从 card_db 中补充种族、法术学派等元数据。

        关键词提取规则：
        - GameTag.TAUNT → has_taunt
        - GameTag.DIVINE_SHIELD → has_divine_shield
        - GameTag.CHARGE → has_charge / can_attack
        - GameTag.RUSH → has_rush
        - GameTag.STEALTH → has_stealth
        - GameTag.WINDFURY → has_windfury
        - GameTag.POISONOUS → has_poisonous
        - GameTag.LIFESTEAL → has_lifesteal
        - GameTag.REBORN → has_reborn
        - GameTag.IMMUNE → has_immune
        - GameTag.CANT_ATTACK → cant_attack
        - GameTag.DORMANT → is_dormant
        - GameTag.SPELLPOWER → spell_power
        - GameTag.FROZEN → frozen_until_next_turn
        - GameTag.MEGA_WINDFURY → has_mega_windfury
        - GameTag.MAGNETIC → has_magnetic
        - GameTag.INVOKE_COUNTER → has_invoke（注：INVOKE 标签在 python-hearthstone 中为 INVOKE_COUNTER）
        - GameTag.CORRUPT → has_corrupt
        - GameTag.SPELLBURST → has_spellburst
        - GameTag.OUTCAST → is_outcast

        Args:
            entity_data: entity_cache 中的实体数据字典
            card_db: 可选的 CardDB 实例（用于查询卡牌元数据）

        Returns:
            Minion 实例
        """
        tags = entity_data.get("tags", {})
        card_id = entity_data.get("card_id", "")

        # 基础属性
        attack = _safe_int(tags.get(GameTag.ATK, 0))
        health = _safe_int(tags.get(GameTag.HEALTH, 0))
        cost = _safe_int(tags.get(GameTag.COST, 0))
        max_health = _safe_int(tags.get(GameTag.HEALTH, health))

        # 关键词标记
        has_taunt = bool(tags.get(GameTag.TAUNT, 0))
        has_divine_shield = bool(tags.get(GameTag.DIVINE_SHIELD, 0))
        has_charge = bool(tags.get(GameTag.CHARGE, 0))
        has_rush = bool(tags.get(GameTag.RUSH, 0))
        has_stealth = bool(tags.get(GameTag.STEALTH, 0))
        has_windfury = bool(tags.get(GameTag.WINDFURY, 0))
        has_poisonous = bool(tags.get(GameTag.POISONOUS, 0))
        has_lifesteal = bool(tags.get(GameTag.LIFESTEAL, 0))
        has_reborn = bool(tags.get(GameTag.REBORN, 0))
        has_immune = bool(tags.get(GameTag.IMMUNE, 0))
        cant_attack = bool(tags.get(GameTag.CANT_ATTACK, 0))
        is_dormant = bool(tags.get(GameTag.DORMANT, 0))
        has_magnetic = bool(tags.get(GameTag.MAGNETIC, 0))
        # INVOKE 在 python-hearthstone 中为 INVOKE_COUNTER (value=1366)
        has_invoke = bool(tags.get(GameTag.INVOKE_COUNTER, 0))
        has_corrupt = bool(tags.get(GameTag.CORRUPT, 0))
        has_spellburst = bool(tags.get(GameTag.SPELLBURST, 0))
        is_outcast = bool(tags.get(GameTag.OUTCAST, 0))
        # WARD 标签在 python-hearthstone 中不存在，从卡牌数据库的 mechanics 推断
        has_ward = False
        has_mega_windfury = bool(tags.get(GameTag.MEGA_WINDFURY, 0))
        spell_power = _safe_int(tags.get(GameTag.SPELLPOWER, 0))
        frozen = bool(tags.get(GameTag.FROZEN, 0))

        # 判断是否可以攻击
        # 有 CHARGE 标记的随从可以立即攻击
        # RUSH 随从只能攻击随从（搜索树中简化为可攻击）
        # 如果 EXHAUSTED=1，表示本回合已疲劳不可攻击
        exhausted = bool(tags.get(GameTag.EXHAUSTED, 0))
        num_attacks = _safe_int(tags.get(GameTag.NUM_ATTACKS_THIS_TURN, 0))
        can_attack = (
            (has_charge or has_rush)
            and not cant_attack
            and not is_dormant
            and not exhausted
        )
        # 非新打出随从（没有 charge/rush）也可以攻击
        # EXHAUSTED=0 表示可以攻击
        if not has_charge and not has_rush and not exhausted and not cant_attack and not is_dormant:
            can_attack = True

        # 从卡牌数据库获取种族和法术学派
        race = ""
        spell_school = ""
        dbf_id = 0
        name = ""

        if card_id:
            # 尝试从传入的 card_db 或默认数据库获取元数据
            meta = {}
            if card_db is not None:
                card_data = card_db.get_card(card_id) if hasattr(card_db, 'get_card') else None
                if card_data:
                    meta = card_data
            if not meta:
                meta = self._get_card_meta(card_id)

            if meta:
                race = meta.get("race", "")
                spell_school = meta.get("spellSchool", "")
                dbf_id = _safe_int(meta.get("dbfId", 0), 0)
                name = meta.get("name", "")

                # 从 mechanics 推断 WARD（WARD 标签不在 GameTag 中）
                mechanics_list = meta.get("mechanics", [])
                if not has_ward:
                    has_ward = "WARD" in [m.upper() for m in (mechanics_list or [])]

        # 构建 KeywordSet
        kw_set = KeywordSet()
        if has_taunt:
            kw_set = kw_set.add("taunt")
        if has_divine_shield:
            kw_set = kw_set.add("divine_shield")
        if has_charge:
            kw_set = kw_set.add("charge")
        if has_rush:
            kw_set = kw_set.add("rush")
        if has_stealth:
            kw_set = kw_set.add("stealth")
        if has_windfury:
            kw_set = kw_set.add("windfury")
        if has_poisonous:
            kw_set = kw_set.add("poisonous")
        if has_lifesteal:
            kw_set = kw_set.add("lifesteal")
        if has_reborn:
            kw_set = kw_set.add("reborn")
        if has_immune:
            kw_set = kw_set.add("immune")
        if cant_attack:
            kw_set = kw_set.add("cant_attack")
        if is_dormant:
            kw_set = kw_set.add("dormant")
        if has_spellburst:
            kw_set = kw_set.add("spellburst")
        if has_magnetic:
            kw_set = kw_set.add("magnetic")
        if has_invoke:
            kw_set = kw_set.add("invoke")
        if has_corrupt:
            kw_set = kw_set.add("corrupt")
        if is_outcast:
            kw_set = kw_set.add("outcast")
        if has_ward:
            kw_set = kw_set.add("ward")  # 从 mechanics 推断
        if has_mega_windfury:
            kw_set = kw_set.add("mega_windfury")

        # 休眠随从的苏醒倒计时
        dormant_turns_remaining = 0
        if is_dormant:
            # DORMANT_VISUAL 标签包含休眠阶段的剩余回合数
            dormant_turns_remaining = _safe_int(tags.get(GameTag.DORMANT_VISUAL, 0), 0)

        return Minion(
            dbf_id=dbf_id,
            name=name,
            attack=attack,
            health=health,
            max_health=max_health,
            cost=cost,
            can_attack=can_attack,
            has_divine_shield=has_divine_shield,
            has_taunt=has_taunt,
            has_stealth=has_stealth,
            has_windfury=has_windfury,
            has_rush=has_rush,
            has_charge=has_charge,
            has_poisonous=has_poisonous,
            has_lifesteal=has_lifesteal,
            has_reborn=has_reborn,
            has_immune=has_immune,
            cant_attack=cant_attack,
            is_dormant=is_dormant,
            dormant_turns_remaining=dormant_turns_remaining,
            has_magnetic=has_magnetic,
            has_invoke=has_invoke,
            has_corrupt=has_corrupt,
            has_spellburst=has_spellburst,
            is_outcast=is_outcast,
            race=race,
            spell_school=spell_school,
            spell_power=spell_power,
            has_attacked_once=num_attacks >= 1,
            frozen_until_next_turn=frozen,
            has_ward=has_ward,
            has_mega_windfury=has_mega_windfury,
            card_id=card_id,
            keywords=kw_set,
        )

    # ── 核心：从 entity_cache 条目构建 Card ────────────────────

    def _extract_card_from_entity(
        self,
        entity_data: Dict,
        card_db=None,
    ) -> Card:
        """从 entity_cache 条目构建 Card 对象。

        与 _extract_minion_from_entity 不同，此方法构建的是
        手牌中的卡牌表示，包含费用、类型等信息，
        用于搜索树中的手牌列表。

        card_type 字段必须是以下大写字符串之一：
        "MINION", "SPELL", "WEAPON", "HERO", "LOCATION"

        Args:
            entity_data: entity_cache 中的实体数据字典
            card_db: 可选的 CardDB 实例

        Returns:
            Card 实例
        """
        tags = entity_data.get("tags", {})
        card_id = entity_data.get("card_id", "")

        # 基础属性
        cost = _safe_int(tags.get(GameTag.COST, 0))
        attack = _safe_int(tags.get(GameTag.ATK, 0))
        health = _safe_int(tags.get(GameTag.HEALTH, 0))
        card_type_val = _safe_int(tags.get(GameTag.CARDTYPE, 0))
        card_type_str = _card_type_to_str(card_type_val)

        # 从卡牌数据库补充元数据
        name = ""
        race = ""
        spell_school = ""
        dbf_id = 0
        mechanics = []
        card_class = ""
        rarity = ""
        overload = 0
        spell_damage = 0
        armor = 0
        durability = 0
        text = ""
        ename = ""
        english_text = ""

        if card_id:
            meta = {}
            if card_db is not None:
                card_data = card_db.get_card(card_id) if hasattr(card_db, 'get_card') else None
                if card_data:
                    meta = card_data
            if not meta:
                meta = self._get_card_meta(card_id)

            if meta:
                name = meta.get("name", "")
                race = meta.get("race", "")
                spell_school = meta.get("spellSchool", "")
                dbf_id = _safe_int(meta.get("dbfId", 0), 0)
                mechanics = meta.get("mechanics", [])
                card_class = meta.get("cardClass", "")
                rarity = meta.get("rarity", "")
                overload = _safe_int(meta.get("overload", 0), 0)
                spell_damage = _safe_int(meta.get("spellDamage", 0), 0)
                armor = _safe_int(meta.get("armor", 0), 0)
                durability = _safe_int(meta.get("durability", 0), 0)
                text = meta.get("text", "")
                ename = meta.get("englishName", "")
                english_text = meta.get("englishText", "")

                # 如果 entity_cache 没有类型信息，从数据库补充
                if not card_type_str:
                    card_type_str = meta.get("type", "").upper()

                # 如果 entity_cache 没有费用信息，从数据库补充
                if cost <= 0:
                    cost = _safe_int(meta.get("cost", 0), 0)

                # 武器的攻击力/耐久度
                if card_type_str == "WEAPON":
                    if attack <= 0:
                        attack = _safe_int(meta.get("attack", 0), 0)
                    if durability <= 0:
                        durability = _safe_int(meta.get("durability", 0), 0)

                # 随从的攻击力/血量
                if card_type_str == "MINION":
                    if attack <= 0:
                        attack = _safe_int(meta.get("attack", 0), 0)
                    if health <= 0:
                        health = _safe_int(meta.get("health", 0), 0)

        return Card(
            card_id=card_id,
            dbf_id=dbf_id,
            name=name,
            cost=cost,
            original_cost=cost,
            card_type=card_type_str,
            attack=attack,
            health=health,
            rarity=rarity,
            card_class=card_class,
            race=race,
            mechanics=mechanics,
            overload=overload,
            spell_damage=spell_damage,
            armor=armor,
            durability=durability,
            spell_school=spell_school,
            text=text,
            ename=ename,
            english_text=english_text,
        )

    # ── 从 GlobalTracker 构建对手状态 ─────────────────────────

    def _build_opp_state_from_global_tracker(
        self,
        global_tracker,
    ) -> OpponentState:
        """从 GlobalTracker 构建对手可见/推断状态。

        GlobalTracker 维护了对手层面的聚合数据：
        - opp_board_minions: 对手场上随从列表
        - opp_hand_count: 对手手牌数
        - opp_deck_remaining: 对手牌库剩余
        - opp_weapon/opp_weapon_atk/opp_weapon_durability: 对手武器
        - opp_secrets: 对手奥秘
        - opp_corpses/opp_herald_count: 对手机制状态
        - opp_quests: 对手任务
        - opp_known_cards: 对手已知卡牌

        opp_board_minions 的每个条目是包含以下键的字典：
        {"card_id": str, "entity_id": int, "attack": int, "health": int,
         "has_taunt": bool, "has_divine_shield": bool, ...}

        对于对手场上随从，我们优先使用 GlobalTracker 的数据
        （因为它通过 SHOW_ENTITY 事件获取了对手打出时的精确属性），
        同时通过 card_id 查询卡牌数据库补充种族、学派等元数据。

        Args:
            global_tracker: GlobalTracker 实例

        Returns:
            OpponentState 实例
        """
        gt_state = global_tracker.state

        # 构建对手英雄状态
        opp_hero = HeroState(
            hp=30,  # 默认值，entity_cache 会覆写
            max_hp=30,
            hero_class=gt_state.opp_hero_class or "",
        )

        # 对手武器
        opp_weapon = None
        if gt_state.opp_weapon:
            opp_weapon = Weapon(
                attack=gt_state.opp_weapon_atk,
                health=gt_state.opp_weapon_durability,
                name=gt_state.opp_weapon,
            )
            opp_hero.weapon = opp_weapon

        # 对手场上随从
        opp_board = self._build_opp_minions_from_tracker(global_tracker)

        # 对手已知手牌（从各种追踪效果推断的）
        opp_hand = []
        # 从 opp_hand_card_ids 获取已知手牌
        for entity_id, (card_id, zone) in gt_state.opp_hand_card_ids.items():
            if card_id and zone in (Zone.HAND.value, 2):  # ZONE_HAND
                card = self._build_card_from_card_id(card_id)
                if card:
                    opp_hand.append(card)

        # 对手奥秘
        opp_secrets = list(gt_state.opp_secrets) if gt_state.opp_secrets else []

        # 对手已知卡牌（打出/揭示过的）
        opp_known_cards = []
        for kc in gt_state.opp_known_cards:
            opp_known_cards.append({
                "card_id": kc.card_id,
                "turn_seen": kc.turn_seen,
                "source": kc.source.value if hasattr(kc.source, 'value') else str(kc.source),
                "card_type": kc.card_type,
                "cost": kc.cost,
            })

        # 构建对手状态
        opp_state = OpponentState(
            hero=opp_hero,
            board=opp_board,
            hand=opp_hand,
            hand_count=gt_state.opp_hand_count,
            secrets=opp_secrets,
            deck_remaining=gt_state.opp_deck_remaining,
            opp_known_cards=opp_known_cards,
            opp_generated_count=len(gt_state.opp_generated_seen),
            opp_secrets_triggered=[
                {"card_id": kc.card_id, "turn": kc.turn_seen}
                for kc in gt_state.opp_secrets_triggered
            ],
            # 对手机制状态
            opp_corpses=gt_state.opp_corpses,
            opp_herald_count=gt_state.opp_herald_count,
            opp_quests=list(gt_state.opp_quests) if gt_state.opp_quests else [],
            opp_shuffled_into_deck=list(gt_state.opp_shuffled_into_deck),
            opp_corrupted_cards=list(gt_state.opp_corrupted_cards),
            opp_weapon_card_id=gt_state.opp_weapon,
            # P1 #10: 额外追踪字段
            opp_known_deck_cards=dict(gt_state.opp_known_deck_cards),
            opp_known_hand_types=list(gt_state.opp_known_hand_types),
            opp_entity_transforms=dict(gt_state.opp_entity_transforms),
            opp_revealed_hand_cards=list(gt_state.opp_revealed_hand_cards),
            opp_revealed_deck_cards=list(gt_state.opp_revealed_deck_cards),
            opp_transform_events=list(gt_state.opp_transform_events),
            opp_tutor_evidence=list(gt_state.opp_tutor_evidence),
            opp_deck_insert_events=list(gt_state.opp_deck_insert_events),
        )

        return opp_state

    def _build_opp_minions_from_tracker(
        self,
        global_tracker,
    ) -> List[Minion]:
        """从 GlobalTracker 的 opp_board_minions 构建对手随从列表。

        GlobalTracker.state.opp_board_minions 是一个字典列表，
        每个字典包含 card_id、entity_id 等信息。
        对于早期版本可能只包含 card_id 和 entity_id，
        此时需要从卡牌数据库和 entity_cache 补充属性。

        Args:
            global_tracker: GlobalTracker 实例

        Returns:
            Minion 对象列表
        """
        gt_state = global_tracker.state
        opp_minions: List[Minion] = []

        for minion_data in gt_state.opp_board_minions:
            card_id = minion_data.get("card_id", "")
            entity_id = minion_data.get("entity_id", 0)

            # 尝试从 entity_cache 获取精确属性
            minion = None
            ec = global_tracker  # GlobalTracker 本身没有 entity_cache
            # 注意：entity_cache 在 GameTracker 上，需要从外部传入
            # 这里先用 GlobalTracker 中已有的属性构建
            # 后续 build_from_tracker 会用 entity_cache 覆写

            # 从 GlobalTracker 数据构建基础随从
            meta = self._get_card_meta(card_id) if card_id else {}

            attack = minion_data.get("attack", 0)
            health = minion_data.get("health", 0)
            has_taunt = minion_data.get("has_taunt", False)
            has_divine_shield = minion_data.get("has_divine_shield", False)

            # 如果 GlobalTracker 没有提供属性，从卡牌数据库获取默认值
            if attack <= 0 and meta:
                attack = meta.get("attack", 0)
            if health <= 0 and meta:
                health = meta.get("health", 0)

            # 从 mechanics 推断关键词
            mechanics = meta.get("mechanics", [])
            mechanics_set = set(m.upper() for m in (mechanics or []))

            if not has_taunt:
                has_taunt = "TAUNT" in mechanics_set
            if not has_divine_shield:
                has_divine_shield = "DIVINE_SHIELD" in mechanics_set

            has_charge = "CHARGE" in mechanics_set
            has_rush = "RUSH" in mechanics_set
            has_stealth = "STEALTH" in mechanics_set
            has_windfury = "WINDFURY" in mechanics_set
            has_poisonous = "POISONOUS" in mechanics_set
            has_lifesteal = "LIFESTEAL" in mechanics_set
            has_reborn = "REBORN" in mechanics_set

            race = meta.get("race", "")
            spell_school = meta.get("spellSchool", "")
            dbf_id = _safe_int(meta.get("dbfId", 0), 0)
            name = meta.get("name", "")
            cost = _safe_int(meta.get("cost", 0), 0)

            # 构建 KeywordSet
            kw_set = KeywordSet.from_mechanics(mechanics)

            minion = Minion(
                dbf_id=dbf_id,
                name=name,
                attack=attack,
                health=health,
                max_health=health,
                cost=cost,
                can_attack=not (has_rush and not has_charge),
                has_divine_shield=has_divine_shield,
                has_taunt=has_taunt,
                has_stealth=has_stealth,
                has_windfury=has_windfury,
                has_rush=has_rush,
                has_charge=has_charge,
                has_poisonous=has_poisonous,
                has_lifesteal=has_lifesteal,
                has_reborn=has_reborn,
                race=race,
                spell_school=spell_school,
                card_id=card_id,
                owner="enemy",
                keywords=kw_set,
            )

            opp_minions.append(minion)

        return opp_minions

    def _build_card_from_card_id(self, card_id: str) -> Optional[Card]:
        """从 card_id 构建 Card 对象。

        查询卡牌数据库获取完整的卡牌信息，
        包括费用、类型、种族、法术学派等。

        Args:
            card_id: 卡牌ID

        Returns:
            Card 实例，查询失败返回 None
        """
        if not card_id:
            return None

        meta = self._get_card_meta(card_id)
        if not meta:
            # 数据库中没有，返回最小化 Card
            return Card(
                card_id=card_id,
                card_type="MINION",  # 默认假设
            )

        return Card.from_hsdb_dict(meta)

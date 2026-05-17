# -*- coding: utf-8 -*-
"""game_state.py — 完整游戏状态管理器

统一的游戏状态管理器，作为 UI 读取的唯一数据源（Single Source of Truth）。
整合 GlobalTracker、HandPredictor 等模块的数据，提供完整的游戏视图。

类似于 Firestone 等商业工具，追踪：
- 双方牌库: 剩余卡牌、已打出卡牌、原始 vs 衍生
- 双方手牌: 已知卡牌、预测卡牌、手牌数量
- 棋盘状态: 双方场上的随从及属性
- 奥秘: 活跃奥秘、已触发奥秘、概率模型
- 光环: 棋盘上的活跃光环效果
- 任务/主任务: 活跃任务进度
- 武器/地点: 活跃武器和地点
- 英雄状态: 生命值、护甲、英雄技能
- 疲劳计数: 双方疲劳计数器
- 残骸计数: 死亡骑士残骸
- 过载追踪: 当前和下回合过载
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from analysis.utils.hero_class import class_to_cn
from analysis.watcher.tracker_types import CardSource

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class MinionState:
    """场上随从状态。"""
    card_id: str = ""
    name: str = ""
    attack: int = 0
    health: int = 0
    max_health: int = 0
    cost: int = 0
    has_taunt: bool = False
    has_stealth: bool = False
    has_divine_shield: bool = False
    has_rush: bool = False
    has_charge: bool = False
    has_windfury: bool = False
    has_poisonous: bool = False
    has_lifesteal: bool = False
    has_reborn: bool = False
    frozen: bool = False
    cant_attack: bool = False
    owner: str = "friendly"  # "friendly" | "enemy"


@dataclass
class HeroState:
    """英雄状态。"""
    card_id: str = ""
    name: str = ""
    hero_class: str = ""
    hero_class_cn: str = ""
    health: int = 30
    armor: int = 0
    max_health: int = 30
    attack: int = 0


@dataclass
class WeaponState:
    """武器状态。"""
    card_id: str = ""
    name: str = ""
    attack: int = 0
    durability: int = 0


@dataclass
class LocationState:
    """地点状态。"""
    card_id: str = ""
    name: str = ""
    durability: int = 0


@dataclass
class SecretState:
    """奥秘状态。"""
    card_id: str = ""
    name: str = ""
    probability: float = 0.0
    trigger_risk: str = ""  # "attack" | "spell" | "minion_play" | "unknown"


@dataclass
class QuestState:
    """任务状态。"""
    card_id: str = ""
    name: str = ""
    progress: int = 0
    total: int = 1
    quest_type: str = "quest"  # "quest" | "main_quest" | "sidequest"


@dataclass
class CardInDeck:
    """卡组中的卡牌。"""
    card_id: str = ""
    name: str = ""
    cost: int = 0
    quantity: int = 1
    remaining: int = 1
    card_type: str = ""
    source: str = "deck"  # "deck" | "generated"
    in_hand: bool = False
    played: bool = False
    race: str = ""


@dataclass
class CardInHand:
    """手牌中的卡牌。"""
    card_id: str = ""
    name: str = ""
    cost: int = 0
    probability: float = 1.0
    source: str = "revealed"  # "revealed" | "predicted" | "inferred"
    card_type: str = ""
    race: str = ""
    entity_id: int = 0


@dataclass
class PlayerState:
    """单方玩家完整状态。"""
    hero: HeroState = field(default_factory=HeroState)
    weapon: Optional[WeaponState] = None
    locations: List[LocationState] = field(default_factory=list)
    board: List[MinionState] = field(default_factory=list)
    hand: List[CardInHand] = field(default_factory=list)
    deck: List[CardInDeck] = field(default_factory=list)
    hand_count: int = 0
    deck_remaining: int = 0
    initial_deck_size: int = 30
    secrets: List[SecretState] = field(default_factory=list)
    quests: List[QuestState] = field(default_factory=list)
    corpses: int = 0
    fatigue_damage: int = 0
    overload_current: int = 0
    overload_next: int = 0
    stats: Dict = field(default_factory=dict)
    is_first_player: bool = True


@dataclass
class CompleteGameState:
    """完整游戏状态（Single Source of Truth）。"""
    in_game: bool = False
    turn: int = 0
    step: str = "NOT_STARTED"

    # 双方状态
    player: PlayerState = field(default_factory=PlayerState)
    opponent: PlayerState = field(default_factory=PlayerState)

    # 贝叶斯推断
    archetype_name: str = ""
    archetype_confidence: float = 0.0
    playstyle: str = "unknown"
    top_archetypes: List[Tuple[str, float]] = field(default_factory=list)

    # 奥秘风险
    attack_risk: float = 0.0
    spell_risk: float = 0.0

    # 硬币
    coin_used: bool = False

    # 对手手牌预测
    hand_predictions: List[Dict] = field(default_factory=list)
    deck_predictions: List[Dict] = field(default_factory=list)
    multi_deck_predictions: List[Dict] = field(default_factory=list)
    conditional_evidence: List[Dict] = field(default_factory=list)


# ── 游戏状态管理器 ──────────────────────────────────────────────

class GameStateManager:
    """完整游戏状态管理器。

    从 LogMonitor 提供的状态字典构建完整的游戏状态，
    作为叠加 UI 的唯一数据源。

    用法::

        manager = GameStateManager()
        manager.update(state_dict)
        game_state = manager.state
    """

    def __init__(self):
        self._state = CompleteGameState()
        self._card_db = None

    @property
    def state(self) -> CompleteGameState:
        """获取当前完整游戏状态。"""
        return self._state

    def _ensure_card_db(self):
        """延迟加载卡牌数据库。"""
        if self._card_db is None:
            try:
                from analysis.data.card_data import get_db
                self._card_db = get_db()
            except Exception as e:
                logger.warning("无法加载卡牌数据库: %s", e)

    def update(self, state_dict: dict, prediction_result=None):
        """从状态字典更新完整游戏状态。

        Args:
            state_dict: 来自 LogMonitor._build_state_dict() 的状态字典
            prediction_result: 可选的 HandPredictor.predict() 结果
        """
        self._ensure_card_db()

        gs = self._state
        gs.in_game = state_dict.get("in_game", False)
        gs.turn = state_dict.get("turn", 0)
        gs.step = state_dict.get("step", "NOT_STARTED")
        gs.coin_used = state_dict.get("coin_used", False)

        # 更新对手状态
        self._update_opponent(gs, state_dict)

        # 更新我方状态
        self._update_player(gs, state_dict)

        # 更新贝叶斯推断
        bayesian = state_dict.get("bayesian", {})
        gs.archetype_name = bayesian.get("archetype_name", "") or ""
        gs.archetype_confidence = bayesian.get("deck_confidence", 0.0)
        gs.playstyle = bayesian.get("playstyle", "unknown")
        top_decks = bayesian.get("top_decks", [])
        gs.top_archetypes = [(name, prob) for _, name, prob in top_decks]

        # 更新奥秘风险
        secret_report = state_dict.get("secret_report", {})
        try:
            gs.attack_risk = float(secret_report.get("attack_risk", "0.00"))
        except (ValueError, TypeError):
            gs.attack_risk = 0.0
        try:
            gs.spell_risk = float(secret_report.get("spell_risk", "0.00"))
        except (ValueError, TypeError):
            gs.spell_risk = 0.0

        # 更新对手奥秘
        gs.opponent.secrets = self._build_secrets(state_dict)

        # 更新手牌/卡组预测
        if prediction_result is not None:
            gs.hand_predictions = [
                {
                    "card_id": hp.card_id,
                    "name": hp.name,
                    "cost": hp.cost,
                    "probability": hp.probability,
                    "source": hp.source,
                    "card_type": hp.card_type,
                    "rarity": getattr(hp, 'rarity', ''),
                    "race": getattr(hp, 'race', ''),
                }
                for hp in prediction_result.hand_predictions
            ]
            gs.deck_predictions = [
                {
                    "card_id": dp.card_id,
                    "name": dp.name,
                    "cost": dp.cost,
                    "quantity": dp.quantity,
                    "remaining": dp.remaining,
                    "source": dp.source,
                    "in_hand": dp.in_hand,
                    "played": dp.played,
                    "card_type": dp.card_type,
                    "race": getattr(dp, 'race', ''),
                    "hand_probability": getattr(dp, 'hand_probability', 0.0),
                }
                for dp in prediction_result.deck_predictions
            ]
            gs.conditional_evidence = prediction_result.conditional_evidence

            # 多卡组预测
            multi = getattr(prediction_result, 'multi_deck_predictions', [])
            gs.multi_deck_predictions = [
                {
                    "archetype_name": name,
                    "probability": prob,
                    "cards": [
                        {
                            "card_id": dp.card_id,
                            "name": dp.name,
                            "cost": dp.cost,
                            "quantity": dp.quantity,
                            "remaining": dp.remaining,
                            "source": dp.source,
                            "in_hand": dp.in_hand,
                            "played": dp.played,
                            "card_type": dp.card_type,
                            "hand_probability": dp.hand_probability,
                        }
                        for dp in cards
                    ],
                }
                for name, prob, cards in multi
            ]

    def _update_opponent(self, gs: CompleteGameState, state_dict: dict):
        """更新对手状态。"""
        opp = gs.opponent

        # 英雄
        opp_class = state_dict.get("opp_class_en", "UNKNOWN")
        opp.hero.hero_class = opp_class
        opp.hero.hero_class_cn = state_dict.get("opp_class", "未知")

        # 手牌数量
        opp.hand_count = state_dict.get("opp_hand_count", 0)

        # 牌库
        opp.deck_remaining = state_dict.get("opp_deck_count", 0)
        opp.initial_deck_size = state_dict.get("opp_initial_deck_size", 30)

        # 武器
        weapon_id = state_dict.get("opp_weapon", "")
        if weapon_id:
            opp.weapon = self._build_weapon(weapon_id, state_dict)
        else:
            opp.weapon = None

        # 地点
        opp.locations = [
            self._build_location(cid) for cid in state_dict.get("opp_locations", [])
        ]

        # 残骸
        opp.corpses = state_dict.get("opp_corpses", 0)

        # 疲劳
        opp_stats = state_dict.get("opp_stats", {})
        opp.fatigue_damage = opp_stats.get("fatigue_damage", 0)
        opp.overload_next = opp_stats.get("overload_next", 0)

        # 已知手牌
        opp.hand = self._build_known_hand(state_dict)

        # 统计
        opp.stats = state_dict.get("opp_stats", {})

        # 已打出/已知卡牌 → 构建牌库列表
        opp.deck = self._build_opponent_deck(state_dict)

    def _update_player(self, gs: CompleteGameState, state_dict: dict):
        """更新我方状态。"""
        player = gs.player

        # 英雄
        player_class = state_dict.get("player_class_en", "UNKNOWN")
        player.hero.hero_class = player_class
        player.hero.hero_class_cn = state_dict.get("player_class", "未知")

        # 残骸
        player.corpses = state_dict.get("player_corpses", 0)

        # 疲劳
        player_stats = state_dict.get("player_stats", {})
        player.fatigue_damage = player_stats.get("fatigue_damage", 0)
        player.overload_next = player_stats.get("overload_next", 0)

        # 先手
        player.is_first_player = state_dict.get("is_first_player", True)

        # 统计
        player.stats = state_dict.get("player_stats", {})

    def _build_weapon(self, card_id: str, state_dict: dict) -> WeaponState:
        """构建武器状态。"""
        ws = WeaponState(
            card_id=card_id,
            attack=state_dict.get("opp_weapon_atk", 0),
            durability=state_dict.get("opp_weapon_durability", 0),
        )
        if self._card_db is not None:
            card = self._card_db.get_card(card_id)
            if card:
                ws.name = card.get("name", card_id)
        if not ws.name:
            ws.name = card_id
        return ws

    def _build_location(self, card_id: str) -> LocationState:
        """构建地点状态。"""
        ls = LocationState(card_id=card_id)
        if self._card_db is not None:
            card = self._card_db.get_card(card_id)
            if card:
                ls.name = card.get("name", card_id)
        if not ls.name:
            ls.name = card_id
        return ls

    def _build_known_hand(self, state_dict: dict) -> List[CardInHand]:
        """构建已知手牌列表。"""
        hand = []
        known_hand = state_dict.get("known_hand", [])

        for eid, card_id in known_hand:
            cih = CardInHand(
                card_id=card_id,
                probability=1.0,
                source="revealed",
                entity_id=eid,
            )
            if self._card_db is not None:
                card = self._card_db.get_card(card_id)
                if card:
                    cih.name = card.get("name", card_id)
                    cih.cost = card.get("cost", 0)
                    cih.card_type = card.get("type", "")
                    cih.race = card.get("race", "")
            if not cih.name:
                cih.name = card_id
            hand.append(cih)

        return hand

    def _build_secrets(self, state_dict: dict) -> List[SecretState]:
        """构建奥秘状态列表。"""
        secrets = []
        active_secrets = state_dict.get("opp_secrets", [])
        secret_report = state_dict.get("secret_report", {})
        most_likely = secret_report.get("most_likely", [])

        # 已知奥秘
        known_set = set(active_secrets)
        for card_id in active_secrets:
            ss = SecretState(
                card_id=card_id,
                probability=1.0,
            )
            if self._card_db is not None:
                card = self._card_db.get_card(card_id)
                if card:
                    ss.name = card.get("name", card_id)
            if not ss.name:
                ss.name = card_id
            secrets.append(ss)

        # 预测的奥秘
        for cid, name, prob in most_likely:
            if cid not in known_set:
                ss = SecretState(
                    card_id=cid,
                    name=name if name else cid,
                    probability=prob,
                )
                secrets.append(ss)

        return secrets

    def _build_opponent_deck(self, state_dict: dict) -> List[CardInDeck]:
        """从已知卡牌构建对手牌库列表。"""
        deck = []
        known_cards = state_dict.get("known_cards", [])
        generated = state_dict.get("generated_cards", set())

        # 统计每张牌的打出数量
        from collections import Counter
        played_count = Counter()
        for kc in known_cards:
            cid = kc.get("card_id", "")
            if cid and kc.get("source") == "deck":
                played_count[cid] += 1

        # 从卡组预测获取
        card_breakdown = state_dict.get("card_breakdown", {})
        deck_played = card_breakdown.get("deck_cards_played", [])

        # 构建去重列表
        seen = set()
        for kc in known_cards:
            cid = kc.get("card_id", "")
            if not cid or cid in seen:
                continue
            seen.add(cid)

            source = kc.get("source", "unknown")
            is_generated = cid in generated or source == "generated"

            cideck = CardInDeck(
                card_id=cid,
                source="generated" if is_generated else "deck",
                played=True,
            )
            if self._card_db is not None:
                card = self._card_db.get_card(cid)
                if card:
                    cideck.name = card.get("name", cid)
                    cideck.cost = card.get("cost", 0)
                    cideck.card_type = card.get("type", "")
                    cideck.race = card.get("race", "")
                    rarity = card.get("rarity", "COMMON").upper()
                    max_copies = 1 if rarity == "LEGENDARY" else 2
                    cideck.quantity = max_copies
                    cideck.remaining = max(0, max_copies - played_count.get(cid, 0))
            if not cideck.name:
                cideck.name = cid
            deck.append(cideck)

        deck.sort(key=lambda c: (c.cost, c.name))
        return deck

    def reset(self):
        """重置游戏状态。"""
        self._state = CompleteGameState()

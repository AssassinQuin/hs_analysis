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
    entity_id: int = 0
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
    probability: float = 0.0  # 默认 0.0（未知），仅真正揭示的牌才设 1.0
    source: str = "unknown"  # "revealed" | "predicted" | "inferred" | "unknown"
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
    is_first_player: Optional[bool] = None  # None=未知, True=先手, False=后手


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

    # 对手墓地（卡组来源 + 衍生牌）
    opp_graveyard: List[Dict] = field(default_factory=list)

    # 对手手牌预测
    hand_predictions: List[Dict] = field(default_factory=list)
    deck_predictions: List[Dict] = field(default_factory=list)
    multi_deck_predictions: List[Dict] = field(default_factory=list)
    conditional_evidence: List[Dict] = field(default_factory=list)

    # 衍生牌详细记录（含来源、回合、entity_id等）
    generated_card_records: List[Dict] = field(default_factory=list)

    # 逐位手牌预测
    position_predictions: List[Dict] = field(default_factory=list)

    # MCTS状态
    mcts_applied: bool = False                    # Whether MCTS simulation was used
    mcts_top_predictions: list = field(default_factory=list)  # Top MCTS predictions [(card_id, prob)]


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
                from analysis.card.data.card_data import get_db
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
        self._update_opponent(gs, state_dict, prediction_result)

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

            # MCTS状态
            gs.mcts_applied = getattr(prediction_result, 'mcts_applied', False)
            gs.mcts_top_predictions = list(getattr(prediction_result, 'mcts_top_predictions', []))

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

            # 衍生牌详细记录
            gs.generated_card_records = list(
                getattr(prediction_result, 'generated_card_records', [])
            )

            # 逐位手牌预测
            gs.position_predictions = list(
                getattr(prediction_result, 'position_predictions', [])
            )

    def _update_opponent(self, gs: CompleteGameState, state_dict: dict,
                            prediction_result=None):
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

        # 已知手牌 (revealed + predicted)
        opp.hand = self._build_known_hand(state_dict)

        # Append predicted hand cards from HandPredictor (if available)
        if prediction_result is not None:
            known_ids = {h.card_id for h in opp.hand if h.card_id}
            for hp in prediction_result.hand_predictions:
                # 只添加有实际预测价值的卡牌：有 card_id、非未知来源、概率 > 5%
                if (hp.card_id
                    and hp.card_id not in known_ids
                    and hp.source not in ("unknown", "")
                    and hp.probability > 0.02):
                    cih = CardInHand(
                        card_id=hp.card_id,
                        name=hp.name,
                        cost=hp.cost,
                        probability=hp.probability,
                        source=hp.source,
                        card_type=hp.card_type,
                        race=getattr(hp, 'race', ''),
                    )
                    opp.hand.append(cih)
                    known_ids.add(hp.card_id)

        # 统计
        opp.stats = state_dict.get("opp_stats", {})

        # 对手墓地：从 state_dict 的 graveyard 字段构建
        gs.opp_graveyard = self._build_graveyard(state_dict)

        # 对手棋盘随从
        opp.board = []
        for bm in state_dict.get("opp_board_minions", []):
            cid = bm.get("card_id", "")
            ms = MinionState(
                card_id=cid,
                entity_id=bm.get("entity_id", 0),
                owner="enemy",
            )
            if self._card_db is not None and cid:
                card = self._card_db.get_card(cid)
                if card:
                    ms.name = card.get("name", cid)
                    ms.cost = card.get("cost", 0)
            if not ms.name and cid:
                ms.name = cid
            opp.board.append(ms)

        # 已打出/已知卡牌 → 构建牌库列表
        opp.deck = self._build_opponent_deck(state_dict)

    def _update_player(self, gs: CompleteGameState, state_dict: dict):
        """更新我方状态。"""
        player = gs.player

        # 英雄
        player_class = state_dict.get("player_class_en", "UNKNOWN")
        player.hero.hero_class = player_class
        player.hero.hero_class_cn = state_dict.get("player_class", "未知")

        # 手牌/牌库计数
        player.hand_count = state_dict.get("player_hand_count", 0)
        player.deck_remaining = state_dict.get("player_deck_count", 0)
        player.initial_deck_size = state_dict.get("player_initial_deck_size", 30)

        # 武器
        player_weapon_id = state_dict.get("player_weapon", "")
        if player_weapon_id:
            player.weapon = WeaponState(
                card_id=player_weapon_id,
                attack=state_dict.get("player_weapon_atk", 0),
                durability=state_dict.get("player_weapon_durability", 0),
            )
            if self._card_db is not None:
                card = self._card_db.get_card(player_weapon_id)
                if card:
                    player.weapon.name = card.get("name", player_weapon_id)
        else:
            player.weapon = None

        # 地点
        player.locations = [
            self._build_location(cid)
            for cid in state_dict.get("player_locations", [])
        ]

        # 棋盘随从
        player.board = []
        for bm in state_dict.get("player_board_minions", []):
            cid = bm.get("card_id", "")
            ms = MinionState(
                card_id=cid,
                entity_id=bm.get("entity_id", 0),
                owner="friendly",
            )
            if self._card_db is not None and cid:
                card = self._card_db.get_card(cid)
                if card:
                    ms.name = card.get("name", cid)
                    ms.cost = card.get("cost", 0)
            if not ms.name and cid:
                ms.name = cid
            player.board.append(ms)

        # 残骸
        player.corpses = state_dict.get("player_corpses", 0)

        # 疲劳
        player_stats = state_dict.get("player_stats", {})
        player.fatigue_damage = player_stats.get("fatigue_damage", 0)
        player.overload_next = player_stats.get("overload_next", 0)

        # 先手
        player.is_first_player = state_dict.get("is_first_player", None)

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
        """构建已知手牌列表。

        只有通过 SHOW_ENTITY 真正揭示到 HAND 区域的卡牌才标记为
        probability=1.0 / source="revealed"（100% 确认）。
        其他未知手牌不在 opp.hand 中创建条目——UI 层根据
        opp.hand_count 显示"？？"占位符。
        """
        hand = []
        known_hand = state_dict.get("known_hand", [])

        for eid, card_id, *_ in known_hand:
            # 只有有真实 card_id 的牌才是「已确认」的
            # card_id 为空意味着我们知道该实体在手牌区域，但不知道具体是什么牌
            if not card_id:
                continue
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
        shuffled_into_deck = state_dict.get("opp_shuffled_into_deck", [])

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
            # 跳过英雄技能 — 不是卡牌
            if kc.get("card_type", "").upper() == "HERO_POWER":
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

        # Include shuffled-into-deck cards (known but not yet played/drawn)
        shuffled_seen = set()
        for cid in shuffled_into_deck:
            if not cid or cid in seen or cid in shuffled_seen:
                continue
            shuffled_seen.add(cid)
            cideck = CardInDeck(
                card_id=cid,
                source="generated",
                played=False,
            )
            if self._card_db is not None:
                card = self._card_db.get_card(cid)
                if card:
                    cideck.name = card.get("name", cid)
                    cideck.cost = card.get("cost", 0)
                    cideck.card_type = card.get("type", "")
                    cideck.race = card.get("race", "")
                    cideck.quantity = 1
                    cideck.remaining = 1
            if not cideck.name:
                cideck.name = cid
            deck.append(cideck)

        deck.sort(key=lambda c: (c.cost, c.name))
        return deck

    def _build_graveyard(self, state_dict: dict) -> List[Dict]:
        """从 state_dict 构建对手墓地列表。

        数据来源：
        1. opp_graveyard_seen: 直接区域变化检测到的卡牌（最可靠）
        2. known_cards 中已打出的卡牌（排除仍在场上的随从/武器/地点）

        每条记录包含: card_id, name, cost, source("deck"/"generated"), rarity
        """
        graveyard = []
        seen_ids = set()

        # 收集仍在场上的卡牌（不应出现在墓地）
        on_board_ids = set()
        for bm in state_dict.get("opp_board_minions", []):
            cid = bm.get("card_id", "")
            if cid:
                on_board_ids.add(cid)
        opp_weapon = state_dict.get("opp_weapon", "")
        if opp_weapon:
            on_board_ids.add(opp_weapon)
        for loc in state_dict.get("opp_locations", []):
            if loc:
                on_board_ids.add(loc)

        # 来源1: opp_graveyard_seen（区域变化 PLAY/HAND/SECRET→GRAVEYARD）
        raw_graveyard = state_dict.get("graveyard", [])
        for card_id in raw_graveyard:
            if not card_id or card_id in seen_ids:
                continue
            seen_ids.add(card_id)
            entry = {"card_id": card_id, "source": "deck", "name": card_id, "cost": 0, "rarity": ""}
            if self._card_db is not None:
                card = self._card_db.get_card(card_id)
                if card:
                    entry["name"] = card.get("name", card_id)
                    entry["cost"] = card.get("cost", 0)
                    entry["rarity"] = card.get("rarity", "")
            graveyard.append(entry)

        # 来源2: known_cards（已被揭示且打出的卡牌）
        # 排除仍在场上的随从/武器/地点 —— 它们还没进墓地
        generated_set = state_dict.get("generated_cards", set())
        # 奥秘仍在场不算墓地
        active_secrets = set(state_dict.get("opp_secrets", []))
        for kc in state_dict.get("known_cards", []):
            cid = kc.get("card_id", "")
            if not cid or cid in seen_ids:
                continue
            # 跳过仍在场上的卡牌
            if cid in on_board_ids or cid in active_secrets:
                continue
            # 跳过英雄技能 — 不是卡牌，不属于墓地
            card_type = kc.get("card_type", "")
            if card_type.upper() == "HERO_POWER":
                continue
            source = kc.get("source", "unknown")
            is_generated = cid in generated_set or source == "generated"
            seen_ids.add(cid)
            entry = {
                "card_id": cid,
                "source": "generated" if is_generated else "deck",
                "name": cid,
                "cost": kc.get("cost", 0),
                "rarity": kc.get("rarity", ""),
                "card_type": card_type,
            }
            if self._card_db is not None:
                card = self._card_db.get_card(cid)
                if card:
                    entry["name"] = card.get("name", cid)
                    entry["cost"] = card.get("cost", card.get("cost", 0))
                    entry["rarity"] = card.get("rarity", "")
            graveyard.append(entry)

        # 按来源分组排序：卡组来源优先，然后按费用
        graveyard.sort(key=lambda c: (0 if c.get("source") == "deck" else 1, c.get("cost", 0), c.get("name", "")))
        return graveyard

    def reset(self):
        """重置游戏状态。"""
        self._state = CompleteGameState()

"""tracker_types.py — 全局追踪器使用的纯数据类型定义

包含：
- CardSource: 卡牌来源分类枚举
- KnownCard: 对手已知卡牌记录
- OppHandIntel: 结构化对手手牌情报
- SideStats: 单方运行时统计
- GlobalGameState: 跨回合全局游戏状态

所有类型均为纯数据，不依赖 watcher 内部机制。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# 卡牌来源分类
# ---------------------------------------------------------------------------

class CardSource(str, Enum):
    """卡牌进入游戏的方式"""
    DECK = "deck"           # 从牌库抽到的
    GENERATED = "generated"  # 衍生/发现的牌（不在原始牌库中）
    UNKNOWN = "unknown"      # 无法判断来源


# ---------------------------------------------------------------------------
# 已知卡牌记录（用于对手手牌追踪）
# ---------------------------------------------------------------------------

@dataclass
class KnownCard:
    """对手打出或揭示过的卡牌"""
    card_id: str = ""
    turn_seen: int = 0          # 回合数
    source: CardSource = CardSource.UNKNOWN
    from_zone: str = ""         # "HAND" / "DECK" / "SETASIDE" — 打出前在哪个区域
    card_type: str = ""         # MINION / SPELL / WEAPON / HERO / LOCATION
    cost: int = 0
    spell_school: str = ""      # 法术学派 (FIRE, FROST, HOLY, etc.)
    race: str = ""              # 种族 (BEAST, DEMON, DRAGON, etc.)
    conditional_evidence: str = ""  # 条件触发证据 (如 "HOLDING_DRAGON", "HOLDING_SPELL_SCHOOL:FIRE")
    effect_triggered: bool = False  # 条件效果是否触发（True=确认手牌有对应类型）


@dataclass
class OppHandIntel:
    """结构化的对手手牌情报（用于展示）"""
    confirmed_hand: List[str] = field(default_factory=list)
    returned_to_hand: List[str] = field(default_factory=list)
    graveyard_cards: List[str] = field(default_factory=list)
    probable_hand_over_50: List[str] = field(default_factory=list)
    secrets_active: List[str] = field(default_factory=list)
    secrets_triggered: List[str] = field(default_factory=list)
    deck_cards_played: List[str] = field(default_factory=list)
    generated_cards: List[str] = field(default_factory=list)
    hand_count: int = 0
    deck_count: int = 0
    confirmed_pct: int = 0


# ---------------------------------------------------------------------------
# 单方统计
# ---------------------------------------------------------------------------

@dataclass
class SideStats:
    """单方（玩家或对手）的运行时统计"""
    # 卡牌类型统计
    minions_played: int = 0
    spells_played: int = 0
    weapons_played: int = 0
    heroes_played: int = 0
    locations_played: int = 0

    # 法术学派统计 {school_name: count}
    spell_schools: Dict[str, int] = field(default_factory=dict)

    # 衍生牌计数
    generated_cards_played: int = 0
    deck_cards_played: int = 0

    # 种族统计 {race_name: count}
    races_played: Dict[str, int] = field(default_factory=dict)

    # 抽牌统计
    cards_drawn: int = 0       # 总抽牌数（含疲劳抽牌）
    cards_milled: int = 0      # 爆牌数（手牌满时抽牌直接进墓地）

    # 疲劳追踪 (§8.3)
    fatigue_damage: int = 0    # 下次疲劳伤害值
    times_fatigued: int = 0    # 已经疲劳抽牌次数

    # 过载追踪 (§2.2)
    overload_next: int = 0     # 下回合被锁的法力


# ---------------------------------------------------------------------------
# 全局游戏状态
# ---------------------------------------------------------------------------

@dataclass
class GlobalGameState:
    """跨回合的全局游戏状态追踪器

    在整场游戏回放过程中维护，由 GlobalTracker 随 Power.log
    行的处理而更新。
    """
    # ---- 对手手牌追踪 ----
    opp_known_cards: List[KnownCard] = field(default_factory=list)
    """对手已知的卡牌（打出/揭示时记录）"""

    opp_hand_card_ids: Dict[int, Tuple[str, int]] = field(default_factory=dict)
    """对手手牌 entity_id -> (card_id, zone)（SHOW_ENTITY 揭示的）"""

    # ---- 对手牌库追踪 ----
    opp_deck_remaining: int = 0
    """对手牌库剩余（精确 ZONE_DECK 计数）"""

    opp_initial_deck_size: int = 0
    """对手初始牌库大小（游戏开始时记录）"""

    opp_generated_seen: Set[str] = field(default_factory=set)
    """对手已打出的衍生牌 card_id 集合"""

    opp_graveyard_seen: List[str] = field(default_factory=list)
    """对手已进入墓地的已知 card_id 历史（按时间顺序）"""

    opp_returned_to_hand_seen: List[str] = field(default_factory=list)
    """对手已打出后回到手牌的 card_id 历史（100%确认）"""

    # ---- 我方追踪 ----
    player_generated_seen: Set[str] = field(default_factory=set)
    """我方已打出的衍生牌 card_id 集合"""

    player_cards_played_history: List[str] = field(default_factory=list)
    """我方打出卡牌的 card_id 历史列表（按打出顺序）"""

    player_minions_died: List[str] = field(default_factory=list)
    """我方死亡随从的 card_id 列表"""

    # ---- 先后手 (§1.7) ----
    is_first_player: bool = True
    """我方是否先手"""
    coin_used: bool = False
    """硬币是否已使用"""
    coin_entity_id: int = 0
    """硬币 entity_id"""

    # ---- 英雄职业 ----
    player_hero_class: str = ""
    """我方英雄职业 (PRIEST, MAGE, etc.)"""
    opp_hero_class: str = ""
    """对手英雄职业"""

    # ---- 对手武器/地点 ----
    opp_weapon: str = ""
    """对手当前武器 card_id"""
    opp_weapon_atk: int = 0
    opp_weapon_durability: int = 0

    opp_locations: List[str] = field(default_factory=list)
    """对手当前地点 card_id 列表"""

    # ---- 残骸 (DK Corpse) ----
    player_corpses: int = 0
    opp_corpses: int = 0

    # ---- 兆示 / 任务 ----
    player_quests: List[Dict] = field(default_factory=list)
    opp_quests: List[Dict] = field(default_factory=list)
    player_herald_count: int = 0
    opp_herald_count: int = 0

    # ---- 奥秘 ----
    opp_secrets: List[str] = field(default_factory=list)
    """对手当前奥秘 card_id 列表"""

    opp_secrets_triggered: List[KnownCard] = field(default_factory=list)
    """对手已触发的奥秘"""

    # ---- 本回合出牌记录 (延系等需要 §9.3) ----
    cards_played_this_turn_player: List[str] = field(default_factory=list)
    """我方本回合打出的 card_id"""
    cards_played_this_turn_opp: List[str] = field(default_factory=list)
    """对手本回合打出的 card_id"""
    last_turn_races_player: Set[str] = field(default_factory=set)
    """我方上回合打出的种族"""
    last_turn_schools_player: Set[str] = field(default_factory=set)
    """我方上回合打出的法术学派"""

    # ---- 附魔追踪 (§5.5) ----
    active_enchantments: Dict[int, str] = field(default_factory=dict)
    """entity_id -> card_id of enchantment"""

    # ---- 洗入牌库追踪 ----
    opp_shuffled_into_deck: List[str] = field(default_factory=list)
    """对手洗入牌库的已知 card_id（如爆牌鱼、污染等效果）"""
    
    opp_shuffled_known_cards: Dict[str, bool] = field(default_factory=dict)
    """对手洗入的已知卡牌: card_id → 是否已知 (True=已知是什么牌, False=未知)"""
    
    opp_shuffled_card_sources: Dict[int, str] = field(default_factory=dict)
    """洗入牌的来源追踪: entity_id → source_card_id (是谁衍生的)"""

    player_shuffled_into_deck: List[str] = field(default_factory=list)
    """我方洗入牌库的已知 card_id"""

    # ---- 腐蚀追踪 ----
    opp_corrupted_cards: List[str] = field(default_factory=list)
    """对手已腐蚀升级的原始 card_id 列表（升级前的card_id）"""

    opp_corrupted_upgrades: Dict[str, str] = field(default_factory=dict)
    """对手腐蚀映射: original_card_id -> upgraded_card_id"""

    # ---- 统计 ----
    player_stats: SideStats = field(default_factory=SideStats)
    opp_stats: SideStats = field(default_factory=SideStats)

    # ---- 回合数 ----
    current_turn: int = 0

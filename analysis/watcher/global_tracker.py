"""global_tracker.py — 全局游戏状态追踪器

跨回合追踪双方的关键信息：
- 对手手牌（从打出/揭示的卡牌推断）
- 牌库数量（精确计数 ZONE_DECK）
- 衍生牌 vs 牌库牌区分
- 残骸(Corpse)计数
- 法术学派 / 种族统计
- 卡牌类型统计（随从/法术/武器等各打出多少）
- 疲劳计数（§8.3）
- 过载追踪（§2.2）
- 抽牌/爆牌追踪（§8.2）
- 先后手/硬币追踪（§1.7）
- 英雄职业检测
- 对手武器/地点追踪
- 本回合出牌记录（延系等需要）
- 奥秘/任务/兆示追踪

设计原则：
- 只记录"已知"信息，不推测未知
- 衍生牌通过出生区域检测（SETASIDE/HAND 出生 = 衍生）
- 文件保持简洁，可被 GameReplayer / DecisionLoop 共用
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Card source classification
# ---------------------------------------------------------------------------

class CardSource(str, Enum):
    """How a card entered the game."""
    DECK = "deck"           # 从牌库抽到的
    GENERATED = "generated"  # 衍生/发现的牌（不在原始牌库中）
    UNKNOWN = "unknown"      # 无法判断来源


# ---------------------------------------------------------------------------
# Known card record (for opponent hand tracking)
# ---------------------------------------------------------------------------

@dataclass
class KnownCard:
    """A card we've seen the opponent play or reveal."""
    card_id: str = ""
    turn_seen: int = 0          # 回合数
    source: CardSource = CardSource.UNKNOWN
    from_zone: str = ""         # "HAND" / "DECK" / "SETASIDE" — 打出前在哪个区域
    card_type: str = ""         # MINION / SPELL / WEAPON / HERO / LOCATION
    cost: int = 0
    spell_school: str = ""      # 法术学派 (FIRE, FROST, HOLY, etc.)
    race: str = ""              # 种族 (BEAST, DEMON, DRAGON, etc.)


# ---------------------------------------------------------------------------
# Per-side stats
# ---------------------------------------------------------------------------

@dataclass
class SideStats:
    """Running statistics for one side (player or opponent)."""
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
# Global Game State
# ---------------------------------------------------------------------------

@dataclass
class GlobalGameState:
    """Cross-turn global game state tracker.

    Maintained across the entire game replay. Updated by GlobalTracker
    as Power.log lines are processed.
    """
    # ---- 对手手牌追踪 ----
    opp_known_cards: List[KnownCard] = field(default_factory=list)
    """对手已知的卡牌（打出/揭示时记录）"""

    opp_hand_card_ids: Dict[int, str] = field(default_factory=dict)
    """对手手牌 entity_id -> card_id（SHOW_ENTITY 揭示的）"""

    # ---- 对手牌库追踪 ----
    opp_deck_remaining: int = 0
    """对手牌库剩余（精确 ZONE_DECK 计数）"""

    opp_initial_deck_size: int = 0
    """对手初始牌库大小（游戏开始时记录）"""

    opp_generated_seen: Set[str] = field(default_factory=set)
    """对手已打出的衍生牌 card_id 集合"""

    # ---- 我方追踪 ----
    player_generated_seen: Set[str] = field(default_factory=set)
    """我方已打出的衍生牌 card_id 集合"""

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

    # ---- 统计 ----
    player_stats: SideStats = field(default_factory=SideStats)
    opp_stats: SideStats = field(default_factory=SideStats)

    # ---- 回合数 ----
    current_turn: int = 0


# ---------------------------------------------------------------------------
# Global Tracker
# ---------------------------------------------------------------------------

class GlobalTracker:
    """Processes Power.log events to maintain GlobalGameState.

    Usage::

        gt = GlobalTracker()
        # In your line processor:
        gt.on_full_entity(entity_id, card_id, controller, zone, ...)
        gt.on_show_entity(entity_id, card_id, controller, zone, ...)
        gt.on_zone_change(entity_id, controller, old_zone, new_zone, ...)
        gt.on_turn_change(turn)
        # At decision point:
        state = gt.state
    """

    # Zone constants
    ZONE_PLAY = 1
    ZONE_DECK = 2
    ZONE_HAND = 3
    ZONE_GRAVEYARD = 5
    ZONE_SETASIDE = 6
    ZONE_SECRET = 7

    # CardType constants
    CT_HERO = 3
    CT_MINION = 4
    CT_SPELL = 5
    CT_LOCATION = 6
    CT_WEAPON = 7
    CT_HERO_POWER = 10
    CT_ENCHANTMENT = 6  # Not used as card_type, enchantment is tracked separately

    # Known coin card IDs
    COIN_CARD_IDS = {"GAME_005", "TB_BlingBrawl_Coin", "NEW1_008t"}

    def __init__(self, our_controller: int = 0, opp_controller: int = 0):
        self.state = GlobalGameState()
        self.our_controller = our_controller
        self.opp_controller = opp_controller

        # Entity birth tracking — record when/where an entity first appeared
        self._entity_birth: Dict[int, _EntityBirth] = {}
        # Card DB reference for race/school lookup (lazy)
        self._card_db = None

    def set_controllers(self, our: int, opp: int):
        self.our_controller = our
        self.opp_controller = opp

    def on_game_start(self):
        """Reset state for a new game."""
        self.state = GlobalGameState()
        self._entity_birth.clear()
        self._card_db = None

    # ---------------------------------------------------------------
    # Lazy card DB access
    # ---------------------------------------------------------------

    def _get_card_db(self):
        """Lazy-load HSCardDB for card metadata (race, school, etc.)."""
        if self._card_db is None:
            try:
                from analysis.data.hsdb import get_db
                self._card_db = get_db()
            except Exception:
                logger.warning("HSCardDB unavailable, race/school tracking disabled")
        return self._card_db

    def _card_metadata(self, card_id: str) -> Dict:
        """Get card metadata from DB. Returns dict with race, school, class, etc."""
        db = self._get_card_db()
        if db is None:
            return {}
        card = db.get_card(card_id)
        if card is None:
            return {}
        return card

    # ---------------------------------------------------------------
    # Entity lifecycle
    # ---------------------------------------------------------------

    def on_full_entity(self, entity_id: int, card_id: str, controller: int,
                       zone: int, card_type: int = 0, cost: int = 0):
        """Called when FULL_ENTITY - Creating is parsed."""
        birth = _EntityBirth(
            entity_id=entity_id,
            card_id=card_id,
            controller=controller,
            initial_zone=zone,
            card_type=card_type,
            cost=cost,
        )
        self._entity_birth[entity_id] = birth

        # Track initial deck size for opponent
        if controller == self.opp_controller and zone == self.ZONE_DECK:
            if card_type not in (2,):  # Not PLAYER type
                self.state.opp_initial_deck_size += 1

        # Detect hero class from hero entities
        if card_type == self.CT_HERO and card_id:
            meta = self._card_metadata(card_id)
            hero_class = meta.get("cardClass", "")
            if controller == self.our_controller:
                self.state.player_hero_class = hero_class
            elif controller == self.opp_controller:
                self.state.opp_hero_class = hero_class

        # Detect coin entity
        if card_id in self.COIN_CARD_IDS:
            self.state.coin_entity_id = entity_id

    def on_show_entity(self, entity_id: int, card_id: str, controller: int,
                       zone: int, card_type: int = 0, cost: int = 0):
        """Called when SHOW_ENTITY reveals a hidden entity."""
        if controller == self.opp_controller:
            self.state.opp_hand_card_ids[entity_id] = card_id

        if entity_id in self._entity_birth:
            self._entity_birth[entity_id].card_id = card_id

        # Detect hero class from revealed hero cards
        if card_type == self.CT_HERO and card_id:
            meta = self._card_metadata(card_id)
            hero_class = meta.get("cardClass", "")
            if controller == self.our_controller and not self.state.player_hero_class:
                self.state.player_hero_class = hero_class
            elif controller == self.opp_controller and not self.state.opp_hero_class:
                self.state.opp_hero_class = hero_class

    def on_zone_change(self, entity_id: int, controller: int,
                       old_zone: int, new_zone: int,
                       card_id: str = "", card_type: int = 0):
        """Called when an entity's ZONE tag changes.

        Key transitions:
        - HAND -> PLAY: card played
        - DECK -> HAND: card drawn
        - DECK -> GRAVEYARD: card milled (§8.2)
        - HAND -> SECRET: secret played
        - SECRET -> GRAVEYARD: secret triggered
        - PLAY -> GRAVEYARD: minion died, weapon destroyed
        - SETASIDE -> HAND: generated card enters hand
        - SETASIDE -> PLAY: token summoned
        """
        is_opp = (controller == self.opp_controller)

        # Card played: HAND -> PLAY
        if old_zone == self.ZONE_HAND and new_zone == self.ZONE_PLAY:
            self._on_card_played(entity_id, controller, card_id, card_type)

        # Card drawn: DECK -> HAND (§8.2)
        elif old_zone == self.ZONE_DECK and new_zone == self.ZONE_HAND:
            stats = self.state.opp_stats if is_opp else self.state.player_stats
            stats.cards_drawn += 1

        # Card milled: DECK -> GRAVEYARD when hand full (§8.2)
        elif old_zone == self.ZONE_DECK and new_zone == self.ZONE_GRAVEYARD:
            stats = self.state.opp_stats if is_opp else self.state.player_stats
            stats.cards_milled += 1
            stats.cards_drawn += 1  # counts as a draw

        # Fatigue draw: no entity in DECK, game creates one in HAND
        # Detected via DECK count hitting 0 + draw event
        # Tracked implicitly through deck count

        # Generated card enters hand: SETASIDE -> HAND
        elif old_zone == self.ZONE_SETASIDE and new_zone == self.ZONE_HAND:
            pass  # Entity birth already marks it as generated

        # Token summoned: SETASIDE -> PLAY
        elif old_zone == self.ZONE_SETASIDE and new_zone == self.ZONE_PLAY:
            pass  # Summoned tokens don't count as "played"

        # Secret played: HAND -> SECRET (§7)
        elif old_zone == self.ZONE_HAND and new_zone == self.ZONE_SECRET:
            if is_opp and card_id:
                self.state.opp_secrets.append(card_id)
            self._on_card_played(entity_id, controller, card_id, card_type)

        # Secret triggered/expired: SECRET -> GRAVEYARD/SETASIDE
        elif old_zone == self.ZONE_SECRET and new_zone in (self.ZONE_GRAVEYARD, self.ZONE_SETASIDE):
            if is_opp and card_id:
                if card_id in self.state.opp_secrets:
                    self.state.opp_secrets.remove(card_id)
                self.state.opp_secrets_triggered.append(KnownCard(
                    card_id=card_id,
                    turn_seen=self.state.current_turn,
                    source=self._classify_source(entity_id, card_id),
                    card_type="SPELL",
                ))

        # Weapon equipped: implicit — tracked via weapon entities in PLAY
        # Location played: tracked via location entities in PLAY

        # Coin used: detect coin spell going from HAND to PLAY/GRAVEYARD
        if (old_zone == self.ZONE_HAND and
            card_id in self.COIN_CARD_IDS):
            self.state.coin_used = True

    def _on_card_played(self, entity_id: int, controller: int,
                        card_id: str, card_type: int):
        """Record a card being played (HAND -> PLAY or HAND -> SECRET)."""
        is_opp = (controller == self.opp_controller)
        source = self._classify_source(entity_id, card_id)

        # Look up card metadata for race/school
        meta = self._card_metadata(card_id) if card_id else {}
        spell_school = meta.get("spellSchool", "")
        race = meta.get("race", "")

        # Build known card record
        known = KnownCard(
            card_id=card_id,
            turn_seen=self.state.current_turn,
            source=source,
            from_zone="HAND",
            card_type=self._card_type_name(card_type),
            cost=self._entity_birth.get(entity_id, _EntityBirth()).cost,
            spell_school=spell_school,
            race=race,
        )

        # Update stats
        stats = self.state.opp_stats if is_opp else self.state.player_stats
        self._update_play_stats(stats, card_id, card_type, source, meta)

        # Track cards played this turn
        if is_opp:
            self.state.cards_played_this_turn_opp.append(card_id)
            self.state.opp_known_cards.append(known)
            if source == CardSource.GENERATED:
                self.state.opp_generated_seen.add(card_id)
        else:
            self.state.cards_played_this_turn_player.append(card_id)
            if source == CardSource.GENERATED:
                self.state.player_generated_seen.add(card_id)

        # Remove from hand tracking if applicable
        if is_opp and entity_id in self.state.opp_hand_card_ids:
            del self.state.opp_hand_card_ids[entity_id]

    def _classify_source(self, entity_id: int, card_id: str) -> CardSource:
        """Determine if a card is from deck or generated.

        Heuristics:
        1. If entity was born in DECK zone → deck card
        2. If entity was born in SETASIDE or HAND (non-initial) → generated
        3. Check card DB if available: non-collectible = generated
        """
        birth = self._entity_birth.get(entity_id)
        if birth:
            if birth.initial_zone == self.ZONE_DECK:
                return CardSource.DECK
            if birth.initial_zone == self.ZONE_SETASIDE:
                return CardSource.GENERATED
            # HAND zone for non-deck cards (e.g., generated into hand)
            if birth.initial_zone == self.ZONE_HAND:
                return CardSource.GENERATED

        # Fallback: check card DB collectibility
        if card_id:
            meta = self._card_metadata(card_id)
            if meta:
                if not meta.get("collectible", False):
                    return CardSource.GENERATED
                return CardSource.DECK

        return CardSource.UNKNOWN

    def _card_type_name(self, card_type: int) -> str:
        """Convert numeric card type to string."""
        _map = {4: "MINION", 5: "SPELL", 7: "WEAPON", 3: "HERO",
                6: "LOCATION", 10: "HERO_POWER"}
        return _map.get(card_type, "UNKNOWN")

    def _update_play_stats(self, stats: SideStats, card_id: str,
                           card_type: int, source: CardSource, meta: Dict):
        """Update per-side statistics for a played card."""
        if card_type == self.CT_MINION:
            stats.minions_played += 1
        elif card_type == self.CT_SPELL:
            stats.spells_played += 1
        elif card_type == self.CT_WEAPON:
            stats.weapons_played += 1
        elif card_type == self.CT_HERO:
            stats.heroes_played += 1
        elif card_type == self.CT_LOCATION:
            stats.locations_played += 1

        if source == CardSource.GENERATED:
            stats.generated_cards_played += 1
        elif source == CardSource.DECK:
            stats.deck_cards_played += 1

        # Race tracking (§9.3 延系需要)
        if meta:
            race = meta.get("race", "")
            if race:
                for r in race.split():
                    stats.races_played[r] = stats.races_played.get(r, 0) + 1

            # Spell school tracking
            school = meta.get("spellSchool", "")
            if school:
                stats.spell_schools[school] = stats.spell_schools.get(school, 0) + 1

    # ---------------------------------------------------------------
    # Turn / game events
    # ---------------------------------------------------------------

    def on_turn_change(self, turn: int):
        """Called when game TURN tag changes."""
        # Before switching turn, save current turn's races/schools for kindred
        if turn != self.state.current_turn:
            # Rotate: current becomes last turn for player (we are the player)
            player_stats = self.state.player_stats
            if player_stats.races_played:
                self.state.last_turn_races_player = set(player_stats.races_played.keys())
            if player_stats.spell_schools:
                self.state.last_turn_schools_player = set(player_stats.spell_schools.keys())

            # Clear per-turn cards played tracking
            if turn % 2 == 1:  # Our turn starts
                self.state.cards_played_this_turn_player.clear()
            else:
                self.state.cards_played_this_turn_opp.clear()

        self.state.current_turn = turn

    def on_corpse_change(self, controller: int, total_corpses: int):
        """Called when Corpse total changes."""
        if controller == self.opp_controller:
            self.state.opp_corpses = total_corpses
        else:
            self.state.player_corpses = total_corpses

    def on_overload_change(self, controller: int, overload_next: int):
        """Called when OVERLOAD_OWED tag changes (§2.2)."""
        stats = self.state.opp_stats if controller == self.opp_controller else self.state.player_stats
        stats.overload_next = overload_next

    def on_herald_change(self, controller: int, count: int):
        """Called when Herald counter changes."""
        if controller == self.opp_controller:
            self.state.opp_herald_count = count
        else:
            self.state.player_herald_count = count

    def on_fatigue_change(self, controller: int, fatigue_damage: int):
        """Called when FATIGUE tag changes (§8.3)."""
        stats = self.state.opp_stats if controller == self.opp_controller else self.state.player_stats
        stats.fatigue_damage = fatigue_damage
        stats.times_fatigued += 1

    def on_first_player(self, is_our_player: bool):
        """Called when FIRST_PLAYER is detected (§1.7)."""
        self.state.is_first_player = is_our_player

    # ---------------------------------------------------------------
    # Deck count tracking
    # ---------------------------------------------------------------

    def count_opp_deck(self, opp_entities: list) -> int:
        """Count opponent entities currently in DECK zone."""
        count = sum(1 for e in opp_entities if getattr(e, 'zone', 0) == self.ZONE_DECK)
        self.state.opp_deck_remaining = count
        return count

    def count_player_deck(self, our_entities: list) -> int:
        """Count player entities currently in DECK zone."""
        return sum(1 for e in our_entities if getattr(e, 'zone', 0) == self.ZONE_DECK)

    # ---------------------------------------------------------------
    # Opponent hand / weapon / location tracking
    # ---------------------------------------------------------------

    def get_opp_hand_count(self, opp_entities: list) -> int:
        """Count opponent entities currently in HAND zone."""
        return sum(1 for e in opp_entities if getattr(e, 'zone', 0) == self.ZONE_HAND)

    def get_opp_known_hand(self) -> List[Tuple[int, str]]:
        """Return list of (entity_id, card_id) for known opponent hand cards."""
        return list(self.state.opp_hand_card_ids.items())

    def update_opp_weapon(self, opp_entities: list):
        """Update opponent weapon from entities in PLAY zone."""
        for e in opp_entities:
            if (getattr(e, 'zone', 0) == self.ZONE_PLAY and
                getattr(e, 'card_type', 0) == self.CT_WEAPON):
                self.state.opp_weapon = getattr(e, 'card_id', '')
                self.state.opp_weapon_atk = getattr(e, 'atk', 0)
                self.state.opp_weapon_durability = getattr(e, 'health', 0)
                return
        # No weapon found — clear
        self.state.opp_weapon = ""
        self.state.opp_weapon_atk = 0
        self.state.opp_weapon_durability = 0

    def update_opp_locations(self, opp_entities: list):
        """Update opponent locations from entities in PLAY zone."""
        self.state.opp_locations = [
            getattr(e, 'card_id', '')
            for e in opp_entities
            if (getattr(e, 'zone', 0) == self.ZONE_PLAY and
                getattr(e, 'card_type', 0) == self.CT_LOCATION)
        ]

    # ---------------------------------------------------------------
    # Summary for logging
    # ---------------------------------------------------------------

    def opp_summary_str(self, opp_entities: list, card_name_fn=None) -> str:
        """Generate a human-readable opponent state summary string."""
        deck = self.count_opp_deck(opp_entities)
        hand = self.get_opp_hand_count(opp_entities)
        known_hand = self.get_opp_known_hand()

        parts = [f"手牌={hand}张", f"牌库={deck}张"]

        if known_hand:
            name_fn = card_name_fn or (lambda cid: cid)
            known_str = ", ".join(name_fn(cid) for _, cid in known_hand)
            parts.append(f"已知手牌: [{known_str}]")

        if self.state.opp_generated_seen:
            parts.append(f"衍生牌={len(self.state.opp_generated_seen)}张")

        if self.state.opp_secrets:
            parts.append(f"奥秘={len(self.state.opp_secrets)}个")

        if self.state.opp_weapon:
            name_fn = card_name_fn or (lambda cid: cid)
            parts.append(f"武器={name_fn(self.state.opp_weapon)} {self.state.opp_weapon_atk}/{self.state.opp_weapon_durability}")

        if self.state.opp_hero_class:
            parts.append(f"职业={self.state.opp_hero_class}")

        stats = self.state.opp_stats
        total_played = (stats.minions_played + stats.spells_played +
                       stats.weapons_played + stats.heroes_played)
        if total_played > 0:
            parts.append(f"已出牌={total_played}(衍生{stats.generated_cards_played})")

        if stats.fatigue_damage > 0:
            parts.append(f"疲劳={stats.fatigue_damage}")

        if stats.cards_milled > 0:
            parts.append(f"爆牌={stats.cards_milled}")

        return " | ".join(parts)

    def player_summary_str(self, card_name_fn=None) -> str:
        """Generate a human-readable player global stats string."""
        parts = []
        stats = self.state.player_stats
        if stats.generated_cards_played > 0:
            parts.append(f"衍生牌={stats.generated_cards_played}张")
        if self.state.player_corpses > 0:
            parts.append(f"残骸={self.state.player_corpses}")
        if self.state.player_herald_count > 0:
            parts.append(f"兆示={self.state.player_herald_count}")
        if stats.spell_schools:
            top_schools = sorted(stats.spell_schools.items(), key=lambda x: -x[1])[:3]
            parts.append(f"学派={','.join(f'{k}:{v}' for k,v in top_schools)}")
        if stats.overload_next > 0:
            parts.append(f"过载={stats.overload_next}")
        if stats.fatigue_damage > 0:
            parts.append(f"疲劳={stats.fatigue_damage}")

        if not parts:
            return ""
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

@dataclass
class _EntityBirth:
    """Record of when an entity first appeared in the game."""
    entity_id: int = 0
    card_id: str = ""
    controller: int = 0
    initial_zone: int = 0
    card_type: int = 0
    cost: int = 0

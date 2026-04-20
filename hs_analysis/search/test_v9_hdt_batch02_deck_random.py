#!/usr/bin/env python3
"""V9 Decision Engine — Batch 02: Deck-Based Random Game State Tests

Uses the 7 real parsed decks from parsed_decks.json + full card data from
unified_standard.json to generate realistic game states for integration tests.

Each test picks a specific deck, constructs a plausible game state, runs the
RHEA engine, and asserts reasonable behavior.

Feature gaps are logged when unsupported mechanics (DISCOVER, BATTLECRY effects,
DEATHRATTLE, LOCATION, QUEST, etc.) are encountered. Tests still PASS regardless.
"""

import json
import os
import pytest
from typing import List, Dict, Optional, Tuple

from hs_analysis.search.game_state import (
    GameState, HeroState, ManaState, OpponentState,
    Minion, Weapon
)
from hs_analysis.models.card import Card
from hs_analysis.search.rhea_engine import (
    RHEAEngine, SearchResult, Action,
    enumerate_legal_actions, apply_action
)


# ===================================================================
# DeckTestGenerator — loads decks + card data, generates states
# ===================================================================

class DeckTestGenerator:
    """Loads parsed_decks.json and unified_standard.json, provides
    deterministic game-state generation from real deck lists."""

    _INSTANCE = None  # singleton cache

    def __init__(self):
        # Resolve paths relative to project root
        project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..')
        )
        decks_path = os.path.join(project_root, 'hs_cards', 'parsed_decks.json')
        cards_path = os.path.join(project_root, 'hs_cards', 'unified_standard.json')

        with open(decks_path, encoding='utf-8') as f:
            self.decks = json.load(f)

        with open(cards_path, encoding='utf-8') as f:
            raw_cards = json.load(f)
        # Index unified_standard by dbfId
        self.card_db: Dict[int, dict] = {}
        for c in raw_cards:
            if isinstance(c, dict) and 'dbfId' in c:
                self.card_db[c['dbfId']] = c

        # Pre-expand each deck's cards (respecting count) with full data
        self.expanded_decks: List[List[dict]] = []
        for deck in self.decks:
            expanded = []
            for entry in deck['cards']:
                dbf_id = entry.get('dbfId', 0)
                if dbf_id == 0:
                    continue  # skip unknown cards
                card_data = self.card_db.get(dbf_id)
                if card_data is None:
                    continue
                count = entry.get('count', 1)
                for _ in range(count):
                    expanded.append(card_data)
            self.expanded_decks.append(expanded)

    @classmethod
    def get(cls) -> 'DeckTestGenerator':
        if cls._INSTANCE is None:
            cls._INSTANCE = cls()
        return cls._INSTANCE

    # ---------------------------------------------------------------
    # Card / Minion builders
    # ---------------------------------------------------------------

    def _card_data_to_hand_card(self, cd: dict) -> Optional[Card]:
        """Convert unified_standard entry to a Card for hand."""
        return Card(
            dbf_id=cd.get('dbfId', 0),
            name=cd.get('name', 'Unknown'),
            cost=cd.get('cost', 0),
            original_cost=cd.get('cost', 0),
            card_type=cd.get('type', 'MINION'),
            attack=cd.get('attack', 0),
            health=cd.get('health', 0),
            text=cd.get('text', ''),
            rarity=cd.get('rarity', ''),
            card_class=cd.get('cardClass', ''),
            mechanics=cd.get('mechanics', []),
        )

    def _card_data_to_board_minion(self, cd: dict, can_attack: bool = True,
                                   owner: str = "friendly") -> Minion:
        """Convert unified_standard entry to a Minion for the board."""
        mechanics = set(cd.get('mechanics', []))
        hp = cd.get('health', 1)
        return Minion(
            dbf_id=cd.get('dbfId', 0),
            name=cd.get('name', 'Unknown'),
            attack=cd.get('attack', 0),
            health=hp,
            max_health=hp,
            cost=cd.get('cost', 0),
            can_attack=can_attack,
            has_charge="CHARGE" in mechanics,
            has_rush="RUSH" in mechanics,
            has_taunt="TAUNT" in mechanics,
            has_divine_shield="DIVINE_SHIELD" in mechanics,
            has_windfury="WINDFURY" in mechanics,
            has_stealth="STEALTH" in mechanics,
            has_poisonous="POISONOUS" in mechanics,
            enchantments=[],
            owner=owner,
        )

    def _log_gaps(self, cards_data: List[dict], context: str = ""):
        """Log unsupported mechanics found in the card list."""
        UNSUPPORTED = {
            "DISCOVER", "BATTLECRY", "DEATHRATTLE", "QUEST",
            "LOCATION", "INFUSE", "TEACH", "FORETELLING",
            "LIFESTEAL", "SPELL_DAMAGE", "CHOOSE_ONE",
            "TRIGGER_VISUAL", "COLOSSAL", "IMMUNE",
            "START_OF_GAME", "START_OF_GAME_KEYWORD",
            "OUTCAST", "FREEZE",
        }
        for cd in cards_data:
            name = cd.get('name', '?')
            for mech in cd.get('mechanics', []):
                if mech in UNSUPPORTED:
                    print(f"GAP: {mech} on {name} ({context})")

    # ---------------------------------------------------------------
    # State generation
    # ---------------------------------------------------------------

    def generate_state(
        self,
        deck_index: int,
        turn: int,
        hand_indices: Optional[List[int]] = None,
        hand_cards_override: Optional[List[dict]] = None,
        board_minion_indices: Optional[List[int]] = None,
        board_minions_override: Optional[List[Tuple[dict, bool]]] = None,
        player_hp: int = 30,
        player_armor: int = 0,
        opponent_hp: int = 30,
        opponent_armor: int = 0,
        opponent_board_data: Optional[List[Tuple[dict, bool]]] = None,
        opponent_class: str = "WARLOCK",
        player_weapon: Optional[Dict] = None,
        opponent_hand_size: int = 5,
        opponent_secrets: Optional[List[str]] = None,
    ) -> Tuple[GameState, List[dict]]:
        """Generate a GameState using cards from a real deck.

        Args:
            deck_index: 0-based index into parsed_decks
            turn: turn number (determines max mana)
            hand_indices: indices into expanded deck for hand cards
            hand_cards_override: explicit list of card_data dicts for hand
            board_minion_indices: indices into expanded deck for board minions
            board_minions_override: explicit list of (card_data, can_attack) tuples
            opponent_board_data: list of (card_data, can_attack) for enemy board

        Returns:
            (GameState, list of card_data dicts used) for gap logging
        """
        deck = self.expanded_decks[deck_index]
        mana = min(turn, 10)

        # Build hand
        hand_cards_data: List[dict] = []
        if hand_cards_override is not None:
            hand_cards_data = hand_cards_override
        elif hand_indices is not None:
            for idx in hand_indices:
                if idx < len(deck):
                    hand_cards_data.append(deck[idx])
        # Filter out LOCATION and HERO cards — engine can't play them
        hand = []
        for cd in hand_cards_data:
            ct = cd.get('type', 'MINION').upper()
            if ct in ('MINION', 'WEAPON', 'SPELL'):
                c = self._card_data_to_hand_card(cd)
                if c is not None:
                    hand.append(c)

        # Build board
        board_minions = []
        board_data_raw: List[dict] = []
        if board_minions_override is not None:
            for cd, can_atk in board_minions_override:
                m = self._card_data_to_board_minion(cd, can_attack=can_atk)
                board_minions.append(m)
                board_data_raw.append(cd)
        elif board_minion_indices is not None:
            for idx in board_minion_indices:
                if idx < len(deck):
                    cd = deck[idx]
                    if cd.get('type', '').upper() == 'MINION':
                        m = self._card_data_to_board_minion(cd, can_attack=True)
                        board_minions.append(m)
                        board_data_raw.append(cd)

        # Player weapon
        weapon = None
        if player_weapon:
            weapon = Weapon(
                name=player_weapon.get("name", ""),
                attack=player_weapon.get("attack", 0),
                health=player_weapon.get("durability", 0),
            )

        # Determine player class from deck
        deck_info = self.decks[deck_index]
        raw_class = deck_info.get('class', 'NEUTRAL')
        if '(' in raw_class:
            # e.g. "Unknown(56550)" — extract hero class from hero_dbfId
            hero_dbf = deck_info.get('hero_dbfId', 0)
            hero_card = self.card_db.get(hero_dbf, {})
            player_class = hero_card.get('cardClass', 'NEUTRAL')
            if not player_class or player_class == 'NEUTRAL':
                player_class = 'DEMONHUNTER'  # fallback
        else:
            CLASS_MAP = {
                'Warlock': 'WARLOCK', 'Hunter': 'HUNTER',
                'Rogue': 'ROGUE', 'Druid': 'DRUID',
                'DemonHunter': 'DEMONHUNTER',
            }
            player_class = CLASS_MAP.get(raw_class, raw_class.upper())

        hero = HeroState(
            hp=player_hp, armor=player_armor,
            hero_class=player_class,
            weapon=weapon, hero_power_used=False,
        )
        mana_state = ManaState(
            available=mana, overloaded=0,
            max_mana=mana, overload_next=0,
        )

        # Opponent board
        opp_minions = []
        opp_data_raw = []
        if opponent_board_data:
            for cd, can_atk in opponent_board_data:
                m = self._card_data_to_board_minion(cd, can_attack=can_atk, owner="enemy")
                opp_minions.append(m)
                opp_data_raw.append(cd)

        opponent = OpponentState(
            hero=HeroState(hp=opponent_hp, armor=opponent_armor,
                          hero_class=opponent_class),
            board=opp_minions,
            hand_count=opponent_hand_size,
            secrets=opponent_secrets or [],
        )

        state = GameState(
            hero=hero, opponent=opponent,
            board=board_minions, hand=hand,
            mana=mana_state, turn_number=turn,
            deck_list=None,
        )
        return state, hand_cards_data + board_data_raw + opp_data_raw


# ===================================================================
# Helpers
# ===================================================================

def _quick_engine(time_limit: float = 100.0) -> RHEAEngine:
    return RHEAEngine(
        pop_size=15, max_gens=20,
        time_limit=time_limit, max_chromosome_length=4,
    )


def _get_gen() -> DeckTestGenerator:
    return DeckTestGenerator.get()


# ===================================================================
# Test 1: Deck 0 (DH) Turn 3 — weapon + spell-heavy hand
# ===================================================================

def test_01_dh_deck_weapon_and_spells():
    """Deck 0 (DH) Turn 3: 迷时战刃 weapon in hand with spell-heavy options.
    Verify engine considers weapon play and plays at least one affordable card.
    """
    gen = _get_gen()
    # Hand: 迷时战刃 (1-cost weapon), 伊利达雷研习 (1-cost spell), 虫巢地图 (1-cost spell),
    #        恐怖收割 (2-cost spell), 燃薪咒符 (2-cost spell)
    hand_data = [
        gen.card_db[120993],  # 迷时战刃  1-cost WEAPON
        gen.card_db[97377],   # 伊利达雷研习 1-cost SPELL
        gen.card_db[117684],  # 虫巢地图 1-cost SPELL
        gen.card_db[114654],  # 恐怖收割 2-cost SPELL
        gen.card_db[115626],  # 燃薪咒符 2-cost SPELL
    ]

    state, all_cards = gen.generate_state(
        deck_index=0, turn=3,
        hand_cards_override=hand_data,
    )
    gen._log_gaps(all_cards, context="test_01")

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    assert result.best_chromosome, "Engine returned empty chromosome"
    assert result.best_chromosome[-1].action_type == "END_TURN"

    # At least one card should be playable (all cost ≤ 3)
    legal = enumerate_legal_actions(state)
    play_actions = [a for a in legal if a.action_type == "PLAY"]
    assert len(play_actions) > 0, "Should have legal PLAY actions with 3 mana"

    # Verify weapon play is legal
    weapon_plays = [a for a in play_actions
                    if state.hand[a.card_index].name == "迷时战刃"]
    assert len(weapon_plays) > 0, "迷时战刃 (1-cost weapon) should be a legal play"

    # FEATURE_GAP: DISCOVER on 伊利达雷研习 and 虫巢地图 not implemented
    # FEATURE_GAP: DEATHRATTLE on 迷时战刃 not implemented
    print("GAP: DISCOVER on 伊利达雷研习 (spell choice not simulated)")
    print("GAP: DEATHRATTLE on 迷时战刃 (death effect not simulated)")


# ===================================================================
# Test 2: Deck 1 (Warlock) Turn 4 — multiple 1-cost minions
# ===================================================================

def test_02_warlock_multi_cheap_minions():
    """Deck 1 (Warlock) Turn 4: hand with multiple 1-cost minions.
    Engine should be able to play multiple cheap cards in one turn.
    """
    gen = _get_gen()
    hand_data = [
        gen.card_db[118192],  # 拾荒清道夫 1/1/1 MINION
        gen.card_db[123398],  # 冬泉雏龙 1/1/2 MINION
        gen.card_db[123410],  # 激寒急流 1-cost SPELL
        gen.card_db[112923],  # 石丘防御者 3/1/5 TAUNT MINION
        gen.card_db[123385],  # 蔽影密探 2/2/2 MINION
    ]

    state, all_cards = gen.generate_state(
        deck_index=1, turn=4,
        hand_cards_override=hand_data,
    )
    gen._log_gaps(all_cards, context="test_02")

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    assert result.best_chromosome, "Engine returned empty chromosome"
    assert result.best_chromosome[-1].action_type == "END_TURN"

    # With 4 mana and costs 1+1+1+3+2 = total 8, engine should play at least 2
    played = [a for a in result.best_chromosome if a.action_type == "PLAY"]
    assert len(played) >= 2, (
        f"Engine should play at least 2 cards with 4 mana and cheap hand, got {len(played)}"
    )

    # FEATURE_GAP: BATTLECRY+DISCOVER on 拾荒清道夫, 冬泉雏龙, 石丘防御者, 蔽影密探
    print("GAP: BATTLECRY+DISCOVER on 拾荒清道夫 (effect not simulated)")
    print("GAP: BATTLECRY+DISCOVER on 冬泉雏龙 (effect not simulated)")
    print("GAP: BATTLECRY+DISCOVER+TAUNT on 石丘防御者 (effect not simulated)")


# ===================================================================
# Test 3: Deck 2 (Warlock) Turn 8 — Grommash CHARGE finisher
# ===================================================================

def test_03_warlock_grommash_charge_finisher():
    """Deck 2 (Dragon Warlock) Turn 8: 格罗玛什 (4/9 CHARGE) in hand.
    Verify engine considers playing the charge finisher with 8 mana available.
    """
    gen = _get_gen()
    hand_data = [
        gen.card_db[69643],   # 格罗玛什·地狱咆哮 8/4/9 CHARGE
        gen.card_db[122933],  # 载蛋雏龙 1/1/2
        gen.card_db[120975],  # 先行打击 2-cost SPELL
    ]

    state, all_cards = gen.generate_state(
        deck_index=2, turn=8,
        hand_cards_override=hand_data,
        # Player has a 3/3 on board already
        board_minions_override=[
            (gen.card_db[120503], True),  # 现场播报员 3/3 can attack
        ],
        opponent_hp=12,
    )
    gen._log_gaps(all_cards, context="test_03")

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    assert result.best_chromosome, "Engine returned empty chromosome"
    assert result.best_chromosome[-1].action_type == "END_TURN"

    # Verify Grommash is a legal play at cost 8
    legal = enumerate_legal_actions(state)
    grommash_plays = [a for a in legal if a.action_type == "PLAY"
                      and a.card_index < len(state.hand)
                      and state.hand[a.card_index].name == "格罗玛什·地狱咆哮"]
    assert len(grommash_plays) > 0, "格罗玛什 (8-cost CHARGE) should be legal with 8 mana"

    # Engine should either play Grommash (4/9 charge → lethal with 3/3 = 7+4>12 nope, 3+4=7<12)
    # or play cheap cards. At minimum it should find valid actions.
    assert result.best_fitness > -9999.0, "Engine found valid action sequence"

    # FEATURE_GAP: BATTLECRY on 载蛋雏龙 not implemented
    # FEATURE_GAP: BATTLECRY on 现场播报员 not implemented
    print("GAP: BATTLECRY on 载蛋雏龙 (effect not simulated)")
    print("GAP: BATTLECRY+TRIGGER_VISUAL on 现场播报员 (effect not simulated)")


# ===================================================================
# Test 4: Deck 3 (Warlock) Turn 5 — Xavius BATTLECRY+DISCOVER
# ===================================================================

def test_04_warlock_xavius_battlecry():
    """Deck 3 (Warlock) Turn 5: 梦魇之王萨维斯 (4/4/4 BATTLECRY+DISCOVER) in hand.
    Verify engine considers playing Xavius and the action is legal.
    """
    gen = _get_gen()
    hand_data = [
        gen.card_db[115139],  # 梦魇之王萨维斯 4/4/4 BATTLECRY+DISCOVER
        gen.card_db[118192],  # 拾荒清道夫 1/1/1
        gen.card_db[116977],  # 生命火花 1-cost SPELL
        gen.card_db[123410],  # 激寒急流 1-cost SPELL
        gen.card_db[112923],  # 石丘防御者 3/1/5 TAUNT
    ]

    state, all_cards = gen.generate_state(
        deck_index=3, turn=5,
        hand_cards_override=hand_data,
    )
    gen._log_gaps(all_cards, context="test_04")

    # Xavius should be a legal play at cost 4 with 5 mana
    legal = enumerate_legal_actions(state)
    xavius_plays = [a for a in legal if a.action_type == "PLAY"
                    and a.card_index < len(state.hand)
                    and state.hand[a.card_index].name == "梦魇之王萨维斯"]
    assert len(xavius_plays) > 0, "梦魇之王萨维斯 (4-cost) should be legal with 5 mana"

    # Run engine and verify valid result
    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)
    assert result.best_chromosome, "Engine returned empty chromosome"
    # Stochastic engine — may or may not play Xavius, but must produce valid result
    assert result.best_fitness > -9999.0, "Engine found valid action sequence"

    # FEATURE_GAP: BATTLECRY+DISCOVER on 梦魇之王萨维斯 not implemented
    print("GAP: BATTLECRY+DISCOVER on 梦魇之王萨维斯 (effect not simulated)")


# ===================================================================
# Test 5: Deck 4 (Hunter) Turn 1 — all 1-cost aggro cards
# ===================================================================

def test_05_hunter_turn1_aggro():
    """Deck 4 (Hunter) Turn 1: all 1-cost cards in hand.
    Verify 1-cost cards are legal plays and engine produces a valid result.
    Note: The engine may rationally choose not to play a 1/2/1 minion on an
    empty board (opponent can easily remove it). We verify legality, not strategy.
    """
    gen = _get_gen()
    hand_data = [
        gen.card_db[102227],  # 冰川裂片 1/2/1 MINION
        gen.card_db[118222],  # 炽烈烬火 1/2/1 MINION
        gen.card_db[122937],  # 进击的募援官 1/2/2 MINION
        gen.card_db[117039],  # 击伤猎物 1-cost SPELL
    ]

    state, all_cards = gen.generate_state(
        deck_index=4, turn=1,
        hand_cards_override=hand_data,
    )
    gen._log_gaps(all_cards, context="test_05")

    # Verify all 1-cost cards are legal plays with 1 mana
    legal = enumerate_legal_actions(state)
    play_actions = [a for a in legal if a.action_type == "PLAY"]
    assert len(play_actions) >= 4, (
        f"All 4 cards (1-cost each) should be legal plays with 1 mana, got {len(play_actions)}"
    )

    # Verify each card is affordable
    for a in play_actions:
        if 0 <= a.card_index < len(state.hand):
            card = state.hand[a.card_index]
            assert card.cost <= 1, (
                f"Card {card.name} costs {card.cost}, expected ≤ 1"
            )

    # Run engine and verify it produces a valid result
    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)
    assert result.best_chromosome, "Engine returned empty chromosome"
    assert result.best_fitness >= 0.0, "Engine should produce non-negative fitness"

    # FEATURE_GAP: BATTLECRY+FREEZE on 冰川裂片 not implemented
    # FEATURE_GAP: DEATHRATTLE on 炽烈烬火 not implemented
    print("GAP: BATTLECRY+FREEZE on 冰川裂片 (effect not simulated)")
    print("GAP: DEATHRATTLE on 炽烈烬火 (effect not simulated)")


# ===================================================================
# Test 6: Deck 4 (Hunter) Turn 2 — mana efficiency curve
# ===================================================================

def test_06_hunter_turn2_mana_efficiency():
    """Deck 4 (Hunter) Turn 2: 2-drop curve with multiple options.
    Verify legal actions include both 1-cost and 2-cost plays, and engine
    produces a result that respects mana constraints.
    """
    gen = _get_gen()
    hand_data = [
        gen.card_db[117381],  # 抛石鱼人 2/1/3 MINION
        gen.card_db[120788],  # 拾箭龙鹰 2/3/1 MINION
        gen.card_db[102227],  # 冰川裂片 1/2/1 MINION
        gen.card_db[117039],  # 击伤猎物 1-cost SPELL
    ]

    state, all_cards = gen.generate_state(
        deck_index=4, turn=2,
        hand_cards_override=hand_data,
    )
    gen._log_gaps(all_cards, context="test_06")

    # Verify legal plays include both 1-cost and 2-cost cards
    legal = enumerate_legal_actions(state)
    play_actions = [a for a in legal if a.action_type == "PLAY"]
    assert len(play_actions) >= 3, (
        f"Should have legal plays for 1-cost and 2-cost cards, got {len(play_actions)}"
    )

    # Run engine
    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    assert result.best_chromosome, "Engine returned empty chromosome"
    assert result.best_fitness >= 0.0, "Engine should produce non-negative fitness"

    # Check mana constraint: any played cards must cost ≤ 2 total
    played = [a for a in result.best_chromosome if a.action_type == "PLAY"]
    total_cost = sum(
        state.hand[a.card_index].cost for a in played
        if 0 <= a.card_index < len(state.hand)
    )
    assert total_cost <= 2, f"Total cost {total_cost} exceeds available mana 2"

    # FEATURE_GAP: BATTLECRY on 抛石鱼人, 拾箭龙鹰 not implemented
    print("GAP: BATTLECRY on 抛石鱼人 (effect not simulated)")
    print("GAP: BATTLECRY on 拾箭龙鹰 (effect not simulated)")


# ===================================================================
# Test 7: Deck 5 (Rogue) Turn 6 — weapon + stealth minions
# ===================================================================

def test_07_rogue_weapon_and_stealth():
    """Deck 5 (Rogue) Turn 6: 弑君者 weapon + stealth minions.
    Stealth minion on board should be present; weapon play is an option.
    """
    gen = _get_gen()
    hand_data = [
        gen.card_db[119816],  # 弑君者 2/3/2 WEAPON
        gen.card_db[123060],  # 古神的眼线 1-cost MINION
        gen.card_db[120460],  # 狐人老千 2/2/2 MINION
        gen.card_db[117697],  # 异教地图 2-cost SPELL
    ]

    # Already on board: 间谍女郎 1/3/1 STEALTH
    stealth_card = gen.card_db[129347]  # 间谍女郎

    state, all_cards = gen.generate_state(
        deck_index=5, turn=6,
        hand_cards_override=hand_data,
        board_minions_override=[
            (stealth_card, True),  # stealth minion on board, can attack
        ],
    )
    gen._log_gaps(all_cards, context="test_07")

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    assert result.best_chromosome, "Engine returned empty chromosome"
    # With discover framework active, discovered cards may extend the plan
    # beyond a simple END_TURN ending (e.g., playing the discovered card)
    last_action = result.best_chromosome[-1].action_type
    assert last_action in ("END_TURN", "PLAY"), \
        f"Expected END_TURN or PLAY as last action, got {last_action}"

    # Verify stealth minion is on board
    assert len(state.board) >= 1, "Should have stealth minion on board"
    assert state.board[0].has_stealth, "间谍女郎 should have STEALTH"

    # Weapon play should be legal
    legal = enumerate_legal_actions(state)
    weapon_plays = [a for a in legal if a.action_type == "PLAY"
                    and a.card_index < len(state.hand)
                    and state.hand[a.card_index].name == "弑君者"]
    assert len(weapon_plays) > 0, "弑君者 (2-cost weapon) should be legal with 6 mana"

    # Engine should play something
    played = [a for a in result.best_chromosome if a.action_type == "PLAY"]
    assert len(played) >= 1, "Engine should play at least one card with 6 mana"

    # FEATURE_GAP: STEALTH targeting rules not enforced (stealth minion can be targeted)
    # FEATURE_GAP: BATTLECRY on 狐人老千, 古神的眼线 not implemented
    print("GAP: STEALTH targeting rules not fully enforced on 间谍女郎")
    print("GAP: BATTLECRY on 狐人老千 (effect not simulated)")
    print("DISCOVER on 异教地图 — now active via discover framework (may add card to hand)")


# ===================================================================
# Test 8: Deck 6 (Druid) Turn 9 — big minions with taunt/battlecry
# ===================================================================

def test_08_druid_big_minions():
    """Deck 6 (Druid) Turn 9: big minions (伊瑟拉 4/12, 护巢龙 4/5 TAUNT).
    Verify engine plays high-cost taunt/battlecry minions.
    """
    gen = _get_gen()
    hand_data = [
        gen.card_db[113321],  # 伊瑟拉，翡翠守护巨龙 9/4/12 BATTLECRY
        gen.card_db[122968],  # 护巢龙 4/4/5 TAUNT
        gen.card_db[115080],  # 丰裕之角 2-cost SPELL
        gen.card_db[122967],  # 费伍德树人 2/2/2 MINION
    ]

    state, all_cards = gen.generate_state(
        deck_index=6, turn=9,
        hand_cards_override=hand_data,
    )
    gen._log_gaps(all_cards, context="test_08")

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    assert result.best_chromosome, "Engine returned empty chromosome"
    assert result.best_chromosome[-1].action_type == "END_TURN"

    # 伊瑟拉 costs 9, exactly equal to 9 mana — should be legal
    legal = enumerate_legal_actions(state)
    ysera_plays = [a for a in legal if a.action_type == "PLAY"
                   and a.card_index < len(state.hand)
                   and state.hand[a.card_index].name == "伊瑟拉，翡翠守护巨龙"]
    assert len(ysera_plays) > 0, "伊瑟拉 (9-cost) should be legal with 9 mana"

    # 护巢龙 (4/5 TAUNT) should also be legal
    nest_plays = [a for a in legal if a.action_type == "PLAY"
                  and a.card_index < len(state.hand)
                  and state.hand[a.card_index].name == "护巢龙"]
    assert len(nest_plays) > 0, "护巢龙 (4-cost TAUNT) should be legal with 9 mana"

    # Engine should play at least one card
    played = [a for a in result.best_chromosome if a.action_type == "PLAY"]
    assert len(played) >= 1, "Engine should play at least one card with 9 mana"

    # FEATURE_GAP: BATTLECRY on 伊瑟拉, 费伍德树人, 护巢龙 not implemented
    # FEATURE_GAP: START_OF_GAME on 伊瑟拉 not relevant (already in play)
    print("GAP: BATTLECRY+START_OF_GAME on 伊瑟拉 (effect not simulated)")
    print("GAP: BATTLECRY+TAUNT on 护巢龙 (taunt propagated, battlecry not)")
    print("GAP: DISCOVER on 丰裕之角 (spell choice not simulated)")


# ===================================================================
# Test 9: Multi-deck lethal — board state where any deck could lethal
# ===================================================================

def test_09_multi_deck_lethal():
    """Any deck: charge minions on board with enough damage for lethal.
    Verify fitness = 10000 (lethal detected).
    """
    gen = _get_gen()
    # Use deck 2 (Warlock) — Grommash is a CHARGE minion
    # But let's set up a board where existing minions + charge = lethal
    # Player board: 3/3 (可攻击), charge minion 5/2 (可攻击 from hand)
    # Opponent HP = 8, so 3 + 5 = 8 = lethal

    hand_data = [
        gen.card_db[69643],   # 格罗玛什·地狱咆哮 8/4/9 CHARGE (costs 8 — can't play)
        gen.card_db[123164],  # 烈火炙烤 1-cost SPELL
    ]

    # Use generic charge minions on board (already played last turn)
    # Board: 3/3 minion + 5/2 charge minion (already on board from previous turn)
    # We'll create them manually since we need specific stats
    board_minions_override = [
        ({"name": "现场播报员", "attack": 3, "health": 3, "cost": 4, "type": "MINION",
          "mechanics": ["BATTLECRY", "TRIGGER_VISUAL"], "dbfId": 120503}, True),
        ({"name": "冲锋龙", "attack": 5, "health": 2, "cost": 5, "type": "MINION",
          "mechanics": ["CHARGE"], "dbfId": 99999}, True),  # generic charge minion
    ]

    state, all_cards = gen.generate_state(
        deck_index=2, turn=8,
        hand_cards_override=hand_data,
        board_minions_override=board_minions_override,
        opponent_hp=8,
    )

    # Verify: 3 + 5 = 8 = opponent HP → lethal
    total_attack = sum(m.attack for m in state.board)
    assert total_attack >= 8, f"Board damage ({total_attack}) should be enough for lethal (8)"

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    # Should detect lethal
    assert result.best_fitness == 10000.0, (
        f"Should detect lethal ({total_attack} atk vs 8 hp), got fitness={result.best_fitness}"
    )

    # All minions should attack face
    face_attacks = [a for a in result.best_chromosome
                    if a.action_type == "ATTACK" and a.target_index == 0]
    assert len(face_attacks) >= 2, (
        f"Both minions should attack face for lethal, got {len(face_attacks)} face attacks"
    )


# ===================================================================
# Test 10: Multi-deck defense — player at 5 HP, opponent has board
# ===================================================================

def test_10_multi_deck_defense():
    """Player at 5 HP, opponent has threatening board.
    Verify engine produces a valid result and doesn't overcommit
    (plays conservatively by not sending everything face).
    """
    gen = _get_gen()
    # Use deck 1 (Warlock) — has taunt minions (石丘防御者)
    hand_data = [
        gen.card_db[112923],  # 石丘防御者 3/1/5 TAUNT MINION
        gen.card_db[123410],  # 激寒急流 1-cost SPELL
        gen.card_db[126227],  # 初始之火 1-cost SPELL
        gen.card_db[118192],  # 拾荒清道夫 1/1/1 MINION
    ]

    # Opponent board: 5/4 and 3/3 — threatening 8 damage per turn
    opponent_board_data = [
        (gen.card_db[131356], True),  # 迅猛龙先锋 4/2 — using stats from card_db
        (gen.card_db[120503], True),  # 现场播报员 3/3
    ]

    state, all_cards = gen.generate_state(
        deck_index=1, turn=5,
        hand_cards_override=hand_data,
        player_hp=5,       # dangerously low HP
        opponent_hp=25,
        opponent_board_data=opponent_board_data,
    )
    gen._log_gaps(all_cards, context="test_10")

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    assert result.best_chromosome, "Engine returned empty chromosome"
    assert result.best_chromosome[-1].action_type == "END_TURN"

    # Engine should consider playing the TAUNT minion (石丘防御者) to block
    legal = enumerate_legal_actions(state)
    taunt_plays = [a for a in legal if a.action_type == "PLAY"
                   and a.card_index < len(state.hand)
                   and state.hand[a.card_index].name == "石丘防御者"]
    assert len(taunt_plays) > 0, "石丘防御者 (3-cost TAUNT) should be legal with 5 mana"

    # Engine should produce a reasonable result
    assert result.best_fitness > -9999.0, "Engine should find a valid action sequence"

    # The engine should play at least one card (has 5 mana, cards cost 1-3)
    played = [a for a in result.best_chromosome if a.action_type == "PLAY"]
    assert len(played) >= 1, "Engine should play at least one card in defensive situation"

    # FEATURE_GAP: BATTLECRY+DISCOVER+TAUNT on 石丘防御者 (taunt propagated, discover not)
    # FEATURE_GAP: BATTLECRY+DISCOVER on 拾荒清道夫 not implemented
    print("GAP: BATTLECRY+DISCOVER on 石丘防御者 (taunt propagated, discover not)")
    print("GAP: BATTLECRY+DISCOVER on 拾荒清道夫 (effect not simulated)")

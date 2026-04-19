"""
test_v9_hdt_batch13.py — V9 HDT Batch13: High-Complexity Stress & Edge-Case Tests
==================================================================================

Philosophy: 1 test = 1 extreme scenario, pushing engine boundaries with
multi-system interactions, edge cases, and stress conditions.

Previous: B01-B10 (single mechanism), B11-B12 (complex scenarios).
Batch13: 10 high-complexity stress/edge-case tests. 332 → 342.
"""

import pytest
import math

from hs_analysis.search.test_v9_hdt_batch02_deck_random import DeckTestGenerator
from hs_analysis.search.rhea_engine import (
    RHEAEngine, Action, apply_action, enumerate_legal_actions,
    next_turn_lethal_check,
)
from hs_analysis.utils.spell_simulator import resolve_effects, EffectParser, EffectApplier
from hs_analysis.models.card import Card
from hs_analysis.search.game_state import (
    GameState, Minion, HeroState, ManaState, OpponentState, Weapon,
)
from hs_analysis.search.lethal_checker import check_lethal, max_damage_bound
from hs_analysis.evaluators.composite import (
    evaluate, evaluate_delta, evaluate_with_risk, evaluate_delta_with_risk,
)
from hs_analysis.evaluators.multi_objective import (
    evaluate as mo_evaluate,
    evaluate_delta as mo_evaluate_delta,
    pareto_filter,
)
from hs_analysis.search.risk_assessor import RiskAssessor
from hs_analysis.search.opponent_simulator import OpponentSimulator
from hs_analysis.search.action_normalize import (
    normalize_chromosome, action_hash, are_commutative,
)


# ---------------------------------------------------------------------------
# Helpers (matching batch12 pattern exactly)
# ---------------------------------------------------------------------------

def _make_minion(name, attack, health, cost=0, *, can_attack=False,
                 has_charge=False, has_rush=False, has_taunt=False,
                 has_stealth=False, has_divine_shield=False,
                 has_windfury=False, has_poisonous=False,
                 owner="player", dbf_id=0, enchantments=None):
    """Create a Minion with sensible defaults."""
    return Minion(
        dbf_id=dbf_id or hash(name) % 100000,
        name=name,
        attack=attack,
        health=health,
        max_health=health,
        cost=cost,
        can_attack=can_attack,
        has_charge=has_charge,
        has_rush=has_rush,
        has_taunt=has_taunt,
        has_stealth=has_stealth,
        has_divine_shield=has_divine_shield,
        has_windfury=has_windfury,
        has_poisonous=has_poisonous,
        enchantments=enchantments or [],
        owner=owner,
    )


def _make_card(name, cost, *, dbf_id=0, card_type="SPELL", text="",
               attack=0, health=0, mechanics=None, race=""):
    """Create a Card with sensible defaults."""
    return Card(
        dbf_id=dbf_id or hash(name) % 100000,
        name=name,
        cost=cost,
        original_cost=cost,
        card_type=card_type,
        attack=attack,
        health=health,
        text=text,
        mechanics=mechanics or [],
        race=race,
    )


def _make_weapon(attack=1, health=2):
    return Weapon(name="TestWeapon", attack=attack, health=health)


def _base_hero(hp=30, armor=0, weapon=None):
    return HeroState(hp=hp, armor=armor, weapon=weapon)


def _base_mana(available, max_mana=None):
    return ManaState(available=available, overloaded=0,
                     max_mana=max_mana or available, overload_next=0)


def _base_state(*, hero, mana, board, hand, deck_remaining,
                opponent_hero, opponent_board,
                opponent_hand_count=5, opponent_class="WARLOCK",
                opponent_deck_remaining=20, turn_number=4,
                fatigue=0):
    """Build a GameState from components."""
    return GameState(
        hero=hero,
        mana=mana,
        board=board,
        hand=hand,
        deck_remaining=deck_remaining,
        fatigue_damage=fatigue,
        opponent=OpponentState(
            hero=opponent_hero,
            board=opponent_board,
            hand_count=opponent_hand_count,
            secrets=[],
            deck_remaining=opponent_deck_remaining,
        ),
        turn_number=turn_number,
    )


# ===========================================================================
# Test 1: Maximum actions single turn (stress test)
# ===========================================================================

class Test01MaxActionsSingleTurnT10:
    """Stress: 7 board minions attacking + weapon + hero power + spell. Turn 10."""

    @pytest.fixture
    def state(self):
        board = [
            _make_minion("M1", 5, 5, can_attack=True),
            _make_minion("M2", 4, 4, can_attack=True),
            _make_minion("M3", 3, 3, can_attack=True),
            _make_minion("M4", 2, 2, can_attack=True),
            _make_minion("M5", 1, 1, can_attack=True),
            _make_minion("M6", 6, 6, can_attack=True),
            _make_minion("M7", 3, 3, can_attack=True),
        ]
        hand = [
            _make_card("Damage", 3, card_type="SPELL", text="造成 4 点伤害"),
            _make_card("Draw", 2, card_type="SPELL", text="抽 2 张牌"),
        ]
        opp_board = [
            _make_minion("Taunt1", 4, 4, has_taunt=True, owner="opponent"),
            _make_minion("OppM", 3, 3, owner="opponent"),
        ]
        return _base_state(
            hero=_base_hero(hp=20, weapon=_make_weapon(attack=3, health=2)),
            mana=_base_mana(10),
            board=board, hand=hand, deck_remaining=25,
            opponent_hero=_base_hero(hp=25),
            opponent_board=opp_board, opponent_class="WARRIOR",
        )

    def test_max_actions_single_turn(self, state):
        # 1. enumerate_legal_actions returns many actions
        actions = enumerate_legal_actions(state)
        print(f"[T01] legal_actions count: {len(actions)}")
        # 7 minions × targets (2 enemies + face = 3 each if no taunt block)
        # With taunt, minions can only target taunt minions + face
        # + 2 PLAY + HERO_POWER + END_TURN
        assert len(actions) >= 10, f"Expected 10+ actions, got {len(actions)}"

        # 2. Engine search completes within time_limit
        engine = RHEAEngine(pop_size=30, max_gens=80, time_limit=250.0)
        result = engine.search(state)
        assert result is not None, "Engine returned None"
        print(f"[T01] best_fitness={result.best_fitness}")

        # 3. Result has multiple actions
        assert len(result.best_chromosome) >= 1, "Chromosome empty"

        # 4. best_fitness is finite
        assert math.isfinite(result.best_fitness), \
            f"Non-finite fitness: {result.best_fitness}"

        # 5. normalize_chromosome doesn't crash
        normalized = normalize_chromosome(result.best_chromosome, state)
        print(f"[T01] normalized chromosome length: {len(normalized)}")
        assert normalized is not None


# ===========================================================================
# Test 2: Cascading deaths — AoE kills many minions
# ===========================================================================

class Test02CascadingDeaths5MinionsDie:
    """AoE spell causes 5+ deaths on both sides. Death cleanup chain. Turn 7."""

    @pytest.fixture
    def state(self):
        board = [
            _make_minion("F1", 2, 1, can_attack=True),
            _make_minion("F2", 2, 1, can_attack=True),
            _make_minion("F3", 3, 2, can_attack=True),
            _make_minion("F4", 4, 1, can_attack=True),
            _make_minion("F5", 1, 1, can_attack=True),
            _make_minion("F6", 2, 2, can_attack=True),
        ]
        hand = [
            _make_card("AoE", 4, card_type="SPELL",
                       text="对所有 随从造成 2 点伤害"),
        ]
        opp_board = [
            _make_minion("E1", 3, 1, owner="opponent"),
            _make_minion("E2", 3, 1, owner="opponent"),
            _make_minion("E3", 2, 2, owner="opponent"),
        ]
        return _base_state(
            hero=_base_hero(hp=15),
            mana=_base_mana(7),
            board=board, hand=hand, deck_remaining=20,
            opponent_hero=_base_hero(hp=20),
            opponent_board=opp_board, opponent_class="MAGE",
        )

    def test_cascading_deaths(self, state):
        aoe_card = state.hand[0]

        # resolve_effects AoE: hardcoded side='enemy' — only hits enemy board
        state_after = state.copy()
        state_after = resolve_effects(state_after, aoe_card)

        enemy_after = len(state_after.opponent.board)
        print(f"[T02] After enemy AoE: enemy board 3 → {enemy_after}")
        # Enemy: 3/1×2 die (HP 1-2=-1), 2/2 dies (HP 2-2=0, _resolve_deaths removes health<=0)
        assert enemy_after == 0, \
            f"Expected 0 enemy minions after AoE, got {enemy_after}"

        # Friendly-fire AoE via EffectApplier directly
        # NOTE: apply_aoe does NOT call _resolve_deaths; must do it manually
        from hs_analysis.utils.spell_simulator import _resolve_deaths
        state_friendly = state.copy()
        EffectApplier.apply_aoe(state_friendly, 2, side="friendly")
        _resolve_deaths(state_friendly)
        friendly_after = len(state_friendly.board)
        print(f"[T02] After friendly AoE: friendly board 6 → {friendly_after}")
        # All die: 2/1→-1, 2/1→-1, 3/2→0, 4/1→-1, 1/1→-1, 2/2→0
        assert friendly_after == 0, \
            f"Expected 0 friendly minions, got {friendly_after}"

        # Engine search still works after AoE state
        engine = RHEAEngine(pop_size=30, max_gens=80, time_limit=250.0)
        result = engine.search(state_after)
        assert result is not None, "Engine failed on post-AoE state"
        assert math.isfinite(result.best_fitness)

        # evaluate on post-AoE state is finite
        score_before = evaluate(state)
        score_after = evaluate(state_after)
        print(f"[T02] score before={score_before:.2f}, after_enemy_aoe={score_after:.2f}")
        assert math.isfinite(score_before) and math.isfinite(score_after)


# ===========================================================================
# Test 3: Lethal with 5 sources — exact damage
# ===========================================================================

class Test03LethalWith5SourcesT8:
    """5 different damage sources combine for exact lethal (17 damage). Turn 8."""

    @pytest.fixture
    def state(self):
        board = [
            _make_minion("A1", 3, 3, can_attack=True),
            _make_minion("A2", 4, 2, can_attack=True),
            _make_minion("A3", 2, 1, can_attack=True),
        ]
        hand = [
            _make_card("Dmg5", 4, card_type="SPELL", text="造成 5 点伤害"),
            _make_card("Dmg3", 2, card_type="SPELL", text="造成 3 点伤害"),
        ]
        return _base_state(
            hero=_base_hero(hp=20),
            mana=_base_mana(8),
            board=board, hand=hand, deck_remaining=20,
            opponent_hero=_base_hero(hp=17),
            opponent_board=[], opponent_class="MAGE",
        )

    def test_lethal_5_sources(self, state):
        # 1. max_damage_bound >= 17 (board 3+4+2=9 + spells 5+3=8)
        bound = max_damage_bound(state)
        print(f"[T03] max_damage_bound={bound}")
        assert bound >= 17, f"Expected bound >= 17, got {bound}"

        # 2. check_lethal finds lethal path
        lethal = check_lethal(state)
        assert lethal is not None, "check_lethal did not find lethal path"
        print(f"[T03] lethal path length={len(lethal)}, actions: {[a.action_type for a in lethal]}")

        # 3. Engine search: best_fitness == 10000.0
        engine = RHEAEngine(pop_size=30, max_gens=80, time_limit=250.0)
        result = engine.search(state)
        assert result is not None
        print(f"[T03] engine best_fitness={result.best_fitness}")
        assert result.best_fitness == 10000.0, \
            f"Expected lethal fitness 10000.0, got {result.best_fitness}"

        # 4. Result includes ATTACK + PLAY actions
        has_attack = any(a.action_type == "ATTACK" for a in result.best_chromosome)
        has_play = any(a.action_type == "PLAY" for a in result.best_chromosome)
        assert has_attack, "Lethal path missing ATTACK actions"
        assert has_play, "Lethal path missing PLAY spell actions"

        # 5. At least 3 actions used
        assert len(result.best_chromosome) >= 3, \
            f"Expected 3+ actions in lethal path, got {len(result.best_chromosome)}"


# ===========================================================================
# Test 4: Weapon break mid-combo
# ===========================================================================

class Test04WeaponBreakMidCombo:
    """Weapon breaks during attack sequence. Engine must handle gracefully. Turn 6."""

    @pytest.fixture
    def state(self):
        board = [
            _make_minion("B1", 4, 4, can_attack=True),
            _make_minion("B2", 3, 3, can_attack=True),
        ]
        hand = [
            _make_card("Minion1", 3, card_type="MINION", attack=3, health=3),
            _make_card("Spell1", 2, card_type="SPELL", text="造成 2 点伤害"),
        ]
        opp_board = [
            _make_minion("Taunt", 2, 2, has_taunt=True, owner="opponent"),
            _make_minion("Big", 5, 5, owner="opponent"),
            _make_minion("Med", 3, 3, owner="opponent"),
        ]
        return _base_state(
            hero=_base_hero(hp=22, weapon=_make_weapon(attack=2, health=1)),
            mana=_base_mana(6),
            board=board, hand=hand, deck_remaining=20,
            opponent_hero=_base_hero(hp=20),
            opponent_board=opp_board, opponent_class="WARRIOR",
        )

    def test_weapon_break_mid_combo(self, state):
        # 1. Weapon attack on taunt — durability goes to 0, weapon breaks
        weapon_atk = Action(
            action_type="ATTACK", source_index=-1,
            target_index=1,  # first enemy minion = taunt (1-indexed)
        )
        s2 = apply_action(state, weapon_atk)

        taunt_died = all(m.name != "Taunt" for m in s2.opponent.board)
        print(f"[T04] taunt_died={taunt_died}, weapon={s2.hero.weapon}")
        assert s2.hero.weapon is None, f"Weapon should be None after break, got {s2.hero.weapon}"
        assert taunt_died, "Taunt should have died from weapon attack"

        # 2. After weapon breaks, hero.weapon is None
        assert s2.hero.weapon is None

        # 3. enumerate_legal_actions on post-break state still has minion ATTACKs
        actions_post = enumerate_legal_actions(s2)
        attack_actions = [a for a in actions_post if a.action_type == "ATTACK"]
        print(f"[T04] post-break ATTACK actions: {len(attack_actions)}")
        assert len(attack_actions) >= 2, \
            f"Expected 2+ minion attacks, got {len(attack_actions)}"

        # 4. Engine search handles weapon break mid-sequence
        engine = RHEAEngine(pop_size=30, max_gens=80, time_limit=250.0)
        result = engine.search(state)
        assert result is not None, "Engine crashed with weapon break scenario"
        assert math.isfinite(result.best_fitness)

        # 5. get_total_attack after weapon break excludes weapon
        total_atk = s2.get_total_attack()
        print(f"[T04] total_attack after weapon break={total_atk}")
        assert total_atk >= 0


# ===========================================================================
# Test 5: Draw into fatigue boundary
# ===========================================================================

class Test05DrawIntoFatigueBoundary:
    """Draw last cards from deck, approaching fatigue. Turn 10."""

    @pytest.fixture
    def state(self):
        board = [_make_minion("B1", 5, 5)]
        hand = [
            _make_card("Draw3", 2, card_type="SPELL", text="抽 3 张牌"),
        ]
        opp_board = [
            _make_minion("O1", 4, 4, owner="opponent"),
            _make_minion("O2", 3, 3, owner="opponent"),
        ]
        return _base_state(
            hero=_base_hero(hp=12),
            mana=_base_mana(10),
            board=board, hand=hand, deck_remaining=2,
            opponent_hero=_base_hero(hp=18),
            opponent_board=opp_board, opponent_class="WARLOCK",
        )

    def test_draw_fatigue_boundary(self, state):
        # 1. resolve_effects(draw 3): hand grows, deck_remaining drops
        draw_card = state.hand[0]
        s2 = state.copy()
        s2 = resolve_effects(s2, draw_card)

        print(f"[T05] deck_remaining: {state.deck_remaining} → {s2.deck_remaining}")
        print(f"[T05] hand size: {len(state.hand)} → {len(s2.hand)}")
        assert s2.deck_remaining <= state.deck_remaining, \
            "deck_remaining should decrease after draw"

        # 2. deck_remaining hits 0 or negative
        assert s2.deck_remaining <= 0, \
            f"deck_remaining should be <=0, got {s2.deck_remaining}"

        # 3. Engine search still returns valid result with depleted deck
        engine = RHEAEngine(pop_size=30, max_gens=80, time_limit=250.0)
        result = engine.search(s2)
        assert result is not None, "Engine failed with depleted deck"
        assert math.isfinite(result.best_fitness)

        # 4. FEATURE_GAP: fatigue_damage not incremented when drawing beyond deck
        print(f"[T05] fatigue_damage before={state.fatigue_damage}, "
              f"after={s2.fatigue_damage}")
        assert s2.fatigue_damage == 0, \
            "FEATURE_GAP: fatigue should trigger but doesn't"

        # 5. evaluate handles 0 deck cards
        score = evaluate(s2)
        print(f"[T05] evaluate with 0 deck={score:.2f}")
        assert math.isfinite(score)


# ===========================================================================
# Test 6: Taunt death unlocks face — multi-step lethal
# ===========================================================================

class Test06TauntDeathUnlocksFaceT7:
    """Kill only taunt with spell → minions go face for lethal. Turn 7."""

    @pytest.fixture
    def state(self):
        board = [
            _make_minion("A1", 5, 5, can_attack=True),
            _make_minion("A2", 4, 4, can_attack=True),
            _make_minion("A3", 3, 3, can_attack=True),
        ]
        hand = [
            _make_card("KillSpell", 3, card_type="SPELL", text="造成 4 点伤害"),
        ]
        opp_board = [
            _make_minion("Wall", 1, 4, has_taunt=True, owner="opponent"),
        ]
        return _base_state(
            hero=_base_hero(hp=15),
            mana=_base_mana(7),
            board=board, hand=hand, deck_remaining=20,
            opponent_hero=_base_hero(hp=12),
            opponent_board=opp_board, opponent_class="WARRIOR",
        )

    def test_taunt_death_unlocks_face(self, state):
        # 1. max_damage_bound: 5+4+3+4(spell) = 16 ≥ 12
        bound = max_damage_bound(state)
        print(f"[T06] max_damage_bound={bound}")
        assert bound >= 12, f"Expected bound >= 12, got {bound}"

        # 2. check_lethal finds path through taunt
        lethal = check_lethal(state)
        assert lethal is not None, "check_lethal should find path through taunt"
        print(f"[T06] lethal path: {[(a.action_type, a.target_index) for a in lethal]}")

        # 3. Engine search: best_fitness == 10000.0
        engine = RHEAEngine(pop_size=30, max_gens=80, time_limit=250.0)
        result = engine.search(state)
        assert result is not None
        print(f"[T06] engine best_fitness={result.best_fitness}")
        assert result.best_fitness == 10000.0, \
            f"Expected lethal fitness 10000.0, got {result.best_fitness}"

        # 4. Result includes PLAY + ATTACK actions
        has_play = any(a.action_type == "PLAY" for a in result.best_chromosome)
        has_attack = any(a.action_type == "ATTACK" for a in result.best_chromosome)
        assert has_play, "Missing PLAY spell to kill taunt"
        assert has_attack, "Missing ATTACK actions to go face"

        # 5. Manual sequence: spell kills taunt (4 HP → 0) → minions go face
        # Taunt has 4 HP, spell does 4 → dead. Then 5+4+3=12 face damage = lethal
        s3 = state.copy()
        s3 = apply_action(s3, Action(action_type="PLAY", card_index=0, target_index=0))
        taunt_dead = len(s3.opponent.board) == 0
        print(f"[T06] taunt_dead after spell: {taunt_dead}")
        if taunt_dead:
            s3 = apply_action(s3, Action(action_type="ATTACK", source_index=0, target_index=0))
            s3 = apply_action(s3, Action(action_type="ATTACK", source_index=1, target_index=0))
            s3 = apply_action(s3, Action(action_type="ATTACK", source_index=2, target_index=0))
            print(f"[T06] opp HP after combo: {s3.opponent.hero.hp}")


# ===========================================================================
# Test 7: Chromosome normalization — complex commutative pairs
# ===========================================================================

class Test07ChromosomeNormalizationComplex:
    """Complex action sequences with many commutative pairs. Turn 6."""

    @pytest.fixture
    def state(self):
        board = [
            _make_minion("C1", 3, 3, can_attack=True),
            _make_minion("C2", 4, 4, can_attack=True),
            _make_minion("C3", 2, 2, can_attack=True),
        ]
        hand = [
            _make_card("Minion1", 2, card_type="MINION", attack=2, health=3),
            _make_card("Minion2", 3, card_type="MINION", attack=3, health=4),
        ]
        opp_board = [
            _make_minion("T1", 3, 3, owner="opponent"),
            _make_minion("T2", 2, 2, owner="opponent"),
        ]
        return _base_state(
            hero=_base_hero(hp=22),
            mana=_base_mana(6),
            board=board, hand=hand, deck_remaining=20,
            opponent_hero=_base_hero(hp=22),
            opponent_board=opp_board, opponent_class="HUNTER",
        )

    def test_chromosome_normalization(self, state):
        # 1. are_commutative: different source minions attacking face
        atk1 = Action(action_type="ATTACK", source_index=0, target_index=0)
        atk2 = Action(action_type="ATTACK", source_index=1, target_index=0)
        assert are_commutative(atk1, atk2, state), \
            "Different source minions attacking face should be commutative"

        # Same source → not commutative
        atk_dup_a = Action(action_type="ATTACK", source_index=0, target_index=1)
        atk_dup_b = Action(action_type="ATTACK", source_index=0, target_index=2)
        assert not are_commutative(atk_dup_a, atk_dup_b, state), \
            "Same source attacking different targets: not commutative"

        # 2. normalize_chromosome produces consistent ordering
        chrom_a = [atk1, atk2]
        chrom_b = [atk2, atk1]
        norm_a = normalize_chromosome(chrom_a, state)
        norm_b = normalize_chromosome(chrom_b, state)
        print(f"[T07] norm_a hashes: {[action_hash(a) for a in norm_a]}")
        print(f"[T07] norm_b hashes: {[action_hash(a) for a in norm_b]}")
        assert [action_hash(a) for a in norm_a] == [action_hash(a) for a in norm_b], \
            "Normalized chromosomes should be identical for commutative pairs"

        # 3. action_hash produces deterministic tuples
        h1 = action_hash(atk1)
        h2 = action_hash(atk2)
        assert isinstance(h1, tuple), f"action_hash should return tuple, got {type(h1)}"
        assert h1 != h2, "Different actions should have different hashes"
        assert action_hash(atk1) == action_hash(atk1), "action_hash not deterministic"

        # 4. Engine search result's chromosome is valid
        engine = RHEAEngine(pop_size=30, max_gens=80, time_limit=250.0)
        result = engine.search(state)
        assert result is not None
        print(f"[T07] engine chromosome length={len(result.best_chromosome)}")
        for a in result.best_chromosome:
            assert a.action_type in ("ATTACK", "PLAY", "HERO_POWER", "END_TURN"), \
                f"Invalid action type: {a.action_type}"

        # 5. normalize_chromosome on engine result doesn't crash
        normalized = normalize_chromosome(result.best_chromosome, state)
        assert normalized is not None


# ===========================================================================
# Test 8: Opponent sim worst-case — we're vulnerable
# ===========================================================================

class Test08OpponentSimWorstCaseT8:
    """Opponent sim finds lethal on us. Should heavily penalize. Turn 8."""

    @pytest.fixture
    def state(self):
        board = [
            _make_minion("D1", 6, 6, can_attack=True),
            _make_minion("D2", 4, 4, can_attack=True),
            _make_minion("D3", 3, 3, can_attack=True),
        ]
        hand = [
            _make_card("BigMinion", 4, card_type="MINION", attack=5, health=5),
            _make_card("DmgSpell", 3, card_type="SPELL", text="造成 4 点伤害"),
        ]
        opp_board = [
            _make_minion("OA1", 4, 4, owner="opponent"),
            _make_minion("OA2", 3, 2, owner="opponent"),
        ]
        return _base_state(
            hero=_base_hero(hp=5),
            mana=_base_mana(8),
            board=board, hand=hand, deck_remaining=20,
            opponent_hero=_base_hero(hp=20),
            opponent_board=opp_board, opponent_class="HUNTER",
            opponent_hand_count=4,
        )

    def test_opponent_sim_worst_case(self, state):
        # 1. OpponentSimulator returns valid result
        opp_sim = OpponentSimulator()
        opp_result = opp_sim.simulate_best_response(state)
        assert opp_result is not None
        print(f"[T08] opp_sim: damage={opp_result.worst_case_damage}, "
              f"lethal_exposure={opp_result.lethal_exposure}")

        # 2. worst_case_damage >= 0
        assert opp_result.worst_case_damage >= 0, \
            f"worst_case_damage should be >=0, got {opp_result.worst_case_damage}"

        # 3. board_resilience_delta is a valid float
        assert math.isfinite(opp_result.board_resilience_delta), \
            f"Non-finite board_resilience_delta: {opp_result.board_resilience_delta}"

        # 4. RiskAssessor.survival_score for 5 HP is very low (≤0.3)
        risk_assessor = RiskAssessor()
        survival = risk_assessor.survival_score(state)
        print(f"[T08] survival_score for 5 HP: {survival}")
        assert survival <= 0.3, \
            f"Expected survival_score <= 0.3 for 5 HP, got {survival}"

        # 5. evaluate_delta_with_risk produces valid result
        s_after = state.copy()
        s_after = apply_action(s_after, Action(action_type="PLAY", card_index=1, target_index=0))

        risk_report = risk_assessor.assess(s_after)
        delta_no_risk = evaluate_delta(state, s_after)
        delta_with_risk = evaluate_delta_with_risk(state, s_after, risk_report=risk_report)
        print(f"[T08] delta_no_risk={delta_no_risk:.2f}, "
              f"delta_with_risk={delta_with_risk:.2f}")
        assert math.isfinite(delta_no_risk) and math.isfinite(delta_with_risk)


# ===========================================================================
# Test 9: Spell buff chain — stacking buffs on same minion
# ===========================================================================

class Test09SpellBuffChainT5:
    """Multiple buff effects stacking on same minion. Turn 5."""

    @pytest.fixture
    def state(self):
        board = [
            _make_minion("BufTarget", 2, 2, can_attack=True),
        ]
        hand = [
            _make_card("Buff1", 1, card_type="SPELL", text="+2 攻击力"),
            _make_card("Buff2", 1, card_type="SPELL", text="+3 攻击力"),
            _make_card("NewMinion", 3, card_type="MINION", attack=4, health=4),
        ]
        opp_board = [
            _make_minion("BigOpp", 5, 5, owner="opponent"),
        ]
        return _base_state(
            hero=_base_hero(hp=25),
            mana=_base_mana(5),
            board=board, hand=hand, deck_remaining=20,
            opponent_hero=_base_hero(hp=25),
            opponent_board=opp_board, opponent_class="PALADIN",
        )

    def test_spell_buff_chain(self, state):
        # FEATURE_GAP: buff_atk in resolve_effects applies to ALL friendly minions

        # 1. First buff: +2 attack → minion attack increases by 2
        # FEATURE_GAP: buff_atk applies to ALL friendly minions, not single target
        s2 = state.copy()
        s2 = resolve_effects(s2, state.hand[0])
        assert len(s2.board) >= 1, "Board should still have minion"
        print(f"[T09] After buff +2: attack={s2.board[0].attack} (was 2)")
        assert s2.board[0].attack >= 4, \
            f"Expected attack >= 4 after +2 buff, got {s2.board[0].attack}"

        # 2. Second buff: +3 attack → minion attack increases further
        s3 = s2.copy()
        s3 = resolve_effects(s3, state.hand[1])
        print(f"[T09] After buff +3: attack={s3.board[0].attack}")
        assert s3.board[0].attack >= 7, \
            f"Expected attack >= 7 after +2+3 buffs, got {s3.board[0].attack}"

        # 3. After buff stack, attack the 5/5 opponent minion
        s4 = s3.copy()
        atk_action = Action(action_type="ATTACK", source_index=0, target_index=1)
        s4 = apply_action(s4, atk_action)

        opp_alive = len(s4.opponent.board)
        print(f"[T09] After trade: opp_board size={opp_alive}, "
              f"friendly_board size={len(s4.board)}")

        # Opponent minion dies (5 HP - 7 atk = -2)
        assert opp_alive == 0, "Opponent minion should die from buffed hit"

        # 4. Our minion also dies (2 HP - 5 counter-attack = -3)
        if len(s4.board) == 0:
            print("[T09] Buffed minion dies in trade (2 HP < 5 atk) — expected")
        else:
            print("[T09] Buffed minion survived trade")

        # 5. Engine explores buff-then-trade vs direct play
        engine = RHEAEngine(pop_size=30, max_gens=80, time_limit=250.0)
        result = engine.search(state)
        assert result is not None
        assert math.isfinite(result.best_fitness)
        print(f"[T09] engine best_fitness={result.best_fitness}")


# ===========================================================================
# Test 10: Multi-objective conflict — tempo vs survival
# ===========================================================================

class Test10MultiObjectiveConflictT9:
    """Clear tension between tempo (lethal) and survival (low HP). Turn 9."""

    @pytest.fixture
    def state(self):
        board = [
            _make_minion("X1", 5, 5, can_attack=True),
            _make_minion("X2", 3, 3, can_attack=True),
        ]
        hand = [
            _make_card("Heal", 2, card_type="SPELL", text="恢复 8 点生命值"),
            _make_card("TauntMinion", 3, card_type="MINION",
                       attack=1, health=8, mechanics=["TAUNT"]),
            _make_card("Burst", 4, card_type="SPELL", text="造成 6 点伤害"),
            _make_card("BigMinion", 5, card_type="MINION", attack=7, health=7),
        ]
        opp_board = [
            _make_minion("Y1", 6, 6, owner="opponent"),
            _make_minion("Y2", 4, 3, owner="opponent"),
        ]
        return _base_state(
            hero=_base_hero(hp=7, weapon=_make_weapon(attack=4, health=1)),
            mana=_base_mana(9),
            board=board, hand=hand, deck_remaining=20,
            opponent_hero=_base_hero(hp=8),
            opponent_board=opp_board, opponent_class="HUNTER",
        )

    def test_multi_objective_conflict(self, state):
        # 1. max_damage_bound >= 8 (5+3 board + 4 weapon + 6 spell = 18)
        bound = max_damage_bound(state)
        print(f"[T10] max_damage_bound={bound}")
        assert bound >= 8, f"Expected bound >= 8, got {bound}"

        # 2. check_lethal finds lethal path (board 5+3=8 vs 8 HP)
        lethal = check_lethal(state)
        assert lethal is not None, "check_lethal should find lethal (8+ damage vs 8 HP)"
        print(f"[T10] lethal path: {[(a.action_type, a.target_index) for a in lethal]}")

        # 3. mo_evaluate: v_survival for 7 HP is low
        mo_result = mo_evaluate(state)
        print(f"[T10] mo_evaluate: tempo={mo_result.v_tempo:.3f}, "
              f"value={mo_result.v_value:.3f}, survival={mo_result.v_survival:.3f}")
        assert mo_result.v_survival < 0.5, \
            f"v_survival should be low for 7 HP, got {mo_result.v_survival}"

        # 4. mo_evaluate_delta shows trade-off after lethal play
        s_lethal = state.copy()
        for i in range(len(s_lethal.board)):
            if s_lethal.board[i].can_attack:
                # Opponent has no taunts, so face (target_index=0) is open
                s_lethal = apply_action(
                    s_lethal,
                    Action(action_type="ATTACK", source_index=i, target_index=0),
                )
        mo_after = mo_evaluate(s_lethal)
        print(f"[T10] After attacks: tempo={mo_after.v_tempo:.3f}, "
              f"survival={mo_after.v_survival:.3f}")

        # 5. Engine search: if lethal found, fitness=10000 (lethal prioritized)
        engine = RHEAEngine(pop_size=30, max_gens=80, time_limit=250.0)
        result = engine.search(state)
        assert result is not None
        print(f"[T10] engine best_fitness={result.best_fitness}")
        assert result.best_fitness == 10000.0, \
            f"Expected lethal fitness 10000.0, got {result.best_fitness}"

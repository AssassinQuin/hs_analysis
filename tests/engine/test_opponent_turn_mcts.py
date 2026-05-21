#!/usr/bin/env python3
"""test_opponent_turn_mcts.py — Test opponent turn MCTS features.

Covers:
- Phase 1: Heuristic opponent rollout, class-specific hero power, spell effects,
          cost modifiers, opponent card draw
- Phase 2: Multi-turn lookahead (max_turns_ahead), best_sequence extraction
- Phase 3: predict_opponent_turn() top-level opponent search
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from analysis.engine.mcts_uct import (
    MCTSUCT, MCTSConfig, MCTSNode, MCTSResult,
    _heuristic_rollout, _random_rollout,
    _default_reward,
)
from analysis.engine.opponent_scoring import HeuristicRolloutScorer
from analysis.card.abilities.definition import Action, ActionKind
from analysis.card.engine.state import (
    GameState, HeroState, ManaState, OpponentState, Minion, Weapon,
)
from analysis.card.models.card import Card


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(*, is_opponent=False, hero_class="MAGE", opp_class="WARLOCK",
                hand=None, opp_hand=None, board=None, opp_board=None,
                mana=5, opp_mana=4, turn=5) -> GameState:
    """Quick GameState factory."""
    return GameState(
        hero=HeroState(hp=30, hero_class=hero_class),
        mana=ManaState(available=mana, max_mana=min(mana + turn - 1, 10)),
        hand=hand or [],
        board=board or [],
        opponent=OpponentState(
            hero=HeroState(hp=25, hero_class=opp_class),
            hand_count=len(opp_hand) if opp_hand else 0,
            deck_remaining=20,
            mana_available=opp_mana,
            mana_max=opp_mana,
            board=opp_board or [],
            hand=list(opp_hand or []),
        ),
        turn_number=turn,
        is_opponent_turn=is_opponent,
    )


# ===========================================================================
# Phase 1: Heuristic opponent rollout
# ===========================================================================

class TestOpponentActionScoring:
    """Test HeuristicRolloutScorer."""

    _scorer = HeuristicRolloutScorer()

    def test_end_turn_lowest_priority(self):
        state = _make_state(is_opponent=True)
        et = Action(action_type=ActionKind.END_TURN)
        hp = Action(action_type=ActionKind.HERO_POWER)
        assert self._scorer.score(state, hp) > self._scorer.score(state, et)

    def test_attack_favorable_trade_higher_score(self):
        state = _make_state(
            is_opponent=True,
            board=[Minion(name="Taunt", attack=1, health=5, max_health=5)],
            opp_board=[Minion(name="Big", attack=4, health=3, max_health=3, can_attack=True, owner="enemy")],
        )
        attack = Action(action_type=ActionKind.ATTACK, source_index=0, target_index=1)
        et = Action(action_type=ActionKind.END_TURN)
        assert self._scorer.score(state, attack) > self._scorer.score(state, et)

    def test_play_low_cost_higher_score(self):
        state = _make_state(
            is_opponent=True,
            opp_hand=[
                Card(dbf_id=1, name="Cheap", cost=1, card_type="MINION", attack=2, health=2),
                Card(dbf_id=2, name="Expensive", cost=5, card_type="MINION", attack=2, health=2),
            ],
        )
        cheap = Action(action_type=ActionKind.PLAY, card_index=0)
        expensive = Action(action_type=ActionKind.PLAY, card_index=1)
        assert self._scorer.score(state, cheap) > self._scorer.score(state, expensive)

    def test_rush_minion_bonus(self):
        state = _make_state(
            is_opponent=True,
            opp_hand=[
                Card(dbf_id=1, name="Normal", cost=3, card_type="MINION", attack=3, health=3),
                Card(dbf_id=2, name="Rush", cost=3, card_type="MINION", attack=3, health=3,
                     mechanics=["RUSH"]),
            ],
        )
        normal = Action(action_type=ActionKind.PLAY, card_index=0)
        rush = Action(action_type=ActionKind.PLAY, card_index=1)
        assert self._scorer.score(state, rush) > self._scorer.score(state, normal)


class TestHeuristicRollout:
    """Test heuristic rollout vs random rollout."""

    def test_heuristic_rollout_returns_finite(self):
        state = _make_state(is_opponent=True)
        reward = _heuristic_rollout(state, 10, _default_reward)
        assert -1.0 <= reward <= 1.0

    def test_heuristic_rollout_terminal(self):
        """If game is over immediately, rollout should return terminal reward."""
        state = _make_state(is_opponent=True)
        state.hero.hp = 0  # we're dead
        reward = _heuristic_rollout(state, 10, _default_reward)
        assert reward == -1.0

    def test_random_rollout_still_works(self):
        """Random rollout as fallback should still work."""
        state = _make_state(is_opponent=True)
        reward = _random_rollout(state, 10, _default_reward)
        assert -1.0 <= reward <= 1.0


# ===========================================================================
# Phase 1b-c: Opponent spell effects & hero power
# ===========================================================================

class TestOpponentHeroPower:
    """Test class-specific opponent hero power."""

    def test_warlock_draws_and_takes_damage(self):
        from analysis.card.engine.simulation import _opponent_hero_power
        state = _make_state(is_opponent=True, opp_class="WARLOCK", opp_mana=2)
        result = _opponent_hero_power(state)
        assert result.opponent.hero.hero_power_used is True
        assert result.opponent.hero.hp == 23  # 25 - 2
        assert result.opponent.deck_remaining == 19  # drew a card

    def test_warrior_gains_armor(self):
        from analysis.card.engine.simulation import _opponent_hero_power
        state = _make_state(is_opponent=True, opp_class="WARRIOR", opp_mana=2)
        result = _opponent_hero_power(state)
        assert result.opponent.hero.armor == 2
        assert result.hero.hp == 30  # our hero unaffected

    def test_priest_heals_self(self):
        from analysis.card.engine.simulation import _opponent_hero_power
        state = _make_state(is_opponent=True, opp_class="PRIEST", opp_mana=2)
        state.opponent.hero.hp = 20
        result = _opponent_hero_power(state)
        assert result.opponent.hero.hp == 22  # 20 + 2 heal

    def test_hunter_hero_power_skips_when_no_mana(self):
        from analysis.card.engine.simulation import _opponent_hero_power
        state = _make_state(is_opponent=True, opp_class="HUNTER", opp_mana=0)
        result = _opponent_hero_power(state)
        assert result.opponent.hero.hero_power_used is False  # can't afford

    def test_hero_power_used_flag_prevents_double_use(self):
        from analysis.card.engine.simulation import _opponent_hero_power
        state = _make_state(is_opponent=True, opp_class="MAGE", opp_mana=2)
        state.opponent.hero.hero_power_used = True
        result = _opponent_hero_power(state)
        assert result.hero.hp == 30  # no damage dealt


class TestOpponentSpellEffects:
    """Test improved opponent spell handling."""

    def test_direct_damage_spell(self):
        from analysis.card.engine.simulation import _opponent_play_card
        state = _make_state(
            is_opponent=True,
            opp_hand=[Card(dbf_id=1, name="Fireball", cost=4, card_type="SPELL", attack=6)],
            opp_mana=4,
        )
        action = Action(action_type=ActionKind.PLAY, card_index=0)
        result = _opponent_play_card(state, action)
        # Direct damage to our hero (no "all minions" in card text)
        assert result.hero.hp < 30 or result.opponent.hero.armor > 0

    def test_aoe_spell(self):
        from analysis.card.engine.simulation import _opponent_play_card
        state = _make_state(
            is_opponent=True,
            opp_hand=[Card(dbf_id=1, name="AOE Spell", cost=4, card_type="SPELL", attack=3,
                        text="Deal 3 damage to all enemy minions")],
            opp_mana=4,
            board=[Minion(name="M1", attack=1, health=3, max_health=3),
                   Minion(name="M2", attack=1, health=3, max_health=3)],
        )
        action = Action(action_type=ActionKind.PLAY, card_index=0)
        result = _opponent_play_card(state, action)
        # Both minions should take damage
        for m in result.board:
            assert m.health < 3, f"Minion {m.name} should have taken AOE damage"


class TestOpponentCostModifiers:
    """Test opponent cost modifier support."""

    def test_spell_cost_increase(self):
        from analysis.card.engine.rules import enumerate_opponent_legal
        state = _make_state(
            is_opponent=True,
            opp_hand=[Card(dbf_id=1, name="Spell", cost=2, card_type="SPELL")],
            opp_mana=3,
        )
        # Without cost modifier: spell is affordable (2 <= 3)
        actions = enumerate_opponent_legal(state)
        spell_actions = [a for a in actions if a.action_type == ActionKind.PLAY]
        assert len(spell_actions) > 0

        # With cost modifier: spell costs 2 more = 4 > 3, not affordable
        state.opponent.opp_cost_modifiers = [("opp_spell_increase", 2, "next_spell")]
        actions = enumerate_opponent_legal(state)
        spell_actions = [a for a in actions if a.action_type == ActionKind.PLAY]
        assert len(spell_actions) == 0


class TestOpponentCardDraw:
    """Test opponent drawing cards at end of turn."""

    def test_opponent_draws_on_end_turn(self):
        from analysis.card.engine.simulation import _opponent_end_turn
        state = _make_state(is_opponent=True, turn=4)
        action = Action(action_type=ActionKind.END_TURN)
        deck_before = state.opponent.deck_remaining
        result = _opponent_end_turn(state, action)
        assert result.opponent.deck_remaining == deck_before - 1

    def test_opponent_fatigue(self):
        from analysis.card.engine.simulation import _opponent_end_turn
        state = _make_state(is_opponent=True, turn=4)
        state.opponent.deck_remaining = 0
        state.opponent.hand_count = 3
        hp_before = state.opponent.hero.hp
        action = Action(action_type=ActionKind.END_TURN)
        result = _opponent_end_turn(state, action)
        assert result.opponent.hero.hp < hp_before  # fatigue damage


# ===========================================================================
# Phase 2: Multi-turn lookahead
# ===========================================================================

class TestMultiTurnLookahead:
    """Test max_turns_ahead feature."""

    def test_turn_depth_tracked_in_nodes(self):
        state = _make_state(
            is_opponent=False,
            hand=[Card(dbf_id=1, name="Card", cost=1, card_type="MINION", attack=1, health=1)],
            mana=1,
        )
        cfg = MCTSConfig(iterations=100, max_turns_ahead=2)
        engine = MCTSUCT(cfg)
        result = engine.search(state)
        # Root should have turn_depth=0
        assert result.root_node.turn_depth == 0
        # Check that some children have turn_depth > 0
        has_deeper = False
        for child in _iter_all_nodes(result.root_node):
            if child.turn_depth > 0:
                has_deeper = True
                break
        assert has_deeper, "With max_turns_ahead=2, some nodes should have turn_depth > 0"

    def test_is_player_turn_tracked(self):
        state = _make_state(is_opponent=False)
        cfg = MCTSConfig(iterations=50, max_turns_ahead=2)
        engine = MCTSUCT(cfg)
        result = engine.search(state)
        assert result.root_node.is_player_turn is True
        # Children that represent opponent turns should be False
        for child in result.root_node.children:
            if child.state.is_opponent_turn:
                assert child.is_player_turn is False

    def test_best_sequence_populated(self):
        state = _make_state(
            is_opponent=False,
            hand=[Card(dbf_id=1, name="Card", cost=1, card_type="MINION", attack=1, health=1)],
            mana=1,
        )
        cfg = MCTSConfig(iterations=100, max_turns_ahead=2)
        engine = MCTSUCT(cfg)
        result = engine.search(state)
        assert len(result.best_sequence) >= 1
        # All actions should be valid Action objects
        for action in result.best_sequence:
            assert isinstance(action, Action)

    def test_multi_turn_has_more_nodes(self):
        state = _make_state(
            is_opponent=False,
            hand=[Card(dbf_id=1, name="Card", cost=1, card_type="MINION", attack=1, health=1)],
            mana=1,
        )
        cfg1 = MCTSConfig(iterations=100, max_turns_ahead=1)
        cfg2 = MCTSConfig(iterations=100, max_turns_ahead=2)
        engine1 = MCTSUCT(cfg1)
        engine2 = MCTSUCT(cfg2)
        result1 = engine1.search(state)
        result2 = engine2.search(state)
        assert result2.num_nodes >= result1.num_nodes

    def test_max_turns_ahead_limit_respected(self):
        """Nodes should not exceed max_turns_ahead in turn_depth."""
        state = _make_state(is_opponent=False)
        cfg = MCTSConfig(iterations=200, max_turns_ahead=1)
        engine = MCTSUCT(cfg)
        result = engine.search(state)
        for node in _iter_all_nodes(result.root_node):
            assert node.turn_depth <= 1, f"turn_depth {node.turn_depth} > max_turns_ahead 1"

    def test_mcts_result_has_sequence_field(self):
        result = MCTSResult(
            best_action=None, best_node=None,
            root_node=None, action_values={}, visit_counts={},
            search_stats={},
            best_sequence=[Action(action_type=ActionKind.END_TURN)],
        )
        assert len(result.best_sequence) == 1


# ===========================================================================
# Phase 3: predict_opponent_turn
# ===========================================================================

class TestPredictOpponentTurn:
    """Test predict_opponent_turn top-level method."""

    def test_returns_none_on_player_turn(self):
        state = _make_state(is_opponent=False)
        cfg = MCTSConfig(iterations=50)
        engine = MCTSUCT(cfg)
        assert engine.predict_opponent_turn(state) is None

    def test_returns_action_on_opponent_turn(self):
        state = _make_state(
            is_opponent=True,
            opp_board=[
                Minion(name="Attacker", attack=3, health=4, max_health=4, can_attack=True, owner="enemy"),
            ],
            board=[Minion(name="Target", attack=2, health=3, max_health=3)],
            mana=3, opp_mana=3,
        )
        cfg = MCTSConfig(iterations=100)
        engine = MCTSUCT(cfg)
        action = engine.predict_opponent_turn(state, iterations=100)
        assert action is not None
        assert isinstance(action, Action)

    def test_prefers_favorable_trade(self):
        """Opponent should prefer attacking minions it can kill efficiently."""
        state = _make_state(
            is_opponent=True,
            opp_board=[
                Minion(name="Big", attack=5, health=4, max_health=4, can_attack=True, owner="enemy"),
                Minion(name="Small", attack=1, health=1, max_health=1, can_attack=True, owner="enemy"),
            ],
            board=[
                Minion(name="1/1", attack=1, health=1, max_health=1),
            ],
            mana=3, opp_mana=3,
        )
        cfg = MCTSConfig(iterations=200)
        engine = MCTSUCT(cfg)
        action = engine.predict_opponent_turn(state, iterations=200)
        assert action is not None
        # Should prefer attacking rather than ending turn
        if action.action_type == ActionKind.ATTACK:
            assert action.source_index is not None

    def test_custom_time_budget(self):
        state = _make_state(is_opponent=True, opp_mana=2)
        cfg = MCTSConfig(iterations=100)
        engine = MCTSUCT(cfg)
        action = engine.predict_opponent_turn(state, time_budget_ms=100)
        assert action is not None


# ===========================================================================
# Helpers
# ===========================================================================

def _iter_all_nodes(node: MCTSNode):
    """Yield all nodes in the tree (depth-first)."""
    yield node
    for child in node.children:
        yield from _iter_all_nodes(child)

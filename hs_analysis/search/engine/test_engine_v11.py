"""V11 Engine tests — comprehensive coverage of all components."""

import pytest
from dataclasses import dataclass

from hs_analysis.search.game_state import GameState, Minion, HeroState, ManaState, OpponentState, Weapon
from hs_analysis.models.card import Card
from hs_analysis.search.rhea_engine import Action


# ===================================================================
# Fixtures
# ===================================================================

def _make_card(name="Test", cost=2, card_type="SPELL", attack=0, health=0,
               mechanics=None, text="", dbf_id=0, score=3.0):
    return Card(
        dbf_id=dbf_id or hash(name) % 10000,
        name=name, cost=cost, original_cost=cost,
        card_type=card_type, attack=attack, health=health,
        score=score, text=text, mechanics=mechanics or [],
    )


def _simple_state(hero_hp=30, mana=5, max_mana=5, board=None, hand=None,
                  opp_hp=30, opp_board=None, turn=5):
    return GameState(
        hero=HeroState(hp=hero_hp),
        mana=ManaState(available=mana, max_mana=max_mana),
        board=board or [],
        hand=hand or [],
        opponent=OpponentState(
            hero=HeroState(hp=opp_hp),
            board=opp_board or [],
        ),
        turn_number=turn,
    )


# ===================================================================
# MechanicRegistry tests
# ===================================================================


# ===================================================================
# FactorGraph tests
# ===================================================================

class TestFactorGraph:
    def test_empty_evaluator_returns_zero(self):
        from hs_analysis.search.engine.factors.factor_graph import FactorGraphEvaluator
        from hs_analysis.search.engine.factors.factor_base import EvalContext

        evaluator = FactorGraphEvaluator()
        state = _simple_state()
        ctx = EvalContext.from_state(state)
        scores = evaluator.evaluate(state, state, context=ctx)
        assert scores.total == 0.0

    def test_board_control_friendly_advantage(self):
        from hs_analysis.search.engine.factors.factor_graph import FactorGraphEvaluator
        from hs_analysis.search.engine.factors.board_control import BoardControlFactor
        from hs_analysis.search.engine.factors.factor_base import EvalContext

        evaluator = FactorGraphEvaluator()
        evaluator.register(BoardControlFactor())

        before = _simple_state()
        after = _simple_state(board=[Minion(name="Yeti", attack=4, health=5, max_health=5)])

        ctx = EvalContext.from_state(after)
        scores = evaluator.evaluate(before, after, context=ctx)
        assert scores.board_control > 0

    def test_lethal_threat_factor(self):
        from hs_analysis.search.engine.factors.lethal_threat import LethalThreatFactor
        from hs_analysis.search.engine.factors.factor_base import EvalContext

        factor = LethalThreatFactor()
        ctx = EvalContext(phase="mid", turn_number=5)

        before = _simple_state(opp_hp=10)
        after = _simple_state(opp_hp=0)
        score = factor.compute(before, after, None, ctx)
        assert score == 1.0

    def test_tempo_factor_positive_on_play(self):
        from hs_analysis.search.engine.factors.tempo import TempoFactor
        from hs_analysis.search.engine.factors.factor_base import EvalContext

        factor = TempoFactor()
        ctx = EvalContext(phase="mid", turn_number=5)

        before = _simple_state(mana=5, max_mana=5)
        after = _simple_state(mana=2, max_mana=5,
                              board=[Minion(name="Yeti", attack=4, health=5, cost=4)])
        score = factor.compute(before, after, None, ctx)
        assert score > 0

    def test_survival_factor_negative_on_damage(self):
        from hs_analysis.search.engine.factors.survival import SurvivalFactor
        from hs_analysis.search.engine.factors.factor_base import EvalContext

        factor = SurvivalFactor()
        ctx = EvalContext(phase="mid", turn_number=5)

        before = _simple_state(hero_hp=30)
        after = _simple_state(hero_hp=15)
        score = factor.compute(before, after, None, ctx)
        assert score < 0

    def test_all_factors_registered(self):
        from hs_analysis.search.engine.pipeline import _build_default_evaluator
        evaluator = _build_default_evaluator()
        names = evaluator.factor_names()
        assert "board_control" in names
        assert "lethal_threat" in names
        assert "tempo" in names
        assert "value" in names
        assert "survival" in names
        assert "resource_efficiency" in names
        assert "discover_ev" in names


# ===================================================================
# ActionPruner tests
# ===================================================================

class TestActionPruner:
    def test_prune_wastes_divine_shield(self):
        from hs_analysis.search.engine.action_pruner import ActionPruner

        pruner = ActionPruner()
        state = _simple_state(
            board=[Minion(name="Wisp", attack=1, health=1, max_health=1, can_attack=True)],
            opp_board=[Minion(name="Shielded", attack=3, health=3, max_health=3,
                              has_divine_shield=True)],
        )
        actions = [
            Action(action_type="ATTACK", source_index=0, target_index=1),
        ]
        pruned = pruner.prune(actions, state)
        assert len(pruned) == 0

    def test_prune_keeps_good_trade(self):
        from hs_analysis.search.engine.action_pruner import ActionPruner

        pruner = ActionPruner()
        state = _simple_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5, cost=4, can_attack=True)],
            opp_board=[Minion(name="Wisp", attack=1, health=1, max_health=1, cost=1)],
        )
        actions = [
            Action(action_type="ATTACK", source_index=0, target_index=1),
        ]
        pruned = pruner.prune(actions, state)
        assert len(pruned) == 1

    def test_prune_keeps_end_turn(self):
        from hs_analysis.search.engine.action_pruner import ActionPruner

        pruner = ActionPruner()
        state = _simple_state()
        actions = [Action(action_type="END_TURN")]
        pruned = pruner.prune(actions, state)
        assert any(a.action_type == "END_TURN" for a in pruned)

    def test_prune_full_board_minion(self):
        from hs_analysis.search.engine.action_pruner import ActionPruner

        pruner = ActionPruner()
        board = [Minion(name=f"M{i}", attack=1, health=1, max_health=1) for i in range(7)]
        state = _simple_state(
            board=board,
            hand=[_make_card("Extra", cost=1, card_type="MINION")],
        )
        actions = [Action(action_type="PLAY", card_index=0, position=0)]
        pruned = pruner.prune(actions, state)
        assert len(pruned) == 0


# ===================================================================
# AttackPlanner tests
# ===================================================================

class TestAttackPlanner:
    def test_plan_finds_lethal(self):
        from hs_analysis.search.engine.attack_planner import AttackPlanner

        state = _simple_state(
            opp_hp=3,
            board=[Minion(name="Charger", attack=3, health=1, max_health=1,
                          can_attack=True, has_charge=True)],
        )
        planner = AttackPlanner()
        plan = planner.plan(state)
        assert len(plan.attacks) >= 1
        assert plan.state_after is not None
        assert plan.state_after.is_lethal() or plan.score > 100

    def test_plan_picks_best_trade(self):
        from hs_analysis.search.engine.attack_planner import AttackPlanner

        state = _simple_state(
            board=[
                Minion(name="Big", attack=5, health=5, max_health=5, can_attack=True),
                Minion(name="Small", attack=2, health=2, max_health=2, can_attack=True),
            ],
            opp_board=[
                Minion(name="Target1", attack=1, health=4, max_health=4),
                Minion(name="Target2", attack=1, health=1, max_health=1),
            ],
        )
        planner = AttackPlanner()
        plan = planner.plan(state)
        assert len(plan.attacks) >= 1

    def test_plan_no_attackers_empty(self):
        from hs_analysis.search.engine.attack_planner import AttackPlanner

        state = _simple_state()
        planner = AttackPlanner()
        plan = planner.plan(state)
        assert len(plan.attacks) == 0


# ===================================================================
# Strategic layer tests
# ===================================================================

class TestStrategic:
    def test_lethal_mode(self):
        from hs_analysis.search.engine.strategic import strategic_decision

        state = _simple_state(
            opp_hp=0,
        )
        mode = strategic_decision(state)
        assert mode.mode == "LETHAL"

    def test_defensive_mode(self):
        from hs_analysis.search.engine.strategic import strategic_decision

        state = _simple_state(
            hero_hp=5,
            opp_board=[Minion(name="Big", attack=6, health=6, max_health=6, can_attack=True)],
        )
        mode = strategic_decision(state)
        assert mode.mode == "DEFENSIVE"

    def test_development_mode(self):
        from hs_analysis.search.engine.strategic import strategic_decision

        state = _simple_state(
            hero_hp=30,
            opp_hp=30,
        )
        mode = strategic_decision(state)
        assert mode.mode == "DEVELOPMENT"


# ===================================================================
# Probability Models tests
# ===================================================================

class TestDrawModel:
    def test_empty_deck_negative(self):
        from hs_analysis.search.engine.models.draw_model import DrawModel
        model = DrawModel()
        state = _simple_state()
        state.deck_remaining = 0
        ev = model.expected_draw_value(state)
        assert ev <= 0

    def test_deck_with_cards_positive(self):
        from hs_analysis.search.engine.models.draw_model import DrawModel
        model = DrawModel()
        state = _simple_state()
        state.deck_list = [_make_card("A", cost=3, score=4.0) for _ in range(5)]
        state.deck_remaining = 5
        ev = model.expected_draw_value(state, n_cards=1)
        assert ev > 0


class TestDiscoverModel:
    def test_empty_pool(self):
        from hs_analysis.search.engine.models.discover_model import DiscoverModel
        model = DiscoverModel()
        state = _simple_state()
        card, ev = model.best_discover([], state)
        assert card is None
        assert ev == 0.0

    def test_pool_picks_best(self):
        from hs_analysis.search.engine.models.discover_model import DiscoverModel
        model = DiscoverModel()
        state = _simple_state()
        pool = [
            _make_card("Bad", cost=1, score=1.0),
            _make_card("Good", cost=5, score=6.0),
            _make_card("Medium", cost=3, score=3.5),
            _make_card("Great", cost=7, score=8.0),
        ]
        card, ev = model.best_discover(pool, state, n_samples=30)
        assert ev > 0


class TestRNGModel:
    def test_fixed_damage(self):
        from hs_analysis.search.engine.models.rng_model import RNGModel
        model = RNGModel()
        state = _simple_state()
        ev = model.expected_value("damage 3", state)
        assert ev == 3.0

    def test_empty_effect(self):
        from hs_analysis.search.engine.models.rng_model import RNGModel
        model = RNGModel()
        state = _simple_state()
        ev = model.expected_value("", state)
        assert ev == 0.0


# ===================================================================
# DecisionPipeline integration tests
# ===================================================================

class TestDecisionPipeline:
    def test_simple_development(self):
        from hs_analysis.search.engine.pipeline import DecisionPipeline

        state = _simple_state(
            mana=5, max_mana=5, turn=5,
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5, can_attack=True)],
            hand=[_make_card("Fireball", cost=4, card_type="SPELL")],
            opp_board=[Minion(name="Wisp", attack=1, health=1, max_health=1)],
        )
        pipeline = DecisionPipeline()
        decision = pipeline.decide(state)
        assert decision.best_plan is not None
        assert len(decision.best_plan) >= 1
        assert decision.best_plan[-1].action_type == "END_TURN"
        assert decision.time_elapsed_ms >= 0
        assert decision.strategic_mode.mode in ("LETHAL", "DEFENSIVE", "DEVELOPMENT")

    def test_empty_board_hand(self):
        from hs_analysis.search.engine.pipeline import DecisionPipeline

        state = _simple_state(mana=0, max_mana=3)
        pipeline = DecisionPipeline()
        decision = pipeline.decide(state)
        assert len(decision.best_plan) >= 1
        assert decision.best_plan[-1].action_type == "END_TURN"

    def test_lethal_detection(self):
        from hs_analysis.search.engine.pipeline import DecisionPipeline

        state = _simple_state(
            opp_hp=2,
            board=[Minion(name="Charger", attack=3, health=1, max_health=1,
                          can_attack=True, has_charge=True)],
            mana=3, max_mana=5,
        )
        pipeline = DecisionPipeline()
        decision = pipeline.decide(state)
        assert decision.strategic_mode.mode == "LETHAL"
        assert decision.best_score >= 1000

    def test_factor_scores_populated(self):
        from hs_analysis.search.engine.pipeline import DecisionPipeline

        state = _simple_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5, can_attack=True)],
            hand=[_make_card("Bolt", cost=2)],
        )
        pipeline = DecisionPipeline()
        decision = pipeline.decide(state)
        scores = decision.factor_scores
        assert isinstance(scores.board_control, float)
        assert isinstance(scores.tempo, float)
        assert isinstance(scores.survival, float)
        assert isinstance(scores.total, float)

    def test_time_budget_reasonable(self):
        from hs_analysis.search.engine.pipeline import DecisionPipeline

        state = _simple_state(
            mana=7, max_mana=7,
            board=[Minion(name=f"M{i}", attack=3+i, health=3+i, max_health=3+i, can_attack=True)
                   for i in range(4)],
            hand=[_make_card(f"C{i}", cost=2+i) for i in range(4)],
            opp_board=[Minion(name=f"E{i}", attack=2, health=3, max_health=3) for i in range(3)],
        )
        pipeline = DecisionPipeline(time_budget_ms=100.0)
        decision = pipeline.decide(state)
        assert decision.time_elapsed_ms < 500  # generous budget

    def test_describe_output(self):
        from hs_analysis.search.engine.pipeline import DecisionPipeline

        state = _simple_state()
        pipeline = DecisionPipeline()
        decision = pipeline.decide(state)
        desc = decision.describe(state)
        assert "模式" in desc
        assert "置信度" in desc


# ===================================================================
# FactorScores tests
# ===================================================================

class TestFactorScores:
    def test_as_dict(self):
        from hs_analysis.search.engine.factors.factor_graph import FactorScores
        scores = FactorScores(board_control=0.5, tempo=-0.3, total=0.2)
        d = scores.as_dict()
        assert d["board_control"] == 0.5
        assert d["tempo"] == -0.3
        assert d["total"] == 0.2

    def test_describe_nonzero(self):
        from hs_analysis.search.engine.factors.factor_graph import FactorScores
        scores = FactorScores(board_control=0.5, tempo=-0.3)
        desc = scores.describe()
        assert "board_control" in desc
        assert "tempo" in desc


# ===================================================================
# EvalContext tests
# ===================================================================

class TestEvalContext:
    def test_from_state_early(self):
        from hs_analysis.search.engine.factors.factor_base import EvalContext
        state = _simple_state(turn=2)
        ctx = EvalContext.from_state(state)
        assert ctx.phase == "early"

    def test_from_state_mid(self):
        from hs_analysis.search.engine.factors.factor_base import EvalContext
        state = _simple_state(turn=6)
        ctx = EvalContext.from_state(state)
        assert ctx.phase == "mid"

    def test_from_state_late(self):
        from hs_analysis.search.engine.factors.factor_base import EvalContext
        state = _simple_state(turn=10)
        ctx = EvalContext.from_state(state)
        assert ctx.phase == "late"

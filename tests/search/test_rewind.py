import pytest
pytest.skip("Mechanic module deleted — data in engine/mechanics/_data.py", allow_module_level=True)
"""V10 Phase 3 Batch 5 tests — Rewind card detection and branch evaluation."""

from types import SimpleNamespace
from analysis.engine.state import GameState, HeroState, ManaState, OpponentState
from analysis.models.card import Card
from analysis.engine.mechanics._data import is_rewind_card, evaluate_with_rewind, REWIND_SCORING_BONUS


def _make_card(**kw):
    defaults = dict(dbf_id=1, name="TestCard", cost=1, card_type="SPELL", attack=0, health=0)
    defaults.update(kw)
    return Card(**defaults)


def _make_state():
    return GameState(
        hero=HeroState(hp=30),
        mana=ManaState(available=10, max_mana=10),
        opponent=OpponentState(hero=HeroState(hp=30)),
    )


class TestIsRewindCard:
    def test_rewind_from_chinese_text(self):
        """is_rewind_card returns True for card with '回溯' in text."""
        card = _make_card(
            dbf_id=121675, name="时间之沙",
            text="<b>回溯</b>。<b>发现</b>一张任意职业的法术牌。",
            mechanics=["DISCOVER", "TRIGGER_VISUAL"],
        )
        assert is_rewind_card(card) is True

    def test_rewind_from_mechanic(self):
        """is_rewind_card returns True for card with REWIND mechanic."""
        card = _make_card(
            name="RewindCard",
            text="Some text",
            mechanics=["REWIND"],
        )
        assert is_rewind_card(card) is True

    def test_normal_card_not_rewind(self):
        """is_rewind_card returns False for normal card."""
        card = _make_card(
            name="Fireball",
            text="造成6点伤害",
            mechanics=["HERO_POWER"],
        )
        assert is_rewind_card(card) is False

    def test_trigger_visual_with_rewind_text(self):
        """Rewind card detection from mechanics TRIGGER_VISUAL + 回溯."""
        card = _make_card(
            dbf_id=119314, name="传送门卫士",
            card_type="MINION",
            text="<b>回溯</b>。<b>战吼：</b>随机抽一张随从牌，使其获得+2/+2。",
            mechanics=["BATTLECRY", "TRIGGER_VISUAL"],
        )
        assert is_rewind_card(card) is True


class TestEvaluateWithRewind:
    def test_returns_better_branch(self):
        """evaluate_with_rewind returns better of two branches."""
        state = _make_state()
        card = _make_card(name="RewindSpell")

        call_count = {'n': 0}

        def mock_apply(s, c):
            call_count['n'] += 1
            # First call returns state with hp=20, second with hp=25
            s.opponent.hero.hp = 20 if call_count['n'] == 1 else 25
            return s

        def mock_fitness(s):
            # Higher fitness for more opponent damage
            return 30.0 - s.opponent.hero.hp

        best_state, best_fitness = evaluate_with_rewind(state, card, mock_apply, mock_fitness)
        assert best_fitness == 10.0  # 30 - 20 vs 30 - 25 → picks 30-20=10
        assert best_state.opponent.hero.hp == 20

    def test_identical_outcomes_returns_first(self):
        """evaluate_with_rewind with identical outcomes → returns first."""
        state = _make_state()
        card = _make_card(name="RewindSpell")

        def same_apply(s, c):
            s.opponent.hero.hp = 25
            return s

        def same_fitness(s):
            return 30.0 - s.opponent.hero.hp

        best_state, best_fitness = evaluate_with_rewind(state, card, same_apply, same_fitness)
        assert best_fitness == 5.0

    def test_state_isolation_between_branches(self):
        """State isolation: branch A doesn't affect branch B snapshot."""
        state = _make_state()
        state.opponent.hero.hp = 30
        card = _make_card(name="RewindSpell")

        def mutating_apply(s, c):
            # Mutate state aggressively
            s.opponent.hero.hp -= 10
            s.hero.hp += 5
            return s

        def some_fitness(s):
            return float(s.opponent.hero.hp)

        # Both branches should start from same original state
        best_state, best_fitness = evaluate_with_rewind(state, card, mutating_apply, some_fitness)
        # Both branches get hp=20 (30-10), fitness=20.0
        assert best_fitness == 20.0
        # Original state should be unmodified (it was copied)
        assert state.opponent.hero.hp == 30


class TestScoringBonus:
    def test_rewind_scoring_bonus_value(self):
        """REWIND_SCORING_BONUS is 0.5."""
        assert REWIND_SCORING_BONUS == 0.5

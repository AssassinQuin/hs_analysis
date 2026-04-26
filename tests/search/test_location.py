"""Tests for location card support (V10 Phase 2)."""

import pytest

from analysis.engine.state import GameState, HeroState, ManaState, Minion, OpponentState
from analysis.engine.mechanics.location import Location, activate_location, tick_location_cooldowns
from analysis.search.abilities import (
    Action,
    ActionType,
    enumerate_legal_actions,
    apply_action,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_state_with_location(
    durability: int = 3,
    cooldown_current: int = 0,
    cooldown_max: int = 2,
    text: str = "",
    english_text: str = "Deal 2 damage",
) -> GameState:
    """Build a GameState with one ready location."""
    loc = Location(
        dbf_id=90001,
        name="Test Location",
        cost=0,
        durability=durability,
        cooldown_current=cooldown_current,
        cooldown_max=cooldown_max,
        text=text,
        english_text=english_text,
    )
    return GameState(
        hero=HeroState(hp=30),
        mana=ManaState(available=5, max_mana=5),
        locations=[loc],
        opponent=OpponentState(hero=HeroState(hp=30)),
    )


# ------------------------------------------------------------------
# 1. Location dataclass
# ------------------------------------------------------------------

def test_location_dataclass():
    """Basic creation and field defaults."""
    loc = Location()
    assert loc.dbf_id == 0
    assert loc.name == ""
    assert loc.cost == 0
    assert loc.durability == 0
    assert loc.cooldown_current == 0
    assert loc.cooldown_max == 2
    assert loc.text == ""

    loc2 = Location(dbf_id=123, name="Foo", durability=3, cooldown_max=1)
    assert loc2.dbf_id == 123
    assert loc2.durability == 3
    assert loc2.cooldown_max == 1


# ------------------------------------------------------------------
# 2. activate_location — valid activation
# ------------------------------------------------------------------

def test_activate_location_valid():
    """Activating a ready location decreases durability and sets cooldown."""
    state = _make_state_with_location(durability=3, cooldown_current=0)
    result = activate_location(state.copy(), 0)

    assert result.locations[0].durability == 2
    assert result.locations[0].cooldown_current == 2  # set to cooldown_max
    # Original state unchanged
    assert state.locations[0].durability == 3


# ------------------------------------------------------------------
# 3. activate_location — cooldown blocks reactivation
# ------------------------------------------------------------------

def test_activate_location_cooldown():
    """After activation, location is on cooldown and cannot be reactivated."""
    state = _make_state_with_location(durability=3)
    result = activate_location(state.copy(), 0)
    assert result.locations[0].cooldown_current == 2

    # Try to activate again on same result — should fail
    result2 = activate_location(result.copy(), 0)
    assert result2.locations[0].durability == 2  # unchanged
    assert result2.locations[0].cooldown_current == 2  # unchanged


# ------------------------------------------------------------------
# 4. activate_location — no durability
# ------------------------------------------------------------------

def test_activate_location_no_durability():
    """Location with 0 durability cannot be activated."""
    state = _make_state_with_location(durability=0)
    result = activate_location(state.copy(), 0)
    assert result.locations[0].durability == 0  # unchanged
    assert result.locations[0].cooldown_current == 0  # unchanged


# ------------------------------------------------------------------
# 5. activate_location — on cooldown
# ------------------------------------------------------------------

def test_activate_location_on_cooldown():
    """Location with cooldown > 0 cannot be activated."""
    state = _make_state_with_location(durability=3, cooldown_current=1)
    result = activate_location(state.copy(), 0)
    assert result.locations[0].durability == 3  # unchanged
    assert result.locations[0].cooldown_current == 1  # unchanged


# ------------------------------------------------------------------
# 6. tick_location_cooldowns
# ------------------------------------------------------------------

def test_tick_location_cooldowns():
    """After END_TURN, cooldowns decrement."""
    state = _make_state_with_location(durability=2, cooldown_current=2)
    result = tick_location_cooldowns(state.copy())
    assert result.locations[0].cooldown_current == 1
    # Original unchanged
    assert state.locations[0].cooldown_current == 2


# ------------------------------------------------------------------
# 7. tick cooldown reaches zero
# ------------------------------------------------------------------

def test_tick_cooldown_reaches_zero():
    """After enough turns, location becomes ready again."""
    state = _make_state_with_location(durability=2, cooldown_current=1)
    result = tick_location_cooldowns(state.copy())
    assert result.locations[0].cooldown_current == 0  # ready!


# ------------------------------------------------------------------
# 8. enumerate includes ACTIVATE_LOCATION
# ------------------------------------------------------------------

def test_enumerate_includes_location():
    """GameState with ready location yields ACTIVATE_LOCATION action."""
    state = _make_state_with_location(durability=3, cooldown_current=0)
    actions = enumerate_legal_actions(state)
    loc_actions = [a for a in actions if a.action_type == ActionType.ACTIVATE_LOCATION]
    assert len(loc_actions) == 1
    assert loc_actions[0].source_index == 0


# ------------------------------------------------------------------
# 9. enumerate excludes cooldown location
# ------------------------------------------------------------------

def test_enumerate_excludes_cooldown_location():
    """Location on cooldown does NOT appear in legal actions."""
    state = _make_state_with_location(durability=3, cooldown_current=1)
    actions = enumerate_legal_actions(state)
    loc_actions = [a for a in actions if a.action_type == ActionType.ACTIVATE_LOCATION]
    assert len(loc_actions) == 0


# ------------------------------------------------------------------
# 10. GameState copy preserves locations
# ------------------------------------------------------------------

def test_gamestate_copy_includes_locations():
    """Deep copy preserves locations independently."""
    state = _make_state_with_location(durability=3)
    copied = state.copy()

    assert len(copied.locations) == 1
    assert copied.locations[0].name == "Test Location"

    # Mutating copy doesn't affect original
    copied.locations[0].durability = 0
    assert state.locations[0].durability == 3


# ------------------------------------------------------------------
# 11. activate_location — damage effect resolves
# ------------------------------------------------------------------

def test_activate_location_damage_effect():
    """Location with damage text deals damage to enemy hero."""
    state = _make_state_with_location(durability=3, english_text="Deal 2 damage")
    result = activate_location(state.copy(), 0)
    assert result.opponent.hero.hp == 28  # 30 - 2


# ------------------------------------------------------------------
# 12. activate_location — heal effect resolves
# ------------------------------------------------------------------

def test_activate_location_heal_effect():
    """Location with heal text heals friendly hero."""
    state = _make_state_with_location(durability=3, english_text="Restore 3 Health")
    state.hero.hp = 25
    result = activate_location(state.copy(), 0)
    assert result.hero.hp == 28  # 25 + 3


# ------------------------------------------------------------------
# 13. apply_action END_TURN ticks cooldowns
# ------------------------------------------------------------------

def test_end_turn_ticks_location_cooldowns():
    """END_TURN via apply_action ticks location cooldowns."""
    state = _make_state_with_location(durability=2, cooldown_current=2)
    result = apply_action(state, Action(action_type=ActionType.END_TURN))
    assert result.locations[0].cooldown_current == 1

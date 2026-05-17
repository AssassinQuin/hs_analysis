"""
Tests for the aura engine — continuous board buff recomputation.
"""
import pytest

from analysis.search.aura_engine import recompute_auras, AURA_REGISTRY
from analysis.search.enchantment import apply_enchantment, Enchantment
from analysis.search.game_state import (
    GameState,
    Minion,
    HeroState,
    ManaState,
    OpponentState,
)


def _minion(name: str, attack: int = 1, health: int = 1) -> Minion:
    """Helper to create a simple minion."""
    return Minion(
        dbf_id=0,
        name=name,
        attack=attack,
        health=health,
        max_health=health,
    )


def _state_with_board(*minions: Minion) -> GameState:
    """Create a GameState with minions on the friendly board."""
    return GameState(
        hero=HeroState(),
        mana=ManaState(),
        board=list(minions),
        hand=[],
        opponent=OpponentState(board=[]),
    )


# -----------------------------------------------------------------------
# 1. No aura minions → no changes
# -----------------------------------------------------------------------
def test_no_aura_minions_no_changes():
    s = _state_with_board(_minion("Wisp", 1, 1), _minion("Yeti", 4, 5))
    original_atk = [m.attack for m in s.board]
    recompute_auras(s)
    assert [m.attack for m in s.board] == original_atk
    for m in s.board:
        assert not any(e.enchantment_id.startswith("aura_") for e in m.enchantments)


# -----------------------------------------------------------------------
# 2. Raid Leader: +1 attack to all other friendly
# -----------------------------------------------------------------------
def test_raid_leader_buffs_other_friendly():
    leader = _minion("Raid Leader", 2, 2)
    wisp = _minion("Wisp", 1, 1)
    yeti = _minion("Yeti", 4, 5)
    s = _state_with_board(leader, wisp, yeti)
    recompute_auras(s)
    # Leader does NOT buff itself
    assert leader.attack == 2
    assert wisp.attack == 2  # 1+1
    assert yeti.attack == 5  # 4+1
    # Health unchanged
    assert wisp.health == 1
    assert yeti.health == 5


# -----------------------------------------------------------------------
# 3. Stormwind Champion: +1/+1 to other friendly
# -----------------------------------------------------------------------
def test_stormwind_champion_buffs_other_friendly():
    champ = _minion("Stormwind Champion", 6, 6)
    wisp = _minion("Wisp", 1, 1)
    s = _state_with_board(champ, wisp)
    recompute_auras(s)
    assert champ.attack == 6 and champ.health == 6  # no self-buff
    assert wisp.attack == 2 and wisp.health == 2 and wisp.max_health == 2


# -----------------------------------------------------------------------
# 4. Flametongue Totem: +2 attack to adjacent only
# -----------------------------------------------------------------------
def test_flametongue_totem_adjacent_only():
    totem = _minion("Flametongue Totem", 0, 3)
    left = _minion("Wisp", 1, 1)
    right = _minion("Yeti", 4, 5)
    far = _minion("Boar", 2, 2)
    s = _state_with_board(left, totem, right, far)
    recompute_auras(s)
    assert left.attack == 3    # 1+2 (adjacent)
    assert totem.attack == 0   # no self-buff
    assert right.attack == 6   # 4+2 (adjacent)
    assert far.attack == 2     # not adjacent


# -----------------------------------------------------------------------
# 5. Murloc Warleader: +2 attack to murlocs only
# -----------------------------------------------------------------------
def test_murloc_warleader_buffs_murlocs_only():
    leader = _minion("Murloc Warleader", 3, 3)
    murloc = _minion("Murloc Tidecaller", 1, 2)
    non_murloc = _minion("Wisp", 1, 1)
    s = _state_with_board(leader, murloc, non_murloc)
    recompute_auras(s)
    assert leader.attack == 3       # no self-buff
    assert murloc.attack == 3       # 1+2 murloc buff
    assert non_murloc.attack == 1   # not a murloc


# -----------------------------------------------------------------------
# 6. Aura removal when source dies
# -----------------------------------------------------------------------
def test_aura_removed_when_source_dies():
    leader = _minion("Raid Leader", 2, 2)
    wisp = _minion("Wisp", 1, 1)
    s = _state_with_board(leader, wisp)
    recompute_auras(s)
    assert wisp.attack == 2
    # Simulate leader dying — remove from board
    s.board.pop(0)
    recompute_auras(s)
    assert wisp.attack == 1  # buff removed


# -----------------------------------------------------------------------
# 7. Aura not applied to source itself
# -----------------------------------------------------------------------
def test_aura_not_applied_to_source():
    leader = _minion("Raid Leader", 2, 2)
    s = _state_with_board(leader)
    recompute_auras(s)
    assert leader.attack == 2  # unchanged
    assert not any(e.enchantment_id.startswith("aura_") for e in leader.enchantments)


# -----------------------------------------------------------------------
# 8. Multiple aura minions stacking
# -----------------------------------------------------------------------
def test_multiple_auras_stack():
    leader1 = _minion("Raid Leader", 2, 2)
    leader2 = _minion("Raid Leader", 2, 2)
    wisp = _minion("Wisp", 1, 1)
    s = _state_with_board(leader1, wisp, leader2)
    recompute_auras(s)
    assert wisp.attack == 3  # 1 + 1 + 1 from both leaders
    assert leader1.attack == 3  # 2 + 1 from leader2
    assert leader2.attack == 3  # 2 + 1 from leader1


# -----------------------------------------------------------------------
# 9. Idempotency
# -----------------------------------------------------------------------
def test_recompute_idempotent():
    leader = _minion("Raid Leader", 2, 2)
    wisp = _minion("Wisp", 1, 1)
    s = _state_with_board(leader, wisp)
    recompute_auras(s)
    atk_after_first = [m.attack for m in s.board]
    recompute_auras(s)
    atk_after_second = [m.attack for m in s.board]
    assert atk_after_first == atk_after_second


# -----------------------------------------------------------------------
# 10. Empty board
# -----------------------------------------------------------------------
def test_empty_board():
    s = _state_with_board()
    recompute_auras(s)
    assert s.board == []
    assert s.opponent.board == []


# -----------------------------------------------------------------------
# 11. Full board (7 minions) with aura
# -----------------------------------------------------------------------
def test_full_board_with_aura():
    leader = _minion("Raid Leader", 2, 2)
    minions = [leader] + [_minion(f"Token{i}", 1, 1) for i in range(6)]
    s = _state_with_board(*minions)
    assert len(s.board) == 7
    recompute_auras(s)
    assert leader.attack == 2  # no self-buff
    for m in s.board[1:]:
        assert m.attack == 2  # all get +1


# -----------------------------------------------------------------------
# 12. Aura on opponent side
# -----------------------------------------------------------------------
def test_opponent_aura_affects_opponent_board():
    s = GameState(
        hero=HeroState(),
        mana=ManaState(),
        board=[_minion("Wisp", 1, 1)],
        hand=[],
        opponent=OpponentState(
            board=[
                _minion("Raid Leader", 2, 2),
                _minion("Yeti", 4, 5),
            ]
        ),
    )
    recompute_auras(s)
    # Friendly wisp unaffected
    assert s.board[0].attack == 1
    # Opponent yeti gets buffed
    assert s.opponent.board[1].attack == 5


# -----------------------------------------------------------------------
# 13. max_iterations guard
# -----------------------------------------------------------------------
def test_max_iterations_guard():
    # Even with aura minions that could chain, it should terminate
    leader = _minion("Raid Leader", 2, 2)
    wisp = _minion("Wisp", 1, 1)
    s = _state_with_board(leader, wisp)
    # Force very low max_iterations — should still complete
    result = recompute_auras(s, max_iterations=1)
    assert result is s  # returns same state
    assert wisp.attack == 2  # still applied correctly


# -----------------------------------------------------------------------
# 14. Chinese name variant works
# -----------------------------------------------------------------------
def test_chinese_name_variant():
    leader = _minion("掠夺者", 2, 2)  # Raid Leader CN name
    wisp = _minion("Wisp", 1, 1)
    s = _state_with_board(leader, wisp)
    recompute_auras(s)
    assert wisp.attack == 2


# -----------------------------------------------------------------------
# 15. Grimscale Oracle only buffs murlocs
# -----------------------------------------------------------------------
def test_grimscale_oracle_murlocs_only():
    oracle = _minion("Grimscale Oracle", 1, 1)
    murloc = _minion("Murloc Tidehunter", 2, 1)
    non_murloc = _minion("Wisp", 1, 1)
    s = _state_with_board(oracle, murloc, non_murloc)
    recompute_auras(s)
    assert murloc.attack == 3   # 2+1
    assert non_murloc.attack == 1
    assert oracle.attack == 1  # no self buff

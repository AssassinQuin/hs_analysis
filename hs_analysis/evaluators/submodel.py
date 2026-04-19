# -*- coding: utf-8 -*-
"""
Sub-Model Evaluator for Hearthstone AI Decision Engine.

Specialised evaluation functions for different aspects of game state:
  A) Board Control     — eval_board()
  B) Threat Assessment — eval_threat()
  C) Lingering Effects — eval_lingering()
  D) Trigger / RNG EV  — eval_trigger()

Runnable independently:  python3 -m hs_analysis.evaluators.submodel
"""

from __future__ import annotations

from hs_analysis.search.game_state import GameState, Minion


# ──────────────────────────────────────────────────────────────
# Keyword bonus values (aligned with v2_scoring_engine weights)
# ──────────────────────────────────────────────────────────────
KEYWORD_BONUS: dict[str, float] = {
    "taunt":         1.5,
    "divine_shield": 2.0,
    "rush":          1.0,
    "charge":        1.5,
    "windfury":      1.5,
    "poisonous":     1.5,
}


def _minion_base_score(m: Minion) -> float:
    """Approximate V2 score from raw stats + keyword bonuses."""
    score = m.attack * 1.0 + m.health * 0.8
    if m.has_taunt:         score += KEYWORD_BONUS["taunt"]
    if m.has_divine_shield: score += KEYWORD_BONUS["divine_shield"]
    if m.has_rush:          score += KEYWORD_BONUS["rush"]
    if m.has_charge:        score += KEYWORD_BONUS["charge"]
    if m.has_windfury:      score += KEYWORD_BONUS["windfury"]
    if m.has_poisonous:     score += KEYWORD_BONUS["poisonous"]
    return score


def _survival_weight(m: Minion) -> float:
    """Higher-health minions are harder to kill → more value weight."""
    return 1.0 + 0.1 * (m.health - 1)


# ──────────────────────────────────────────────────────────────
# A) Board Control Evaluation  (Sub-Model A)
# ──────────────────────────────────────────────────────────────
def eval_board(state: GameState) -> float:
    """Board control advantage: friendly weighted value minus enemy threat.

    • friendly_value = Σ (base_score × survival_weight)  for each friendly minion
    • enemy_threat   = Σ (base_score × 1.2)              for each enemy minion
    • Returns 0.0 when both boards are empty.
    """
    friendly = state.board
    enemy = state.opponent.board

    if not friendly and not enemy:
        return 0.0

    friendly_value = sum(
        _minion_base_score(m) * _survival_weight(m)
        for m in friendly
    )

    threat_multiplier = 1.2
    enemy_threat = sum(
        _minion_base_score(m) * threat_multiplier
        for m in enemy
    )

    return friendly_value - enemy_threat


# ──────────────────────────────────────────────────────────────
# B) Threat Assessment  (Sub-Model B)
# ──────────────────────────────────────────────────────────────
def eval_threat(state: GameState) -> float:
    """Evaluate danger from the opponent's board.  Range: [-50, 0].

    Returns -50.0 immediately when lethal damage is detected.
    """
    enemy_board = state.opponent.board
    opp_hero = state.opponent.hero

    # Board damage from minions that can attack this turn
    opponent_board_damage = sum(
        m.attack for m in enemy_board
        if m.can_attack or m.has_rush or m.has_charge
    )

    # Weapon damage
    weapon_damage = 0.0
    if opp_hero.weapon is not None:
        weapon_damage = opp_hero.weapon.attack

    # Lethal check — can the opponent kill us right now?
    lethal = opponent_board_damage + weapon_damage
    total_defense = state.hero.hp + state.hero.armor
    if lethal >= total_defense:
        return -50.0

    # Hero danger: how close we are to dying
    danger = max(0, 30 - state.hero.hp - state.hero.armor) * 0.5

    # Extra threat from charge minions (surprise burst)
    charge_threat = sum(m.attack * 0.5 for m in enemy_board if m.has_charge)

    threat_score = -danger - (opponent_board_damage * 0.3) - charge_threat

    # Clamp to [-50, 0]
    return max(-50.0, min(0.0, threat_score))


# ──────────────────────────────────────────────────────────────
# C) Lingering / Continuous Effects  (Sub-Model C)
# ──────────────────────────────────────────────────────────────
def eval_lingering(state: GameState) -> float:
    """Ongoing board value with time discounting (0.85 per turn).

    Minion value is discounted by 0.85^(estimated turns remaining).
    Weapon and secrets receive a single round of discount.
    """
    discount = 0.85
    total = 0.0

    # Minion lingering value
    for m in state.board:
        base = _minion_base_score(m)
        turns_ahead = max(1, m.health / 2)   # rough estimate
        total += base * (discount ** turns_ahead)

    # Weapon value (discounted once)
    if state.hero.weapon is not None:
        w = state.hero.weapon
        total += w.attack * w.health * discount

    # Secrets value (each worth ~2, discounted once)
    secrets = getattr(state, "secrets", [])
    total += len(secrets) * 2.0 * discount

    return total


# ──────────────────────────────────────────────────────────────
# D) Trigger / Random Effects EV  (Sub-Model D)
# ──────────────────────────────────────────────────────────────
def eval_trigger(state: GameState) -> float:
    """Rough expected value from trigger effects and hand-card EV.

    • Minions with enchantments:  battlecry_EV = 2.0,  deathrattle_EV = 1.5
    • Hand cards:  spell = +0.5,  weapon = +0.3
    """
    total = 0.0

    # Board minions with enchantments / special keywords
    for m in state.board:
        ench = m.enchantments or []
        if ench:
            total += 2.0   # battlecry EV — any mechanics present
            if any("deathrattle" in str(e).lower() for e in ench):
                total += 1.5

    # Hand card EV (rough estimate)
    for card in state.hand:
        ct = getattr(card, "card_type", "").upper()
        if ct == "SPELL":
            total += 0.5
        elif ct == "WEAPON":
            total += 0.3

    return total


# ======================================================================
# __main__ demo / self-test
# ======================================================================
if __name__ == "__main__":
    from hs_analysis.search.game_state import Weapon, HeroState, OpponentState, ManaState
    from hs_analysis.models.card import Card

    errors: list[str] = []

    print("=" * 60)
    print("Sub-Model Evaluator — Demo / Self-Test")
    print("=" * 60)

    # ── Test 1: Empty board ──────────────────────────────────
    empty = GameState()

    print("\n--- Test 1: Empty Board ---")
    b  = eval_board(empty)
    t  = eval_threat(empty)
    li = eval_lingering(empty)
    tr = eval_trigger(empty)
    print(f"  eval_board:     {b:+.2f}")
    print(f"  eval_threat:    {t:+.2f}")
    print(f"  eval_lingering: {li:+.2f}")
    print(f"  eval_trigger:   {tr:+.2f}")
    if abs(b) >= 0.01:
        errors.append(f"Empty board eval_board should be ~0, got {b}")
    else:
        print("  ✓ eval_board ≈ 0")

    # ── Test 2: Full board (friendly advantage) ──────────────
    full = GameState(
        hero=HeroState(hp=30, armor=0),
        board=[
            Minion(attack=5, health=5, has_taunt=True, name="Tank"),
            Minion(attack=3, health=3, has_divine_shield=True, name="Shielded"),
            Minion(attack=7, health=2, has_charge=True, name="Charger"),
        ],
        opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[Minion(attack=2, health=2, name="Weakling")],
        ),
    )

    print("\n--- Test 2: Full Board (friendly advantage) ---")
    b  = eval_board(full)
    t  = eval_threat(full)
    li = eval_lingering(full)
    tr = eval_trigger(full)
    print(f"  eval_board:     {b:+.2f}")
    print(f"  eval_threat:    {t:+.2f}")
    print(f"  eval_lingering: {li:+.2f}")
    print(f"  eval_trigger:   {tr:+.2f}")
    if b <= 0:
        errors.append(f"Full friendly board eval_board should be > 0, got {b}")
    else:
        print("  ✓ eval_board > 0")

    # ── Test 3: Lethal danger ────────────────────────────────
    lethal = GameState(
        hero=HeroState(hp=5, armor=0),
        opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[
                Minion(attack=4, health=4, can_attack=True, name="Attacker1"),
                Minion(attack=3, health=3, can_attack=True, name="Attacker2"),
            ],
        ),
    )

    print("\n--- Test 3: Lethal Danger ---")
    b  = eval_board(lethal)
    t  = eval_threat(lethal)
    li = eval_lingering(lethal)
    tr = eval_trigger(lethal)
    print(f"  eval_board:     {b:+.2f}")
    print(f"  eval_threat:    {t:+.2f}")
    print(f"  eval_lingering: {li:+.2f}")
    print(f"  eval_trigger:   {tr:+.2f}")
    if t > -49:
        errors.append(f"Lethal danger eval_threat should be ≤ -49, got {t}")
    else:
        print("  ✓ eval_threat very negative (lethal detected)")

    # ── Test 4: Trigger EV with enchantments + hand cards ────
    trigger_state = GameState(
        hero=HeroState(hp=30),
        board=[
            Minion(attack=3, health=3, enchantments=["deathrattle"], name="DR Minion"),
            Minion(attack=2, health=2, enchantments=["battlecry"], name="BC Minion"),
        ],
        hand=[
            Card(name="Fireball", card_type="SPELL"),
            Card(name="Arcane Reaper", card_type="WEAPON"),
            Card(name="Murloc", card_type="MINION"),
        ],
    )

    print("\n--- Test 4: Trigger EV with enchantments ---")
    tr = eval_trigger(trigger_state)
    # 2 minions with enchantments → 2 × 2.0 = 4.0
    # 1 has deathrattle           → +1.5
    # hand: 1 spell (+0.5) + 1 weapon (+0.3) + 1 minion (+0) = 0.8
    expected_trigger = 4.0 + 1.5 + 0.5 + 0.3
    print(f"  eval_trigger: {tr:+.2f}  (expected {expected_trigger:.1f})")
    if abs(tr - expected_trigger) > 0.01:
        errors.append(f"eval_trigger expected {expected_trigger}, got {tr}")
    else:
        print(f"  ✓ eval_trigger = {expected_trigger:.1f} as expected")

    # ── Test 5: Lingering with weapon ────────────────────────
    linger_state = GameState(
        hero=HeroState(
            hp=30,
            weapon=Weapon(attack=3, health=2, name="Arcanite Reaper"),
        ),
        board=[
            Minion(attack=4, health=6, name="Big Body"),
        ],
    )

    print("\n--- Test 5: Lingering with weapon ---")
    li = eval_lingering(linger_state)
    # Minion: base = 4*1.0 + 6*0.8 = 8.8, turns = max(1, 6/2) = 3
    #   discounted = 8.8 * 0.85^3 = 8.8 * 0.614125 = 5.40
    # Weapon: 3 * 2 * 0.85 = 5.10
    # Secrets: 0
    expected_minion_part = 8.8 * (0.85 ** 3)
    expected_weapon_part = 3 * 2 * 0.85
    expected_lingering = expected_minion_part + expected_weapon_part
    print(f"  eval_lingering: {li:+.2f}  (expected ~{expected_lingering:.2f})")
    if abs(li - expected_lingering) > 0.01:
        errors.append(f"eval_lingering expected ~{expected_lingering:.2f}, got {li}")
    else:
        print(f"  ✓ eval_lingering ≈ {expected_lingering:.2f} as expected")

    # ── Report ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    if errors:
        print("❌ Some tests FAILED:")
        for e in errors:
            print(f"  • {e}")
        raise SystemExit(1)
    else:
        print("All tests passed ✓")
    print("=" * 60)

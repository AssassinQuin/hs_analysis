#!/usr/bin/env python3
"""spell_simulator.py — Backward-compatible re-export stub.

This module redirects to analysis.effects.orchestration.spell.
New code should import directly from there.
"""

from analysis.effects.orchestration.spell import (
    EffectApplier,
    resolve_effects,
    _resolve_deaths,
    _pick_target_for_damage,
    _resolve_target_from_index,
)

__all__ = [
    "EffectApplier",
    "resolve_effects",
    "_resolve_deaths",
    "_pick_target_for_damage",
    "_resolve_target_from_index",
]

if __name__ == "__main__":
    from analysis.effects.orchestration.spell import _build_test_state
    from analysis.card.models.card import Card

    errors: list[str] = []

    # ---- Test 1: EffectParser basic parsing ----
    from analysis.effects.parser.legacy_adapter import EffectParser

    effects = EffectParser.parse("Deal 6 damage.")
    if not effects or effects[0][0] != 'direct_damage' or effects[0][1] != 6:
        errors.append(f"FAIL: direct_damage parse: got {effects}")
    else:
        print(f"V direct_damage parse: {effects}")

    effects = EffectParser.parse("Draw 2 cards.")
    if not effects or effects[0][0] != 'draw' or effects[0][1] != 2:
        errors.append(f"FAIL: draw parse: got {effects}")
    else:
        print(f"V draw parse: {effects}")

    effects = EffectParser.parse("Deal 2 damage to all minions.")
    if not effects or effects[0][0] != 'aoe_damage' or effects[0][1] != 2:
        errors.append(f"FAIL: aoe_damage parse: got {effects}")
    else:
        print(f"V aoe_damage parse: {effects}")

    effects = EffectParser.parse("Summon a 3/5 minion.")
    if not effects or effects[0][0] != 'summon_stats' or effects[0][1] != (3, 5):
        errors.append(f"FAIL: summon_stats parse: got {effects}")
    else:
        print(f"V summon_stats parse: {effects}")

    effects = EffectParser.parse("Gain 5 Armor.")
    if not effects or effects[0][0] != 'armor' or effects[0][1] != 5:
        errors.append(f"FAIL: armor parse: got {effects}")
    else:
        print(f"V armor parse: {effects}")

    effects = EffectParser.parse("+3 Attack.")
    if not effects or effects[0][0] != 'buff_atk' or effects[0][1] != 3:
        errors.append(f"FAIL: buff_atk parse: got {effects}")
    else:
        print(f"V buff_atk parse: {effects}")

    # ---- Test 2: Fireball (6 damage) reduces target HP by 6 ----
    base = _build_test_state()
    fireball = Card(dbf_id=5001, name="Fireball", cost=4, card_type="SPELL",
                    text="Deal 6 damage.")

    result = resolve_effects(base, fireball)
    murloc_alive = any(m.name == "Murloc Raider" for m in result.opponent.board)
    if murloc_alive:
        errors.append(f"FAIL: Fireball should kill Murloc Raider (1 HP - 6 damage)")
    else:
        print("V Fireball kills Murloc Raider (1 HP - 6 damage)")

    if base.opponent.hero.hp != 30:
        errors.append("FAIL: original state mutated after Fireball test")
    else:
        print("V Original state unchanged after Fireball test")

    # ---- Test 3: AOE clears multiple minions ----
    base = _build_test_state()
    aoe_card = Card(dbf_id=5002, name="Arcane Explosion", cost=2, card_type="SPELL",
                    text="Deal 2 damage to all minions.")

    result = resolve_effects(base, aoe_card)
    voidwalker_alive = any(m.name == "Voidwalker" for m in result.opponent.board)
    murloc_alive = any(m.name == "Murloc Raider" for m in result.opponent.board)
    if murloc_alive:
        errors.append(f"FAIL: AOE should kill Murloc Raider")
    if not voidwalker_alive:
        errors.append(f"FAIL: AOE (2 dmg) should NOT kill Voidwalker (3 HP, 1 remaining)")
    else:
        vw = [m for m in result.opponent.board if m.name == "Voidwalker"][0]
        if vw.health != 1:
            errors.append(f"FAIL: Voidwalker should have 1 HP after AOE, got {vw.health}")
        else:
            print(f"V AOE kills Murloc Raider, leaves Voidwalker at 1 HP")

    # ---- Test 4: Buff increases minion attack/health ----
    base = _build_test_state()
    buff_card = Card(dbf_id=5003, name="Blessing of Might", cost=1, card_type="SPELL",
                     text="+3 Attack.")

    result = resolve_effects(base, buff_card)
    fire_fly = [m for m in result.board if m.name == "Fire Fly"][0]
    if fire_fly.attack != 5:
        errors.append(f"FAIL: Fire Fly attack should be 5, got {fire_fly.attack}")
    else:
        print("V Buff increases Fire Fly attack from 2 to 5")

    original_ff = [m for m in base.board if m.name == "Fire Fly"][0]
    if original_ff.attack != 2:
        errors.append("FAIL: original state mutated by buff")
    else:
        print("V Original state unchanged after buff test")

    # ---- Test 5: Draw adds cards to hand ----
    base = _build_test_state()
    base.deck_remaining = 10
    draw_card = Card(dbf_id=5004, name="Arcane Intellect", cost=2, card_type="SPELL",
                     text="Draw 2 cards.")

    result = resolve_effects(base, draw_card)
    added = len(result.hand) - len(base.hand)
    if added != 2:
        errors.append(f"FAIL: draw should add 2 cards, added {added}")
    else:
        print("V Draw adds 2 cards to hand")

    if result.deck_remaining != 8:
        errors.append(f"FAIL: deck_remaining should be 8, got {result.deck_remaining}")
    else:
        print("V deck_remaining decreased from 10 to 8")

    # ---- Report ----
    print()
    if errors:
        print("X Some tests FAILED:")
        for e in errors:
            print(f"  * {e}")
        raise SystemExit(1)
    else:
        print("V All spell_simulator tests passed.")

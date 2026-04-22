"""imbue.py — Imbue hero power upgrade system.

V10 Phase 3: Tracks Imbue mechanic for hero power upgrades.
When a card with IMBUE mechanic is played, the hero power gets stronger.
"""

from __future__ import annotations

from analysis.search.game_state import GameState, Minion, Weapon

# ===================================================================
# Imbue hero power table
# ===================================================================

IMBUE_HERO_POWERS = {
    "DRUID": {
        "effect": "summon",
        "base_attack": 1,
        "base_health": 1,
        "scaling": True,
        "text": "召唤一个{imbue_level}/{imbue_level}的树人",
    },
    "HUNTER": {
        "effect": "damage",
        "base_damage": 1,
        "scaling": True,
        "text": "造成{1 + imbue_level}点伤害",
    },
    "MAGE": {
        "effect": "damage",
        "base_damage": 1,
        "scaling": True,
        "text": "造成{1 + imbue_level}点伤害",
    },
    "PALADIN": {
        "effect": "summon",
        "base_attack": 1,
        "base_health": 1,
        "scaling": True,
        "text": "召唤一个{1+imbue_level}/{1+imbue_level}的报告兵",
    },
    "PRIEST": {
        "effect": "heal",
        "base_heal": 2,
        "scaling": True,
        "text": "恢复{2 + imbue_level}点生命",
    },
    "ROGUE": {
        "effect": "weapon",
        "base_attack": 1,
        "base_durability": 2,
        "scaling": True,
        "text": "装备一把{1+imbue_level}/2的匕首",
    },
    "SHAMAN": {
        "effect": "random_totem",
        "base_text": "随机召唤一个图腾",
    },
    "WARLOCK": {
        "effect": "damage_self_draw",
        "base_damage": 2,
        "base_draw": 1,
        "text": "造成{2}点伤害，抽{1}张牌",
    },
    "WARRIOR": {
        "effect": "armor",
        "base_armor": 2,
        "scaling": True,
        "text": "获得{2 + imbue_level}点护甲",
    },
    "DEMONHUNTER": {
        "effect": "damage",
        "base_damage": 1,
        "scaling": True,
        "text": "造成{1+imbue_level}点伤害",
    },
    "DEATHKNIGHT": {
        "effect": "armor",
        "base_armor": 2,
        "scaling": True,
        "text": "获得{2+imbue_level}点护甲",
    },
}


# ===================================================================
# apply_imbue
# ===================================================================

def apply_imbue(state: GameState, card) -> GameState:
    """Check if card has IMBUE mechanic; if so, increment imbue_level.

    Returns modified state (same object, mutated in-place for performance).
    """
    mechanics = getattr(card, "mechanics", None) or []
    text = getattr(card, "text", "") or ""

    has_imbue = "IMBUE" in mechanics or "灌注" in text

    if has_imbue:
        state.hero.imbue_level += 1

    return state


# ===================================================================
# apply_hero_power
# ===================================================================

def apply_hero_power(state: GameState) -> GameState:
    """Apply the hero power effect based on class and imbue_level.

    Looks up the hero class in IMBUE_HERO_POWERS and applies the
    appropriate effect. Falls back to a generic damage effect if
    the class is not found.

    Returns modified state.
    """
    hero_class = (getattr(state.hero, "hero_class", "") or "").upper()
    imbue_level = getattr(state.hero, "imbue_level", 0)

    power_info = IMBUE_HERO_POWERS.get(hero_class)
    if power_info is None:
        # Generic fallback: deal 1 + imbue_level damage
        if state.opponent.board:
            state.opponent.board[0].health -= (1 + imbue_level)
        else:
            state.opponent.hero.hp -= (1 + imbue_level)
        return state

    effect = power_info.get("effect", "")

    if effect == "damage":
        base = power_info.get("base_damage", 1)
        total = base + imbue_level
        # Prefer hitting enemy minion; fall back to hero
        if state.opponent.board:
            state.opponent.board[0].health -= total
        else:
            state.opponent.hero.hp -= total

    elif effect == "heal":
        base = power_info.get("base_heal", 2)
        total = base + imbue_level
        state.hero.hp += total

    elif effect == "armor":
        base = power_info.get("base_armor", 2)
        total = base + imbue_level
        state.hero.armor += total

    elif effect == "summon":
        base_atk = power_info.get("base_attack", 1)
        base_hp = power_info.get("base_health", 1)
        atk = base_atk + imbue_level
        hp = base_hp + imbue_level
        if not state.board_full():
            state.board.append(Minion(
                name="Hero Power Minion",
                attack=atk,
                health=hp,
                max_health=hp,
                owner="friendly",
            ))

    elif effect == "weapon":
        base_atk = power_info.get("base_attack", 1)
        base_dur = power_info.get("base_durability", 2)
        atk = base_atk + imbue_level
        state.hero.weapon = Weapon(
            attack=atk,
            health=base_dur,
            name="Hero Power Weapon",
        )

    elif effect == "random_totem":
        # Simplified: summon a 0/1 totem if board not full
        if not state.board_full():
            state.board.append(Minion(
                name="Totem",
                attack=0,
                health=1,
                max_health=1,
                owner="friendly",
            ))

    elif effect == "damage_self_draw":
        dmg = power_info.get("base_damage", 2)
        draw_count = power_info.get("base_draw", 1)
        state.hero.hp -= dmg
        for _ in range(draw_count):
            if state.deck_remaining > 0:
                state.deck_remaining -= 1
            else:
                state.fatigue_damage += 1
                state.hero.hp -= state.fatigue_damage

    return state

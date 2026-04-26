# -*- coding: utf-8 -*-
"""Shared effect keyword constants for card text detection.

Centralised keyword sets used across:
  - opponent_simulator.py (threat classification)
  - evaluators/submodel.py (spell threat estimation)
  - mcts/pruning.py (action pruning)
  - mcts/turn_advance.py (opponent simulation)
  - abilities/tokens.py (ability parsing)

All keyword matching uses `kw in text_lower` semantics.
"""


# ═══════════════════════════════════════════════════════════════
# Damage detection (EN + CN)
# ═══════════════════════════════════════════════════════════════

DAMAGE_KEYWORDS: frozenset[str] = frozenset({
    'deal $', 'deals $',          # EN: "Deal $3 damage"
    '造成$',                        # CN: "造成$3点伤害"
    'lava burst', '火炎',          # Special cards
})

DAMAGE_TEXT_FRAGMENTS: frozenset[str] = frozenset({
    '造成', '伤害', 'damage',       # Loose text fragments for broad matching
})

# ═══════════════════════════════════════════════════════════════
# Heal detection
# ═══════════════════════════════════════════════════════════════

HEAL_KEYWORDS: frozenset[str] = frozenset({
    '恢复', '治疗', 'heal', 'restore',
})

# ═══════════════════════════════════════════════════════════════
# Board clear / AoE
# ═══════════════════════════════════════════════════════════════

BOARD_CLEAR_KEYWORDS: frozenset[str] = frozenset({
    'all minions', 'all enemies',
    '所有敌方', '全体随从',
    'hellfire', 'blizzard', 'flamestrike', 'avalanche',
    'brawl', 'twisting nether',
})

# ═══════════════════════════════════════════════════════════════
# Removal / Destroy
# ═══════════════════════════════════════════════════════════════

REMOVAL_KEYWORDS: frozenset[str] = frozenset({
    'destroy', 'destroy a', 'destroy an', 'silence',
    '消灭', '摧毁', '变形',
    'polymorph', 'hex', 'assassinate', 'execute',
    'shadow word: death', '暗言术：灭', '自然平衡',
    'soul of the forest',
})

# ═══════════════════════════════════════════════════════════════
# Weapon
# ═══════════════════════════════════════════════════════════════

WEAPON_KEYWORDS: frozenset[str] = frozenset({
    'weapon', 'equip', '武器',
})

# ═══════════════════════════════════════════════════════════════
# Mechanics (for opponent simulation)
# ═══════════════════════════════════════════════════════════════

RUSH_KEYWORDS: frozenset[str] = frozenset({'rush', '突袭'})
TAUNT_KEYWORDS: frozenset[str] = frozenset({'taunt', '嘲讽'})
BATTLECRY_KEYWORDS: frozenset[str] = frozenset({'battlecry', '战吼'})

---
date: 2026-04-17
topic: "Hearthstone Card Value Model v2"
status: draft
---

# Hearthstone Card Value Mathematical Model v2

## Problem Statement

The current model uses a flat `2N+1` vanilla test with fixed keyword bonuses. Analysis of 256 legendary cards across 9 standard sets reveals **7 critical flaws**:

1. Linear vanilla curve doesn't match sub-linear actual stat growth
2. Fixed keyword values (e.g., BATTLECRY=1.5) are wildly off from observed data (avg deficit -3.8)
3. 100-mana placeholder cards break scoring
4. Mechanical flags (TRIGGER_VISUAL, AURA, COLOSSAL) treated as power keywords
5. Card text effects (damage, draw, summon) completely ignored
6. No card type distinction (minion vs spell vs weapon vs location)
7. No class balance or rarity budget consideration

## Constraints

- **Data scope**: 256 legendaries (227 minions, 16 spells, 4 weapons, 3 locations, 6 heroes)
- **Standard sets**: CATACLYSM, TIME_TRAVEL, THE_LOST_CITY, EMERALD_DREAM, SPACE, ISLAND_VACATION, WHIZBANGS_WORKSHOP, EVENT, CORE
- **No external APIs at runtime** — all analysis is offline from cached JSON
- **Python-based** — must work with existing scripts infrastructure
- **Cards with mana >= 99 excluded** from vanilla curve fitting (quest rewards/placeholders)

## Approach: Three-Layer Value Model

Replace the flat formula with a **layered model**:

- **Layer 1**: Non-linear vanilla stat curve (regression-fitted)
- **Layer 2**: Empirically calibrated keyword budget with mana interaction
- **Layer 3**: Card text effect parsing with effect budget table

This approach was chosen over:
- **Machine learning model** — too opaque, hard to interpret, overkill for 256 cards
- **Piecewise linear** — more parameters, arbitrary breakpoints, harder to maintain
- **Expert-only manual values** — not reproducible, no data backing

## Architecture

### Layer 1: Non-Linear Vanilla Curve

**Formula**: `expected_stats(mana) = a * mana^b + c`

Parameters `a`, `b`, `c` fit via least-squares regression on actual vanilla-ish minion data.

**Observed stat averages by mana cost** (from analysis):

| Mana | Avg Stats | 2N+1 Expected | Actual Deficit |
|------|-----------|---------------|----------------|
| 1    | 2.0       | 3             | -1.0           |
| 2    | 7.0       | 5             | +2.0           |
| 3    | 7.2       | 7             | +0.2           |
| 4    | 8.3       | 9             | -0.7           |
| 5    | 9.0       | 11            | -2.0           |
| 6    | 10.4      | 13            | -2.6           |
| 7    | 12.6      | 15            | -2.4           |
| 8    | 13.7      | 17            | -3.3           |
| 9    | 13.8      | 19            | -5.2           |
| 10   | 17.0      | 21            | -4.0           |

**Key insight**: Deficit grows with mana cost. High-cost minions trade stats for effects.

### Layer 2: Keyword Budget (Empirically Calibrated)

**Three-tier classification**:

| Tier | Keywords | Valuation |
|------|----------|-----------|
| **Power** | BATTLECRY, DEATHRATTLE, DISCOVER, DIVINE_SHIELD, RUSH, CHARGE, WINDFURY, TAUNT, LIFESTEAL, STEALTH | Calibrated from data, scales with mana |
| **Mechanical** | TRIGGER_VISUAL, AURA, COLOSSAL, QUEST, START_OF_GAME | Flat 0.5-1.0 (enablers, not standalone value) |
| **Niche** | STARSHIP, IMBUE, SPELLBURST, MINIATURIZE, TITAN, COMBO, TRADEABLE, etc. | Default 1.0 until sufficient samples |

**Mana interaction**: Keywords scale with cost.

```
keyword_value = base_value * (1 + 0.1 * mana_cost)
```

**Calibrated base values from data** (avg score of cards with keyword):

| Keyword | Empirical Base | Notes |
|---------|---------------|-------|
| WINDFURY | 4.5 | Rare but very high impact |
| DIVINE_SHIELD | 3.5 | Premium defensive keyword |
| DISCOVER | 2.9 | Strong card generation |
| BATTLECRY | 2.9 | Most common, versatile |
| DEATHRATTLE | 2.8 | Strong but needs setup |
| RUSH | 2.3 | Immediate board impact |
| TAUNT | 2.3 | Defensive premium |
| LIFESTEAL | 2.0 | Sustain value |
| STEALTH | 1.5 | Guarantee one turn |
| CHARGE | 1.1 | Penalized by low-stats-on-charge-cards |

### Layer 3: Card Text Effect Budget

Parse card text using regex patterns. Budget per effect:

| Effect Type | Value Formula | Reasoning |
|-------------|--------------|-----------|
| Summon X/X | summoned_stats * 0.5 | Half vanilla value for tokens |
| Deal N damage | N * 0.7 | Slightly below stat equivalence |
| Draw N cards | N * 1.5 | Card advantage premium |
| AOE N damage | N * 0.5 * expected_targets(3) | Multiplied by likely target count |
| Generate card | 2.5 per card | Discover-like value |
| Copy | 2.0 per card | Slightly less than generate |
| Buff +N/+N | N * 0.5 | Half stat value |
| Heal N | N * 0.3 | Reactive, lowest value |
| Destroy target | 4.0 per target | Premium hard removal |
| Mana reduction | reduced * 1.0 | Tempo value equals mana saved |
| Armor N | N * 0.4 | Between heal and stat value |
| Silence | 1.5 | Utility, situational |
| Conditional | base * 0.6 | Discount for requirements |

### Card Type Adjustments

| Type | Baseline Treatment |
|------|-------------------|
| **Minion** | Standard vanilla test (stat + keyword + text) |
| **Spell** | No stat baseline — pure effect budget from text |
| **Weapon** | attack * durability as stat points, then vanilla test |
| **Location** | charges * effect_value per use |
| **Hero** | armor_value + hero_power_budget(5.0) + text_effects |

### Class Balance Multiplier

From deficit analysis:

| Class | Multiplier | Reasoning |
|-------|-----------|-----------|
| Neutral | 0.85 | Intentionally weaker than class cards |
| DH, Hunter | 0.95 | Slightly over-budget on stats |
| Warrior | 0.98 | Near baseline |
| Paladin, Rogue, Mage | 1.00 | Standard class budget |
| DK, Priest, Warlock | 1.02 | Slightly under-budget (compensated by effects) |
| Druid, Shaman | 1.05 | Most effect-reliant, biggest stat deficit |

## Composite Score Formula

```
L1_fair = curve_expected(mana) * class_multiplier
L1_actual = attack + health  (minions) | weapon_stats | 0 (spells)

L2_keyword = sum(keyword_base * (1 + 0.1 * mana)) for each keyword

L3_text = sum(effect_value) from parsed card text

card_value = L1_actual + L2_keyword + L3_text
fair_value = L1_fair + L2_expected + L3_expected
score = card_value - fair_value
```

**Interpretation**:
- score > 3: Over-budget (strong card)
- score -3..3: Balanced
- score < -3: Under-budget (weak or synergy-dependent)

## Error Handling

- **Mana >= 99**: Exclude from curve fitting, flag as "special" in output
- **Missing card text**: L3 defaults to 0
- **Unknown keywords**: Default 0.5 base value
- **Empty mechanics array**: Skip L2 entirely
- **Non-minion without text**: Score = 0, flag for manual review

## Testing Strategy

1. **Unit tests**: Verify curve fitting against known stat averages
2. **Regression test**: Score vanilla minions (no keywords, no text) — should score near 0
3. **Face test**: Top-tier meta cards should score positive; known bad cards should score negative
4. **Distribution test**: Score histogram should be roughly normal, not right-skewed
5. **Edge cases**: 0-mana cards, 10+ mana cards, spells, weapons, locations

## Open Questions

1. **Text effect parsing accuracy** — Regex is fragile. Should we invest in a proper parser?
2. **Quest chain valuation** — How to value the reward card considering the quest step costs?
3. **Location card model** — Structurally different enough to need its own sub-model?
4. **Expansion to all rarities** — Current model is legendary-only. Common/rare have different budgets.

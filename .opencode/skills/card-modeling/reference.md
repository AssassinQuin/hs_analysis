# Card Modeling — Extended Reference

Detailed methodology comparisons, statistical techniques, and templates for the card-modeling skill.

---

## Methodology Comparison Matrix

### When to Use Each Approach

| Scenario | Recommended Approach | Why |
|----------|---------------------|-----|
| First model, <500 cards | Linear pricing + keyword table | Fast, interpretable, good baseline |
| High-cost cards diverge | Power-law curve fitting | Captures sub-linear stat growth |
| Many correlated keywords | Ridge regression | Handles multicollinearity without dropping features |
| Need card-level accuracy | Gradient boosting (XGBoost) | Best predictive power, but opaque |
| Validating balance changes | Wilcoxon signed-rank test | Non-parametric, works with small samples |
| Generating new cards | Reward distribution + DBSCAN | Clusters by power level, searches valid combos |
| Multi-game comparison | Dong-style conversion factors | Normalizes across different mana systems |

### Statistical Techniques Reference

#### 1. Power-Law Curve Fitting

Use when: Stat growth is sub-linear (high-cost cards get diminishing returns).

```python
from scipy.optimize import curve_fit
import numpy as np

def power_law(mana, a, b, c):
    return a * np.power(mana, b) + c

# mana_costs = [1, 2, 3, ..., 10]
# avg_stats = [observed average atk+hp for each mana]
params, covariance = curve_fit(power_law, mana_costs, avg_stats, p0=[2.5, 0.85, 0.5])
a, b, c = params
```

**Parameter constraints:**
- `b` should be 0.7–0.95 (sub-linear but not flat)
- `a` should be positive (more mana = more stats)
- `c` is a small constant offset

**Validation:** Residual mean < 1.0, parameter b in expected range.

#### 2. OLS Regression for Keyword Values

Use when: You have many cards with known keywords and want data-driven keyword prices.

**Design matrix:** Each card is a row. Columns = mana_cost, keyword_1, keyword_2, ..., keyword_N.
**Target:** Actual stat total (atk + hp).

The coefficients on keyword columns represent their stat value.

**Caveats:**
- Keywords that always co-occur are confounded
- Requires many cards per keyword (≥10 for stable estimates)
- Assumes keyword values are independent and additive

#### 3. K-Fold Cross-Validation

Use when: Using regression or ML models. Prevents over-fitting.

```python
from sklearn.model_selection import cross_val_score
from sklearn.linear_model import Ridge

model = Ridge(alpha=1.0)
scores = cross_val_score(model, X, y, cv=5, scoring='neg_mean_squared_error')
print(f"MSE: {-scores.mean():.3f} ± {scores.std():.3f}")
```

**Rule of thumb:** If train MSE << validation MSE, model is over-fit.

#### 4. Wilcoxon Signed-Rank Test

Use when: Comparing V1 vs V2 model quality on the same card set.

```python
from scipy.stats import wilcoxon

# residuals_v1[i] = |actual[i] - predicted_v1[i]|
# residuals_v2[i] = |actual[i] - predicted_v2[i]|
statistic, p_value = wilcoxon(residuals_v1, residuals_v2)
```

If p < 0.05, the improvement from V1→V2 is statistically significant.

---

## Phase Output Templates

### Phase 1 Output: Data Collection Report

```markdown
# Data Collection Report

## Sources
- API: [URL] — [date fetched]
- Total records fetched: N
- After filtering: N

## Filtering Criteria
- Rarity: [e.g., LEGENDARY only]
- Sets: [e.g., standard sets only]
- Card types: [all / minions only]
- Exclusions: [mana >= 99, uncollectible, etc.]

## Validation
- [ ] Card count matches expected (N expected, N actual)
- [ ] No duplicate IDs
- [ ] All card types represented
- [ ] No placeholder entries

## Output Files
- `data/raw_cards.json` — Raw API response
- `data/cards_clean.json` — Filtered + deduplicated
```

### Phase 4 Output: Model Critique Report

```markdown
# Model Critique: V1

## Residual Analysis

| Mana | Actual Avg | Model Expected | Residual | Notes |
|------|-----------|---------------|----------|-------|
| 1    | 2.1       | 3.0           | -0.9     |       |
| 2    | 4.8       | 5.0           | -0.2     |       |
| ...  | ...       | ...           | ...      |       |
| 9    | 13.8      | 19.0          | -5.2     | SEVERE |

## Defect List

| # | Defect | Evidence | Severity | Proposed Fix |
|---|--------|----------|----------|-------------|
| 1 | Linear assumption fails at high mana | 9-mana deficit -5.2 | HIGH | Power-law curve |
| 2 | Flat keyword values | Divine Shield = Taunt in model, clearly unequal | HIGH | Three-tier classification |
| 3 | No card type distinction | Spells scored same as minions | MEDIUM | Type-specific valuation |
| 4 | Text effects ignored | ~60% of cards have unmodeled text effects | HIGH | Regex effect parser |
| 5 | Class imbalance unaddressed | Warlock cards systematically undervalued | LOW | Class balance multiplier |

## Literature Comparison
- Bursztein (2014): Uses OLS regression → R²=0.59
- Our V1: Uses expert-assigned constants → no R² computed
- Gap: We should compute R² for comparison

## Error Budget
- Target: Mean absolute residual < 1.5 stats across all mana costs
- Current V1: Mean absolute residual = [computed value]
- Required improvement: [X]%
```

### Phase 5 Task Template

```markdown
---
task_id: T### 
title: "[Task Title]"
status: pending
priority: critical | high | medium
depends_on: [T###, ...]
phase: [phase-name]
---

# T###: [Task Title]

## Goal
[One sentence describing what this task achieves]

## Background
[Why this task exists — reference to Phase 4 flaw #]

## Steps

### Step 1: [Action]
- Input: [file(s)]
- Operation: [what to do]
- Output: [what's produced]

### Step 2: [Action]
...

## Acceptance Criteria
- [ ] [Quantitative criterion 1]
- [ ] [Quantitative criterion 2]
- [ ] [Script runs independently]

## Artifacts
- `[output file path]` — [description]
```

---

## Card Type Valuation Strategies

### Minions
- **Baseline:** Vanilla test (stats vs expected curve)
- **Keywords:** Additive bonus from calibrated value table
- **Text effects:** Parsed from description, applied via effect budget

### Spells
- **No stats baseline.** Value is purely in text effects.
- **Approach:** Effect budget only. `spell_value = Σ(parsed_effect_values)`
- **Calibration:** Compare to minions at same mana cost — a N-mana spell should be worth roughly as much as a N-mana minion's total value.
- **Special handling:** AoE gets multiplier on per-target damage. Draw effects valued at ~1.5 per card.

### Weapons
- **Stats:** `attack × durability` = total damage potential. Treat as stat budget.
- **Baseline:** Similar to minion vanilla test but using damage potential.
- **Example:** 3-mana 3/2 weapon = 6 damage potential. Compare to 3-mana minion (expected ~7 stats).

### Locations
- **Stats:** `charges` × `effect_per_activation`
- **Special:** Locations have no attack/health. Valuation depends on effect parsing.
- **Baseline assumption:** Charges × per-use effect value, discounted by activation delay.

### Heroes
- **Stats:** Armor value + hero power budget
- **Hero power budget:** Typically valued at ~5.0 (equivalent to a 2-mana card)
- **Text effects:** Parsed normally
- **Baseline:** `armor + 5.0 + text_effect_value`

---

## Mana Interaction Model

Most card effects scale with mana cost. A flat keyword value is a V1 simplification.

**V2 mana-interaction formula:**

```
keyword_value(card) = base_value × (1 + scaling_coefficient × mana_cost)
```

Where:
- `base_value` = keyword's intrinsic worth (from calibration)
- `scaling_coefficient` = how much the keyword benefits from more mana (typically 0.05–0.15)
- Taunt benefits less from mana (low scaling)
- Divine Shield benefits more from mana (high scaling — on a big body it's worth more)

**Calibration method:**
1. Group cards by keyword
2. For each keyword, regress `stat_deficit` against `mana_cost`
3. Slope = scaling coefficient, intercept = base value

---

## Diagnostic Checklist

When the model produces unexpected results, check:

- [ ] **Data integrity:** Are input files complete? No missing fields?
- [ ] **Filter correctness:** Are placeholder/invalid cards excluded?
- [ ] **Formula correctness:** Is the scoring formula implemented as designed?
- [ ] **Parameter sanity:** Are fitted parameters in expected ranges?
- [ ] **Edge cases:** 0-mana cards, 10+ mana cards, cards with no text
- [ ] **Unit consistency:** All values in same units (stat points, not mana)
- [ ] **Aggregation bias:** Are averages weighted correctly? (per-card vs per-mana-bucket)
- [ ] **Language handling:** Chinese text patterns match actual card descriptions?

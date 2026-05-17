---
name: card-modeling
description: "Use this skill whenever the user wants to build, analyze, refine, or validate a mathematical model for trading card game (TCG/CCG) card valuation. Triggers include: any mention of 'card model', 'card value', 'mana curve', 'vanilla test', 'card balance', 'card scoring', 'card analysis', or requests to mathematically evaluate game cards. Also use when designing card evaluation systems, fitting curves to card stat data, building keyword value tables, or comparing card power levels. Works for Hearthstone, MTG, Shadowverse, Yu-Gi-Oh, or any stat-based card game. Do NOT use for card image recognition, gameplay AI agents, or deck building optimization (those are separate concerns)."
---

# Card Mathematical Modeling

Build rigorous, reproducible mathematical models for card game valuation using a structured scientific workflow.

**Core principle:** Every model claim must be backed by data. Every model change must be validated against measurable criteria. No hand-waving.

## Overview

This skill implements a **5-phase scientific methodology** for card game mathematical modeling:

1. **Data Collection** — Acquire, clean, persist card data
2. **Exploratory Data Analysis** — Understand distributions, find anomalies, measure baselines
3. **First-Order Model** — Build initial scoring formula from domain knowledge
4. **Model Critique** — Quantify errors, identify flaws, compare to alternatives
5. **Iterative Refinement** — Design fixes, decompose into tasks, execute with validation gates

Each phase has a **validation gate** — you do not proceed until the gate passes. This prevents compounding errors.

---

## Quick Reference

| Phase | Key Question | Output | Validation Gate |
|-------|-------------|--------|-----------------|
| P1: Collect | Do we have clean, complete data? | Cached JSON/SQLite | Count matches expected |
| P2: EDA | What does the data look like? | Distribution tables, anomaly list | All dimensions examined |
| P3: Model V1 | Can we score cards with a simple formula? | Scored dataset + ranking | Face validity check |
| P4: Critique | Where does the model fail? | Flaw list + error quantification | ≥3 specific flaws identified |
| P5: Refine | Can we fix the flaws systematically? | V2 model + task plans | Acceptance criteria pass |

---

## The Process

### Phase 1: Data Collection

**Goal:** Produce a clean, deduplicated, persisted dataset as the single source of truth.

**Steps:**

1. **Identify data sources** — Official APIs, community databases (HearthstoneJSON, Scryfall for MTG), wiki scrapes
2. **Write acquisition scripts** — HTTP fetch with pagination, rate limiting, error retry
3. **Filter to scope** — Standard/Wild format, rarity tiers, card types (minion/spell/weapon)
4. **Clean and deduplicate** — Remove placeholders (mana ≥ 99), merge duplicate entries by card ID
5. **Persist to cache** — Write to JSON files or SQLite; this becomes the **canonical dataset**
6. **Validate counts** — Card count matches expected (e.g., "256 standard legendaries")

**Validation Gate:**
- Total card count matches official numbers
- No duplicate card IDs
- All expected card types present
- No placeholder/junk entries (mana ≥ 99, unnamed cards)

**CRITICAL:** All subsequent phases read from this cached data. No live API calls during analysis.

---

### Phase 2: Exploratory Data Analysis (EDA)

**Goal:** Understand the data landscape before making any modeling assumptions.

**Steps:**

1. **Distribution analysis** — Mana cost, attack, health, card type frequencies. Build histograms.
2. **Keyword/mechanic census** — Count every mechanic tag. Identify rare vs common keywords.
3. **Text pattern mining** — Regex scan card descriptions for effect types (damage, draw, summon, buff, etc.). Build effect frequency table.
4. **Baseline measurement** — For minions, compute actual stat totals (atk+hp) by mana cost. This is the empirical curve.
5. **Anomaly detection** — Flag outliers: cards with stats far from peers at same mana cost, cards with unique mechanics.
6. **Keyword co-occurrence** — Which keywords appear together? This reveals synergy patterns.

**Validation Gate:**
- All major card attributes analyzed
- At least 3 distribution tables produced
- Anomalies documented for Phase 3 assumptions

**Key outputs:**
- Mana cost distribution table
- Stat average by mana cost table (the empirical baseline)
- Keyword frequency ranking
- Text effect pattern coverage percentage

---

### Phase 3: First-Order Model (V1)

**Goal:** Build the simplest model that produces meaningful card scores.

**Steps:**

1. **State assumptions** — Write down every assumption explicitly. Example: "Mana cost is linear in card power", "Each keyword has a constant value independent of mana cost"
2. **Define baseline formula** — The "vanilla test": expected stats for a no-effect card at each mana cost. Start with linear (e.g., `2N+1` for Hearthstone).
3. **Build keyword value table** — Assign constant values to each keyword based on domain knowledge. Simple starting point: binary presence/absence × fixed value.
4. **Compute scores** — For each card: `score = keyword_bonus - stat_deficit` where `deficit = actual_stats - expected_stats`
5. **Rank and persist** — Sort by score descending. Write enriched dataset (original data + scores).
6. **Face validity check** — Do the top-ranked cards make sense? Are known-strong cards ranked high?

**Validation Gate:**
- Face validity: Top 20 cards include recognizable strong cards
- Score distribution is not degenerate (not all zero, not all extreme)
- Model applies to ≥90% of cards in scope

**WARNING:** V1 is intentionally simple. Do not over-fit in this phase. Its purpose is to be **wrong in measurable ways** so Phase 4 can fix it.

---

### Phase 4: Model Critique

**Goal:** Quantify exactly where and how the model fails. This is the most important phase.

**Steps:**

1. **Residual analysis** — At each mana cost, compute `actual_avg_stats - model_expected_stats`. Plot residuals. Where does the model diverge most?
2. **Defect enumeration** — List every flaw with specific evidence. Example: "At 9-mana, actual avg is 13.8 vs expected 19 (deficit -5.2). The linear assumption fails at high mana."
3. **Keyword value audit** — Compare model keyword values against observed stat deficits for cards with each keyword. Are values too high/low? By how much?
4. **Literature comparison** — Search academic papers (Bursztein, Eger, etc.) for alternative approaches. Note what others found.
5. **Feature gap analysis** — What card properties does V1 ignore entirely? (Card text effects, conditional abilities, card type differences)

**Validation Gate:**
- ≥3 specific, quantified flaws identified
- Each flaw has numerical evidence (not just "it seems wrong")
- Alternative approaches from literature documented
- Error budget established: "acceptable residual < X"

**Output format — Flaw table:**

| # | Flaw | Evidence | Impact | Proposed Fix |
|---|------|----------|--------|-------------|
| 1 | Linear assumption breaks at high mana | 9-mana deficit -5.2 | High | Non-linear curve fitting |
| 2 | Keyword values flat, ignoring mana scaling | ... | Medium | Mana-interaction coefficient |

---

### Phase 5: Iterative Refinement (V2+)

**Goal:** Fix identified flaws through structured tasks with acceptance criteria.

**Steps:**

1. **Write design document** — Specify the improved model with formulas, parameter tables, and rationale for each change
2. **Decompose into tasks** — Each task has: title, steps, input files, output files, acceptance criteria, dependencies
3. **Define acceptance criteria** — Quantitative gates for each task. Example: "Fitting residual mean < 1.0", "Parameter b ∈ [0.7, 0.95]"
4. **Execute sequentially** — Respect dependency order. Update execution log after each step.
5. **Validate against V1** — Side-by-side comparison: does V2 score known-strong cards higher? Are residuals smaller?
6. **Iterate if needed** — If V2 still has flaws, repeat Phase 4→5

**Validation Gate:**
- All task acceptance criteria pass
- V2 residuals < V1 residuals on aggregate
- Known-strong cards score higher than known-weak cards
- Score distribution approximately normal (not skewed or bimodal)

**Acceptance criteria must be:**
- **Quantitative** — Numbers, not feelings
- **Falsifiable** — Can clearly pass or fail
- **Pre-committed** — Written before implementation, not adjusted after

---

## Methodology Reference

### Curve Fitting

When replacing a linear baseline with non-linear:

- **Power law** `f(x) = a * x^b + c` — Good for mana curves (sub-linear growth at high cost). Use `scipy.optimize.curve_fit`
- **Piecewise linear** — Good if there are clear breakpoints (e.g., "stats scale differently after 6-mana")
- **Polynomial** — Rarely justified; over-fits with few data points per mana level

Always validate: residual plot, parameter constraint (e.g., b should be sub-linear), comparison table old vs new.

### Keyword Calibration Methods

| Method | When to Use | Pros | Cons |
|--------|------------|------|------|
| Expert assignment | V1, no data | Fast, interpretable | Subjective |
| Mean deficit per keyword | V2, with V1 data | Data-driven | Confounded by multi-keyword cards |
| OLS regression | Many cards, few keywords | Statistically rigorous | Assumes linear independence |
| Ridge/Lasso regression | Many keywords, correlated | Handles multicollinearity | Less interpretable |

### Text Effect Valuation

1. Build regex pattern library from EDA patterns
2. For each effect type, define value formula: `value = base × quantity`
3. Conditional effects (e.g., "if X, then Y") get discount multiplier (0.5–0.7×)
4. Validate coverage: what % of text-bearing cards can be parsed?

### Validation Toolkit

| Technique | What It Tests | How |
|-----------|--------------|-----|
| Face validity | Does ranking make sense? | Top 20 inspection by domain expert |
| Residual analysis | Where does model diverge? | `actual - predicted` by mana bucket |
| Vanilla minion test | Do no-effect cards score ≈ 0? | Filter vanilla minions, check score distribution |
| Cross-validation | Is model over-fit? | K-fold CV if using regression |
| Wilcoxon signed-rank | Is V2 significantly better? | Compare paired scores on same card set |
| Distribution shape | Is output well-behaved? | Histogram + normality test |

---

## Critical Rules

1. **No live API calls during analysis.** Data acquisition is Phase 1 only. All analysis reads from cache.
2. **Every model change needs quantitative justification.** "I think keywords should be worth more" is not acceptable. "Cards with keyword X have average deficit 3.2, suggesting value should be at least 3.0" is.
3. **Acceptance criteria are written BEFORE implementation.** Never adjust criteria to fit results.
4. **State assumptions explicitly.** Every phase starts with "we assume X because Y."
5. **Persist everything.** Each phase writes output files. Analysis is reproducible from cached data + scripts.
6. **Chinese card text uses regex, not NLP.** Card descriptions follow predictable patterns. Full NLP is over-engineering.
7. **Validate with constraint, not just fit.** Goodness-of-fit is necessary but not sufficient. Parameters must also be physically meaningful (e.g., mana scaling exponent should be sub-linear).

---

## Common Mistakes

| ❌ Don't | ✅ Do Instead |
|---------|-------------|
| Skip EDA, jump to modeling | Always run full EDA first — it reveals assumptions |
| Use ML because it's "better" | Start with interpretable formulas; ML only if parametric fails |
| Adjust acceptance criteria after results | Pre-commit criteria; if model fails, fix the model |
| Model all card types together | Separate minion/spell/weapon/location — they have different value axes |
| Trust a single validation method | Use at least 3: face validity + residual analysis + distribution check |
| Proceed despite failed validation gate | STOP. Diagnose. Fix. Then proceed. |
| Over-fit to current card pool | Prefer simpler models that generalize across set rotations |
| Ignore the mana scaling dimension | Most card effects scale with mana cost; flat values miss this |

---

## File Organization

```
project/
├── data/                        # Phase 1 output
│   ├── raw_cards.json           # Raw API response
│   ├── cards_clean.json         # Cleaned + filtered
│   └── card_list.json           # Simplified summary
├── scripts/                     # All phases
│   ├── fetch_data.py            # P1: Acquisition
│   ├── analyze_eda.py           # P2: EDA
│   ├── score_v1.py              # P3: First-order model
│   ├── v2_curve.py              # P5: Refinement scripts
│   └── v2_keywords.py           # P5: Keyword calibration
├── output/                      # Analysis results
│   ├── v1_scores.json           # P3: Scored dataset
│   ├── v2_params.json           # P5: Fitted parameters
│   └── comparison.json          # P5: V1 vs V2 comparison
├── docs/                        # Design documents
│   ├── v1_model.md              # P3: Model assumptions
│   ├── critique.md              # P4: Flaw analysis
│   └── v2_design.md             # P5: Improved model spec
└── logs/                        # Execution logs
    ├── T001.md                  # Per-task execution log
    └── T002.md
```

---

## Academic References

- **Bursztein (2014)** — "I am a Legend: Hacking Hearthstone" — OLS regression for mana pricing, residual analysis for identifying overpowered cards
- **Dong (2023)** — Northeastern thesis — Cross-game mathematical model, Wilcoxon signed-rank test for validation
- **Zhang et al. (2025)** — U. Washington — Reward distribution framework, MCTS simulation + DBSCAN clustering
- **Eger & Sauma (2020)** — FDG — Bayesian inference for card prediction
- **Jaffe et al. (2012)** — AAAI — Restricted-play balance framework, game-theoretic win rate analysis

For detailed methodology comparisons, see [reference.md](reference.md).

---

## Integration with Agent Workflow

This skill produces structured outputs that feed into downstream systems:

- **Card scores** → Opponent prediction (card value priors for Bayesian inference)
- **Keyword values** → Decision engine (card evaluation during MCTS rollouts)
- **Text effect parser** → Card recognition (effect type matching from visual detection)
- **Score distributions** → Balance analysis (identifying outlier cards for nerf/buff candidates)

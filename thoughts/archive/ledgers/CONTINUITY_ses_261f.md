---
session: ses_261f
updated: 2026-04-18T02:55:29.943Z
---

# Session Summary

## Goal
Build an AI decision engine for Hearthstone standard mode that evaluates all decision points (play cards, attack, hero power) with random effects (Discover, Dark Gift, random generation) using mathematical modeling to find the **highest expected value** option, then ranks decisions for the player.

## Constraints & Preferences
- **Hardware**: i5-12400F (6C/12T), RTX 4060 8GB VRAM, 16GB RAM, Hearthstone runs on same machine
- **Card pool**: Standard mode only, ~1015 cards (from iyingdi API, total reported: 1015)
- **Tech**: Python 3.12, Windows 11, PowerShell 5.1 (use `; if ($?) { }` not `&&`)
- **Commands**: `python` not `python3`, `Remove-Item -Recurse -Force` not `rm -rf`
- **Skills directory**: `D:\code\game\skills\{name}/` (not global)
- **Git convention**: `feat(task/T001): 简述`, `fix(task/T002): ...`, `analysis(task/T003): ...`
- **Gitignored**: `*.db`, `hs_cards/images/`, `hs_cards/crops/`
- **Card text locale**: Chinese (zhCN)
- **No full simulator**: User explicitly confirmed — lightweight expected-value modeling approach
- **Random effects must be modeled analytically**: Discover, Dark Gift, random generation — all via expected value calculation, not simulation
- **Must consider**: opponent class → Top 5 meta decks (HSReplay) → Bayesian deck inference → predict opponent future plays → adjust EV dynamically
- **Must include**: Location (地标) benefits, card pool definitions per random effect, Discover rules (self-exclusion, class ×4 weight, type/cost/race filters)

## Progress
### Done
- [x] **V2 three-layer card value model designed** — Layer 1: `a*mana^b+c`, Layer 2: keyword tiers with mana scaling, Layer 3: text effect budget table; doc at `thoughts/shared/designs/2026-04-17-hearthstone-card-model-v2-design.md`
- [x] **iyingdi API fully decoded** — POST form-encoded, `ignoreHero=1` critical, `standard=1` returns 1015 cards, paginated, fields: mana/attack/hp/rule(HTML)/cname/ename/rarity/race/mechanics/img etc.
- [x] **HDT analysis report** — C# .NET 4.7.2, WPF, plugin system IPlugin.OnUpdate(~100ms), game state from log parsing + HearthMirror memory; report at `thoughts/shared/designs/2026-04-18-hdt-analysis-report.md`
- [x] **14 GitHub projects surveyed** — hearthstone-ai (MO-MCTS+NN, 79%), fireplace (Python sim, 4.2 games/sec, no deepcopy — blockers), HS_SPR_CAL (exhaustive lethal), SilverFish (heuristic), card2code (DeepMind); report at `thoughts/shared/designs/2026-04-18-hearthstone-projects-survey.md`
- [x] **EV decision engine design created and updated** — Three-tier EV framework (Tier 1 precomputed, Tier 2 state-aware, Tier 3 branching lookahead) + 6 evaluation sub-models; doc at `thoughts/shared/designs/2026-04-18-ev-decision-engine-design.md`
- [x] **Scenario coverage analysis completed** — 9 scenarios evaluated, overall ~79% coverage with 6 sub-models
- [x] **6 sub-models designed**: A(Board Eval+Hand+Location), B(Opponent Threat), C(Lingering Effects), D(Trigger Probability), E(Meta Intelligence/HSReplay/Bayesian), F(Card Pool+Discover Rules)
- [x] **Key historical info saved to persistent memory** (aivectormemory) — 9 entries covering: project overview, constraints, V2 model formulas, iyingdi API details, open-source survey, HDT analysis, EV engine design, 6 sub-models + Meta layer, Location modeling
- [x] **iyingdi paginated scraper written** — `scripts/scrape_iyingdi_standard.py` (not yet run)

### In Progress
- [ ] **Fetching all 1015 standard cards from iyingdi** — scraper written, needs to be executed

### Blocked
- (none)

## Key Decisions
- **Lightweight custom approach over full simulators**: fireplace (4.2 games/sec, no deepcopy) and hearthstone-ai (frozen 2017) both impractical
- **Python over C++**: V2 model in Python, C++ simulators too complex to maintain
- **Expected value modeling over Monte Carlo simulation**: User confirmed — model Discover/Dark Gift/random effects analytically using pre-computed card values
- **Standard mode only (~1015 cards)**: Manageable card pool from iyingdi API
- **HDT Plugin + Python backend (方案 B)**: Recommended — HDT plugin ~200 lines C# for game state bridge, Python AI backend for analysis
- **iyingdi API as sole data source**: Single source for Chinese card data, replaces Blizzard CN + HearthstoneJSON
- **HSReplay API for meta intelligence**: Built-in HDT key `089b2bc6-3c26-4aab-adbe-bcfd5bb48671`, fetch Top 5 decks per class
- **6 sub-models added** to cover 9 real-game scenarios: Board Eval, Opponent Threat, Lingering Effects, Trigger Probability, Meta Intelligence (Bayesian deck inference), Card Pool & Discover Rules
- **Discover rules engine**: Self-exclusion, class cards ×4 weight, type/cost/race/class filters, standard-only restriction

## Next Steps
1. **Run `scripts/scrape_iyingdi_standard.py`** — fetch all 1015 standard cards from iyingdi API (paginated)
2. **Analyze fetched card data** — verify total count, distribution by class/type/rarity/mechanics, catalog all random effects and their pools
3. **Build Card Pool Database** — parse card texts to define precise random effect pools (Sub-Model F)
4. **Build Discover Rules Engine** — implement self-exclusion, class weighting, type/cost/race filtering
5. **Implement V2 Card Model (T001-T005)** — curve fitting, keyword calibration, text parser, card types, composite scoring using the full 1015-card dataset
6. **Integrate HSReplay API** — fetch Top 5 decks per class, cache to SQLite (Sub-Model E)
7. **Build Bayesian deck inference** — real-time opponent deck detection from seen cards
8. **Build lightweight board state representation** — Python dataclass with fast copy
9. **Implement action enumeration** — all legal plays, attacks, hero power from game state
10. **Implement three-tier EV calculator** — Tier 1 lookup + Tier 2 state adjustment + Tier 3 branching lookahead, integrated with 6 sub-models

## Critical Context

### iyingdi API
- **Endpoint**: `https://api2.iyingdi.com/hearthstone/card/search/vertical`
- **Method**: POST, `application/x-www-form-urlencoded; charset=UTF-8`
- **Critical param**: `ignoreHero=1` — without it only 30 hero cards return
- **Params**: `standard=1`, `page`, `size` (max ~50)
- **Response**: `{ success: true, data: { cards: [...], total: 1015 } }`
- **Card fields**: id, gameid (dbfId), cname, ename, mana, attack, hp, rule (HTML with `<b>` tags), description, clazz (随从/法术/武器), faction (Warlock/Druid etc.), rarity (Chinese: 史诗/传说/稀有/普通/免费), race, series, seriesAbbr (IED/EWT/LCU/DOR/ATT/EOI/CAT/CS2026/GIFT), seriesName, img, thumbnail, standard/wild/arena flags, runeCost, relatedCard
- **9 standard series**: IED(145), EWT(39), LCU(145), DOR(38), ATT(145), EOI(38), CAT(135), CS2026(289), GIFT(11) ≈ 1015 total
- **Current data**: `iyingdi_standard_full.json` has only 20 cards (first page), `iyingdi_all_standard.json` will have all 1015 after scraper runs

### V2 Card Model Formulas
- **L1**: `expected_stats(mana) = a * mana^b + c` (scipy curve_fit)
- **L2**: `keyword_value = base_value * (1 + 0.1 * mana_cost)` — Power/Mechanical/Niche tiers
- **L2 calibrated bases**: WINDFURY 4.5, DIVINE_SHIELD 3.5, DISCOVER 2.9, BATTLECRY 2.9, DEATHRATTLE 2.8, RUSH 2.3, TAUNT 2.3, LIFESTEAL 2.0, STEALTH 1.5, CHARGE 1.1
- **L3 effects**: Summon stats×0.5, Damage N×0.7, Draw N×1.5, AOE N×0.5×3, Generate 2.5/card, Copy 2.0/card, Buff N×0.5, Heal N×0.3, Destroy 4.0, Mana reduction ×1.0, Armor N×0.4, Silence 1.5, Conditional ×0.6
- **Score**: `card_value - fair_value`, >3 over-budget, [-3,3] balanced, <-3 under-budget

### EV Decision Engine — 6 Sub-Models
- **A: Board State Eval** — friendly/enemy board value, hand synergy (curve/combo/resources), Location activation EV (charges × effect × context)
- **B: Opponent Threat** — kill minion EV = V2 × threat_multiplier (Charge/Rush ×1.5, Taunt ×1.0, vanilla ×0.7), board clear EV, hand disruption, deck disruption
- **C: Lingering Effects** — time discount 0.85^n, Weapon (atk×expected_attacks), Dormant (awakened_val×trigger_prob - delay_cost), Aura (impact×duration×affected_count), Secret (effect×trigger_prob), Location (charges×per_activation_EV)
- **D: Trigger Probability** — Deathrattle survival_prob (Taunt+20%, Stealth+30%, base 60-70% removal), Random target E[impact]/targets, Dark Gift weighted avg×suitability, Random summon pool_mean×board_factor
- **E: Meta Intelligence** — HSReplay API Top 5 decks/class, Bayesian inference: `P(deck_i|seen_X) = P(seen_X|deck_i)×P(deck_i)/P(seen_X)`, lock at P>60%, predict future plays from remaining decklist, class-specific adjustments (vs aggro taunt+30%, vs control value+20%, vs combo disruption+40%)
- **F: Card Pool & Rules** — per-card random effect pool definition, Discover rules: self-exclusion, class ×4 weight, standard-only, type/cost/race/class filters, precomputed pool size N + E[max of 3] for Discover

### Discover Order Statistics Formula
```
E[max of k draws] = sum(v_i * [i^k - (i-1)^k]) / N^k
```
where v₁ ≤ v₂ ≤ ... ≤ vₙ are sorted card values in pool of N cards.

### HDT Integration
- **Plugin API**: `IPlugin.OnUpdate()` ~100ms tick, `API/GameEvents.cs` event hooks
- **Prebuilt DLLs** (no source): HearthDb.dll, HearthMirror.dll, HSReplay.dll, BobsBuddy.dll
- **HSReplay API key**: `089b2bc6-3c26-4aab-adbe-bcfd5bb48671`
- **Recommended**: 方案B — HDT plugin ~200 lines C# IPC bridge + Python AI backend

### Key Projects Referenced
- **hearthstone-ai** (326★): MO-MCTS + 25K param NN, 140-dim input, 79% accuracy, frozen 2017
- **fireplace** (728★): Python sim, 4.2 games/sec, no `__deepcopy__` (issue #342), no state hashing (issue #341) — both blockers
- **HS_SPR_CAL** (152★): Exhaustive lethal search with pruning — best lethal detection reference
- **SilverFish** (55★): Per-card behavior priority/cost tables — reference for V2 Layer 3
- **card2code** (245★, DeepMind): Card text → executable code — reference for text formalization

### Scenario Coverage (Final)
| # | Scenario | Coverage | Key Sub-Models |
|---|----------|----------|----------------|
| ① | Discover chain + recursion | 85% | F+A+Tier3 |
| ② | Self board/hand/deck | 85% | A+C |
| ③ | Opponent board/hand/deck | 80% | B+E |
| ④ | Cross-turn (weapon/dormant/aura/secret/location) | 80% | C |
| ⑤ | Dark Gift / buff附加 | 80% | D+F+A |
| ⑥ | Deathrattle/random summon/battlecry | 75% | D+F+Tier1 |
| ⑦ | Opponent deck inference | 80% | E |
| ⑧ | Opponent future play prediction | 70% | E |
| ⑨ | Hand synergy analysis | 75% | A |

## File Operations
### Read
- `D:\code\game\hs_cards\iyingdi_standard_full.json` (1188 lines, 20 cards, total reported: 1015)
- `D:\code\game\scripts\scrape_hs_cards.py` (222 lines, Blizzard CN API scraper — legacy)
- `D:\code\game\thoughts\shared\designs\2026-04-18-ev-decision-engine-design.md` (full read for editing)

### Modified
- `D:\code\game\thoughts\shared\designs\2026-04-18-ev-decision-engine-design.md` — **Major update**: replaced Open Questions + V2 Relationship sections with full 6 sub-models section (A through F), updated architecture diagram, updated data flow, updated error handling, updated testing strategy, scenario coverage matrix, all ~226 lines replaced with ~400+ lines of detailed sub-model specifications
- `D:\code\game\scripts\scrape_iyingdi_standard.py` — **Created**: paginated iyingdi scraper with `ignoreHero=1`, PAGE_SIZE=50, dedup by gameid, summary stats (by class/type/series/rarity/mana/mechanics/random effects), saves full + compact JSON output

### Created (this session)
- `D:\code\game\thoughts\shared\designs\2026-04-18-ev-decision-engine-design.md` — EV decision engine design doc
- `D:\code\game\scripts\scrape_iyingdi_standard.py` — iyingdi paginated scraper
- Memory entries saved: project overview, constraints, V2 model formulas, iyingdi API details, open-source survey, HDT analysis, EV engine design, 6 sub-models, Location modeling

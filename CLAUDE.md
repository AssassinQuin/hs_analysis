# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hearthstone AI decision analysis system. Two pipelines: GUI overlay tracker (active) and CLI decision loop (broken — search layer deleted). The active pipeline parses Power.log, tracks game state across turns, infers opponent hands via inverse MCTS + Bayesian particle filtering, and displays predictions in a PyQt5 overlay.

## Commands

```bash
# Setup
pip install -e .
pip install -e ".[dev]"
pip install PyQt5              # for overlay UI

# Fetch card data (run once)
python scripts/run_fetch.py

# Run
python tracker/app.py                          # PyQt5 overlay (main active entry)
python tracker/diagnostic_app.py               # Flask web diagnostics at localhost:5000
python tracker/verify.py                       # verify full pipeline against Power.log
python scripts/replay_game.py                  # offline log analysis
python scripts/run_world_tracker.py            # world tracker standalone
python scripts/extract_ground_truth.py         # extract opponent hand ground truth from Power.log
python scripts/validate_hand_predictions.py    # compare predictions vs ground truth JSON

# Test
pytest
pytest tests/test_power.py          # single file
pytest -m "not slow"
pytest tests/engine/                # engine-specific
pytest tests/evaluators/            # evaluator-specific
pytest tests/watcher/               # watcher-specific

# Other
python scripts/run_scoring.py       # score card pool
python scripts/update_deck_codes.py # update deck codes
```

## Architecture

### Active pipeline (GUI)

```
Power.log → LogMonitor (QThread)
  → GameTracker (hslog parser) + GlobalTracker (cross-turn state)
  → PowerLogGameStateBuilder → GameState
  → HandPredictor → OpponentHandMCTS (particle filter + inverse MCTS)
  → OverlayWindow (PyQt5)
```

### Key modules

- **`analysis/card/engine/`** — v2 game engine: GameState, legal actions, simulation (apply_action), mechanics (discover, deathrattle, secret, etc.)
- **`analysis/engine/`** — MCTS-UCT, opponent hand inference, particle filter, world model, PowerLogGameStateBuilder
- **`analysis/evaluators/`** — Board position evaluators: composite → BSV (tempo+survival+value) → SIV → submodel fallback
- **`analysis/scorers/`** — Offline card quality scoring (L1 vanilla → L7 HSReplay). NOT the same as evaluators/
- **`analysis/watcher/`** — Log file monitoring, game tracking (hslog), global state tracking, decision loop
- **`analysis/card/data/`** — HSCardDB (bilingual card database, singleton via get_db())
- **`analysis/utils/`** — Shared utilities: BayesianOpponent (deck archetype inference), DeckPoolTracker (sliding-window hand pool), DeckClassifier
- **`tracker/`** — PyQt5 overlay: LogMonitor (QThread), HandPredictor, OverlayWindow, DiagnosticApp (Flask)

### Key abstractions

- **GameState** (`analysis/card/engine/state.py`) — Full game state; supports deep copy for search tree nodes
- **World** (`analysis/engine/world_branch.py`) — Particle filter hypothesis: GameState + Bayesian weight
- **WorldManager** (`analysis/engine/particle_filter.py`) — SIR (Sequential Importance Resampling) over World particles
- **PowerLogGameStateBuilder** (`analysis/engine/powerlog_game_state_builder.py`) — Reconstructs GameState from hslog EntityCache + GlobalTracker. Two entry points: `build_from_tracker()` (own view) and `build_opponent_game_state()` (opponent view)
- **OpponentHandMCTS** (`analysis/engine/opponent_hand_mcts.py`) — Misnamed; actually Bayesian hand inference via opponent turn simulation, not tree search. Contains 5 classes including `HandWorld`, `BehaviorMatcher`, `MultiTurnProbabilityTracker`
- **DynamicProbabilityEngine** (`analysis/engine/dynamic_probability.py`) — Hypergeometric distribution P(card in hand | observed), integrates WorldModelEvidence to replace hardcoded biases
- **WorldModelEvidence** (`analysis/engine/world_model.py`) — Evidence accumulator that drives probability adjustments (replaces hardcoded hold-duration / mulligan / co-occurrence heuristics)
- **CardEffectInferenceEngine** (`analysis/engine/card_effect_inference.py`) — Parses card text to infer conditional holdings (e.g. "if you're holding a Dragon" → infer dragon)
- **BayesianOpponent** (`analysis/utils/bayesian_opponent.py`) — Sequential Bayesian updates on deck archetype priors using HSReplay signature data
- **DeckPoolTracker** (`analysis/utils/deck_pool_tracker.py`) — Sliding-window pool of possible cards in hand when zone reveals are absent

### Opponent Scoring (Strategy Pattern)

`analysis/engine/opponent_scoring.py` provides the shared scoring interface:

- **`OpponentScorer`** (ABC): `score(state, action) -> float` and `select(state, actions) -> Action`
- **`HeuristicRolloutScorer`**: Weighted random sampling for MCTS rollout phase (`mcts_uct.py:_heuristic_rollout()`)
- **`GreedyActionScorer`**: Best-action selection for opponent hand inference (`OpponentTurnSimulator` in `opponent_hand_mcts.py`)

### Duplicated logic to be aware of

- **Two GameState builders**: `StateBridge` (CLI, `analysis/watcher/state_bridge.py`) vs `PowerLogGameStateBuilder` (GUI) — GUI version is more complete

## Code Style

- Python 3.10+ with type annotations
- snake_case functions/variables, PascalCase classes
- Chinese comments for domain logic
- Relative imports: `from analysis.card.models.card import Card`
- Tests use `make_card()` and `make_state()` fixtures from `tests/conftest.py`; `tests/engine/game5/` and `tests/engine/game7/` have their own `conftest.py` with real-game fixtures
- `GlobalTracker` is a 1551-line god object; `OpponentHandMCTS` is 2025+ lines with 5 classes in one file

## Configuration

- `cfg/live.cfg` — Runtime: log paths (multi-platform candidates), MCTS params, output verbosity
- `analysis/config.py` — Module constants, API keys, data directories
- `.env` — HSREPLAY_API_KEY

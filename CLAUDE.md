# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hearthstone AI decision analysis system. Two pipelines: GUI overlay tracker (active) and CLI decision loop (broken — search layer deleted). The active pipeline parses Power.log, tracks game state across turns, infers opponent hands via inverse MCTS + Bayesian particle filtering, and displays predictions in a PyQt5 overlay.

## Architecture

### Opponent Scoring Architecture (Strategy Pattern)

Opponent action scoring uses the **Strategy Pattern** via `analysis/engine/opponent_scoring.py`:

- **`OpponentScorer`** (ABC): Abstract interface with `score(state, action) -> float` and `select(state, actions) -> Action`
- **`HeuristicRolloutScorer`**: Weighted random sampling for MCTS rollout phase. Used by `mcts_uct.py:_heuristic_rollout()`. Evaluates attack trades, play card efficiency, and hero power priority.
- **`GreedyActionScorer`**: Greedy best-action selection for opponent hand inference. Used by `OpponentTurnSimulator` in `opponent_hand_mcts.py`. Uses CompositeEvaluator with heuristic fallback.

Both scorers previously had independent implementations (_score_opponent_action in mcts_uct.py, _select_best_action+_evaluate_state in opponent_hand_mcts.py) that were extracted into the shared strategy module.

## Commands

```bash
# Setup
pip install -e .
pip install -e ".[dev]"
pip install PyQt5              # for overlay UI

# Fetch card data (run once)
python scripts/run_fetch.py

# Run
python tracker/app.py               # PyQt5 overlay (main active entry)
python scripts/replay_game.py       # offline log analysis
python scripts/run_world_tracker.py # world tracker standalone

# Test
pytest
pytest tests/test_power.py          # single file
pytest -m "not slow"
pytest tests/engine/                # engine-specific

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
- **`analysis/evaluators/`** — Board position evaluators: composite → BSV (tempo+survival+value) → submodel fallback
- **`analysis/scorers/`** — Offline card quality scoring (L1 vanilla → L7 HSReplay). NOT the same as evaluators/
- **`analysis/watcher/`** — Log file monitoring, game tracking (hslog), global state tracking, decision loop
- **`analysis/card/data/`** — HSCardDB (bilingual card database, singleton via get_db())
- **`tracker/`** — PyQt5 overlay: LogMonitor (QThread), HandPredictor, OverlayWindow

### Key abstractions

- **GameState** (`analysis/card/engine/state.py`) — Full game state; supports deep copy for search tree nodes
- **World** (`analysis/engine/world_branch.py`) — Particle filter hypothesis: GameState + Bayesian weight
- **PowerLogGameStateBuilder** — Reconstructs GameState from hslog EntityCache + GlobalTracker
- **OpponentHandMCTS** — Misnamed; actually Bayesian hand inference via opponent turn simulation, not tree search

### Duplicated logic to be aware of

- **Two GameState builders**: `StateBridge` (CLI) vs `PowerLogGameStateBuilder` (GUI) — GUI version is more complete

## Code Style

- Python 3.10+ with type annotations
- snake_case functions/variables, PascalCase classes
- Chinese comments for domain logic
- Relative imports: `from analysis.card.models.card import Card`
- Tests use `make_card()` and `make_state()` fixtures from `tests/conftest.py`
- `GlobalTracker` is a 1550-line god object; `OpponentHandMCTS` is 1620+ lines with 5 classes in one file

## Configuration

- `cfg/live.cfg` — Runtime: log paths, MCTS params, output verbosity
- `analysis/config.py` — Module constants, API keys, data directories
- `.env` — HSREPLAY_API_KEY

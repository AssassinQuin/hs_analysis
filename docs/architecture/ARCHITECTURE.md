# Project Architecture

## Overview

**hs_analysis** is a comprehensive Hearthstone card analysis toolkit that builds mathematical models to quantify card value and support game decision-making. The project evolved from simple card evaluation to a sophisticated decision engine with multiple scoring models and search capabilities.

**Purpose**: Quantify card value through mathematical modeling, from single-card evaluation to complete game decision support.

## Tech Stack

- **Language**: Python 3.10+
- **Math Libraries**: NumPy, SciPy
- **Data Processing**: JSON-based card data, SQLite caching
- **Testing**: pytest framework
- **External APIs**: HearthstoneJSON, HSReplay, iyingdi
- **Build System**: setuptools with pyproject.toml

## Directory Structure

```
hs_analysis/
├── hs_analysis/                    # Core analysis library
│   ├── __init__.py                # Package initialization
│   ├── config.py                   # Centralized configuration & paths
│   ├── models/                     # Data models
│   │   ├── __init__.py
│   │   └── card.py                 # Unified Card dataclass & factories
│   ├── data/                      # Data processing & indexing
│   │   ├── __init__.py
│   │   ├── card_index.py          # O(1) multi-attribute card index
│   │   ├── card_cleaner.py        # Data cleaning pipeline
│   │   ├── fetch_hsjson.py        # HearthstoneJSON API client
│   │   ├── fetch_hsreplay.py      # HSReplay API client
│   │   ├── fetch_iyingdi.py       # iyingdi API client
│   │   ├── build_unified_db.py    # Unified database construction
│   │   └── build_wild_db.py       # Wild format database
│   ├── scorers/                   # Card evaluation engines
│   │   ├── __init__.py
│   │   ├── vanilla_curve.py       # Vanilla curve baseline (power law)
│   │   ├── v2_engine.py           # V2 scoring engine (full rarity)
│   │   ├── v7_engine.py           # V7 performance-based scoring
│   │   ├── v8_contextual.py       # V8 contextual awareness
│   │   ├── l6_real_world.py       # L6 real-world data
│   │   └── constants.py           # Scoring constants & parameters
│   ├── evaluators/                # Multi-objective evaluation
│   │   ├── __init__.py
│   │   ├── composite.py           # Composite evaluation
│   │   ├── submodel.py            # Sub-model evaluation
│   │   └── multi_objective.py    # Multi-objective optimization
│   ├── search/                    # Decision search engine
│   │   ├── __init__.py
│   │   ├── rhea_engine.py         # RHEA rolling horizon evolution
│   │   ├── game_state.py          # Game state management
│   │   ├── lethal_checker.py      # Lethal detection
│   │   ├── opponent_simulator.py  # Opponent modeling
│   │   ├── risk_assessor.py       # Risk assessment
│   │   └── action_normalize.py    # Action normalization
│   └── utils/                     # Utility functions
│       ├── __init__.py
│       ├── score_provider.py      # Score data provider
│       ├── bayesian_opponent.py   # Bayesian opponent modeling
│       └── spell_simulator.py    # Spell effect simulation
├── scripts/                       # CLI entry points & tools
│   ├── run_fetch.py               # Data collection runner
│   ├── run_rhea.py                # RHEA engine runner
│   ├── run_score_v2.py            # V2 scoring runner
│   ├── run_score_v7.py            # V7 scoring runner
│   ├── analyze_meta_decks.py      # Meta deck analysis
│   ├── deep_analysis.py           # Deep analysis tools
│   ├── decision_presenter.py      # Decision visualization
│   ├── pool_quality_generator.py  # Card pool quality reports
│   ├── rewind_delta_generator.py  # Rewind delta analysis
│   └── diag_*.py                  # Diagnostic tools
├── tests/                         # Test suite
│   ├── __init__.py
│   ├── test_card_index.py         # Card index functionality
│   ├── test_card_cleaner.py       # Data cleaning tests
│   ├── test_wild_dedup.py         # Wild format deduplication
│   ├── test_score_provider.py     # Score provider tests
│   ├── test_v8_contextual_scorer.py # V8 scoring tests
│   └── test_v8_v9_regression.py   # Version regression tests
├── hs_cards/                      # Card data & reports
│   ├── unified_standard.json      # Standard format card database
│   ├── unified_wild.json          # Wild format card database
│   ├── v2_scoring_report.json     # V2 scoring results
│   ├── v7_scoring_report.json     # V7 scoring results
│   ├── card_list.json             # Card list summary
│   └── various_params.json        # Model parameters
├── libs/                          # External libraries
│   └── hearthstone-deckstrings/   # Deck string parsing library
├── research/                      # Research documentation
├── thoughts/                      # Project planning & design
├── .opencode/                     # OpenCode configuration
├── README.md                      # Main documentation
├── PROGRESS.md                    # Development progress log
├── pyproject.toml                 # Python project configuration
└── hearthstone_enums.json         # Game enums & constants
```

## Core Components

### Data Layer
- **Multi-source Data Integration**: Combines data from HearthstoneJSON, HSReplay, and iyingdi APIs
- **Unified Card Index**: O(1) lookup system supporting complex queries by mechanics, type, class, race, cost
- **Data Cleaning Pipeline**: Standardizes card data from multiple sources with deduplication

### Card Scoring Models
**Evolution of Scoring Engines**:
- **V2**: Vanilla curve fitting + keyword scoring + type adaptation
- **V7**: HSReplay performance-based scoring with real data
- **V8**: Contextual awareness (turn count, board saturation, race synergies)
- **L6**: Real-world composite scoring with multiple data sources

**Scoring Architecture**:
```
Score = L1 (Attribute Deviation) + L2 (Keyword Scoring) + L3 (Effect Parsing) + L5 (Conditional Expectation)
```

### Search Engine (RHEA)
**Rolling Horizon Evolution Algorithm**:
- Game state management with board representation
- Opponent simulation with Bayesian modeling
- Risk assessment and lethal detection
- Action normalization and pruning
- Top-K beam search (K=8, depth=2, <3s)

### Evaluation Framework
**Seven-Submodel EV System**:
- A: Board State (minions, hand, hero, buffs) - 776 cards
- B: Opponent Threats (damage, destroy, silence, freeze) - 315 cards  
- C: Persistent Effects (weapons, auras, secrets, locations) - 388 cards
- D: Trigger Probability (deathrattle, random, battlecry, infused) - 581 cards
- E: Environmental Intelligence (quests, discover, rewards) - 91 cards
- F: Card Pool (discover, shadowed, random) - 207 cards
- G: Player Choice (choice cards) - 23 cards, EV = max(A,B)

## Data Flow

### 1. Data Collection Pipeline
```
API Endpoints → JSON Parsing → Data Cleaning → Unified Database → Card Index
```

### 2. Scoring Pipeline
```
Card Data → Vanilla Curve Fit → Keyword Scoring → Text Parsing → Type Adaptation → Composite Score
```

### 3. Decision Pipeline
```
Game State → Action Enumeration → EV Calculation → Search → Optimal Action
```

## External Integrations

### APIs
- **HearthstoneJSON**: Primary data source for complete card data
- **HSReplay**: Performance data and archetype rankings  
- **iyingdi**: Arena data for validation

### External Libraries
- **hearthstone-deckstrings**: Deck string parsing and formatting

## Configuration Management

**Centralized Configuration** (`hs_analysis/config.py`):
- Path management using `pathlib.Path` for cross-platform compatibility
- API keys from environment variables (never hardcoded)
- Default scoring parameters and class multipliers
- Cache configuration and data file paths

## Build & Deploy

### Development Setup
```bash
# Install dependencies
pip install -e .

# Run tests
pytest

# Data collection
python scripts/run_fetch.py

# Scoring analysis
python scripts/run_score_v7.py

# Decision engine
python scripts/run_rhea.py
```

### Project Build
- Uses setuptools with pyproject.toml configuration
- Python 3.10+ required
- Optional dev dependencies for testing (pytest)

## Key Design Decisions

1. **Multi-Model Evolution**: Each scoring engine version builds upon previous learnings
2. **Data-Driven Approach**: Leverages real HSReplay data for performance validation
3. **Search vs Simulation**: Chooses light EV modeling over full simulation for efficiency
4. **Modular Architecture**: Clean separation between data, scoring, search, and evaluation layers
5. **Type Safety**: Extensive use of dataclasses and type hints throughout the codebase

## Performance Characteristics

- **Card Index**: O(1) queries with pre-computed multi-attribute indexes
- **Scoring Engine**: Processes ~1000 cards in seconds
- **Search Engine**: <3 second response time with depth-2 search
- **Memory Usage**: Efficient with lazy loading and caching strategies
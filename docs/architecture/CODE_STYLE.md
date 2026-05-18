# Code Style Guidelines

## Overview

This document outlines the coding conventions and patterns used throughout the hs_analysis codebase. The project follows Python best practices with emphasis on clarity, type safety, and mathematical precision.

## Language & Framework

- **Primary Language**: Python 3.10+
- **Type System**: Extensive use of type hints and dataclasses
- **Standard Library**: Heavy use of `pathlib`, `json`, `collections`, `re`, `logging`
- **Third-Party**: NumPy, SciPy for mathematical operations

## File Organization

### Package Structure
```
hs_analysis/
├── __init__.py              # Package exports, version info
├── config.py               # Centralized configuration
├── models/                 # Data models
├── data/                   # Data processing
├── scorers/                # Scoring algorithms
├── evaluators/             # Evaluation logic
├── search/                 # Search algorithms
└── utils/                  # Utilities
```

### Script Organization
```
scripts/
├── run_*.py               # Main entry points
├── analyze_*.py           # Analysis tools
├── fetch_*.py             # Data collection
└── diag_*.py              # Diagnostics
```

## Naming Conventions

### Files and Directories
- **Snake_case** for all file and directory names
- **Descriptive names**: `card_index.py`, `vanilla_curve.py`, `rhea_engine.py`
- **Consistent suffixes**:
  - `_engine.py` for scoring/search algorithms
  - `_provider.py` for data service classes
  - `_cleaner.py` for data processing utilities
  - `_index.py` for lookup systems
  - `_simulator.py` for simulation components

### Classes and Functions
- **PascalCase** for class names
- **snake_case** for function and method names
- **Private members** prefixed with underscore (`_private_method`)
- **Constants** in UPPER_SNAKE_CASE

### Variables
- **snake_case** for all variable names
- **Descriptive names**: `curve_popt`, `card_pool`, `mechanics_list`
- **Loop variables**: `card` not `c`, `index` not `i`
- **Boolean variables**: `has_effect`, `is_active`

### Type Aliases
```python
# Used for complex types
CardDict = Dict[str, Any]
MechanicList = List[str]
ScoreComponents = Tuple[float, float, float, List[str]]
```

## Import Style

### Import Organization
```python
# Standard library imports first
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports second
import numpy as np
from scipy.optimize import curve_fit

# Local imports last (with relative paths)
from hs_analysis.config import DATA_DIR
from hs_analysis.models.card import Card
from hs_analysis.scorers.constants import KEYWORD_TIERS
```

### Import Guidelines
- **Group imports** in three sections: stdlib, third-party, local
- **Use relative imports** within the package: `from ..models.card import Card`
- **Import specific items** rather than entire modules where possible
- **Avoid wildcard imports** (`from module import *`)

## Data Models

### Dataclass Pattern
```python
@dataclass
class Card:
    """Unified card data model with factory methods."""
    
    # Required fields
    dbf_id: int = 0
    name: str = ""
    cost: int = 0
    card_type: str = ""  # MINION, SPELL, WEAPON, HERO
    
    # Optional fields with defaults
    attack: int = 0
    health: int = 0
    text: str = ""
    mechanics: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Initialize default fields after dataclass creation."""
        if self.mechanics is None:
            self.mechanics = []
    
    @classmethod
    def from_hsjson(cls, data: dict) -> "Card":
        """Factory method for HearthstoneJSON format."""
        return cls(
            dbf_id=data.get("dbfId", 0),
            name=data.get("name", ""),
            # ... other fields
        )
```

### Model Guidelines
- **Use dataclasses** for structured data
- **Provide factory methods** for different data sources
- **Include type hints** for all fields
- **Add docstrings** explaining field purposes
- **Use `__post_init__`** for complex initialization logic

## Mathematical Code

### Scoring Functions
```python
def score_minion(card: CardDict, curve_popt: List[float], baselines: Dict) -> ScoreComponents:
    """Score a minion card using the V2 engine."""
    
    # Extract base attributes
    mana = max(card.get("cost", 0), 0)
    actual = card.get("attack", 0) + card.get("health", 0)
    
    # Calculate expected attributes using power law
    cls_mult = CLASS_MULTIPLIER.get(card.get("cardClass"), 1.0)
    expected = power_law(mana, *curve_popt) * cls_mult
    
    # Layer 1: Attribute deviation
    l1 = actual - expected
    
    # Layer 2: Keyword scoring
    l2, kw = calc_keyword_score(card, curve_popt)
    
    # Layer 3: Effect parsing
    l3, eff = parse_text_effects(card.get("text", ""))
    
    # Layer 5: Conditional expectation
    base_l2l3 = l2 + l3
    l5, cond = calc_conditional_ev(card, base_l2l3)
    
    return (l1 + base_l2l3 + l5, l1, l2, l3, kw, eff, l5, cond)
```

### Mathematical Guidelines
- **Descriptive variable names**: `curve_popt` (curve parameters optimized), `cls_mult` (class multiplier)
- **Clear formula documentation**: Comments explaining each mathematical layer
- **Type safety**: Use `float` explicitly for mathematical operations
- **Error handling**: Graceful handling of edge cases (negative costs, missing fields)
- **Vectorization**: Use NumPy arrays for batch operations where appropriate

## Configuration Management

### Centralized Configuration
```python
# config.py - All paths, API keys, and defaults
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "hs_cards"

# API configuration with environment fallback
HSREPLAY_API_KEY = os.environ.get("HSREPLAY_API_KEY", "")
HSREPLAY_CARDS_URL = "https://hsreplay.net/api/v1/cards/?game_type=RANKED_STANDARD"

# Default parameters with scientific justification
DEFAULT_CURVE_P0 = [3.0, 0.7, 0.0]
DEFAULT_CURVE_BOUNDS = ([0.1, 0.3, -5.0], [10.0, 1.5, 10.0])
```

### Configuration Guidelines
- **Use pathlib.Path** for cross-platform path handling
- **Environment variables** for sensitive data (API keys)
- **Scientific documentation** of parameter choices
- **Type hints** for configuration values
- **Validation functions** for data integrity

## Error Handling

### Exception Patterns
```python
def fetch_hsreplay_data(api_key: str) -> List[CardDict]:
    """Fetch card data from HSReplay API."""
    try:
        response = requests.get(
            HSREPLAY_CARDS_URL,
            headers=get_api_headers(),
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    
    except requests.RequestException as e:
        logger.error(f"HSReplay API error: {e}")
        raise DataFetchError(f"Failed to fetch HSReplay data: {e}")
    
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {e}")
        raise DataFormatError(f"Invalid JSON response: {e}")

# Custom exceptions
class HSAnalysisError(Exception):
    """Base exception for hs_analysis errors."""
    pass

class DataFetchError(HSAnalysisError):
    """Data fetch failed."""
    pass
```

### Error Handling Guidelines
- **Custom exception hierarchy** for different error types
- **Specific exception types** rather than generic Exception
- **Error logging** with context information
- **Graceful degradation** where possible
- **User-friendly messages** for end users

## Logging

### Logging Pattern
```python
# Module-level logger
logger = logging.getLogger(__name__)

def process_cards(cards: List[CardDict]) -> List[ScoredCard]:
    """Process and score cards."""
    logger.info(f"Processing {len(cards)} cards")
    
    try:
        scored_cards = []
        for card in cards:
            try:
                score = calculate_card_score(card)
                scored_cards.append(score)
            except Exception as e:
                logger.warning(f"Failed to score card {card.get('name', 'unknown')}: {e}")
                continue
        
        logger.info(f"Successfully scored {len(scored_cards)} cards")
        return scored_cards
    
    except Exception as e:
        logger.error(f"Card processing failed: {e}")
        raise
```

### Logging Guidelines
- **Module-level loggers** using `__name__`
- **Appropriate log levels**: DEBUG for detailed info, INFO for normal operations, WARNING for recoverable errors, ERROR for failures
- **Contextual information** in log messages
- **Error logging** with stack traces for debugging
- **Performance logging** for long-running operations

## Testing Patterns

### Test Structure
```python
# test_card_index.py
class TestCardIndex:
    """Test suite for CardIndex functionality."""
    
    def test_index_construction(self):
        """Test index construction with sample data."""
        cards = [
            {"dbfId": 1, "name": "Test Card", "cost": 1, "type": "MINION", "cardClass": "MAGE"},
            # ... more test data
        ]
        index = CardIndex(cards)
        assert index.total == 2
        assert index.get_by_dbf(1) is not None
    
    def test_pool_query(self):
        """Test multi-attribute pool queries."""
        index = get_index()
        taunt_minions = index.get_pool(mechanics="TAUNT", card_type="MINION")
        assert all(c.get("type") == "MINION" for c in taunt_minions)
        
        # Test discover pool
        discover_pool = index.discover_pool("MAGE")
        assert len(discover_pool) > 0
```

### Testing Guidelines
- **Comprehensive test coverage** for core functionality
- **Edge case testing** for boundary conditions
- **Mock external dependencies** for API calls
- **Test data fixtures** for consistent testing
- **Integration tests** for complex workflows

## Code Patterns

### Factory Methods
```python
class CardFactory:
    """Factory for creating Card objects from different sources."""
    
    @staticmethod
    def create_from_hsjson(data: dict) -> Card:
        """Create Card from HearthstoneJSON format."""
        return Card.from_hsjson(data)
    
    @staticmethod
    def create_from_iyingdi(data: dict) -> Card:
        """Create Card from iyingdi format."""
        return Card.from_iyingdi(data)
```

### Builder Pattern
```python
class QueryBuilder:
    """Builder for complex card queries."""
    
    def __init__(self):
        self._filters = {}
    
    def with_class(self, card_class: str) -> "QueryBuilder":
        self._filters["card_class"] = card_class
        return self
    
    def with_mechanic(self, mechanic: str) -> "QueryBuilder":
        self._filters["mechanics"] = mechanic
        return self
    
    def build(self) -> Dict[str, Any]:
        return self._filters
```

### Decorator Pattern
```python
def timing_decorator(func):
    """Decorator to measure function execution time."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start
        logger.debug(f"{func.__name__} executed in {duration:.2f}s")
        return result
    return wrapper
```

## Do's and Don'ts

### Do ✅
- Use descriptive variable names and meaningful comments
- Follow Python type hints consistently
- Write comprehensive docstrings for all public functions
- Use dataclasses for structured data
- Implement proper error handling and logging
- Write tests for all core functionality
- Follow the established directory structure

### Don't ❌
- Use hardcoded values (use configuration instead)
- Ignore type hints in mathematical calculations
- Use overly clever optimizations that hurt readability
- Skip error handling in data processing functions
- Write functions that do more than one logical operation
- Use global variables (use dependency injection instead)
- Ignore performance bottlenecks in data-intensive operations

## Documentation Standards

### Docstring Format
```python
def calculate_vanilla_curve(cards: List[CardDict]) -> List[float]:
    """Calculate power law parameters for vanilla minion curve.
    
    Fits the expected mana curve using a power law model:
    expected_stats = a * mana^b + c
    
    Args:
        cards: List of minion card data dictionaries
        
    Returns:
        List of [a, b, c] parameters for power law fit
        
    Raises:
        ValueError: If insufficient data for fitting
        
    Example:
        >>> cards = [{"cost": 1, "attack": 2, "health": 3}, ...]
        >>> params = calculate_vanilla_curve(cards)
        >>> expected = power_law(3, *params)  # Expected stats at 3 mana
    """
    # Implementation
```

### Documentation Requirements
- **Module docstrings** explaining purpose and scope
- **Function docstrings** with Args/Returns/Raises sections
- **Class docstrings** explaining class responsibilities
- **Inline comments** for complex algorithms
- **Example usage** where helpful
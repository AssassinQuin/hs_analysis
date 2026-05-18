"""executor.py — High-level action executor.

Orchestrates the full pipeline:
  parse → validate → resolve targets → apply effects

This is the main entry point for consuming the effects system.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from analysis.effects.parser import parse as parse_card
from analysis.effects.rules.validator import is_action_legal
from analysis.effects.simulation.resolver import EffectResolver
from analysis.effects.types import (
    Action, ActionKind, Effect, ParsedCard,
)

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


class EffectExecutor:
    """Execute a parsed card effect against a game state.

    Usage:
        executor = EffectExecutor()
        result = executor.execute_card(state, "CORE_EX1_012")
        for step in result:
            print(step)  # logs effect resolution
    """

    def __init__(self) -> None:
        self._resolver = EffectResolver()

    # ════════════════════════════════════════════════════════════
    # Public API
    # ════════════════════════════════════════════════════════════

    def execute_card(self, state: GameState, card_id: str,
                     text: str = "", **context: Any) -> ExecutionResult:
        """Parse and execute a card's effects.

        Args:
            state: Current GameState (will be mutated).
            card_id: Card ID to resolve.
            text: English text fallback.
            **context: Extra context (target_override, etc.)

        Returns:
            ExecutionResult with resolution steps.
        """
        parsed = parse_card(card_id, text)
        if parsed is None:
            return ExecutionResult(
                card_id=card_id,
                success=False,
                error=f"Card {card_id} not found",
            )

        return self.execute_parsed(state, parsed, **context)

    def execute_parsed(self, state: GameState, parsed: ParsedCard,
                       **context: Any) -> ExecutionResult:
        """Execute effects from an already-parsed card."""
        steps: list[EffectStep] = []

        for ability in parsed.abilities:
            for effect in ability.effects:
                resolved = self._resolver.apply(
                    state, effect, source_id=parsed.card_id,
                )
                for r in resolved:
                    steps.append(EffectStep(
                        effect=effect,
                        targets=list(r.target_ids),
                        note=r.resolution_note,
                    ))

        return ExecutionResult(
            card_id=parsed.card_id,
            success=True,
            steps=steps,
            parsed_card=parsed,
        )

    def validate_and_execute(self, state: GameState, action: Action,
                             parsed: ParsedCard | None = None
                             ) -> ExecutionResult:
        """Validate an action first, then execute if legal."""
        if not is_action_legal(state, action, parsed):
            return ExecutionResult(
                card_id=action.card_id,
                success=False,
                error="Action not legal",
            )

        if parsed is None and action.card_id:
            return self.execute_card(state, action.card_id)

        if parsed is not None:
            return self.execute_parsed(state, parsed)

        return ExecutionResult(
            card_id=action.card_id,
            success=True,
            steps=[],
        )


# ════════════════════════════════════════════════════════════════
# Result types
# ════════════════════════════════════════════════════════════════

@dataclass
class EffectStep:
    """One step in the effect resolution log."""
    effect: Effect
    targets: list[str]
    note: str = ""


@dataclass
class ExecutionResult:
    """Result of executing a card's effects."""
    card_id: str
    success: bool
    steps: list[EffectStep] = field(default_factory=list)
    parsed_card: ParsedCard | None = None
    error: str = ""




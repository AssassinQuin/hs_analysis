"""parser — Card ID + English text → ParsedCard.

Public API:
  parse(card_id: str, text: str = "") -> ParsedCard | None
"""

from analysis.effects.parser.interface import CardParser, parse

__all__ = ["CardParser", "parse"]

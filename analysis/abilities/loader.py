#!/usr/bin/env python3
"""loader.py — JSON ability loader that replaces runtime parsing.

Loads pre-built card abilities from analysis/data/card_abilities.json
instead of parsing card text at runtime.

Usage:
    python -m analysis.abilities.loader --build   # offline build
    python -m analysis.abilities.loader --card CS2_029  # inspect card
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from analysis.abilities.definition import (
    AbilityTrigger,
    CardAbility,
    ConditionKind,
    ConditionSpec,
    EffectKind,
    EffectSpec,
    TargetKind,
    TargetSpec,
)

log = logging.getLogger(__name__)

# ── Module-level cache ──────────────────────────────────────────
_cache: Optional[Dict[str, Any]] = None

# ── JSON file path ──────────────────────────────────────────────
_JSON_PATH = Path(__file__).parent.parent / "data" / "card_abilities.json"


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def load_abilities(card_id: str) -> List[CardAbility]:
    """Load abilities for a single card from JSON data."""
    data = _load_json_data()
    cards = data.get("cards", {})
    card_data = cards.get(card_id)
    if not card_data:
        return []
    abilities_json = card_data.get("abilities", [])
    return [_parse_ability(a) for a in abilities_json]


def load_all_abilities() -> Dict[str, List[CardAbility]]:
    """Load abilities for all cards. Returns {card_id: [CardAbility]}."""
    data = _load_json_data()
    result: Dict[str, List[CardAbility]] = {}
    for card_id, card_data in data.get("cards", {}).items():
        abilities_json = card_data.get("abilities", [])
        if abilities_json:
            result[card_id] = [_parse_ability(a) for a in abilities_json]
    return result


# ═══════════════════════════════════════════════════════════════
# Internal: JSON loading
# ═══════════════════════════════════════════════════════════════

def _load_json_data() -> dict:
    """Load the JSON file from disk. Cache result in module-level _cache."""
    global _cache
    if _cache is not None:
        return _cache
    if not _JSON_PATH.exists():
        log.debug("card_abilities.json not found at %s, returning empty dict", _JSON_PATH)
        _cache = {}
        return _cache
    try:
        raw = _JSON_PATH.read_text(encoding="utf-8")
        _cache = json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to load %s: %s", _JSON_PATH, e)
        _cache = {}
    return _cache


# ═══════════════════════════════════════════════════════════════
# Internal: Parsing (JSON → dataclass)
# ═══════════════════════════════════════════════════════════════

def _parse_ability(data: dict) -> CardAbility:
    """Convert JSON ability dict → CardAbility."""
    trigger = _parse_enum(AbilityTrigger, data.get("trigger", ""))
    if trigger is None:
        log.warning("Unknown trigger %r, skipping ability", data.get("trigger"))
        # Return a minimal ability with a fallback trigger
        trigger = AbilityTrigger.TRIGGER_VISUAL
    condition = _parse_condition(data["condition"]) if data.get("condition") else None
    effects = [_parse_effect(e) for e in data.get("effects", [])]
    return CardAbility(
        trigger=trigger,
        condition=condition,
        effects=effects,
        text_raw=data.get("text_raw", ""),
    )


def _parse_effect(data: dict) -> EffectSpec:
    """Convert JSON effect dict → EffectSpec."""
    from analysis.abilities.value_expr import to_lazy_value

    kind = _parse_enum(EffectKind, data.get("kind", ""))
    if kind is None:
        log.warning("Unknown effect kind %r, skipping effect", data.get("kind"))
        kind = EffectKind.ENCHANT  # fallback

    value_raw = data.get("value", 0)
    value2_raw = data.get("value2", 0)

    value = to_lazy_value(value_raw) if isinstance(value_raw, dict) else value_raw
    value2 = to_lazy_value(value2_raw) if isinstance(value2_raw, dict) else value2_raw

    target = _parse_target(data["target"]) if data.get("target") else None
    condition = _parse_condition(data["condition"]) if data.get("condition") else None

    return EffectSpec(
        kind=kind,
        value=value,
        value2=value2,
        subtype=data.get("subtype", ""),
        keyword=data.get("keyword", ""),
        target=target,
        condition=condition,
        text_raw=data.get("text_raw", ""),
    )


def _parse_target(data: dict) -> TargetSpec:
    """Convert target JSON → TargetSpec."""
    kind = _parse_enum(TargetKind, data.get("kind", ""))
    if kind is None:
        log.warning("Unknown target kind %r, defaulting to SINGLE_MINION", data.get("kind"))
        kind = TargetKind.SINGLE_MINION
    return TargetSpec(
        kind=kind,
        count=data.get("count", 1),
        side=data.get("side", ""),
        filters=data.get("filters", []),
    )


def _parse_condition(data: dict) -> ConditionSpec:
    """Convert condition JSON → ConditionSpec."""
    kind = _parse_enum(ConditionKind, data.get("kind", ""))
    if kind is None:
        log.warning("Unknown condition kind %r, defaulting to BOARD_STATE", data.get("kind"))
        kind = ConditionKind.BOARD_STATE
    return ConditionSpec(
        kind=kind,
        params=data.get("params", {}),
    )


def _parse_enum(enum_cls, value: str):
    """Safely convert a string to an enum value. Returns None on failure."""
    if not value:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return None


# ═══════════════════════════════════════════════════════════════
# Internal: Serialization (dataclass → JSON)
# ═══════════════════════════════════════════════════════════════

def _serialize_abilities(abilities: List[CardAbility]) -> list:
    """Convert List[CardAbility] → JSON-serializable list."""
    from analysis.abilities.value_expr import from_lazy_value

    result = []
    for ability in abilities:
        effects = []
        for eff in ability.effects:
            eff_dict: Dict[str, Any] = {"kind": eff.kind.value}
            # Serialize value
            if isinstance(eff.value, int):
                eff_dict["value"] = eff.value
            else:
                eff_dict["value"] = from_lazy_value(eff.value)
            # Serialize value2
            if isinstance(eff.value2, int):
                eff_dict["value2"] = eff.value2
            else:
                eff_dict["value2"] = from_lazy_value(eff.value2)
            if eff.subtype:
                eff_dict["subtype"] = eff.subtype
            if eff.keyword:
                eff_dict["keyword"] = eff.keyword
            if eff.target:
                eff_dict["target"] = {
                    "kind": eff.target.kind.value,
                    "count": eff.target.count,
                    "side": eff.target.side,
                    "filters": eff.target.filters,
                }
            if eff.condition:
                eff_dict["condition"] = {
                    "kind": eff.condition.kind.value,
                    "params": eff.condition.params,
                }
            if eff.text_raw:
                eff_dict["text_raw"] = eff.text_raw
            effects.append(eff_dict)

        entry: Dict[str, Any] = {"trigger": ability.trigger.value}
        if ability.condition:
            entry["condition"] = {
                "kind": ability.condition.kind.value,
                "params": ability.condition.params,
            }
        else:
            entry["condition"] = None
        entry["effects"] = effects
        if ability.text_raw:
            entry["text_raw"] = ability.text_raw
        result.append(entry)
    return result


# ═══════════════════════════════════════════════════════════════
# Offline Build Tool
# ═══════════════════════════════════════════════════════════════

def build_abilities_json() -> None:
    """Build JSON abilities data.

    Phase 3: Runtime parser removed. This function is kept for
    potential future rebuilds from alternative data sources.
    Currently raises NotImplementedError.
    """
    raise NotImplementedError(
        "build_abilities_json() requires the runtime parser "
        "(analysis.search.abilities.parser) which was removed in Phase 3. "
        "Use pre-built analysis/data/card_abilities.json instead."
    )


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--build" in args:
        build_abilities_json()
    elif "--card" in args:
        idx = args.index("--card")
        if idx + 1 < len(args):
            card_id = args[idx + 1]
            abilities = load_abilities(card_id)
            if abilities:
                for a in abilities:
                    print(a)
            else:
                print(f"No abilities found for {card_id}")
        else:
            print("Usage: python -m analysis.abilities.loader --card <CARD_ID>")
    else:
        print("Usage:")
        print("  python -m analysis.abilities.loader --build          Build JSON from parser")
        print("  python -m analysis.abilities.loader --card <CARD_ID> Inspect a card")

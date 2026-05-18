"""json_parser.py — Parse structured card abilities from card_abilities.json.

Reads the pre-built JSON database and produces Ability objects.

This parser handles the "fast path": when structured ability data exists,
we produce typed Ability objects directly without text inference.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from analysis.effects.types import (
    Ability, Effect, EffectKind, ParsedCard, TargetKind, TargetSpec, Trigger,
)

log = logging.getLogger(__name__)

# ── JSON data path ───────────────────────────────────────────

_JSON_PATH = (Path(__file__).parent.parent.parent
              / "card" / "data" / "card_abilities.json")


# ════════════════════════════════════════════════════════════════
# Trigger mapping: JSON string → Trigger enum
# ════════════════════════════════════════════════════════════════

_TRIGGER_MAP: dict[str, Trigger] = {
    "BATTLECRY": Trigger.BATTLECRY,
    "DEATHRATTLE": Trigger.DEATHRATTLE,
    "COMBO": Trigger.COMBO,
    "SPELLBURST": Trigger.SPELLBURST,
    "CHOOSE_ONE": Trigger.CHOOSE_ONE,
    "SECRET": Trigger.SECRET,
    "INSPIRE": Trigger.INSPIRE,
    "FRENZY": Trigger.FRENZY,
    "OUTCAST": Trigger.OUTCAST,
    "INFUSE": Trigger.INFUSE,
    "CORRUPT": Trigger.CORRUPT,
    "QUEST": Trigger.QUEST,
    "ACTIVATE": Trigger.ACTIVATE,
    "AURA": Trigger.AURA,
    "TRIGGER_VISUAL": Trigger.TRIGGER_VISUAL,
    "HERALD": Trigger.HERALD,
    "IMBUE": Trigger.IMBUE,
    "KINDRED": Trigger.KINDRED,
    "COLOSSAL": Trigger.COLOSSAL,
    "CORPSE": Trigger.CORPSE,
    "DORMANT": Trigger.DORMANT,
    "DARK_GIFT": Trigger.DARK_GIFT,
    "TURN_START": Trigger.TURN_START,
    "TURN_END": Trigger.TURN_END,
    "WHENEVER": Trigger.WHENEVER,
    "AFTER": Trigger.AFTER,
    "ON_ATTACK": Trigger.ON_ATTACK,
    "ON_DAMAGE": Trigger.ON_DAMAGE,
    "ON_SPELL_CAST": Trigger.ON_SPELL_CAST,
    "ON_DEATH": Trigger.ON_DEATH,
    "PASSIVE_COST": Trigger.PASSIVE_COST,
}


# ════════════════════════════════════════════════════════════════
# JsonAbilityParser
# ════════════════════════════════════════════════════════════════

class JsonAbilityParser:
    """Parse abilities from the structured card_abilities.json file.

    The JSON stores pre-built ability data generated offline.
    When actions are marked as "TODO", this parser returns [] so the
    ChainingParser falls through to text parsing.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] | None = None

    # ── Public API ────────────────────────────────────────────

    def parse_abilities(self, card_id: str,
                        meta: dict[str, Any] | None = None
                        ) -> list[Ability]:
        """Parse abilities for *card_id* from JSON data.

        Returns an empty list if:
        - Card is not in the JSON database.
        - All actions are still TODO (unbuilt).
        """
        if self._data is None:
            self._load()

        card_data = self._data.get("cards", {}).get(card_id)
        if not card_data:
            return []

        abilities_json = card_data.get("abilities", [])
        if not abilities_json:
            return []

        abilities: list[Ability] = []
        for ab_json in abilities_json:
            trigger_str = ab_json.get("trigger", "")
            trigger = _TRIGGER_MAP.get(trigger_str)
            if trigger is None:
                log.debug("JSON parser: unknown trigger %r for %s",
                          trigger_str, card_id)
                continue

            actions_json = ab_json.get("actions", [])
            # Skip abilities where all actions are TODO
            if actions_json and all(
                a.get("class") == "TODO" for a in actions_json
            ):
                continue

            effects = self._parse_actions(actions_json, card_id)
            if effects:
                abilities.append(Ability(
                    trigger=trigger,
                    effects=effects,
                    source_card_id=card_id,
                ))

        return abilities

    # ── Internal ──────────────────────────────────────────────

    def _parse_actions(self, actions: list[dict[str, Any]],
                       card_id: str) -> list[Effect]:
        """Convert JSON action objects → list[Effect].

        Each action has:
          "class": "DamageSpell" | "SummonSpell" | ...
          Plus class-specific fields.
        """
        effects: list[Effect] = []
        for action in actions:
            cls = action.get("class", "")
            if cls == "TODO":
                continue

            parser = _ACTION_PARSERS.get(cls)
            if parser is None:
                log.debug("No parser for action class %r (%s)", cls, card_id)
                continue

            try:
                eff = parser(action)
                if eff is not None:
                    effects.append(eff)
            except Exception as exc:
                log.warning("Failed to parse action %s for %s: %s",
                            cls, card_id, exc)

        return effects

    def _load(self) -> None:
        path = _JSON_PATH
        if not path.exists():
            log.warning("card_abilities.json not found at %s", path)
            self._data = {"cards": {}}
            return
        try:
            self._data = json.loads(path.read_text(encoding="utf-8"))
            log.info("JsonAbilityParser: loaded %d card entries",
                     len(self._data.get("cards", {})))
        except Exception as exc:
            log.error("Failed to load %s: %s", path, exc)
            self._data = {"cards": {}}


# ════════════════════════════════════════════════════════════════
# Action class parsers
# ════════════════════════════════════════════════════════════════

def _parse_damage(action: dict[str, Any]) -> Effect | None:
    amount = action.get("damage") or action.get("amount", 0)
    if not amount:
        return None
    return Effect.damage(int(amount))


def _parse_summon(action: dict[str, Any]) -> Effect | None:
    card_id = action.get("_card_name", "") or action.get("card_id", "")
    atk = int(action.get("attack", 0))
    hp = int(action.get("health", 0))
    count = int(action.get("count", 1))
    return Effect.summon(card_id=card_id, attack=atk, health=hp, count=count)


def _parse_draw(action: dict[str, Any]) -> Effect | None:
    count = int(action.get("count", 1))
    return Effect.draw(count)


def _parse_heal(action: dict[str, Any]) -> Effect | None:
    amount = int(action.get("amount", 0))
    if not amount:
        return None
    return Effect.heal(amount)


def _parse_buff(action: dict[str, Any]) -> Effect | None:
    atk = int(action.get("attack_bonus", 0))
    hp = int(action.get("health_bonus", 0))
    if atk == 0 and hp == 0:
        return None
    return Effect.buff(atk, hp)


def _parse_armor(action: dict[str, Any]) -> Effect | None:
    amount = int(action.get("amount", 0))
    if not amount:
        return None
    return Effect.armor(amount)


def _parse_discover(action: dict[str, Any]) -> Effect | None:
    pool = action.get("pool", "")
    count = int(action.get("count", 3))
    return Effect.discover(pool=pool, count=count)


_ACTION_PARSERS: dict[str, callable] = {
    "DamageSpell": _parse_damage,
    "SummonSpell": _parse_summon,
    "DrawSpell": _parse_draw,
    "HealSpell": _parse_heal,
    "BuffSpell": _parse_buff,
    "ArmorSpell": _parse_armor,
    "DiscoverSpell": _parse_discover,
    "DamageEffect": _parse_damage,
    "SummonEffect": _parse_summon,
    "DrawEffect": _parse_draw,
    "HealEffect": _parse_heal,
    "BuffEffect": _parse_buff,
    "ArmorEffect": _parse_armor,
    "DiscoverEffect": _parse_discover,
}

# [从 analysis/search/location.py 迁移而来]
# 原文件仍保留，后续 Phase 统一 import 路径后删除原文件。
from __future__ import annotations

"""Location card support — activation, deathrattle, and cooldown management.

Location lifecycle:
  1. Play: added to state.locations (max 2)
  2. Activate: resolve effect, consume durability, set cooldown
  3. Spell react: spellSchool-based cooldown reset (e.g. Fel → Nespirah)
  4. Durability 0: remove from locations, trigger deathrattle
  5. End of turn: tick cooldowns
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState


@dataclass
class Location:
    dbf_id: int = 0
    name: str = ""
    cost: int = 0
    durability: int = 0
    cooldown_current: int = 0
    cooldown_max: int = 2
    text: str = ""
    english_text: str = ""
    card_id: str = ""
    card_type: str = "LOCATION"
    mechanics: list = None

    def __post_init__(self):
        if self.mechanics is None:
            self.mechanics = []

    @property
    def has_deathrattle(self) -> bool:
        if "DEATHRATTLE" in (self.mechanics or []):
            return True
        etext = (self.english_text or self.text or "").lower()
        return "deathrattle" in etext


def activate_location(state: "GameState", location_index: int) -> "GameState":
    """Activate a location: resolve effect, consume durability, handle death.

    NOTE: Caller must provide a mutable copy (apply_action already copies).
    This function mutates state in-place and returns it.
    """
    s = state

    if location_index < 0 or location_index >= len(s.locations):
        return s

    loc = s.locations[location_index]

    if loc.durability <= 0 or loc.cooldown_current > 0:
        return s

    try:
        s = _resolve_location_effect(s, loc)
    except Exception:
        pass

    loc.durability -= 1
    loc.cooldown_current = loc.cooldown_max

    if loc.durability <= 0:
        s = _handle_location_death(s, location_index, loc)

    return s


def _handle_location_death(state: "GameState", index: int, loc: Location) -> "GameState":
    """Handle location durability reaching 0: trigger deathrattle, remove."""
    s = state

    if loc.has_deathrattle:
        s = _execute_location_deathrattle(s, loc)

    if index < len(s.locations):
        s.locations.pop(index)

    return s


def _execute_location_deathrattle(state: "GameState", loc: Location) -> "GameState":
    """Execute a location's deathrattle effect."""
    s = state
    etext = (loc.english_text or loc.text or "").lower()

    if "deathrattle" in etext:
        after_dr = etext.split("deathrattle", 1)[1].strip().lstrip(":").strip()
    else:
        return s

    if "summon" in after_dr:
        from analysis.card.data.token_cards import get_token
        token_id = _extract_summon_token_id(loc)
        if token_id:
            token_data = get_token(token_id)
            if token_data:
                s = _summon_token(s, token_data)
        else:
            s = _summon_generic_from_text(s, after_dr)

    return s


def _extract_summon_token_id(loc: Location) -> str:
    """Try to find the token cardId referenced by this location."""
    card_id = getattr(loc, "card_id", "") or ""
    TOKEN_MAP = {
        "CATA_527": "CATA_527t2",
    }
    return TOKEN_MAP.get(card_id, "")


def _summon_token(s: "GameState", token_data: dict) -> "GameState":
    """Summon a minion from token data onto the friendly board."""
    from analysis.card.engine.state import Minion

    token_mechanics = token_data.get("mechanics", [])
    from analysis.card.abilities.keywords import KeywordSet

    kw = []
    if "DEATHRATTLE" in token_mechanics:
        kw.append("DEATHRATTLE")
    if "TRIGGER_VISUAL" in token_mechanics:
        kw.append("TRIGGER_VISUAL")

    minion = Minion(
        card_id=token_data.get("cardId", ""),
        name=token_data.get("name", ""),
        dbf_id=token_data.get("dbfId", 0),
        attack=token_data.get("attack", 0),
        health=token_data.get("health", 1),
        cost=token_data.get("cost", 0),
        keywords=KeywordSet(kw),
    )

    # Inject english_text so AbilityParser can discover trigger effects
    english_text = token_data.get("englishText", "") or token_data.get("text", "")
    if english_text:
        minion.english_text = english_text  # type: ignore[attr-defined]

    # Inject trigger metadata for direct dispatch without text parsing
    trigger_type = token_data.get("trigger_type", "")
    trigger_effect = token_data.get("trigger_effect", "")
    if trigger_type:
        minion.trigger_type = trigger_type  # type: ignore[attr-defined]
    if trigger_effect:
        minion.trigger_effect = trigger_effect  # type: ignore[attr-defined]

    if len(s.board) < 7:
        s.board.append(minion)
    return s


def _summon_generic_from_text(s: "GameState", text: str) -> "GameState":
    """Fallback: summon a generic minion parsed from text stats."""
    from analysis.card.engine.state import Minion

    atk, hp = 0, 0
    idx = text.find("/")
    if idx > 0:
        before = text[:idx].strip()
        after = text[idx+1:idx+4].strip()
        nums_before = [c for c in before if c.isdigit()]
        nums_after = [c for c in after if c.isdigit()]
        if nums_before:
            atk = int("".join(nums_before))
        if nums_after:
            hp = int("".join(nums_after))

    if atk > 0 and hp > 0:
        minion = Minion(name="Token", attack=atk, health=hp)
        if len(s.board) < 7:
            s.board.append(minion)
    return s


def tick_location_cooldowns(state: "GameState") -> "GameState":
    """Tick cooldowns on all locations at end of turn.

    NOTE: Caller must provide a mutable copy. Mutates in-place.
    """
    for loc in state.locations:
        if loc.cooldown_current > 0:
            loc.cooldown_current -= 1
    return state


def _resolve_location_effect(state: "GameState", loc: Location) -> "GameState":
    """Resolve location activate effect via unified abilities executor.

    Falls back to text-based parsing when no abilities are loaded.
    """
    import re

    from analysis.card.abilities.definition import AbilityTrigger
    from analysis.card.abilities.loader import load_abilities

    abilities = getattr(loc, 'abilities', [])
    if not abilities:
        card_id = getattr(loc, 'card_id', '') or getattr(loc, 'card_ref', None)
        if card_id:
            abilities = load_abilities(card_id if isinstance(card_id, str) else getattr(card_id, 'card_id', ''))
        if not abilities:
            abilities = []

    for ability in abilities:
        if ability.trigger != AbilityTrigger.ACTIVATE:
            continue
        state = ability.execute(state, loc)

    # If no abilities were executed, fall back to text-based parsing
    if not abilities:
        etext = (loc.english_text or loc.text or "").strip()
        if not etext:
            return state

        # "Deal N damage" → damage enemy hero
        m = re.search(r'[Dd]eal\s+(\d+)\s+damage', etext)
        if m:
            amount = int(m.group(1))
            state.opponent.hero.hp = max(0, state.opponent.hero.hp - amount)
            return state

        # "Restore N Health" / "Heal N" → heal friendly hero
        m = re.search(r'[Rr]estore\s+(\d+)\s+[Hh]ealth', etext)
        if m:
            amount = int(m.group(1))
            max_hp = getattr(state.hero, 'max_hp', 30)
            state.hero.hp = min(max_hp, state.hero.hp + amount)
            return state

    return state

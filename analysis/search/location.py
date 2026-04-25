"""Location card support — activation, deathrattle, and cooldown management.

Location lifecycle:
  1. Play: added to state.locations (max 2)
  2. Activate: resolve effect, consume durability, set cooldown
  3. Spell react: spellSchool-based cooldown reset (e.g. Fel → Nespirah)
  4. Durability 0: remove from locations, trigger deathrattle
  5. End of turn: tick cooldowns
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState


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
    """Activate a location: resolve effect, consume durability, handle death."""
    s = state.copy()

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
        from analysis.data.token_cards import get_token
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
    from analysis.search.game_state import Minion

    minion = Minion(
        card_id=token_data.get("cardId", ""),
        name=token_data.get("name", ""),
        dbf_id=token_data.get("dbfId", 0),
        attack=token_data.get("attack", 0),
        health=token_data.get("health", 1),
        cost=token_data.get("cost", 0),
        mechanics=token_data.get("mechanics", []),
        text=token_data.get("text", ""),
        english_text=token_data.get("ename", ""),
        has_deathrattle="DEATHRATTLE" in token_data.get("mechanics", []),
        has_trigger="TRIGGER_VISUAL" in token_data.get("mechanics", []),
    )
    if len(s.board) < 7:
        s.board.append(minion)
    return s


def _summon_generic_from_text(s: "GameState", text: str) -> "GameState":
    """Fallback: summon a generic minion parsed from text stats."""
    from analysis.search.game_state import Minion

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
    """Tick cooldowns on all locations at end of turn."""
    s = state.copy()
    for loc in s.locations:
        if loc.cooldown_current > 0:
            loc.cooldown_current -= 1
    return s


def _resolve_location_effect(state: "GameState", loc: Location) -> "GameState":
    """Resolve location activate effect via unified abilities executor."""
    from analysis.search.abilities.parser import AbilityParser
    from analysis.search.abilities.definition import AbilityTrigger

    abilities = getattr(loc, 'abilities', [])
    if not abilities:
        abilities = AbilityParser.parse(loc)

    for ability in abilities:
        if ability.trigger != AbilityTrigger.ACTIVATE:
            continue
        state = ability.execute(state, loc)

    return state

#!/usr/bin/env python3
"""
Power.log card play effect analysis script.

Parses a Power.log file and extracts ALL actual card play effects:
- Entity -> cardId mapping from FULL_ENTITY and SHOW_ENTITY
- BLOCK_START(PLAY) blocks with TAG_CHANGE details
- Nested sub-blocks (POWER, TRIGGER, etc.)
- Structured JSON output of all effects per card played
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POWER_LOG_PATH = Path(__file__).resolve().parent.parent / "Power.log"

# Numeric tag IDs that carry important game state information
TAG_NAME_MAP = {
    "ZONE": "ZONE",
    "ATK": "ATK",
    "HEALTH": "HEALTH",
    "DAMAGE": "DAMAGE",
    "ARMOR": "ARMOR",
    "CONTROLLER": "CONTROLLER",
    "COST": "COST",
    "ZONE_POSITION": "ZONE_POSITION",
    "EXHAUSTED": "EXHAUSTED",
    "JUST_PLAYED": "JUST_PLAYED",
    "PREDAMAGE": "PREDAMAGE",
    "LAST_AFFECTED_BY": "LAST_AFFECTED_BY",
    "RESOURCES_USED": "RESOURCES_USED",
    "RESOURCES": "RESOURCES",
    "NUM_CARDS_PLAYED_THIS_TURN": "NUM_CARDS_PLAYED_THIS_TURN",
    "NUM_MINIONS_PLAYED_THIS_TURN": "NUM_MINIONS_PLAYED_THIS_TURN",
    "NUM_RESOURCES_SPENT_THIS_GAME": "NUM_RESOURCES_SPENT_THIS_GAME",
    "NUM_SPELLS_PLAYED_THIS_GAME": "NUM_SPELLS_PLAYED_THIS_GAME",
    "CARDTARGET": "CARD_TARGET",
    "CARD_TARGET": "CARD_TARGET",
    "TAUNT": "TAUNT",
    "CHARGE": "CHARGE",
    "RUSH": "RUSH",
    "DIVINE_SHIELD": "DIVINE_SHIELD",
    "STEALTH": "STEALTH",
    "WINDFURY": "WINDFURY",
    "FROZEN": "FROZEN",
    "ENRAGED": "ENRAGED",
    "SILENCED": "SILENCED",
    "DEATHRATTLE": "DEATHRATTLE",
    "BATTLECRY": "BATTLECRY",
    "INSPIRE": "INSPIRE",
    "SPELLPOWER": "SPELLPOWER",
    "COMBO": "COMBO",
    "SECRET": "SECRET",
    "OVERLOAD": "OVERLOAD",
    "SPELLBURST": "SPELLBURST",
    "FRENZY": "FRENZY",
    "HONORABLEKILL": "HONORABLEKILL",
    "LIFESTEAL": "LIFESTEAL",
    "POISONOUS": "POISONOUS",
    "IMMUNE": "IMMUNE",
    "CANT_BE_TARGETED": "CANT_BE_TARGETED",
    "ATK@JsonProperty": "ATK",
}

# Tags that represent meaningful effects we want to track
INTERESTING_TAGS = {
    "DAMAGE", "ATK", "HEALTH", "ARMOR", "ZONE", "CONTROLLER", "COST",
    "ZONE_POSITION", "PREDAMAGE", "RESOURCES", "RESOURCES_USED",
    "TAUNT", "CHARGE", "RUSH", "DIVINE_SHIELD", "STEALTH", "WINDFURY",
    "FROZEN", "SILENCED", "EXHAUSTED", "JUST_PLAYED",
    "LAST_AFFECTED_BY", "OVERLOAD",
}

# Tags to always skip (noise / bookkeeping)
SKIP_TAGS = {
    "ENTITY_ID", "SPAWN_TIME_COUNT", "PREMIUM", "DISPLAY_ENTITY_ON_MOUSEOVER",
    "NUM_TURNS_IN_HAND", "HAS_SIGNATURE_QUALITY", "HAS_ACTIVATE_POWER",
    "TAG_SCRIPT_DATA_NUM_1", "TAG_SCRIPT_DATA_NUM_6",
    "COPIED_BY_KHADGAR", "COPIED_FROM_ENTITY_ID",
    "CREATOR_DBID", "COLLECTION_RELATED_CARD_DATABASE_ID",
    "TAG_LAST_KNOWN_COST_IN_HAND",
}


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# FULL_ENTITY - Creating ID=XX CardID=YY  or  FULL_ENTITY - Updating [entityName=... id=XX ... cardId=YY] CardID=ZZ
RE_FULL_ENTITY_CREATING = re.compile(
    r"FULL_ENTITY - Creating ID=(\d+) CardID=(\S*)"
)
RE_FULL_ENTITY_UPDATING = re.compile(
    r"FULL_ENTITY - Updating \[.*?id=(\d+).*?cardId=(\S*?)\s*\] CardID=(\S*)"
)

# SHOW_ENTITY - Updating Entity=[...] CardID=YY  or  SHOW_ENTITY - Updating Entity=XX CardID=YY
RE_SHOW_ENTITY_NAMED = re.compile(
    r"SHOW_ENTITY - Updating Entity=\[.*?id=(\d+).*?\] CardID=(\S+)"
)
RE_SHOW_ENTITY_BARE = re.compile(
    r"SHOW_ENTITY - Updating Entity=(\d+) CardID=(\S+)"
)

# TAG_CHANGE Entity=[...] tag=NAME value=VALUE  or  TAG_CHANGE Entity=XX tag=NAME value=VALUE
RE_TAG_CHANGE_NAMED = re.compile(
    r"TAG_CHANGE Entity=\[.*?id=(\d+).*?\] tag=(\S+) value=(\S+)\s*$"
)
RE_TAG_CHANGE_NAMED_CARDID = re.compile(
    r"TAG_CHANGE Entity=\[.*?id=(\d+).*?cardId=(\S*?)\s*\] tag=(\S+) value=(\S+)\s*$"
)
RE_TAG_CHANGE_BARE = re.compile(
    r"TAG_CHANGE Entity=(\d+) tag=(\S+) value=(\S+)\s*$"
)
RE_TAG_CHANGE_PLAYER = re.compile(
    r"TAG_CHANGE Entity=UNKNOWN HUMAN PLAYER tag=(\S+) value=(\S+)\s*$"
)
RE_TAG_CHANGE_GAME = re.compile(
    r"TAG_CHANGE Entity=GameEntity tag=(\S+) value=(\S+)\s*$"
)

# BLOCK_START BlockType=PLAY Entity=[...]
RE_BLOCK_PLAY = re.compile(
    r"BLOCK_START BlockType=PLAY Entity=\[.*?id=(\d+).*?cardId=(\S*?)\s*\]"
)
RE_BLOCK_PLAY_BARE = re.compile(
    r"BLOCK_START BlockType=PLAY Entity=\[.*?id=(\d+).*?\]"
)

# BLOCK_START BlockType=XXX Entity=[...]  (generic)
RE_BLOCK_GENERIC = re.compile(
    r"BLOCK_START BlockType=(\w+)"
)

# Entity id from inline descriptions: id=NN
RE_ENTITY_ID = re.compile(r"id=(\d+)")

# cardId from inline descriptions: cardId=XX
RE_CARD_ID_INLINE = re.compile(r"cardId=(\S+?)(?:\s|])")

# Numeric tag value pattern (some tags use numeric IDs)
RE_NUMERIC_TAG = re.compile(r"tag=(\d+) value=(\S+)")

# BLOCK_END
RE_BLOCK_END = re.compile(r"BLOCK_END")


# ---------------------------------------------------------------------------
# Helper: extract entity id from an entity string
# ---------------------------------------------------------------------------

def extract_entity_id(entity_str: str) -> int | None:
    """Extract the numeric entity id from a tag change line's entity field."""
    m = RE_ENTITY_ID.search(entity_str)
    if m:
        return int(m.group(1))
    # Maybe a bare integer
    stripped = entity_str.strip()
    if stripped.isdigit():
        return int(stripped)
    return None


def extract_card_id_inline(entity_str: str) -> str | None:
    """Extract cardId from an entity description string."""
    m = RE_CARD_ID_INLINE.search(entity_str)
    if m:
        cid = m.group(1)
        if cid and cid != "player=":
            return cid
    return None


def tag_value_as_int(val_str: str) -> int | str:
    """Try to interpret a tag value as int; fall back to the raw string."""
    try:
        return int(val_str)
    except (ValueError, TypeError):
        return val_str


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

class PowerLogParser:
    """Parse a Power.log and extract card play effects."""

    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)
        # entity_id -> card_id mapping built from FULL_ENTITY / SHOW_ENTITY
        self.entity_to_card: dict[int, str] = {}
        # Results
        self.card_plays: list[dict] = []

    # ---- phase 1: build entity->cardId map ----

    def _build_entity_map(self, lines: list[str]):
        """First pass: collect all entity_id -> card_id mappings."""
        for line in lines:
            raw = self._strip_prefix(line)
            if raw is None:
                continue

            # FULL_ENTITY - Creating ID=XX CardID=
            m = RE_FULL_ENTITY_CREATING.search(raw)
            if m:
                eid = int(m.group(1))
                cid = m.group(2).strip()
                if cid:
                    self.entity_to_card[eid] = cid
                continue

            # FULL_ENTITY - Updating [...] CardID=YY
            m = RE_FULL_ENTITY_UPDATING.search(raw)
            if m:
                eid = int(m.group(1))
                cid = m.group(3).strip() if m.group(3) else m.group(2).strip()
                if cid:
                    self.entity_to_card[eid] = cid
                continue

            # SHOW_ENTITY - Updating Entity=[...] CardID=YY
            m = RE_SHOW_ENTITY_NAMED.search(raw)
            if m:
                eid = int(m.group(1))
                cid = m.group(2).strip()
                if cid:
                    self.entity_to_card[eid] = cid
                continue

            # SHOW_ENTITY - Updating Entity=XX CardID=YY
            m = RE_SHOW_ENTITY_BARE.search(raw)
            if m:
                eid = int(m.group(1))
                cid = m.group(2).strip()
                if cid:
                    self.entity_to_card[eid] = cid
                continue

    # ---- phase 2: extract PLAY blocks ----

    def _extract_play_blocks(self, lines: list[str]):
        """Second pass: find BLOCK_START BlockType=PLAY and extract effects."""
        n = len(lines)
        i = 0
        while i < n:
            raw = self._strip_prefix(lines[i])
            if raw is None:
                i += 1
                continue

            # Look for top-level PLAY blocks (line starts with BLOCK_START,
            # no leading indentation or exactly the first level)
            m = RE_BLOCK_PLAY.search(raw) or RE_BLOCK_PLAY_BARE.search(raw)
            if m and "BlockType=PLAY" in raw:
                # Check indentation: top-level PLAY blocks are not indented
                # (they appear after "GameState.DebugPrintPower() - BLOCK_START")
                indent = self._indent_level(raw, lines[i])
                if indent <= 1:
                    entity_id = int(m.group(1))
                    play_info = self._parse_play_block(lines, i, entity_id)
                    if play_info:
                        self.card_plays.append(play_info)
            i += 1

    def _indent_level(self, raw: str, full_line: str) -> int:
        """Estimate nesting depth by counting leading spaces after the prefix."""
        # The prefix "GameState.DebugPrintPower() - " is stripped by _strip_prefix
        # Indentation is encoded as extra spaces: "    BLOCK_START" = depth 1
        prefix_match = re.search(r"DebugPrintPower\(\)\s*-\s*(.*)", full_line)
        if prefix_match:
            content = prefix_match.group(1)
            spaces = len(content) - len(content.lstrip())
            return spaces // 4
        return 0

    def _parse_play_block(self, lines: list[str], start: int,
                          play_entity_id: int) -> dict | None:
        """Parse a single PLAY block starting at line *start*."""
        n = len(lines)
        effects: list[dict] = []
        sub_blocks: list[str] = []
        sub_block_details: list[dict] = []
        # Track entity state for deltas
        entity_state: dict[int, dict[str, int]] = defaultdict(dict)

        depth = 0
        i = start

        # Parse the first BLOCK_START line
        raw = self._strip_prefix(lines[i])
        if raw is None:
            return None
        depth = 1
        i += 1

        while i < n and depth > 0:
            raw = self._strip_prefix(lines[i])
            if raw is None:
                i += 1
                continue

            # BLOCK_START
            if "BLOCK_START" in raw:
                bm = RE_BLOCK_GENERIC.search(raw)
                if bm:
                    block_type = bm.group(1)
                    if block_type != "PLAY":
                        sub_blocks.append(block_type)
                        # Collect TAG_CHANGEs inside this sub-block too
                        sub_start = i
                        sub_depth = 1
                        j = i + 1
                        sub_effects: list[dict] = []
                        while j < n and sub_depth > 0:
                            sraw = self._strip_prefix(lines[j])
                            if sraw is None:
                                j += 1
                                continue
                            if "BLOCK_START" in sraw:
                                sub_depth += 1
                            elif "BLOCK_END" in sraw:
                                sub_depth -= 1
                            elif "TAG_CHANGE" in sraw:
                                tc = self._parse_tag_change(sraw)
                                if tc and tc["tag"] not in SKIP_TAGS:
                                    sub_effects.append(tc)
                            j += 1
                        if sub_effects:
                            sub_block_details.append({
                                "type": block_type,
                                "effects": sub_effects,
                            })
                depth += 1
                i += 1
                continue

            # BLOCK_END
            if "BLOCK_END" in raw:
                depth -= 1
                i += 1
                continue

            # TAG_CHANGE inside the play block
            if "TAG_CHANGE" in raw:
                tc = self._parse_tag_change(raw)
                if tc and tc["tag"] not in SKIP_TAGS:
                    # Compute delta for numeric tags
                    eid = tc["entity"]
                    tag = tc["tag"]
                    new_val = tc["new"]
                    old_val = entity_state[eid].get(tag)
                    tc["old"] = old_val
                    entity_state[eid][tag] = new_val
                    effects.append(tc)
                i += 1
                continue

            # SHOW_ENTITY inside the play block (discover / summon reveals)
            if "SHOW_ENTITY" in raw:
                show = self._parse_show_entity(raw)
                if show:
                    effects.append(show)
                i += 1
                continue

            # FULL_ENTITY inside the play block (entity creation)
            if "FULL_ENTITY" in raw:
                fe = self._parse_full_entity_inline(raw)
                if fe:
                    effects.append(fe)
                i += 1
                continue

            i += 1

        # Determine card_id for the played entity
        card_id = self.entity_to_card.get(play_entity_id, "unknown")

        # If still unknown, try to find SHOW_ENTITY inside the block that reveals
        # the card being played (the entity transitions from UNKNOWN to revealed)
        if card_id == "unknown":
            for eff in effects:
                if eff.get("type") == "show_entity" and eff.get("entity") == play_entity_id:
                    card_id = eff.get("card_id", "unknown")
                    break

        # Filter out boring / noise effects
        filtered_effects = self._filter_effects(effects, play_entity_id)

        return {
            "card_id": card_id,
            "entity_id": play_entity_id,
            "block_line": start + 1,  # 1-based line number
            "player": self._determine_player(lines[start]),
            "effects": filtered_effects,
            "sub_blocks": sub_blocks,
            "sub_block_details": sub_block_details,
        }

    def _parse_tag_change(self, raw: str) -> dict | None:
        """Parse a TAG_CHANGE line into a structured dict."""
        # Try named entity with cardId: TAG_CHANGE Entity=[... id=X cardId=Y] tag=T value=V
        m = RE_TAG_CHANGE_NAMED_CARDID.search(raw)
        if m:
            return {
                "type": "tag_change",
                "entity": int(m.group(1)),
                "entity_card_id": m.group(2) or None,
                "tag": m.group(3),
                "new": tag_value_as_int(m.group(4)),
            }

        # Named entity without explicit cardId
        m = RE_TAG_CHANGE_NAMED.search(raw)
        if m:
            eid = int(m.group(1))
            return {
                "type": "tag_change",
                "entity": eid,
                "entity_card_id": self.entity_to_card.get(eid),
                "tag": m.group(2),
                "new": tag_value_as_int(m.group(3)),
            }

        # Bare integer entity
        m = RE_TAG_CHANGE_BARE.search(raw)
        if m:
            eid = int(m.group(1))
            return {
                "type": "tag_change",
                "entity": eid,
                "entity_card_id": self.entity_to_card.get(eid),
                "tag": m.group(2),
                "new": tag_value_as_int(m.group(3)),
            }

        # Player-level tag change
        m = RE_TAG_CHANGE_PLAYER.search(raw)
        if m:
            return {
                "type": "tag_change",
                "entity": "player",
                "entity_card_id": None,
                "tag": m.group(1),
                "new": tag_value_as_int(m.group(2)),
            }

        # GameEntity tag change
        m = RE_TAG_CHANGE_GAME.search(raw)
        if m:
            return {
                "type": "tag_change",
                "entity": "game",
                "entity_card_id": None,
                "tag": m.group(1),
                "new": tag_value_as_int(m.group(2)),
            }

        # Numeric tag: TAG_CHANGE Entity=[...] tag=999 value=X
        m = RE_NUMERIC_TAG.search(raw)
        if m:
            eid_m = RE_ENTITY_ID.search(raw)
            eid = int(eid_m.group(1)) if eid_m else 0
            return {
                "type": "tag_change",
                "entity": eid,
                "entity_card_id": self.entity_to_card.get(eid) if eid else None,
                "tag": m.group(1),
                "new": tag_value_as_int(m.group(2)),
            }

        return None

    def _parse_show_entity(self, raw: str) -> dict | None:
        """Parse a SHOW_ENTITY line."""
        m = RE_SHOW_ENTITY_NAMED.search(raw)
        if m:
            eid = int(m.group(1))
            cid = m.group(2)
            self.entity_to_card[eid] = cid
            return {
                "type": "show_entity",
                "entity": eid,
                "card_id": cid,
                "entity_card_id": cid,
            }
        m = RE_SHOW_ENTITY_BARE.search(raw)
        if m:
            eid = int(m.group(1))
            cid = m.group(2)
            self.entity_to_card[eid] = cid
            return {
                "type": "show_entity",
                "entity": eid,
                "card_id": cid,
                "entity_card_id": cid,
            }
        return None

    def _parse_full_entity_inline(self, raw: str) -> dict | None:
        """Parse a FULL_ENTITY line found inside a PLAY block."""
        m = RE_FULL_ENTITY_CREATING.search(raw)
        if m:
            eid = int(m.group(1))
            cid = m.group(2).strip()
            if cid:
                self.entity_to_card[eid] = cid
            return {
                "type": "full_entity",
                "entity": eid,
                "card_id": cid or None,
            }
        m = RE_FULL_ENTITY_UPDATING.search(raw)
        if m:
            eid = int(m.group(1))
            cid = m.group(3).strip() if m.group(3) else m.group(2).strip()
            if cid:
                self.entity_to_card[eid] = cid
            return {
                "type": "full_entity",
                "entity": eid,
                "card_id": cid or None,
            }
        return None

    def _filter_effects(self, effects: list[dict],
                        play_entity_id: int) -> list[dict]:
        """Filter effects to only meaningful ones for display."""
        filtered = []
        seen_keys = set()
        for eff in effects:
            if eff.get("type") == "show_entity":
                key = ("show", eff["entity"], eff.get("card_id", ""))
                if key not in seen_keys:
                    filtered.append(eff)
                    seen_keys.add(key)
                continue
            if eff.get("type") == "full_entity":
                key = ("full", eff["entity"])
                if key not in seen_keys:
                    filtered.append(eff)
                    seen_keys.add(key)
                continue

            tag = eff.get("tag", "")
            # Skip pure positional / bookkeeping changes
            if tag in ("ZONE_POSITION", "EXHAUSTED", "JUST_PLAYED",
                       "NUM_TURNS_IN_HAND", "1196"):
                continue
            # Skip numeric-only tags that are not interesting
            if tag.isdigit() and int(tag) not in (2187, 1173, 4741, 4587, 3527, 430):
                continue

            # Skip player-level bookkeeping
            if eff.get("entity") == "player" and tag in (
                "NUM_CARDS_PLAYED_THIS_TURN",
                "NUM_MINIONS_PLAYED_THIS_TURN",
                "NUM_RESOURCES_SPENT_THIS_GAME",
                "NUM_SPELLS_PLAYED_THIS_GAME",
            ):
                continue

            # Deduplicate
            key = (eff.get("entity"), tag, eff.get("new"))
            if key not in seen_keys:
                filtered.append(eff)
                seen_keys.add(key)

        return filtered

    def _determine_player(self, line: str) -> int:
        """Determine which player (1 or 2) played the card."""
        if "player=1" in line:
            return 1
        elif "player=2" in line:
            return 2
        return 0

    @staticmethod
    def _strip_prefix(line: str) -> str | None:
        """Strip the timestamp/prefix from a Power.log line, return content."""
        # Format: D HH:MM:SS.mmmmmm GameState.DebugPrintPower() - CONTENT
        # or:     D HH:MM:SS.mmmmmm PowerTaskList.DebugPrintPower() - CONTENT
        idx = line.find("DebugPrintPower() - ")
        if idx >= 0:
            return line[idx + len("DebugPrintPower() - "):]
        return None

    # ---- main entry point ----

    def parse(self):
        """Run the full two-pass parse."""
        if not self.log_path.exists():
            print(f"ERROR: Power.log not found at {self.log_path}", file=sys.stderr)
            sys.exit(1)

        with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        print(f"Read {len(lines)} lines from {self.log_path}", file=sys.stderr)

        # Pass 1: build entity map
        self._build_entity_map(lines)
        print(f"Built entity map: {len(self.entity_to_card)} entities mapped",
              file=sys.stderr)

        # Pass 2: extract PLAY blocks
        self._extract_play_blocks(lines)
        print(f"Found {len(self.card_plays)} card play blocks", file=sys.stderr)


# ---------------------------------------------------------------------------
# Summary / reporting helpers
# ---------------------------------------------------------------------------

def build_summary(card_plays: list[dict]) -> dict:
    """Build a summary table: card_id -> list of effect types."""
    summary: dict[str, dict] = defaultdict(lambda: {
        "play_count": 0,
        "effect_types": set(),
        "sub_block_types": set(),
        "targets_hit": set(),
    })

    for play in card_plays:
        cid = play["card_id"]
        s = summary[cid]
        s["play_count"] += 1

        for eff in play.get("effects", []):
            if eff.get("type") == "tag_change":
                s["effect_types"].add(eff["tag"])
                if isinstance(eff.get("entity"), int) and eff["entity"] != play["entity_id"]:
                    s["targets_hit"].add(eff["entity"])
            elif eff.get("type") == "show_entity":
                s["effect_types"].add("SHOW_ENTITY")
            elif eff.get("type") == "full_entity":
                s["effect_types"].add("FULL_ENTITY")

        for sb in play.get("sub_blocks", []):
            s["sub_block_types"].add(sb)

    # Convert sets to sorted lists for JSON serialization
    result = {}
    for cid, s in sorted(summary.items()):
        result[cid] = {
            "play_count": s["play_count"],
            "effect_types": sorted(s["effect_types"]),
            "sub_block_types": sorted(s["sub_block_types"]),
            "targets_hit": sorted(s["targets_hit"]),
        }
    return result


def print_report(card_plays: list[dict], summary: dict):
    """Print a human-readable report to stderr."""
    print("\n" + "=" * 80, file=sys.stderr)
    print("POWER.LOG CARD PLAY EFFECT ANALYSIS REPORT", file=sys.stderr)
    print("=" * 80, file=sys.stderr)

    # 1. Total unique cards played
    unique_cards = set(p["card_id"] for p in card_plays)
    print(f"\nTotal card play blocks: {len(card_plays)}", file=sys.stderr)
    print(f"Unique cards played: {len(unique_cards)}", file=sys.stderr)
    print(f"Unique card IDs: {sorted(unique_cards)}", file=sys.stderr)

    # 2. Per-card effect details
    print("\n" + "-" * 80, file=sys.stderr)
    print("PER-CARD EFFECT DETAILS", file=sys.stderr)
    print("-" * 80, file=sys.stderr)

    for cid in sorted(unique_cards):
        plays = [p for p in card_plays if p["card_id"] == cid]
        print(f"\n  [{cid}] ({len(plays)} play(s))", file=sys.stderr)
        for idx, play in enumerate(plays):
            player = play.get("player", "?")
            print(f"    Play #{idx+1} (line {play['block_line']}, "
                  f"player={player}, entity={play['entity_id']})", file=sys.stderr)

            # Tag changes
            tag_effects = [e for e in play["effects"]
                          if e.get("type") == "tag_change"]
            if tag_effects:
                print(f"      TAG_CHANGEs:", file=sys.stderr)
                for te in tag_effects:
                    ent = te["entity"]
                    ent_cid = te.get("entity_card_id") or self_entity_card(card_plays, ent)
                    tag = te["tag"]
                    new = te["new"]
                    old = te.get("old")
                    delta_str = f" (was {old})" if old is not None else ""
                    print(f"        Entity[{ent}]({ent_cid or '?'}) "
                          f"{tag} -> {new}{delta_str}", file=sys.stderr)

            # Show/Full entity reveals
            reveals = [e for e in play["effects"]
                      if e.get("type") in ("show_entity", "full_entity")]
            if reveals:
                print(f"      Entity reveals:", file=sys.stderr)
                for rv in reveals:
                    print(f"        Entity[{rv['entity']}] -> {rv.get('card_id', '?')}",
                          file=sys.stderr)

            # Sub-blocks
            if play["sub_blocks"]:
                print(f"      Sub-blocks: {play['sub_blocks']}", file=sys.stderr)
            for sbd in play.get("sub_block_details", []):
                if sbd["effects"]:
                    print(f"        [{sbd['type']}] sub-effects:", file=sys.stderr)
                    for se in sbd["effects"]:
                        ent = se["entity"]
                        print(f"          Entity[{ent}] {se['tag']} -> {se['new']}",
                              file=sys.stderr)

    # 3. Summary table
    print("\n" + "-" * 80, file=sys.stderr)
    print("SUMMARY TABLE: card_id -> effect types", file=sys.stderr)
    print("-" * 80, file=sys.stderr)
    print(f"  {'Card ID':<20} {'Plays':>5}  {'Effect Types':<50}  {'Sub-blocks'}",
          file=sys.stderr)
    print(f"  {'-'*20} {'-----':>5}  {'-'*50}  {'-'*20}", file=sys.stderr)
    for cid, info in summary.items():
        eff_str = ", ".join(info["effect_types"]) or "(none)"
        sb_str = ", ".join(info["sub_block_types"]) or "(none)"
        print(f"  {cid:<20} {info['play_count']:>5}  {eff_str:<50}  {sb_str}",
              file=sys.stderr)

    print("\n" + "=" * 80, file=sys.stderr)


def self_entity_card(card_plays: list[dict], entity_id: int) -> str | None:
    """Best-effort lookup of entity_id -> card_id from all plays."""
    for play in card_plays:
        for eff in play["effects"]:
            if eff.get("entity") == entity_id and eff.get("entity_card_id"):
                return eff["entity_card_id"]
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = PowerLogParser(POWER_LOG_PATH)
    parser.parse()

    # Build summary
    summary = build_summary(parser.card_plays)

    # Print human-readable report to stderr
    print_report(parser.card_plays, summary)

    # Output structured JSON to stdout
    output = {
        "total_plays": len(parser.card_plays),
        "unique_cards": len(set(p["card_id"] for p in parser.card_plays)),
        "card_plays": parser.card_plays,
        "summary": summary,
        "entity_map_size": len(parser.entity_to_card),
    }

    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

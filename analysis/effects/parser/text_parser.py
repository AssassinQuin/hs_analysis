"""text_parser.py — Parse English card text → Ability objects.

This is the general-purpose fallback parser. It handles any card with
English text using regex pattern matching.

All patterns use named capture groups. A single card text may produce
multiple effects (e.g. "Deal $3 damage and draw a card").
"""

from __future__ import annotations

import logging
import re
from typing import Any

from analysis.effects.types import (
    Ability, ConditionKind, ConditionSpec, Effect, EffectKind,
    TargetKind, TargetSpec, Trigger,
)

log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# Regex patterns
# ════════════════════════════════════════════════════════════════

# ── Text cleanup ──────────────────────────────────────────────

_REMOVE_TAGS = re.compile(r"</?b>|</?i>|</?br\s*/?>|\[x\]")
_DRAIN_CHARGE = re.compile(r"\bdrain\b", re.IGNORECASE)
_MULTI_SPACE = re.compile(r"\s+")
_AMOUNT_VAR = re.compile(r"\$(\d+)")  # $6 → variable damage/heal amount

# ── Sentence splitting ────────────────────────────────────────
# Split on periods, but not on "e.g." or "i.e." or decimal numbers
_SENTENCE_SPLIT = re.compile(r"(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.)\s+")

# ── Trigger detection ─────────────────────────────────────────

_TRIGGER_PATTERNS: list[tuple[re.Pattern, Trigger]] = [
    (re.compile(r"<b>Battlecry:</b>", re.IGNORECASE), Trigger.BATTLECRY),
    (re.compile(r"<b>Deathrattle:</b>", re.IGNORECASE), Trigger.DEATHRATTLE),
    (re.compile(r"<b>Combo:</b>", re.IGNORECASE), Trigger.COMBO),
    (re.compile(r"<b>Spellburst:</b>", re.IGNORECASE), Trigger.SPELLBURST),
    (re.compile(r"<b>Choose One</b>", re.IGNORECASE), Trigger.CHOOSE_ONE),
    (re.compile(r"<b>Secret:</b>", re.IGNORECASE), Trigger.SECRET),
    (re.compile(r"<b>Inspire:</b>", re.IGNORECASE), Trigger.INSPIRE),
    (re.compile(r"<b>Frenzy:</b>", re.IGNORECASE), Trigger.FRENZY),
    (re.compile(r"<b>Outcast:</b>", re.IGNORECASE), Trigger.OUTCAST),
    (re.compile(r"<b>Infuse</b>", re.IGNORECASE), Trigger.INFUSE),
    (re.compile(r"<b>Corrupt:</b>", re.IGNORECASE), Trigger.CORRUPT),
    (re.compile(r"<b>Quest:</b>", re.IGNORECASE), Trigger.QUEST),
    (re.compile(r"<b>Herald</b>", re.IGNORECASE), Trigger.HERALD),
    (re.compile(r"<b>Imbue</b>", re.IGNORECASE), Trigger.IMBUE),
    (re.compile(r"<b>Kindred</b>", re.IGNORECASE), Trigger.KINDRED),
    (re.compile(r"<b>Colossal</b>", re.IGNORECASE), Trigger.COLOSSAL),
    (re.compile(r"<b>Dormant</b>", re.IGNORECASE), Trigger.DORMANT),
    (re.compile(r"<b>Dark Gift</b>", re.IGNORECASE), Trigger.DARK_GIFT),
    (re.compile(r"<b>Start of Game:</b>", re.IGNORECASE), Trigger.TURN_START),
]

# ── Effect patterns ───────────────────────────────────────────

# Each pattern: (regex, effect_kind, extractor_fn, target_fn)

_EFFECT_PATTERNS: list[tuple[re.Pattern, EffectKind, callable, callable]] = [
    # --- Damage ---
    (re.compile(r"Deal\s+\$?(?P<dmg>\d+)\s+damage\s+to\s+(?:the\s+)?(?P<target_all>all\s+enemies|all\s+other\s+minions|all\s+minions|all\s+characters)", re.IGNORECASE),
     EffectKind.AOE_DAMAGE,
     lambda m: {"amount": int(m.group("dmg"))},
     lambda m: TargetSpec(_TARGET_FROM_TEXT.get(m.group("target_all").lower(), TargetKind.ALL_ENEMIES))),

    (re.compile(r"Deal\s+\$?(?P<dmg>\d+)\s+damage\s+to\s+(?:a\s+)?(?P<target_d>random\s+)?(?P<target_kind>enemy\s+minion|friendly\s+minion|minion|enemy|character|all\s+minions)s?(?:\s+and\s+(?P<target2>all\s+enemies|all\s+minions))?", re.IGNORECASE),
     EffectKind.DAMAGE,
     lambda m: {"amount": int(m.group("dmg"))},
     lambda m: _target_from_match(m, "target_kind", "target_d")),

    # Generic damage fallback
    (re.compile(r"Deal\s+\$?(?P<dmg>\d+)\s+damage", re.IGNORECASE),
     EffectKind.DAMAGE,
     lambda m: {"amount": int(m.group("dmg"))},
     lambda m: TargetSpec(TargetKind.SELECTED)),

    (re.compile(r"(?P<rdmg>\d+)\s+damage\s+to\s+(?:a\s+)?random\s+(?:enemy\s+)?(?:minion|character)", re.IGNORECASE),
     EffectKind.RANDOM_DAMAGE,
     lambda m: {"amount": int(m.group("rdmg")), "splits": 1},
     lambda m: TargetSpec(TargetKind.RANDOM_ENEMY, random=True)),

    # --- Heal ---
    (re.compile(r"Restore\s+\$?(?P<heal>\d+)\s+Health", re.IGNORECASE),
     EffectKind.HEAL,
     lambda m: {"amount": int(m.group("heal"))},
     lambda m: TargetSpec(TargetKind.SELECTED)),

    (re.compile(r"Restore\s+\$?(?P<heal>\d+)\s+Health\s+to\s+(?:all\s+)?(?:friendly\s+)?characters", re.IGNORECASE),
     EffectKind.HEAL,
     lambda m: {"amount": int(m.group("heal"))},
     lambda m: TargetSpec(TargetKind.ALL_FRIENDLY)),

    # --- Armor ---
    (re.compile(r"Gain\s+\$?(?P<armor>\d+)\s+Armor", re.IGNORECASE),
     EffectKind.ARMOR,
     lambda m: {"amount": int(m.group("armor"))},
     lambda m: TargetSpec(TargetKind.SELF)),

    # --- Draw ---
    (re.compile(r"Draw\s+(?:a\s+)?(?P<draw>\d+)?\s*(?:card|cards)", re.IGNORECASE),
     EffectKind.DRAW,
     lambda m: {"count": int(m.group("draw") or 1)},
     lambda m: TargetSpec(TargetKind.DECK)),

    # --- Summon ---
    (re.compile(r"Summon\s+(?P<summon_count>three|two|a|an?)\s+(?P<summon_atk>\d+)/(?P<summon_hp>\d+)\s+(?P<summon_name>.+?)(?:\.|$)", re.IGNORECASE),
     EffectKind.SUMMON,
     lambda m: {"count": _word_count(m.group("summon_count")), "attack": int(m.group("summon_atk")), "health": int(m.group("summon_hp"))},
     lambda m: TargetSpec(TargetKind.BOARD)),

    (re.compile(r"Summon\s+(?P<summon_count2>three|two|a|an?)\s+(?P<summon_name2>.+?)(?:\.|$)", re.IGNORECASE),
     EffectKind.SUMMON,
     lambda m: {"count": _word_count(m.group("summon_count2"))},
     lambda m: TargetSpec(TargetKind.BOARD)),

    # --- Buff: just +N Attack (or -N Attack, e.g. Shrinkmeister) ---
    (re.compile(r"Give\s+(?:a\s+)?(?:\w+\s+)?(?P<atk_only>[+-]?\d+)\s+Attack", re.IGNORECASE),
     EffectKind.BUFF,
     lambda m: {"attack": int(m.group("atk_only")), "health": 0},
     lambda m: TargetSpec(TargetKind.SELECTED)),

    # --- Buff (Give +N/+N) ---
    (re.compile(r"Give\s+(?:a\s+)?(?P<buff_target>friendly\s+)?(?:\w+\s+)?(?P<buff_atk>[+-]?\d+)/\s*(?P<buff_hp>[+-]?\d+)\s*(?:Attack|Health)?", re.IGNORECASE),
     EffectKind.BUFF,
     lambda m: {"attack": int(m.group("buff_atk")), "health": int(m.group("buff_hp"))},
     lambda m: _target_from_text(m.group("buff_target") or "")),

    # Hand buff (Give +N/+N in hand)
    (re.compile(r"Give\s+(?:a\s+)?(?:\w+\s+)?minion\s+in\s+your\s+hand\s+(?P<hbuff_atk>[+-]?\d+)/\s*(?P<hbuff_hp>[+-]?\d+)", re.IGNORECASE),
     EffectKind.HAND_BUFF,
     lambda m: {"attack": int(m.group("hbuff_atk")), "health": int(m.group("hbuff_hp"))},
     lambda m: TargetSpec(TargetKind.HAND)),

    # --- Transform ---
    (re.compile(r"Transform\s+(?:a\s+|an?\s+)?(?P<transform_target>\w+)?\s*(?:minion|character)\s+into", re.IGNORECASE),
     EffectKind.TRANSFORM,
     lambda m: {},
     lambda m: TargetSpec(TargetKind.SELECTED)),

    # --- Destroy ---
    (re.compile(r"Destroy\s+(?:all\s+)?(?P<destroy_target>minions\s+and\s+locations|minions|all\s+minions|all\s+enemies|all\s+other\s+minions|a\s+damaged\s+(?:enemy\s+)?minion|a\s+minion|an?\s+(?:enemy\s+)?minion)", re.IGNORECASE),
     EffectKind.DESTROY,
     lambda m: {},
     lambda m: _target_from_text(m.group("destroy_target"))),

    # Silence
    (re.compile(r"Silence\s+(?:a\s+)?(?P<silence_target>friendly\s+)?minion", re.IGNORECASE),
     EffectKind.SILENCE,
     lambda m: {},
     lambda m: TargetSpec(TargetKind.SELECTED)),

    # Freeze
    (re.compile(r"Freeze\s+(?:a\s+)?(?P<freeze_target>an?\s+)?(?:enemy\s+)?character", re.IGNORECASE),
     EffectKind.FREEZE,
     lambda m: {},
     lambda m: TargetSpec(TargetKind.SELECTED)),

    # --- Discover ---
    (re.compile(r"Discover\s+(?:a\s+|an?\s+)?(?P<discover_pool>\w+(?:\s+\w+)?)", re.IGNORECASE),
     EffectKind.DISCOVER,
     lambda m: {"pool": m.group("discover_pool"), "count": 3},
     lambda m: TargetSpec(TargetKind.NONE)),

    # --- Equip weapon ---
    (re.compile(r"Equip\s+(?:a\s+)?(?P<weapon_atk>\d+)/(?P<weapon_durability>\d+)\s+(?P<weapon_name>.+?)(?:\.|$)", re.IGNORECASE),
     EffectKind.WEAPON_EQUIP,
     lambda m: {"attack": int(m.group("weapon_atk")), "durability": int(m.group("weapon_durability"))},
     lambda m: TargetSpec(TargetKind.SELF)),

    # --- Discard ---
    (re.compile(r"Discard\s+(?P<discard>\d+)?\s*(?:random\s+)?card", re.IGNORECASE),
     EffectKind.DISCARD,
     lambda m: {"count": int(m.group("discard") or 1)},
     lambda m: TargetSpec(TargetKind.HAND)),

    # Reduce cost
    (re.compile(r"(?:Reduce|Costs)\s*(?:\w+\s+)*\((?P<reduce>\d+)\)", re.IGNORECASE),
     EffectKind.REDUCE_COST,
     lambda m: {"amount": int(m.group("reduce"))},
     lambda m: TargetSpec(TargetKind.HAND)),

    # --- Buff self (when effect applies to self without explicit target) ---
    (re.compile(r"Gain\s+(?P<self_buff_atk>[+-]?\d+)\s*/\s*(?P<self_buff_hp>[+-]?\d+)", re.IGNORECASE),
     EffectKind.BUFF,
     lambda m: {"attack": int(m.group("self_buff_atk")), "health": int(m.group("self_buff_hp"))},
     lambda m: TargetSpec(TargetKind.SELF)),
]

# ── Helpers ──────────────────────────────────────────────────

_WORD_NUMBERS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "both": 2,
}


def _word_count(word: str) -> int:
    """Convert word number to int, fallback to 1."""
    return _WORD_NUMBERS.get(word.lower().strip(), 1)


# ── Target text mapping ───────────────────────────────────────

_TARGET_FROM_TEXT: dict[str, TargetKind] = {
    "all enemies": TargetKind.ALL_ENEMIES,
    "all minions": TargetKind.ALL_MINIONS,
    "all other minions": TargetKind.ALL_OTHER_MINIONS,
    "all characters": TargetKind.ALL_CHARACTERS,
    "minions": TargetKind.ALL_MINIONS,
    "a damaged enemy minion": TargetKind.ENEMY_MINION,
    "a damaged minion": TargetKind.SELECTED,
    "all minions and locations": TargetKind.ALL_MINIONS,
    "minions and locations": TargetKind.ALL_MINIONS,
    "all friendly characters": TargetKind.ALL_FRIENDLY,
    "all friendly minions": TargetKind.ALL_FRIENDLY,
    "a minion": TargetKind.SELECTED,
    "an enemy minion": TargetKind.ENEMY_MINION,
    "enemy minion": TargetKind.ENEMY_MINION,
    "friendly minion": TargetKind.FRIENDLY_MINION,
    "minion": TargetKind.SELECTED,
    "character": TargetKind.SELECTED,
    "enemy": TargetKind.ENEMY_HERO,
    "random enemy": TargetKind.RANDOM_ENEMY,
    "random enemy minion": TargetKind.RANDOM_ENEMY_MINION,
    "random minion": TargetKind.RANDOM_MINION,
    "random friendly minion": TargetKind.RANDOM_FRIENDLY_MINION,
}


def _target_from_match(m: re.Match, kind_group: str = "target_kind",
                       random_group: str | None = None) -> TargetSpec:
    """Build TargetSpec from regex match groups."""
    raw = m.group(kind_group)
    is_random = random_group is not None and m.group(random_group) is not None
    key = raw.strip().lower()
    kind = _TARGET_FROM_TEXT.get(key, TargetKind.SELECTED)
    return TargetSpec(kind, random=is_random)


def _target_from_text(text: str) -> TargetSpec:
    """Build TargetSpec from a short text phrase."""
    key = text.strip().lower()
    kind = _TARGET_FROM_TEXT.get(key, TargetKind.SELECTED)
    return TargetSpec(kind)


# ════════════════════════════════════════════════════════════════
# TextAbilityParser
# ════════════════════════════════════════════════════════════════

class TextAbilityParser:
    """Parse English card text → list[Ability].

    Handles trigger detection, effect extraction, and target inference
    from free-form English text.
    """

    def parse_abilities(self, card_id: str, text: str,
                        meta: dict[str, Any] | None = None
                        ) -> list[Ability]:
        """Parse card text into Ability objects.

        Strategy:
          1. Normalize and clean the text.
          2. Detect triggers (<b>Battlecry:</b> etc.).
          3. Split into effect sentences.
          4. Match each sentence against effect patterns.
          5. Group effects by trigger.
        """
        if not text:
            return []

        cleaned = self._clean(text)

        # Detect all triggers present in the text
        triggers_found = self._detect_triggers(cleaned)
        # Remove trigger markup so effect patterns can match
        effect_text = _REMOVE_TAGS.sub("", cleaned).strip()
        effect_text = _MULTI_SPACE.sub(" ", effect_text)
        effect_text = _DRAIN_CHARGE.sub("heal_drain", effect_text)

        # Split into sentences for individual effect matching
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(effect_text)
                     if s.strip()]

        # Case: no explicit trigger → everything is one implicit trigger
        # (e.g. spells: "Deal 6 damage." → no <b> tag)
        if not triggers_found:
            effects = self._match_effects(sentences, card_id)
            if effects:
                trigger = self._infer_trigger(meta)
                return [Ability(
                    trigger=trigger,
                    effects=effects,
                    source_card_id=card_id,
                )]
            return []

        # Case: triggers found → group sentences by trigger
        return self._group_by_trigger(card_id, effect_text, triggers_found)

    # ── Text normalization ────────────────────────────────────

    def _clean(self, text: str) -> str:
        """Normalize card text for parsing.
        - Remove quotes/italic markers
        - Normalize whitespace
        - Keep <b> tags (used for trigger detection)
        """
        text = text.replace("\n", " ")
        text = text.replace("<i>", "").replace("</i>", "")
        text = _MULTI_SPACE.sub(" ", text).strip()
        return text

    # ── Trigger detection ─────────────────────────────────────

    def _detect_triggers(self, text: str) -> list[tuple[Trigger, int]]:
        """Find all trigger tags and their positions in text.

        Returns list of (trigger, start_position) sorted by position.
        """
        triggers: list[tuple[Trigger, int]] = []
        for pattern, trigger in _TRIGGER_PATTERNS:
            for m in pattern.finditer(text):
                triggers.append((trigger, m.start()))
        triggers.sort(key=lambda x: x[1])
        return triggers

    def _infer_trigger(self, meta: dict[str, Any] | None) -> Trigger:
        """Infer the implicit trigger for a card with no explicit tags.

        For spells → Trigger.BATTLECRY (they resolve on play).
        For everything else → Trigger.TRIGGER_VISUAL.
        """
        if meta and meta.get("type") == "SPELL":
            return Trigger.BATTLECRY
        return Trigger.TRIGGER_VISUAL

    def _get_bolt_trigger(self, meta: dict[str, Any] | None) -> Trigger:
        """Get the appropriate trigger for an untagged effect sentence."""
        if meta and meta.get("type") == "SPELL":
            return Trigger.BATTLECRY  # spells resolve on play
        return Trigger.TRIGGER_VISUAL

    # ── Effect matching ───────────────────────────────────────

    def _match_effects(self, sentences: list[str],
                       card_id: str) -> list[Effect]:
        """Match a list of sentences against effect patterns."""
        effects: list[Effect] = []
        for sentence in sentences:
            matched = False
            for pattern, kind, param_fn, target_fn in _EFFECT_PATTERNS:
                m = pattern.search(sentence)
                if m:
                    params = param_fn(m)
                    target = target_fn(m)
                    # Resolve $ variable amounts from meta if available
                    effects.append(Effect(
                        kind=kind,
                        params=params,
                        target=target,
                    ))
                    matched = True
                    break
            if not matched:
                log.debug("Unmatched sentence in %s: %r", card_id, sentence[:80])

        return effects

    # ── Group by trigger ──────────────────────────────────────

    def _group_by_trigger(self, card_id: str, cleaned_text: str,
                          triggers: list[tuple[Trigger, int]]) -> list[Ability]:
        """Split text by trigger boundaries and parse each segment."""
        abilities: list[Ability] = []

        for i, (trigger, start_pos) in enumerate(triggers):
            # Determine end position (next trigger or end of text)
            if i + 1 < len(triggers):
                end_pos = triggers[i + 1][1]
            else:
                end_pos = len(cleaned_text)

            segment = cleaned_text[start_pos:end_pos].strip()
            segment_clean = _REMOVE_TAGS.sub("", segment).strip()

            if not segment_clean:
                continue

            sentences = [s.strip() for s in _SENTENCE_SPLIT.split(segment_clean)
                         if s.strip()]
            effects = self._match_effects(sentences, card_id)
            if effects:
                abilities.append(Ability(
                    trigger=trigger,
                    effects=effects,
                    source_card_id=card_id,
                ))

        return abilities

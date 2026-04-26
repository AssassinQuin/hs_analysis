"""V8 Contextual Scorer — Adjusts card scores based on game state.

Applies 7 contextual modifiers on top of static scores:
  1. Turn curve adjuster
  2. Type context modifier
  3. Pool quality assessor
  4. Deathrattle EV resolver
  5. Lethal-aware booster
  6. Rewind decision maker
  7. Combo synergy detector (hand-level)

Graceful degradation: if data files are missing, returns raw card.score.

Usage: python -c "from analysis.scorers.v8_contextual import V8ContextualScorer"
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, Optional

from analysis.models.card import Card
from analysis.engine.state import GameState
from analysis.models import Phase, detect_phase
from analysis.config import DATA_DIR
try:
    from analysis.data.card_effects import get_effects
except ImportError:
    get_effects = None


def _fallback_get_effects(card) -> "_Effects":
    """Fallback effects parser when card_effects module is unavailable."""
    text = getattr(card, 'text', '') or ''
    en = getattr(card, 'english_text', '') or ''
    clean = re.sub(r'<[^>]+>', '', text)
    en_clean = re.sub(r'<[^>]+>', '', en)

    summon_attack = summon_health = damage = random_damage = draw = 0
    has_summon = has_hand_transform = False

    # Summon parsing
    sm = re.search(r'召唤一个?(\d+)/(\d+)', clean)
    if not sm:
        sm = re.search(r'[Ss]ummon a[n]? (\d+)/(\d+)', en_clean)
    if sm:
        summon_attack, summon_health = int(sm.group(1)), int(sm.group(2))
        has_summon = True

    # Damage parsing
    dm = re.search(r'造成\s*(\d+)\s*点?伤害', clean)
    if not dm:
        dm = re.search(r'[Dd]eal\s+(\d+)\s*damage', en_clean)
    if dm:
        damage = int(dm.group(1))

    # Random damage
    rdm = re.search(r'随机造成\s*(\d+)\s*点?伤害', clean)
    if not rdm:
        rdm = re.search(r'[Dd]eal\s+(\d+)\s*damage.*random', en_clean)
    if rdm:
        random_damage = int(rdm.group(1))

    # Draw parsing
    dr = re.search(r'抽\s*(\d+)\s*张?牌', clean)
    if not dr:
        dr = re.search(r'[Dd]raw\s+(\d+)', en_clean)
    if dr:
        draw = int(dr.group(1))

    class _Effects:
        pass

    eff = _Effects()
    eff.has_summon = has_summon
    eff.has_hand_transform = has_hand_transform
    eff.summon_attack = summon_attack
    eff.summon_health = summon_health
    eff.damage = damage
    eff.random_damage = random_damage
    eff.draw = draw
    return eff


if get_effects is None:
    get_effects = _fallback_get_effects

logger = logging.getLogger(__name__)

# Race and school names for pool matching
RACE_NAMES_LIST = ["龙", "恶魔", "野兽", "鱼人", "海盗", "元素", "亡灵", "图腾", "机械", "纳迦", "德莱尼"]
SCHOOL_NAMES_LIST = ["火焰", "冰霜", "奥术", "自然", "暗影", "神圣", "邪能"]


class V8ContextualScorer:
    """Contextual scoring layer on top of static scores."""

    def __init__(self, data_dir: Optional[str] = None):
        self._data_dir = data_dir or str(DATA_DIR)
        self.pool_quality: Dict = {}
        self.rewind_delta: Dict = {}
        self.turn_data: Dict = {}
        self.data_loaded = False
        self._load_data()

    def _load_data(self) -> None:
        """Load all data files with graceful degradation."""
        self.pool_quality = self._load_json("pool_quality_report.json")
        self.rewind_delta = self._load_json("rewind_delta_report.json")
        self.turn_data = self._load_json("card_turn_data.json")
        self.data_loaded = bool(self.pool_quality or self.rewind_delta or self.turn_data)

    def _load_json(self, filename: str) -> dict:
        """Load a JSON file, return empty dict on failure."""
        path = os.path.join(self._data_dir, filename)
        if not os.path.isfile(path):
            logger.debug("V8: %s not found, using defaults", filename)
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("V8: failed to load %s: %s", filename, exc)
            return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def contextual_score(self, card: Card, state: GameState) -> float:
        """Compute contextual score for a single card in the given state."""
        base = getattr(card, "score", 0.0)
        if base == 0.0:
            base = self._fallback_base_score(card)
        result = base
        result *= self._turn_factor(card, state)
        result *= self._type_factor(card, state)
        result += self._pool_ev_bonus(card)
        result += self._deathrattle_ev_bonus(card, state)
        result *= self._lethal_boost(card, state)
        result += self._rewind_ev_delta(card, state)
        return result

    def hand_contextual_value(self, state: GameState) -> float:
        """Compute total contextual value for all cards in hand, including synergy."""
        base_sum = sum(self.contextual_score(c, state) for c in state.hand)
        synergy = self._synergy_bonus(state)
        return base_sum + synergy

    def _fallback_base_score(self, card: Card) -> float:
        """Compute a reasonable base score when card.score is 0 (no scoring_report.json).

        Uses card stats and cost to approximate value:
        - Minion: (attack * 1.0 + health * 0.8) / max(cost, 1) — efficiency metric
        - Spell: cost * 0.8 — higher cost = more impact expected
        - Weapon: (attack * durability * 0.9) / max(cost, 1)
        - Other: cost * 0.5
        """
        from analysis.models.card import CardType
        ct = getattr(card, "card_type", CardType.INVALID)
        cost = max(getattr(card, "cost", 0), 1)
        atk = getattr(card, "attack", 0)
        hp = getattr(card, "health", 0)

        if ct == CardType.MINION or (ct == CardType.INVALID and hp > 0):
            return (atk * 1.0 + hp * 0.8) / cost
        if ct == CardType.WEAPON:
            dur = getattr(card, "durability", 1)
            return (atk * dur * 0.9) / cost
        if ct == CardType.SPELL:
            return cost * 0.8
        return cost * 0.5

    # ------------------------------------------------------------------
    # Component 1: Turn Curve Adjuster
    # ------------------------------------------------------------------

    def _turn_factor(self, card: Card, state: GameState) -> float:
        """Adjust value based on how well card cost matches current turn."""
        # Get optimal turn from data or fallback to cost + 1
        dbf_str = str(card.dbf_id)
        turn_entry = self.turn_data.get(dbf_str)
        if turn_entry and isinstance(turn_entry, dict):
            optimal_turn = turn_entry.get("optimal_turn", card.cost + 1)
        else:
            optimal_turn = card.cost + 1

        delta = abs(state.turn_number - optimal_turn)
        factor = 1.0 - 0.08 * delta
        return max(0.5, min(1.2, factor))

    # ------------------------------------------------------------------
    # Component 2: Type Context Modifier
    # ------------------------------------------------------------------

    def _type_factor(self, card: Card, state: GameState) -> float:
        """Adjust value based on card type and game phase."""
        phase = detect_phase(state.turn_number)

        type_table = {
            "MINION": {Phase.EARLY: 1.1, Phase.MID: 1.0, Phase.LATE: 0.85},
            "SPELL":  {Phase.EARLY: 0.8, Phase.MID: 1.0, Phase.LATE: 1.2},
            "WEAPON": {Phase.EARLY: 1.0, Phase.MID: 1.1, Phase.LATE: 0.9},
        }
        card_type = getattr(card, "card_type", "") or ""
        factor = type_table.get(card_type, {}).get(phase, 1.0)

        # Board saturation modifier for minions
        if len(state.board) >= 6 and card_type == "MINION":
            factor *= 0.7

        # AOE value modifier for spells
        text = getattr(card, "text", "") or ""
        if card_type == "SPELL" and ("所有" in text or "全部" in text):
            enemy_attack = sum(m.attack for m in state.opponent.board)
            if enemy_attack > 8:
                factor *= 1.3

        return factor

    # ------------------------------------------------------------------
    # Component 3: Pool Quality Assessor
    # ------------------------------------------------------------------

    def _pool_ev_bonus(self, card: Card) -> float:
        """EV bonus for discover/random effects based on pool quality."""
        text = getattr(card, "text", "") or ""
        # Strip HTML
        clean_text = re.sub(r'<[^>]+>', '', text)

        # Must have discover/random pattern
        if not any(kw in clean_text for kw in ("发现", "随机", "置入你的手牌")):
            return 0.0

        if not self.pool_quality:
            return 0.0

        # Try to match pool name from text
        pool_key = None

        # Check race names
        for race in RACE_NAMES_LIST:
            if race in clean_text:
                pool_key = f"race_{race}"
                break

        # Check school names
        if pool_key is None:
            for school in SCHOOL_NAMES_LIST:
                if school in clean_text:
                    pool_key = f"school_{school}"
                    break

        # Check type mentions
        if pool_key is None:
            type_map = {"随从": "MINION", "法术": "SPELL", "武器": "WEAPON"}
            for cn, en_type in type_map.items():
                if cn in clean_text:
                    pool_key = f"type_{en_type}"
                    break

        if pool_key is None:
            return 0.0

        pool = self.pool_quality.get(pool_key, {})
        if not pool:
            return 0.0

        avg = pool.get("avg_v7", 0.0)
        top_10 = pool.get("top_10_pct_v7", 0.0)
        return (top_10 - avg) * 0.15

    # ------------------------------------------------------------------
    # Component 4: Deathrattle EV Resolver
    # ------------------------------------------------------------------

    def _deathrattle_ev_bonus(self, card: Card, state: GameState) -> float:
        """EV bonus for deathrattle effects."""
        text = getattr(card, "text", "") or ""
        if "亡语" not in text:
            return 0.0

        clean = re.sub(r'<[^>]+>', '', text)
        parsed_value = 0.0

        # Use structured card effects (EN-primary, CN fallback handled internally)
        eff = get_effects(card)

        # Summon stats
        if eff.has_summon and eff.summon_attack > 0 and eff.summon_health > 0:
            parsed_value += (eff.summon_attack + eff.summon_health) * 0.15

        # Damage (direct + random)
        if eff.damage > 0:
            parsed_value += eff.damage * 0.3
        if eff.random_damage > 0:
            parsed_value += eff.random_damage * 0.3

        # Draw
        if eff.draw > 0:
            parsed_value += eff.draw * 0.8

        # Equip
        if "装备" in clean:
            parsed_value += 1.0

        # Default fallback if nothing parsed but has deathrattle
        if parsed_value == 0.0:
            parsed_value = 0.5

        # Trigger probability based on board state
        prob = 0.7 if len(state.board) > 2 else 0.4
        return parsed_value * prob

    # ------------------------------------------------------------------
    # Component 5: Lethal-Aware Booster
    # ------------------------------------------------------------------

    def _lethal_boost(self, card: Card, state: GameState) -> float:
        """Boost damage cards when opponent is in lethal range."""
        opp = state.opponent.hero
        lethal_gap = (opp.hp + opp.armor) - state.get_total_attack()

        # Already lethal
        if lethal_gap <= 0:
            return 1.0

        # Check if card is damage-type
        text = getattr(card, "text", "") or ""
        card_type = getattr(card, "card_type", "") or ""
        is_damage = "造成" in text or "消灭" in text or card_type == "WEAPON"

        if not is_damage:
            return 1.0

        # Boost table
        if lethal_gap <= 3:
            return 1.5
        elif lethal_gap <= 6:
            return 1.3
        elif lethal_gap <= 10:
            return 1.1
        return 1.0

    # ------------------------------------------------------------------
    # Component 6: Rewind Decision Maker
    # ------------------------------------------------------------------

    def _rewind_ev_delta(self, card: Card, state: GameState) -> float:
        """EV delta for rewind cards."""
        text = getattr(card, "text", "") or ""
        if "回溯" not in text:
            return 0.0

        dbf_str = str(card.dbf_id)
        entry = self.rewind_delta.get(dbf_str)
        if not entry or not isinstance(entry, dict):
            return 0.0

        delta = entry.get("delta", 0.0)

        # Board pressure modifier
        opponent_attack = sum(m.attack for m in state.opponent.board)
        if opponent_attack > 10:
            delta *= 0.5

        return delta

    # ------------------------------------------------------------------
    # Component 7: Combo Synergy Detector
    # ------------------------------------------------------------------

    def _synergy_bonus(self, state: GameState) -> float:
        """Detect combo synergies across the hand."""
        bonus = 0.0
        hand = state.hand

        if len(hand) < 2:
            return 0.0

        # Race concentration: count race mentions in card texts
        race_counts: Dict[str, int] = {}
        for c in hand:
            text = getattr(c, "text", "") or ""
            clean = re.sub(r'<[^>]+>', '', text)
            for race in RACE_NAMES_LIST:
                if race in clean:
                    race_counts[race] = race_counts.get(race, 0) + 1

        # If 3+ same race mentions, bonus
        for race, count in race_counts.items():
            if count >= 3:
                bonus += count * 0.5

        # Spell + trigger combo
        spells = sum(1 for c in hand if getattr(c, "card_type", "") == "SPELL")
        triggers = sum(1 for c in hand if "战吼" in (getattr(c, "text", "") or "") or
                       "亡语" in (getattr(c, "text", "") or ""))
        if spells >= 1 and triggers >= 1:
            bonus += 0.3 * min(spells, triggers)

        # Curve completeness
        costs = set()
        for c in hand:
            cost = getattr(c, "cost", 0)
            if cost > 0:
                costs.add(cost)
        bonus += len(costs) * 0.2

        return bonus


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_scorer: Optional[V8ContextualScorer] = None


def get_scorer() -> V8ContextualScorer:
    """Get or create the singleton V8ContextualScorer."""
    global _scorer
    if _scorer is None:
        _scorer = V8ContextualScorer()
    return _scorer


def reset_scorer() -> None:
    """Reset the singleton (for testing)."""
    global _scorer
    _scorer = None

"""Probability models for Hearthstone search engine.

Unified models for draw probability, discover selection, RNG expected value,
and the composite probability panel aggregating all estimates.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from analysis.data.card_roles import RoleTag, classify_card_roles
except ImportError:
    RoleTag = classify_card_roles = None

try:
    from analysis.card.data.card_effects import (
        _DAMAGE_CN, _DAMAGE_EN, _HEAL_CN, _HEAL_EN,
        _DRAW_CN, _DRAW_EN, _BUFF_ATK_CN, _BUFF_ATK_EN,
        _SUMMON_STATS_CN, _SUMMON_STATS_EN,
    )
except ImportError:
    _DAMAGE_CN = _DAMAGE_EN = _HEAL_CN = _HEAL_EN = None
    _DRAW_CN = _DRAW_EN = _BUFF_ATK_CN = _BUFF_ATK_EN = None
    _SUMMON_STATS_CN = _SUMMON_STATS_EN = None

from analysis.card.engine.state import GameState


# ===================================================================
# DiscoverModel
# ===================================================================

class DiscoverModel:
    """Optimal selection from discover pools."""

    def best_discover(self, pool: list, state: GameState,
                      n_samples: int = 50) -> tuple[Optional[object], float]:
        if not pool:
            return None, 0.0

        scored = [(card, self._score_card(card, state)) for card in pool]
        scored.sort(key=lambda x: -x[1])

        if len(scored) <= 3:
            return scored[0]

        total_picks = min(n_samples, 200)
        best_picks: list = []
        pool_size = len(scored)
        for _ in range(total_picks):
            sample_size = min(3, pool_size)
            sample = random.sample(scored, sample_size)
            best_in_sample = max(sample, key=lambda x: x[1])
            best_picks.append(best_in_sample)

        avg_value = sum(p[1] for p in best_picks) / len(best_picks)
        top_card = max(best_picks, key=lambda x: x[1])[0]
        return top_card, avg_value

    def discover_ev(self, pool: list, state: GameState) -> float:
        _, ev = self.best_discover(pool, state)
        return ev

    def discover_role_hit_prob(self, pool: list, role: RoleTag) -> float:
        if not pool:
            return 0.0
        hits = sum(1 for card in pool if role in classify_card_roles(card))
        return hits / len(pool)

    def discover_role_offer_prob(
        self,
        pool: list,
        role: RoleTag,
        offer_size: int = 3,
    ) -> float:
        if not pool or offer_size <= 0:
            return 0.0

        n_total = len(pool)
        n_offer = min(offer_size, n_total)
        role_hits = sum(1 for card in pool if role in classify_card_roles(card))
        if role_hits <= 0:
            return 0.0
        if role_hits >= n_total:
            return 1.0

        miss = math.comb(n_total - role_hits, n_offer) / math.comb(n_total, n_offer)
        return max(0.0, min(1.0, 1.0 - miss))

    def _score_card(self, card, state: GameState) -> float:
        try:
            from analysis.evaluators.siv import siv_score
            return siv_score(card, state)
        except Exception:
            pass

        base = getattr(card, "score", 0.0) or 0.0
        if base > 0:
            return base

        cost = getattr(card, "cost", 0) or 0
        attack = getattr(card, "attack", 0) or 0
        health = getattr(card, "health", 0) or 0
        card_type = getattr(card, "card_type", "") or ""
        mechanics = getattr(card, "mechanics", []) or []

        score = (attack + health) * 0.5 + cost * 0.3
        if card_type.upper() == "SPELL":
            score = cost * 0.8

        keyword_bonus = len(mechanics) * 0.2
        return score + keyword_bonus


# ===================================================================
# DrawModel
# ===================================================================

class DrawModel:
    """Expected value of drawing cards from deck."""

    def expected_draw_value(self, state: GameState, n_cards: int = 1) -> float:
        deck = state.deck_list
        if not deck or len(deck) == 0:
            return -1.0 if state.fatigue_damage > 0 else 0.0

        remaining = state.deck_remaining
        if remaining <= 0:
            return -1.0 * n_cards

        effective_n = min(n_cards, 10 - len(state.hand))
        if effective_n <= 0:
            return 0.0

        avg_value = self._avg_card_value(state, deck)
        return effective_n * avg_value

    def draw_variance(self, state: GameState) -> float:
        deck = state.deck_list
        if not deck or len(deck) <= 1:
            return 0.0
        scores = [self._card_value(c, state) for c in deck]
        n = len(scores)
        mean = sum(scores) / n
        return sum((s - mean) ** 2 for s in scores) / n

    def top_deck_probability(self, state: GameState, threshold: float) -> float:
        deck = state.deck_list
        if not deck or len(deck) == 0:
            return 0.0
        above = sum(1 for c in deck if self._card_value(c, state) >= threshold)
        return above / len(deck)

    def draw_role_probability(
        self,
        state: GameState,
        role: RoleTag,
        n_draws: int = 1,
    ) -> float:
        deck = state.deck_list
        if not deck or n_draws <= 0:
            return 0.0

        deck_size = len(deck)
        draws = min(n_draws, deck_size)
        if draws <= 0:
            return 0.0

        role_hits = sum(1 for c in deck if role in classify_card_roles(c))
        if role_hits <= 0:
            return 0.0
        if role_hits >= deck_size:
            return 1.0

        miss = math.comb(deck_size - role_hits, draws) / math.comb(deck_size, draws)
        return max(0.0, min(1.0, 1.0 - miss))

    def _avg_card_value(self, state: GameState, deck: list) -> float:
        if not deck:
            return 0.0
        total = sum(self._card_value(c, state) for c in deck)
        return total / len(deck)

    def _card_value(self, card, state: GameState) -> float:
        base = getattr(card, "score", 0.0) or 0.0
        if base > 0:
            return base
        cost = getattr(card, "cost", 0) or 0
        attack = getattr(card, "attack", 0) or 0
        health = getattr(card, "health", 0) or 0
        return (attack + health) * 0.5 + cost * 0.3


# ===================================================================
# RNGModel
# ===================================================================

class RNGModel:
    """Expected value of random effects via Monte Carlo sampling."""

    _DMG_RANGE_EN = re.compile(r'(\d+)\s*(?:to|-)\s*(\d+)\s*damage', re.IGNORECASE)
    _DMG_RANGE_CN = re.compile(r'(\d+)\s*[到至]\s*(\d+)\s*点?伤害')
    _DMG_RANGE_FALLBACK = re.compile(r'damage.*?(\d+)\s*[-~]\s*(\d+)', re.IGNORECASE)
    _DMG_SIMPLE = re.compile(r'damage.*?(\d+)', re.IGNORECASE)

    def expected_value(self, effect: str, state: GameState,
                       n_samples: int = 8) -> float:
        if not effect:
            return 0.0

        results = []
        for _ in range(n_samples):
            outcome = self._resolve_random(effect, state)
            results.append(outcome)
        return sum(results) / len(results) if results else 0.0

    def _resolve_random(self, effect: str, state: GameState) -> float:
        effect_lower = effect.lower()

        dmg_match = self._DMG_RANGE_EN.search(effect_lower)
        if not dmg_match:
            dmg_match = self._DMG_RANGE_CN.search(effect)
        if not dmg_match:
            dmg_match = self._DMG_RANGE_FALLBACK.search(effect_lower)
        if dmg_match:
            lo, hi = int(dmg_match.group(1)), int(dmg_match.group(2))
            return random.randint(lo, hi)

        m = _DAMAGE_EN.search(effect) or _DAMAGE_CN.search(effect)
        if m:
            return float(m.group(1))

        m = self._DMG_SIMPLE.search(effect_lower)
        if m:
            return float(m.group(1))

        m = _HEAL_EN.search(effect) or _HEAL_CN.search(effect)
        if m:
            return float(m.group(1)) * 0.8

        m = _SUMMON_STATS_EN.search(effect) or _SUMMON_STATS_CN.search(effect)
        if m:
            atk, hp = int(m.group(1)), int(m.group(2))
            return (atk + hp) * 0.3

        m = _BUFF_ATK_EN.search(effect) or _BUFF_ATK_CN.search(effect)
        if m:
            return float(m.group(1)) * 0.4

        m = _DRAW_EN.search(effect) or _DRAW_CN.search(effect)
        if m:
            n = int(m.group(1))
            return n * 0.5

        random_targets = ["随机", "random"]
        if any(t in effect_lower for t in random_targets):
            return 1.0

        return 0.5


# ===================================================================
# ProbabilityPanel — composite aggregation of all probability models
# ===================================================================

@dataclass
class OpponentThreatEV:
    expected_hero_damage: float = 0.0
    expected_board_clear_power: float = 0.0
    aoe_risk: float = 0.0
    lethal_next_turn_prob: float = 0.0
    top_threats: list[tuple[str, float, str]] = field(default_factory=list)

    def format_lines(self) -> list[str]:
        lines: list[str] = []
        lines.append(
            f"下回合威胁EV: 直伤={self.expected_hero_damage:.1f} "
            f"解场力={self.expected_board_clear_power:.1f} "
            f"AOE风险={self.aoe_risk:.0%}"
        )
        if self.lethal_next_turn_prob >= 0.05:
            lines.append(f"对手下回合斩杀概率: {self.lethal_next_turn_prob:.0%}")
        if self.top_threats:
            parts = [f"{n}({p:.0%},{t})" for n, p, t in self.top_threats[:4]]
            lines.append("主要威胁牌: " + ", ".join(parts))
        return lines


@dataclass
class ProbabilityPanel:
    draw_clear_1: float = 0.0
    draw_heal_1: float = 0.0
    draw_board_1: float = 0.0
    draw_burst_1: float = 0.0
    draw_clear_2: float = 0.0
    discover_clear: float | None = None
    discover_heal: float | None = None
    discover_board: float | None = None
    opp_lethal_prob: float = 0.0
    opp_threat_ev: OpponentThreatEV | None = None

    def format_category_lines(self, min_prob: float = 0.05) -> list[str]:
        lines: list[str] = []
        draw_1 = self._format_bucket(
            "抽牌(1抽)",
            [
                ("解场", self.draw_clear_1),
                ("回血", self.draw_heal_1),
                ("战场", self.draw_board_1),
                ("直伤", self.draw_burst_1),
            ],
            min_prob,
        )
        if draw_1:
            lines.append(draw_1)

        draw_2 = self._format_bucket(
            "抽牌(2抽)",
            [("解场", self.draw_clear_2)],
            min_prob,
        )
        if draw_2:
            lines.append(draw_2)

        discover = self._format_bucket(
            "发现(3选1)",
            [
                ("解场", self.discover_clear),
                ("回血", self.discover_heal),
                ("战场", self.discover_board),
            ],
            min_prob,
        )
        if discover:
            lines.append(discover)

        if self.opp_threat_ev is not None:
            lines.extend(self.opp_threat_ev.format_lines())

        return lines

    @staticmethod
    def _format_bucket(
        title: str,
        items: list[tuple[str, float | None]],
        min_prob: float,
    ) -> str:
        filtered = []
        for name, prob in items:
            if prob is None:
                continue
            if prob < min_prob:
                continue
            filtered.append(f"{name}={prob:.0%}")
        if not filtered:
            return ""
        return f"{title}: " + ", ".join(filtered)


def compute_panel(
    state: GameState,
    discover_pool: list | None = None,
    opp_hand_roles: dict | None = None,
) -> ProbabilityPanel:
    draw_model = DrawModel()
    discover_model = DiscoverModel()

    draw_clear_1 = _draw_any(
        draw_model,
        state,
        [RoleTag.REMOVAL_SINGLE, RoleTag.REMOVAL_AOE],
        1,
    )
    draw_heal_1 = draw_model.draw_role_probability(state, RoleTag.HEAL, n_draws=1)
    draw_board_1 = draw_model.draw_role_probability(state, RoleTag.TEMPO_BOARD, n_draws=1)
    draw_burst_1 = draw_model.draw_role_probability(state, RoleTag.BURST_DAMAGE, n_draws=1)
    draw_clear_2 = _draw_any(
        draw_model,
        state,
        [RoleTag.REMOVAL_SINGLE, RoleTag.REMOVAL_AOE],
        2,
    )
    discover_clear = None
    discover_heal = None
    discover_board = None
    if discover_pool:
        discover_clear = _discover_any(
            discover_model,
            discover_pool,
            [RoleTag.REMOVAL_SINGLE, RoleTag.REMOVAL_AOE],
        )
        discover_heal = discover_model.discover_role_offer_prob(discover_pool, RoleTag.HEAL)
        discover_board = discover_model.discover_role_offer_prob(discover_pool, RoleTag.TEMPO_BOARD)

    opp_threat_ev = compute_threat_ev(state, opp_hand_roles)

    return ProbabilityPanel(
        draw_clear_1=draw_clear_1,
        draw_heal_1=draw_heal_1,
        draw_board_1=draw_board_1,
        draw_burst_1=draw_burst_1,
        draw_clear_2=draw_clear_2,
        discover_clear=discover_clear,
        discover_heal=discover_heal,
        discover_board=discover_board,
        opp_lethal_prob=_estimate_opp_lethal_prob(state),
        opp_threat_ev=opp_threat_ev,
    )


def _draw_any(
    model: DrawModel,
    state: GameState,
    roles: list[RoleTag],
    n_draws: int,
) -> float:
    p = 0.0
    for role in roles:
        p += model.draw_role_probability(state, role, n_draws=n_draws)
    return max(0.0, min(1.0, p))


def _discover_any(
    model: DiscoverModel,
    pool: list,
    roles: list[RoleTag],
) -> float:
    p = 0.0
    for role in roles:
        p += model.discover_role_offer_prob(pool, role)
    return max(0.0, min(1.0, p))


def _estimate_opp_lethal_prob(state: GameState) -> float:
    hero_hp = state.hero.hp + state.hero.armor
    if hero_hp <= 0:
        return 1.0
    enemy_attack = sum(m.attack for m in state.opponent.board)
    if state.opponent.hero.weapon is not None:
        enemy_attack += state.opponent.hero.weapon.attack
    ratio = enemy_attack / hero_hp
    if ratio >= 1.0:
        return 0.95
    if ratio >= 0.7:
        return 0.6
    if ratio >= 0.4:
        return 0.3
    return 0.1 * max(0.0, ratio)


def compute_threat_ev(
    state: GameState,
    opp_hand_roles: dict | None = None,
) -> OpponentThreatEV:
    ev = OpponentThreatEV()
    hero_hp = state.hero.hp + state.hero.armor
    if hero_hp <= 0:
        ev.lethal_next_turn_prob = 1.0
        return ev

    board_damage = sum(m.attack for m in state.opponent.board)
    if state.opponent.hero.weapon is not None:
        board_damage += state.opponent.hero.weapon.attack

    hand_dmg = 0.0
    hand_aoe = 0.0
    hand_removal = 0.0
    threats: list[tuple[str, float, str]] = []

    if opp_hand_roles:
        for role_name, prob in opp_hand_roles.items():
            if "直伤" in role_name or "爆发" in role_name:
                hand_dmg += prob * 4.0
                if prob >= 0.05:
                    threats.append((role_name, prob, "直伤"))
            elif "群体" in role_name or "AOE" in role_name:
                hand_aoe += prob * 3.0
                if prob >= 0.05:
                    threats.append((role_name, prob, "AOE"))
            elif "解场" in role_name:
                hand_removal += prob * 3.0
                if prob >= 0.05:
                    threats.append((role_name, prob, "解场"))

    ev.expected_hero_damage = board_damage + hand_dmg
    ev.expected_board_clear_power = hand_removal + hand_aoe
    ev.aoe_risk = min(1.0, hand_aoe / max(hero_hp, 1))

    total_dmg = board_damage + hand_dmg
    if total_dmg >= hero_hp:
        ev.lethal_next_turn_prob = 0.95
    elif total_dmg >= hero_hp * 0.7:
        ev.lethal_next_turn_prob = 0.6
    elif total_dmg >= hero_hp * 0.4:
        ev.lethal_next_turn_prob = 0.3
    else:
        ev.lethal_next_turn_prob = 0.1 * (total_dmg / max(hero_hp, 1))

    threats.sort(key=lambda x: x[1], reverse=True)
    ev.top_threats = threats[:4]
    return ev

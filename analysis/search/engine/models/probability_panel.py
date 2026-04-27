"""Unified probability panel for draw/discover/opp-threat estimates."""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    from analysis.card.data.card_roles import RoleTag
except ImportError:
    RoleTag = None
from analysis.search.engine.models.discover_model import DiscoverModel
from analysis.search.engine.models.draw_model import DrawModel
from analysis.card.engine.state import GameState


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
        """Format grouped probabilities, filtering items below ``min_prob``."""
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
    draw_board_1 = draw_model.draw_role_probability(
        state,
        RoleTag.TEMPO_BOARD,
        n_draws=1,
    )
    draw_burst_1 = draw_model.draw_role_probability(
        state,
        RoleTag.BURST_DAMAGE,
        n_draws=1,
    )
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
    # Approximation: use independent upper-bound union clamp.
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

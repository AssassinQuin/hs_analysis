"""tracker_rules.py — TrackerRule Protocol for pluggable tracking rules.

Defines the interface that all tracking rule modules must implement.
Rules are event-driven: GlobalTracker dispatches game events to all
registered rules, which can update GlobalGameState.

Design mirrors the existing Mechanic(Protocol) pattern in
analysis/search/mechanic.py.

Usage::

    class ShuffleTrackerRule:
        name = "shuffle"

        def on_zone_change(self, ctx: TrackingContext) -> None:
            if ctx.new_zone == ZONE_DECK and ctx.card_id:
                ...

    # In GlobalTracker.__init__:
    self._rule_dispatcher = TrackerRuleDispatcher()
    self._rule_dispatcher.register(ShuffleTrackerRule())
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Protocol, runtime_checkable

if TYPE_CHECKING:
    from analysis.watcher.global_tracker import GlobalGameState

logger = logging.getLogger(__name__)

__all__ = ["TrackingContext", "TrackerRule", "TrackerRuleDispatcher"]


# ═══════════════════════════════════════════════════════════════════
# Event context — bundles event parameters for dispatch
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TrackingContext:
    """Immutable context passed to TrackerRule handlers.

    Provides all the information a rule needs to decide whether
    and how to update GlobalGameState.
    """
    entity_id: int
    controller: int
    old_zone: int
    new_zone: int
    card_id: str
    card_type: int
    is_opp: bool
    state: GlobalGameState  # mutable reference — rules modify in-place


# ═══════════════════════════════════════════════════════════════════
# TrackerRule Protocol
# ═══════════════════════════════════════════════════════════════════

@runtime_checkable
class TrackerRule(Protocol):
    """Interface for pluggable tracking rules.

    Each rule handles one tracking concern (shuffle detection,
    corrupt tracking, secret management, etc.).

    Rules modify GlobalGameState in-place. Default no-op
    implementations allow rules to only override the events they
    care about.
    """

    @property
    def name(self) -> str:
        """Human-readable name for logging."""
        ...

    def on_zone_change(self, ctx: TrackingContext) -> None:
        """Called when an entity's ZONE tag changes.

        This is the primary event for most tracking rules.
        Rules can inspect ctx.old_zone / ctx.new_zone to decide
        whether to act.
        """
        ...

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        """Called when a hidden entity is revealed (SHOW_ENTITY log entry).

        Used for corrupt detection and opponent hand intelligence.
        """
        ...

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """Called when the turn counter advances."""
        ...


# ═══════════════════════════════════════════════════════════════════
# Dispatcher — manages registered rules and dispatches events
# ═══════════════════════════════════════════════════════════════════

class TrackerRuleDispatcher:
    """Manages TrackerRule instances and dispatches events to them.

    Rules are called in registration order. Exceptions in individual
    rules are caught and logged to prevent one rule from breaking
    the tracking pipeline.
    """

    def __init__(self) -> None:
        self._rules: List[TrackerRule] = []

    def register(self, rule: TrackerRule) -> None:
        """Register a TrackerRule. It will receive all future events."""
        self._rules.append(rule)

    def dispatch_zone_change(self, ctx: TrackingContext) -> None:
        """Dispatch a zone change event to all registered rules."""
        for rule in self._rules:
            try:
                rule.on_zone_change(ctx)
            except Exception as exc:
                logger.warning(
                    "TrackerRule %s failed in on_zone_change: %s",
                    rule.name, exc,
                )

    def dispatch_show_entity(self, entity_id: int, card_id: str,
                             controller: int, zone: int,
                             card_type: int,
                             state: "GlobalGameState",
                             is_opp: bool) -> None:
        """Dispatch a show_entity event to all registered rules."""
        for rule in self._rules:
            try:
                rule.on_show_entity(
                    entity_id, card_id, controller, zone,
                    card_type, state, is_opp,
                )
            except Exception as exc:
                logger.warning(
                    "TrackerRule %s failed in on_show_entity: %s",
                    rule.name, exc,
                )

    def dispatch_turn_change(self, new_turn: int,
                             state: "GlobalGameState") -> None:
        """Dispatch a turn change event to all registered rules."""
        for rule in self._rules:
            try:
                rule.on_turn_change(new_turn, state)
            except Exception as exc:
                logger.warning(
                    "TrackerRule %s failed in on_turn_change: %s",
                    rule.name, exc,
                )

    def dispatch_card_transformed(self, ctx: TrackingContext,
                                  old_card_id: str, new_card_id: str) -> None:
        """Dispatch a card transformation event to all registered rules.

        Called when a ChangeEntity event is detected (card_id changes
        for an existing entity, e.g. Corrupt upgrade, Polymorph).
        """
        for rule in self._rules:
            handler = getattr(rule, 'on_card_transformed', None)
            if handler is not None:
                try:
                    handler(ctx, old_card_id, new_card_id)
                except Exception as exc:
                    logger.warning(
                        "TrackerRule %s failed in on_card_transformed: %s",
                        rule.name, exc,
                    )


# ═══════════════════════════════════════════════════════════════════
# Built-in rule implementations
# ═══════════════════════════════════════════════════════════════════

class ShuffleTrackerRule:
    """Tracks cards shuffled into either player's deck.
    
    Distinguishes between:
    - Known cards (card_id present): specific card shuffled (e.g., 爆牌鱼 effect)
    - Unknown cards (card_id absent): random/unknown card shuffled
    
    Known shuffled cards are tracked as known information for deck inference.
    When played later, they are marked as GENERATED (not from original deck).
    """

    name = "shuffle"

    def __init__(self) -> None:
        from analysis.constants.hs_enums import ZONE_DECK
        self._ZONE_DECK = ZONE_DECK

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        """Shuffle rule doesn't need show_entity — no-op."""
        pass

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """Shuffle rule doesn't need turn_change — no-op."""
        pass

    def on_zone_change(self, ctx: TrackingContext) -> None:
        if ctx.new_zone != self._ZONE_DECK:
            return

        if ctx.is_opp:
            # Always track in the legacy list for backward compat
            if ctx.card_id:
                ctx.state.opp_shuffled_into_deck.append(ctx.card_id)
                # Mark as known card (we know what was shuffled)
                ctx.state.opp_shuffled_known_cards[ctx.card_id] = True
            else:
                # Unknown card shuffled (no card_id visible)
                ctx.state.opp_shuffled_known_cards[f"unknown_{ctx.entity_id}"] = False
            
            # Track source if entity has birth info
            ctx.state.opp_shuffled_card_sources[ctx.entity_id] = ctx.card_id or ""
        else:
            if ctx.card_id:
                ctx.state.player_shuffled_into_deck.append(ctx.card_id)


class CorruptTrackerRule:
    """Tracks Corrupt upgrades in the opponent's hand.

    Detects when a card in the opponent's hand changes its card_id
    via SHOW_ENTITY (the Corrupt mechanic transforms a card while
    it remains in hand).
    """

    name = "corrupt"

    def __init__(self) -> None:
        from analysis.constants.hs_enums import ZONE_HAND
        self._ZONE_HAND = ZONE_HAND

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        if not is_opp:
            return
        if entity_id in state.opp_hand_card_ids:
            old_card_id = state.opp_hand_card_ids[entity_id][0]
            if old_card_id and old_card_id != card_id and zone == self._ZONE_HAND:
                state.opp_corrupted_cards.append(old_card_id)
                state.opp_corrupted_upgrades[old_card_id] = card_id


class RevealTrackerRule:
    """系统化追踪5类信息揭示型卡牌效果。

    对应炉石中5类信息揭示机制：
    1. DECK_PEEK    — 看对手卡组中的牌（洞察、窃取、揭示卡组顶牌等）
    2. HAND_REVEAL  — 看对手手牌（精神视界、诅咒揭示等）
    3. TRANSFORM    — 变化手牌（腐蚀、变形、奖品替换等）
    4. DECK_INSERT  — 往对手卡组塞牌（瘟疫、诅咒、爆牌鱼等）
    5. TUTOR        — 定向检索（抽特定类型牌，知道抽到牌的种族/学派）

    工作原理：
    - 监听 SHOW_ENTITY 事件：区分揭示到 HAND（手牌揭示）vs DECK（卡组窥探）
    - 监听 zone_change → DECK：记录塞牌事件
    - 监听 card_transformed：记录变形事件
    - 更新 opp_known_deck_cards：确认对手卡组中一定存在的牌
    - 更新 opp_known_hand_types：确认对手手牌的类型约束
    """

    name = "reveal"

    def __init__(self) -> None:
        from analysis.constants.hs_enums import (
            ZONE_DECK, ZONE_HAND, ZONE_PLAY, ZONE_SECRET,
        )
        self._ZONE_DECK = ZONE_DECK
        self._ZONE_HAND = ZONE_HAND
        self._ZONE_PLAY = ZONE_PLAY
        self._ZONE_SECRET = ZONE_SECRET

    def on_zone_change(self, ctx: TrackingContext) -> None:
        """追踪往对手卡组塞牌事件（DECK_INSERT 类型）。"""
        if not ctx.is_opp:
            return
        if ctx.new_zone == self._ZONE_DECK and ctx.card_id:
            from analysis.watcher.tracker_types import CardRevealType, CardRevealRecord
            record = CardRevealRecord(
                card_id=ctx.card_id,
                reveal_type=CardRevealType.DECK_INSERT,
                turn=ctx.state.current_turn,
                entity_id=ctx.entity_id,
                details=f"zone: {ctx.old_zone} → {ctx.new_zone}",
                is_opp=True,
            )
            ctx.state.opp_deck_insert_events.append(record)

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        """区分手牌揭示 vs 卡组窥探。

        SHOW_ENTITY 到 HAND 区域 → 对手手牌被揭示
        SHOW_ENTITY 到 DECK 区域 → 对手卡组被窥探（极罕见但存在）
        SHOW_ENTITY 到 PLAY/SECRET 且 entity 之前在 HAND → 对手打出手牌
        """
        if not is_opp or not card_id:
            return

        from analysis.watcher.tracker_types import CardRevealType, CardRevealRecord

        # 对手卡牌揭示到 HAND 区域：这是看对手手牌的情况
        # （例如：精神视界、诅咒被揭示、Mulligan 阶段等）
        if zone == self._ZONE_HAND:
            # 排除初始手牌（turn==0 时的 Mulligan 不算揭示效果）
            if state.current_turn > 0:
                record = CardRevealRecord(
                    card_id=card_id,
                    reveal_type=CardRevealType.HAND_REVEAL,
                    turn=state.current_turn,
                    entity_id=entity_id,
                    details="shown_to_hand",
                    is_opp=True,
                )
                state.opp_revealed_hand_cards.append(record)

        # 对手卡牌揭示到 DECK 区域：这是看对手卡组的情况
        # （极罕见，但某些卡牌效果会揭示卡组中的牌）
        elif zone == self._ZONE_DECK:
            record = CardRevealRecord(
                card_id=card_id,
                reveal_type=CardRevealType.DECK_PEEK,
                turn=state.current_turn,
                entity_id=entity_id,
                details="shown_in_deck",
                is_opp=True,
            )
            state.opp_revealed_deck_cards.append(record)
            # 确认该牌在对手卡组中
            state.opp_known_deck_cards[card_id] = True

        # 对手卡牌揭示到 PLAY 区域：正常打出，但如果是已知手牌的卡牌被打出
        # 则可以从已知手牌中移除（已由 on_zone_change 处理）
        # 但我们可以补充：如果对手之前有类型约束，打出后确认约束成立
        elif zone in (self._ZONE_PLAY, self._ZONE_SECRET):
            self._check_tutor_constraints(card_id, state)

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """Reveal rule doesn't need turn_change — no-op."""
        pass

    def on_card_transformed(self, ctx: TrackingContext,
                            old_card_id: str, new_card_id: str) -> None:
        """追踪变形事件——更新卡组确认信息。

        当一张对手卡牌变形时：
        - 原始卡可能已不在卡组中（如果是衍生牌）
        - 新卡一定不在原始卡组中（变形产物是衍生的）
        """
        if not ctx.is_opp:
            return

        # 新卡（变形产物）一定不在原始卡组中——从已知卡组牌中移除
        if new_card_id in ctx.state.opp_known_deck_cards:
            del ctx.state.opp_known_deck_cards[new_card_id]

        # 如果原始卡在已知卡组牌中，它可能仍然在卡组（变形只影响这一张）
        # 但如果变形发生在手牌中，原始卡的手牌位置被新卡取代

    def _check_tutor_constraints(self, card_id: str,
                                 state: "GlobalGameState") -> None:
        """检查打出的牌是否满足之前的定向检索约束。

        如果对手之前通过定向检索获得某张牌（如"抽一张龙"），
        当这张牌被打出时，我们可以确认它确实符合约束类型，
        从而验证约束信息的正确性。
        """
        # 查找这张牌是否在 tutor_evidence 中
        for evidence in state.opp_tutor_evidence:
            if evidence.card_id == card_id and not evidence.details.startswith("verified:"):
                # 验证约束——标记为已确认
                evidence.details = f"verified:{evidence.details}"
                break

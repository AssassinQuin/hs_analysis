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

    def on_game_start(self, state: "GlobalGameState") -> None:
        """Called when a new game starts.

        Rules should reset any per-game instance state here
        (e.g., entity tracking sets that could collide across games).
        GlobalGameState is already replaced with a fresh instance by
        GlobalTracker.on_game_start() before this is called.
        """
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

    def dispatch_game_start(self, state: "GlobalGameState") -> None:
        """Dispatch a game start event to all registered rules."""
        for rule in self._rules:
            try:
                rule.on_game_start(state)
            except Exception as exc:
                logger.warning(
                    "TrackerRule %s failed in on_game_start: %s",
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
        from analysis.card.constants.hs_enums import ZONE_DECK
        self._ZONE_DECK = ZONE_DECK

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        """No-op."""
        pass

    def on_game_start(self, state: "GlobalGameState") -> None:
        """No-op."""
        pass

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """No-op."""
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
        from analysis.card.constants.hs_enums import ZONE_HAND
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

    def on_game_start(self, state: "GlobalGameState") -> None:
        """No-op."""
        pass

    def on_zone_change(self, ctx: TrackingContext) -> None:
        """Corrupt rule doesn't need zone_change — no-op."""
        pass

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """Corrupt rule doesn't need turn_change — no-op."""
        pass


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
        if zone == self._ZONE_HAND:
            # 让 Mulligan 阶段的揭示也被追踪
            record = CardRevealRecord(
                card_id=card_id,
                reveal_type=CardRevealType.HAND_REVEAL,
                turn=state.current_turn,
                entity_id=entity_id,
                details="shown_to_hand",
                is_opp=True,
            )
            state.opp_revealed_hand_cards.append(record)

        # DECK zone 的窥探已由 DeckPeekTrackerRule 统一处理，此处不再重复

        elif zone in (self._ZONE_PLAY, self._ZONE_SECRET):
            self._check_tutor_constraints(card_id, state)

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

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """No-op."""
        pass

    def on_game_start(self, state: "GlobalGameState") -> None:
        """No-op."""
        pass

    def on_card_transformed(self, ctx: TrackingContext,
                            old_card_id: str, new_card_id: str) -> None:
        """追踪变形事件——更新卡组确认信息。"""
        if not ctx.is_opp:
            return

        if new_card_id in ctx.state.opp_known_deck_cards:
            del ctx.state.opp_known_deck_cards[new_card_id]

    def _check_tutor_constraints(self, card_id: str,
                                 state: "GlobalGameState") -> None:
        """检查打出的牌是否满足之前的定向检索约束。"""
        for evidence in state.opp_tutor_evidence:
            if evidence.card_id == card_id and not evidence.details.startswith("verified:"):
                evidence.details = f"verified:{evidence.details}"
                break


class TransformTrackerRule:
    """Tracks hand transforms (non-Corrupt card_id changes in opponent's hand).

    Distinguishes from Corrupt by delegation order:
    - CorruptTrackerRule is registered first; it records upgrades in opp_corrupted_upgrades
    - This rule runs second and skips any entity already recorded as corrupt
    - Any remaining card_id change is treated as a transform (Chameleos, SP-28, etc.)

    Records original → new card_id mapping for hand inference.
    The original card_id is preserved for deck composition tracking
    (the transformed card is no longer in its original form).
    """

    name = "transform"

    def __init__(self) -> None:
        from analysis.constants.hs_enums import ZONE_HAND
        self._ZONE_HAND = ZONE_HAND

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        if not is_opp or zone != self._ZONE_HAND:
            return
        if entity_id not in state.opp_hand_card_ids:
            return

        old_card_id = state.opp_hand_card_ids[entity_id][0]
        if not old_card_id or old_card_id == card_id:
            return

        # Skip if this entity already has a corrupt upgrade recorded
        if old_card_id in state.opp_corrupted_upgrades:
            return

        # Record the transform
        state.opp_hand_transforms.append({
            "entity_id": entity_id,
            "old_card_id": old_card_id,
            "new_card_id": card_id,
            "turn": state.current_turn,
        })

        logger.info(
            "对手手牌变形: %s → %s (entity=%d, turn=%d)",
            old_card_id, card_id, entity_id, state.current_turn,
        )

    def on_game_start(self, state: "GlobalGameState") -> None:
        """No-op: no per-game state to reset."""
        pass

    def on_zone_change(self, ctx: TrackingContext) -> None:
        """No-op."""
        pass

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """No-op."""
        pass


class DeckPeekTrackerRule:
    """Tracks cards revealed in opponent's deck (peek effects).

    When a SHOW_ENTITY appears in DECK zone for opponent, it means
    a card in their deck was revealed (e.g., "The Light! It Burns!",
    Neural Needle, or Discover from opponent's deck).

    These are tracked separately from hand reveals to provide
    deck composition intelligence.
    """

    name = "deck_peek"

    def __init__(self) -> None:
        from analysis.constants.hs_enums import ZONE_DECK
        self._ZONE_DECK = ZONE_DECK
        self._peeked_entities: set = set()

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        if not is_opp or zone != self._ZONE_DECK:
            return
        if not card_id or entity_id in self._peeked_entities:
            return

        self._peeked_entities.add(entity_id)
        state.opp_peeked_deck_cards.append({
            "card_id": card_id,
            "entity_id": entity_id,
            "turn": state.current_turn,
        })
        # 确认该牌在对手卡组中（唯一写入点，避免与 RevealTrackerRule 重复）
        state.opp_known_deck_cards[card_id] = True

        logger.info(
            "窥探对手牌库: %s (entity=%d, turn=%d)",
            card_id, entity_id, state.current_turn,
        )

    def on_game_start(self, state: "GlobalGameState") -> None:
        """Reset peek tracking for new game (entity IDs can collide across games)."""
        self._peeked_entities.clear()

    def on_zone_change(self, ctx: TrackingContext) -> None:
        """No-op."""
        pass

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """No-op."""
        pass


class DiscardTrackerRule:
    """Tracks opponent's discarded cards for probability exclusion.

    When a card goes from HAND to GRAVEYARD (discard effect like
    Doomguard, Soulfire), the card_id is revealed via SHOW_ENTITY
    and recorded. Discarded cards are excluded from hand probability
    calculations since they can no longer be in hand.
    """

    name = "discard"

    def __init__(self) -> None:
        from analysis.constants.hs_enums import ZONE_HAND, ZONE_GRAVEYARD
        self._ZONE_HAND = ZONE_HAND
        self._ZONE_GRAVEYARD = ZONE_GRAVEYARD

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        """Discard rule doesn't use show_entity directly — no-op.
        
        Discard tracking relies on zone HAND→GRAVEYARD plus
        the card_id being known from SHOW_ENTITY.
        """
        pass

    def on_game_start(self, state: "GlobalGameState") -> None:
        """No-op: discarded_cards is reset via GlobalGameState replacement."""
        pass

    def on_zone_change(self, ctx: TrackingContext) -> None:
        if not ctx.is_opp:
            return
        if ctx.old_zone != self._ZONE_HAND or ctx.new_zone != self._ZONE_GRAVEYARD:
            return

        card_id = ctx.card_id
        # Also check if we know the card from opp_hand_card_ids
        if not card_id and ctx.entity_id in ctx.state.opp_hand_card_ids:
            card_id = ctx.state.opp_hand_card_ids[ctx.entity_id][0]

        if card_id:
            ctx.state.opp_discarded_cards.append(card_id)
            logger.info(
                "对手弃牌: %s (entity=%d, turn=%d)",
                card_id, ctx.entity_id, ctx.state.current_turn,
            )

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """No-op."""
        pass


class TutorConstraintTrackerRule:
    """Tracks tutor effects that confirm card types in opponent's hand.

    When opponent plays a card with "Draw a [type]" or "Discover a [type]",
    we know the opponent's hand now contains a card of that type.
    This creates a HandConstraint for probability calculation.

    Detection strategy:
    - Delegates text parsing to ``card_effects.CardEffects`` (the compiler
      layer) which extracts ``tutor_card_type``, ``tutor_race``, and
      ``tutor_spell_school`` from the card's English text.
    - This rule contains **zero regex** — it only reads structured fields.
    """

    name = "tutor_constraint"

    def __init__(self) -> None:
        pass

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        """No-op: tutor constraints are detected from zone changes."""
        pass

    def on_game_start(self, state: "GlobalGameState") -> None:
        """No-op: constraints are reset via GlobalGameState replacement."""
        pass

    def on_zone_change(self, ctx: TrackingContext) -> None:
        """Detect tutor effects when opponent plays a card (HAND→PLAY)."""
        if not ctx.is_opp:
            return
        from analysis.constants.hs_enums import ZONE_PLAY
        if ctx.new_zone != ZONE_PLAY:
            return

        if not ctx.card_id:
            return

        # Read structured tutor constraints from the compiler layer
        constraints = self._extract_tutor_constraints(ctx.card_id, ctx.state.current_turn)
        for constraint in constraints:
            ctx.state.opp_hand_type_constraints.append(constraint)
            logger.info(
                "导师效果确认对手手牌类型: %s=%s (source=%s, turn=%d)",
                constraint["type"], constraint["value"],
                constraint["card_id"], constraint["turn"],
            )

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """Clear stale constraints.

        Keep constraints from last 2 turns only.  "Draw" and "Discover"
        effects resolve immediately, but the drawn card may stay in hand
        for a turn or two before being played.
        """
        cutoff = new_turn - 2
        state.opp_hand_type_constraints = [
            c for c in state.opp_hand_type_constraints
            if c.get("turn", 0) >= cutoff
        ]

    @staticmethod
    def _extract_tutor_constraints(card_id: str, turn: int) -> list:
        """Read tutor constraints from the structured card effects layer.

        Delegates to ``card_effects.get_effects()`` — no regex here.
        """
        try:
            from analysis.data.hsdb import get_db
            from analysis.data.card_effects import get_effects
            from analysis.models.card import Card

            db = get_db()
            raw = db.get_card(card_id)
            if not raw:
                return []

            card = Card.from_hsdb_dict(raw)
            eff = get_effects(card)
        except Exception:
            return []

        constraints = []
        if eff.tutor_card_type:
            constraints.append({
                "type": "card_type",
                "value": eff.tutor_card_type,
                "card_id": card_id,
                "turn": turn,
            })
        if eff.tutor_race:
            constraints.append({
                "type": "race",
                "value": eff.tutor_race,
                "card_id": card_id,
                "turn": turn,
            })
        if eff.tutor_spell_school:
            constraints.append({
                "type": "spell_school",
                "value": eff.tutor_spell_school,
                "card_id": card_id,
                "turn": turn,
            })
        return constraints


class GallywixTrackerRule:
    """Tracks effects that reveal opponent's hand/deck contents via card copy mechanics.

    Two detection paths:
    1. **Mind Vision / similar**: Our card gains a card_id → the card_id came
       from opponent's hand, confirming what they hold. Detected via SHOW_ENTITY
       for our hand cards that appear as generated copies.
    2. **Thoughtsteal / similar**: Our card gains a card_id → the card_id came
       from opponent's deck, confirming deck composition. Detected similarly.

    Note: A fully correct implementation would need to track which cards we
    played (e.g., Mind Vision) and correlate with the copied card_id.
    This rule detects the pattern at a higher level: when we gain a card in
    hand that matches known copy-source effects, it records the confirmation.

    For now, this rule is a structural placeholder. The actual copy-card
    detection requires correlating:
    - Which card we played (e.g., CS2_004 = Mind Vision)
    - The resulting card_id that appeared in our hand
    This correlation is better handled in on_zone_change or a dedicated
    event pipeline, and is deferred to a future iteration.
    """

    name = "gallywix"

    def __init__(self) -> None:
        pass

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        """No-op: copy-card detection requires play→gain correlation."""
        pass

    def on_game_start(self, state: "GlobalGameState") -> None:
        """No-op."""
        pass

    def on_zone_change(self, ctx: TrackingContext) -> None:
        """No-op: copy-card detection requires play→gain correlation.

        Future implementation:
        1. Track when we play Mind Vision (CS2_004) → next SHOW_ENTITY
           in our hand reveals opponent's hand card
        2. Track when we play Thoughtsteal (EX1_339) → next 2 SHOW_ENTITY
           in our hand reveal opponent's deck cards
        """
        pass

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """No-op."""
        pass

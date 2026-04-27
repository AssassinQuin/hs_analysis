# -*- coding: utf-8 -*-
"""
Bayesian Opponent Model — Infer opponent's deck archetype from observed cards.

Uses HSReplay archetype signature data to perform sequential Bayesian updates
as the opponent plays cards during a Hearthstone match.

Mathematical foundation:
  Prior:     P(deck_i) = usage_rate_i / Σ(usage_rates)
  Likelihood: P(seen_X | deck_i) = 0.8  if X ∈ signature(deck_i)
                             = 0.02  otherwise (epsilon for non-signature)
  Posterior:  P(deck_i | seen_X) ∝ P(seen_X | deck_i) × P(deck_i)

Data sources:
   - CardDB (analysis.data.card_data) → card name lookups
"""
import logging

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

log = logging.getLogger(__name__)

# ── CardDB ──────────────────────────────────────────
from analysis.card.data.card_data import get_db

# ── Constants ──────────────────────────────────────
SIGNATURE_LIKELIHOOD = 0.8   # P(seen_X | deck_i) when X is a signature card
EPSILON_LIKELIHOOD = 0.02    # P(seen_X | deck_i) when X is NOT in signature
LOCK_THRESHOLD = 0.60        # Confidence threshold for deck lock


# ── Playstyle classification ──────────────────────
_AGGRO_KEYWORDS = {'face', 'aggro', 'rush', 'hyper', 'pirate', 'odd', 'murloc', 'zoo', 'token', 'tempo', 'imbue'}
_CONTROL_KEYWORDS = {'control', 'reno', 'highlander', 'wall', 'greed', 'fatigue', 'soul', 'reason'}
_COMBO_KEYWORDS = {'combo', 'otk', 'malygos', 'miracle', 'toggwaggle', 'mechathun', 'raleigh', 'soulfire'}
_MIDRANGE_KEYWORDS = {'midrange', 'dragon', 'even', 'hand', 'bomb', 'ramp', 'menagerie'}


def classify_playstyle(archetype_name: str) -> str:
    """Classify an archetype name into a playstyle category.
    
    Args:
        archetype_name: Archetype name like 'Face Hunter', 'Control Warrior'
    
    Returns:
        One of: 'aggro', 'control', 'combo', 'midrange', 'unknown'
    """
    if not archetype_name:
        return 'unknown'
    
    name_lower = archetype_name.lower()
    
    for kw in _COMBO_KEYWORDS:
        if kw in name_lower:
            return 'combo'
    for kw in _AGGRO_KEYWORDS:
        if kw in name_lower:
            return 'aggro'
    for kw in _CONTROL_KEYWORDS:
        if kw in name_lower:
            return 'control'
    for kw in _MIDRANGE_KEYWORDS:
        if kw in name_lower:
            return 'midrange'
    
    return 'unknown'


class BayesianOpponentModel:
    """Sequential Bayesian inference of opponent deck archetype.

    Maintains a probability distribution over known meta archetypes,
    updating posteriors each time the opponent plays a card. Supports
    class filtering, deck locking, and next-card prediction.

    Attributes:
        decks: list of archetype dicts with keys
               (archetype_id, class, name, cards, winrate, usage_rate)
        posteriors: dict mapping archetype_id → posterior probability
        card_to_decks: inverted index mapping dbfId → set of archetype_ids
        cards_by_dbf: dict mapping dbfId → card info dict
        locked: tuple(archetype_id, confidence) or None
    """

    def __init__(self, player_class=None):
        """Load meta decks and build prior distribution.

        Args:
            player_class: Optional opponent class filter (e.g. 'MAGE').
                          If None, considers all archetypes.
        """
        self.player_class = player_class
        self.decks = []
        self.posteriors = {}
        self.card_to_decks = defaultdict(set)
        self.cards_by_dbf = {}
        self.locked = None

        # Separate tracking for source correctness
        self._seen_deck_cards = Counter()  # dbfId → count, DECK source only
        self._seen_cards_counter = Counter()  # dbfId → count, all sources (DECK+GENERATED)
        self._seen_cards = []               # kept for backward compat (append-only history)

        # Known hand cards (from reveal effects like Tracking, card text)
        self._known_hand_cards = []    # list of (dbfId, turn_seen) tuples

        # Hand-held inference: track how many turns cards stay in hand
        self._hand_hold_since = {}     # entity_id → turn_first_seen_in_hand

        # Load card name lookups
        self._load_card_data()

        # Load meta decks from SQLite cache
        self._load_decks(player_class)

        # Build inverted index: dbfId → {archetype_ids that contain it}
        for deck in self.decks:
            aid = deck["archetype_id"]
            for dbf in deck["cards"]:
                self.card_to_decks[dbf].add(aid)

        # Build initial prior
        self.posteriors = self.build_prior(player_class)

    def _load_card_data(self):
        """Load card data from CardDB for dbfId lookups."""
        try:
            db = get_db()
            self.cards_by_dbf = dict(db.dbf_lookup)
        except Exception:
            self.cards_by_dbf = {}

    def _load_decks(self, player_class=None):
        """Load meta decks from SQLite cache, optionally filtering by class."""
        pass  # HSReplay data source removed; decks remain empty

    def build_prior(self, player_class=None):
        """Build prior probability distribution over archetypes.

        P(deck_i) = usage_rate_i / Σ(usage_rates)

        Falls back to uniform 1/N if no usage rates are available.
        If player_class is given, only archetypes of that class are considered.

        Args:
            player_class: Optional class filter.

        Returns:
            dict[int, float]: archetype_id → prior probability
        """
        if player_class:
            decks = [d for d in self.decks if d["class"] == player_class]
        else:
            decks = self.decks

        if not decks:
            # No data at all — can't build a meaningful prior
            return {}

        # Try usage-rate-weighted prior
        usage_rates = []
        for d in decks:
            rate = d.get("usage_rate") or 0.0
            usage_rates.append(rate)

        total = sum(usage_rates)
        if total > 0:
            return {
                d["archetype_id"]: (d.get("usage_rate") or 0.0) / total
                for d in decks
            }
        else:
            # Uniform prior
            n = len(decks)
            return {d["archetype_id"]: 1.0 / n for d in decks}

    def update(self, seen_card_dbfId: int) -> dict:
        """Perform one Bayesian update after observing a card.

        P(deck_i | seen_X) = P(seen_X | deck_i) * P(deck_i) / P(seen_X)

        Likelihood:
          - 0.8 if seen_card is in deck_i's signature core
          - 0.02 otherwise (epsilon, accounts for non-signature cards)

        Unlock: If locked and the observed card is NOT in the locked deck's
        signature, the lock may be wrong → trigger unlock.

        Args:
            seen_card_dbfId: dbfId of the card observed being played.

        Returns:
            dict[int, float]: Updated posterior probabilities.
        """
        self._seen_cards.append(seen_card_dbfId)
        self._seen_deck_cards[seen_card_dbfId] += 1
        self._seen_cards_counter[seen_card_dbfId] += 1

        # Unlock check: if locked and card doesn't match locked deck
        if self.locked is not None:
            locked_deck = None
            for deck in self.decks:
                if deck["archetype_id"] == self.locked[0]:
                    locked_deck = deck
                    break
            
            if locked_deck is not None:
                if seen_card_dbfId not in locked_deck["cards"]:
                    # Card doesn't belong to locked deck — might be wrong deck
                    self._unlock_count = getattr(self, '_unlock_count', 0) + 1
                    if self._unlock_count >= 2:
                        # 2+ inconsistent cards → unlock
                        self._do_unlock()
                else:
                    # Consistent card — reset unlock counter
                    self._unlock_count = 0
            
            if self.locked is not None:
                return dict(self.posteriors)

        unnormalized = {}
        for deck in self.decks:
            aid = deck["archetype_id"]
            prior = self.posteriors.get(aid, 0.0)
            if prior == 0.0:
                unnormalized[aid] = 0.0
                continue

            # Compute likelihood
            if seen_card_dbfId in deck["cards"]:
                likelihood = SIGNATURE_LIKELIHOOD
            else:
                likelihood = EPSILON_LIKELIHOOD

            unnormalized[aid] = likelihood * prior

        # Normalize
        total = sum(unnormalized.values())
        if total > 0:
            self.posteriors = {
                aid: val / total for aid, val in unnormalized.items()
            }
        # else: keep existing posteriors (shouldn't happen in practice)

        # Check lock
        self.locked = self.get_lock()

        return dict(self.posteriors)

    def update_batch(self, seen_cards: list) -> dict:
        """Sequential Bayesian update for multiple observed cards.

        Args:
            seen_cards: List of dbfId integers.

        Returns:
            dict[int, float]: Final posterior probabilities.
        """
        for dbf in seen_cards:
            self.update(dbf)
        return dict(self.posteriors)

    def update_from_hand(self, seen_card_dbfId: int) -> dict:
        """Update posteriors from a card seen in opponent's hand.
        
        Used for Tracking, Mulligan reveals, and other effects that
        show opponent hand cards. Uses lower confidence than play
        observations (the card might not have been played this game).
        
        Args:
            seen_card_dbfId: dbfId of the card seen in hand.
        
        Returns:
            dict[int, float]: Updated posterior probabilities.
        """
        self._seen_cards.append(seen_card_dbfId)
        self._seen_cards_counter[seen_card_dbfId] += 1
        
        # Don't update if locked
        if self.locked is not None:
            return dict(self.posteriors)
        
        # Lower likelihood for hand observations (less certain than play)
        HAND_LIKELIHOOD = 0.6     # card in deck signature
        HAND_EPSILON = 0.05       # card not in signature
        
        unnormalized = {}
        for deck in self.decks:
            aid = deck["archetype_id"]
            prior = self.posteriors.get(aid, 0.0)
            if prior == 0.0:
                unnormalized[aid] = 0.0
                continue
            
            if seen_card_dbfId in deck["cards"]:
                likelihood = HAND_LIKELIHOOD
            else:
                likelihood = HAND_EPSILON
            
            unnormalized[aid] = likelihood * prior
        
        total = sum(unnormalized.values())
        if total > 0:
            self.posteriors = {
                aid: val / total for aid, val in unnormalized.items()
            }
        
        self.locked = self.get_lock()
        return dict(self.posteriors)

    def update_generated(self, seen_card_dbfId: int) -> dict:
        """Record a GENERATED-source card observation.

        Generated/discovered cards are NOT from the original deck.
        We track them for exclusion in predict_hand() but do NOT
        update posteriors — they provide no information about deck composition.

        Args:
            seen_card_dbfId: dbfId of the generated card.

        Returns:
            dict[int, float]: Current posteriors (unchanged).
        """
        self._seen_cards.append(seen_card_dbfId)
        self._seen_cards_counter[seen_card_dbfId] += 1
        # Do NOT append to _seen_deck_cards — generated cards aren't evidence
        # Do NOT update posteriors — generated cards don't indicate deck choice
        return dict(self.posteriors)

    def record_known_hand_card(self, dbf_id: int, turn: int):
        """Record a card definitively seen in opponent's hand.

        Used for Tracking, Insight, and other reveal effects.
        These cards will be prioritized in hand sampling over
        generic predictions.

        Args:
            dbf_id: dbfId of the card seen in hand.
            turn: Current turn number.
        """
        self._known_hand_cards.append((dbf_id, turn))
        # Also add to exclusion set
        if dbf_id not in self._seen_cards:
            self._seen_cards.append(dbf_id)

    def update_hand_hold(self, entity_id: int, current_turn: int):
        """Track how long an opponent hand card has been held.

        Cards held for many turns are likely high-cost.

        Args:
            entity_id: The entity ID of the hand card.
            current_turn: Current turn number.
        """
        if entity_id not in self._hand_hold_since:
            self._hand_hold_since[entity_id] = current_turn

    def get_cost_bias_for_hand(self, opp_hand_count: int, current_turn: int) -> dict:
        """Compute cost-probability bias based on how long cards have been held.

        If the opponent has held cards for many turns without playing them,
        those cards are more likely to be high-cost.

        Args:
            opp_hand_count: Number of cards in opponent's hand.
            current_turn: Current turn number.

        Returns:
            dict mapping cost → bias multiplier. Higher costs get higher
            bias when cards have been held long.
        """
        if not self._hand_hold_since or opp_hand_count <= 0:
            return {}

        # Compute average hold duration for known hand entities
        hold_durations = []
        for eid, start_turn in self._hand_hold_since.items():
            duration = current_turn - start_turn
            if duration > 0:
                hold_durations.append(duration)

        if not hold_durations:
            return {}

        avg_hold = sum(hold_durations) / len(hold_durations)

        # If average hold is <= 1 turn, no bias needed
        if avg_hold <= 1:
            return {}

        # Bias: cards held for N+ turns are increasingly likely to be high cost
        # Scale: 1 turn = no bias, 3+ turns = strong high-cost bias
        bias_strength = min(1.0, avg_hold / 5.0)  # cap at 1.0

        cost_bias = {}
        for cost in range(0, 11):
            if cost <= 2:
                cost_bias[cost] = 1.0 - 0.3 * bias_strength  # low cost: slight penalty
            elif cost <= 4:
                cost_bias[cost] = 1.0  # mid cost: neutral
            elif cost <= 6:
                cost_bias[cost] = 1.0 + 0.5 * bias_strength  # high cost: boost
            else:
                cost_bias[cost] = 1.0 + 1.0 * bias_strength  # very high: strong boost

        return cost_bias

    def get_lock(self) -> tuple:
        """Check if any archetype exceeds the lock threshold.

        Returns:
            (archetype_id, confidence) if max posterior > 0.60,
            otherwise None.
        """
        if not self.posteriors:
            return None
        best_id = max(self.posteriors, key=self.posteriors.get)
        best_prob = self.posteriors[best_id]
        if best_prob > LOCK_THRESHOLD:
            return (best_id, best_prob)
        return None

    def _do_unlock(self):
        """Unlock the current archetype lock.
        
        Resets lock and reduces all posteriors toward uniform,
        keeping relative ordering but dampening confidence.
        """
        log.info(
            f"BayesianModel: unlocking from {self._deck_name(self.locked[0])} "
            f"(confidence was {self.locked[1]:.2f}, {getattr(self, '_unlock_count', 0)} inconsistencies)"
        )
        self.locked = None
        self._unlock_count = 0
        
        # Dampen posteriors: blend 50% current + 50% uniform
        if self.posteriors:
            n = len(self.posteriors)
            uniform = 1.0 / n
            self.posteriors = {
                aid: 0.5 * prob + 0.5 * uniform
                for aid, prob in self.posteriors.items()
            }

    def get_top_decks(self, n=5) -> list:
        """Return top N archetypes by posterior probability.

        Args:
            n: Number of top decks to return.

        Returns:
            list of (archetype_id, name, probability) tuples,
            sorted by probability descending.
        """
        ranked = sorted(
            self.posteriors.items(), key=lambda x: x[1], reverse=True
        )
        result = []
        for aid, prob in ranked[:n]:
            name = self._deck_name(aid)
            result.append((aid, name, prob))
        return result

    def predict_next_actions(self, n=3) -> list:
        """Predict cards the opponent might play next.

        Based on the locked deck (if available) or the top-probability deck,
        returns signature cards not yet observed, ranked by likelihood.

        Args:
            n: Number of predictions to return.

        Returns:
            list of dicts with keys: dbfId, probability, name
        """
        # Determine which deck to predict from
        if self.locked:
            target_id = self.locked[0]
            target_prob = self.locked[1]
        else:
            top = self.get_top_decks(1)
            if not top:
                return []
            target_id = top[0][0]
            target_prob = top[0][2]

        # Find the deck's signature cards
        deck = self._find_deck(target_id)
        if not deck:
            return []

        # Cards not yet seen
        # Count-aware: deck cards minus seen deck cards
        deck_remaining = list(deck["cards"])
        seen_copy = dict(self._seen_deck_cards)
        unseen = []
        for dbf in deck_remaining:
            if seen_copy.get(dbf, 0) > 0:
                seen_copy[dbf] -= 1
            else:
                unseen.append(dbf)
        if not unseen:
            return []

        predictions = []
        for dbf in unseen[:n]:
            card_info = self.cards_by_dbf.get(dbf, {})
            predictions.append({
                "dbfId": dbf,
                "probability": round(target_prob, 4),
                "name": card_info.get("name", f"Unknown({dbf})"),
            })
        return predictions

    def reset(self):
        """Reset posteriors to prior, clear seen cards and lock."""
        self.posteriors = self.build_prior(self.player_class)
        self._seen_cards = []
        self._seen_deck_cards = Counter()
        self._seen_cards_counter = Counter()
        self._known_hand_cards = []
        self._hand_hold_since = {}
        self.locked = None

    def predict_hand(self, opp, state, current_turn: int = 0) -> list:
        """预测对手手牌候选池（供 Determinizer 采样）。

        综合多种信息源：
        1. 已知手牌（从窥牌效果看到的）— 最高优先级
        2. 锁定/最高后验卡组中未观测到的牌 — 基础池
        3. 持有回合推断 — 对长期未打的手牌增加高费牌权重

        Args:
            opp: OpponentState（用于读取已打出卡牌信息）
            state: GameState（备用上下文）
            current_turn: 当前回合数（用于持有回合推断）

        Returns:
            List[Card]: 对手可能持有的卡牌候选池
        """
        from analysis.card.models.card import Card

        # 确定目标卡组
        if self.locked:
            target_id = self.locked[0]
        else:
            top = self.get_top_decks(1)
            if not top:
                return []
            target_id = top[0][0]

        deck = self._find_deck(target_id)
        if not deck:
            return []

        # 计数排除：已用张数的牌不再出现
        # deck["cards"] 是带重复的 flat list（如 [dbf1, dbf1, dbf2, ...]）
        # _seen_cards_counter 跟踪每种牌已出现的次数
        remaining_dbfs = list(deck["cards"])  # copy the flat list
        
        # 按 dbfId 计数排除
        seen_counts = dict(self._seen_cards_counter)
        # 也排除对手已知已打出的牌
        if hasattr(opp, 'opp_known_cards') and opp.opp_known_cards:
            for kc in opp.opp_known_cards:
                dbf = getattr(kc, 'dbf_id', None) or (kc.get('dbf_id') if isinstance(kc, dict) else None)
                if dbf:
                    seen_counts[dbf] = seen_counts.get(dbf, 0) + 1
        
        # 按已看张数过滤：卡组有 N 张，已见 M 张，剩余 N-M 张
        filtered = []
        for dbf in remaining_dbfs:
            seen = seen_counts.get(dbf, 0)
            if seen > 0:
                seen_counts[dbf] = seen - 1  # consume one copy
            else:
                filtered.append(dbf)
        remaining_dbfs = filtered
        candidates = self._dbfs_to_cards(remaining_dbfs)

        # 应用持有回合推断的成本偏好
        if current_turn > 0 and hasattr(opp, 'hand_count'):
            cost_bias = self.get_cost_bias_for_hand(opp.hand_count, current_turn)
            if cost_bias and candidates:
                # 按偏好加权复制候选牌
                weighted = []
                for card in candidates:
                    cost = getattr(card, 'cost', 0)
                    bias = cost_bias.get(cost, 1.0)
                    # 复制 bias 次（整数部分）+ 按小数部分概率额外复制
                    copies = int(bias)
                    if bias - copies > 0 and (hash(card.card_id) % 100) / 100.0 < (bias - copies):
                        copies += 1
                    copies = max(1, copies)
                    weighted.extend([card] * copies)
                candidates = weighted

        return candidates

    def get_known_hand_cards(self, exclude_dbfs: set = None) -> list:
        """获取已知手牌列表（从窥牌效果确定看到的牌）。

        Args:
            exclude_dbfs: 需要排除的 dbfId 集合（已打出的牌等）

        Returns:
            List[Card]: 确定在对手手牌中的卡牌列表
        """
        from analysis.card.models.card import Card

        if not self._known_hand_cards:
            return []

        exclude = exclude_dbfs or set()
        result = []
        seen_dbfs = set()

        for dbf_id, turn in self._known_hand_cards:
            if dbf_id not in exclude and dbf_id not in seen_dbfs:
                cards = self._dbfs_to_cards([dbf_id])
                if cards:
                    result.extend(cards)
                    seen_dbfs.add(dbf_id)

        return result

    def get_remaining_cards(self, opp) -> list:
        """获取对手剩余牌库（供 Determinizer 采样牌库顺序）。

        Args:
            opp: OpponentState

        Returns:
            List[Card]: 对手剩余卡牌列表
        """
        # 计数排除
        seen_counts = dict(self._seen_cards_counter)
        if hasattr(opp, 'opp_known_cards') and opp.opp_known_cards:
            for kc in opp.opp_known_cards:
                dbf = getattr(kc, 'dbf_id', None) or (kc.get('dbf_id') if isinstance(kc, dict) else None)
                if dbf:
                    seen_counts[dbf] = seen_counts.get(dbf, 0) + 1

        if self.locked:
            deck = self._find_deck(self.locked[0])
            if deck:
                remaining = list(deck["cards"])
                filtered = []
                for dbf in remaining:
                    seen = seen_counts.get(dbf, 0)
                    if seen > 0:
                        seen_counts[dbf] = seen - 1
                    else:
                        filtered.append(dbf)
                return self._dbfs_to_cards(filtered)
            return []

        # 未锁定时，合并 top-3 卡组的剩余卡牌（计数去重）
        all_remaining_dbfs = []
        seen_dbfs = set()
        for aid, _, prob in self.get_top_decks(3):
            deck = self._find_deck(aid)
            if not deck:
                continue
            deck_remaining = list(deck["cards"])
            deck_counts = dict(self._seen_cards_counter)
            for dbf in deck_remaining:
                seen = deck_counts.get(dbf, 0)
                if seen > 0:
                    deck_counts[dbf] = seen - 1
                elif dbf not in seen_dbfs:
                    all_remaining_dbfs.append(dbf)
                    seen_dbfs.add(dbf)

        return self._dbfs_to_cards(all_remaining_dbfs)

    # ── Helpers ─────────────────────────────────────

    def _dbfs_to_cards(self, dbf_ids: list) -> list:
        """将 dbfId 列表转换为 Card 对象列表。

        优先使用 from_hsdb_dict 构建完整 Card，回退到基础字段构造。

        Args:
            dbf_ids: dbfId 整数列表

        Returns:
            List[Card]: Card 对象列表
        """
        from analysis.card.models.card import Card

        cards = []
        for dbf in dbf_ids:
            info = self.cards_by_dbf.get(dbf)
            if info:
                try:
                    cards.append(Card.from_hsdb_dict(info))
                except Exception:
                    cards.append(Card(
                        dbf_id=dbf,
                        name=info.get("name", f"Card#{dbf}"),
                        cost=info.get("cost", 0),
                        card_type=info.get("type", ""),
                        card_class=info.get("cardClass", ""),
                    ))
            else:
                cards.append(Card(
                    dbf_id=dbf,
                    name=f"Card#{dbf}",
                    cost=0,
                ))
        return cards

    def _deck_name(self, archetype_id: int) -> str:
        """Look up archetype name by ID."""
        for d in self.decks:
            if d["archetype_id"] == archetype_id:
                return d["name"]
        return f"Archetype#{archetype_id}"

    def _find_deck(self, archetype_id: int):
        """Find deck dict by archetype_id."""
        for d in self.decks:
            if d["archetype_id"] == archetype_id:
                return d
        return None

    def card_name(self, dbfId: int) -> str:
        """Look up card name by dbfId."""
        info = self.cards_by_dbf.get(dbfId)
        return info["name"] if info else f"dbfId={dbfId}"

    # ── Conditional Evidence (Phase 3) ────────────────

    def conditional_evidence(self, evidence_type: str, value: str = "",
                             likelihood_boost: float = 1.5) -> dict:
        """Apply conditional card effect as Bayesian evidence.

        When an opponent plays a card with a conditional effect that triggers
        (e.g., "If you're holding a Dragon"), this provides evidence about
        their hand composition and thus their deck archetype.

        Args:
            evidence_type: Type of conditional evidence:
                "HOLDING_RACE" — holding a specific race (e.g., Dragon)
                "HOLDING_SPELL_SCHOOL" — holding a specific spell school
                "SPELL_CAST_THIS_TURN" — played a spell this turn
                "MINION_DIED_THIS_TURN" — had a minion die this turn
            value: The specific value (e.g., "DRAGON", "FIRE")
            likelihood_boost: Multiplier for deck archetypes that commonly
                contain cards of the specified type. Default 1.5.

        Returns:
            Updated posteriors.
        """
        if self.locked is not None:
            return dict(self.posteriors)

        if not self.decks or not self.cards_by_dbf:
            return dict(self.posteriors)

        # Determine target card attribute based on evidence type
        target_races = set()
        target_schools = set()

        if evidence_type == "HOLDING_RACE" and value:
            target_races.add(value.upper())
        elif evidence_type == "HOLDING_SPELL_SCHOOL" and value:
            target_schools.add(value.upper())

        if not target_races and not target_schools:
            return dict(self.posteriors)

        # For each deck archetype, check if it contains cards of the
        # specified type and boost accordingly
        unnormalized = {}
        for deck in self.decks:
            aid = deck["archetype_id"]
            prior = self.posteriors.get(aid, 0.0)
            if prior == 0.0:
                unnormalized[aid] = 0.0
                continue

            # Check if deck contains cards matching the condition
            has_match = False
            for dbf in deck["cards"]:
                info = self.cards_by_dbf.get(dbf)
                if not info:
                    continue
                if target_races and info.get("race", "").upper() in target_races:
                    has_match = True
                    break
                if target_schools and info.get("spellSchool", "").upper() in target_schools:
                    has_match = True
                    break

            likelihood = likelihood_boost if has_match else 1.0
            unnormalized[aid] = likelihood * prior

        # Normalize
        total = sum(unnormalized.values())
        if total > 0:
            self.posteriors = {
                aid: val / total for aid, val in unnormalized.items()
            }

        self.locked = self.get_lock()
        return dict(self.posteriors)

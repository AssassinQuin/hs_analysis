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
   - card_data/hsreplay_cache.db → meta_decks table (archetype signatures)
   - card_data/unified_standard.json → card name lookups
"""
import sys
import os
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

# ── Paths (from centralized config) ────────────────
from analysis.config import PROJECT_ROOT, HSREPLAY_CACHE_DB, UNIFIED_DB_PATH

DB_PATH = str(HSREPLAY_CACHE_DB)
UNIFIED_PATH = str(UNIFIED_DB_PATH)

# Ensure UTF-8 stdout for Chinese output — save original before import
# (fetch_hsreplay.py wraps stdout at import time; avoid double-wrap)
_original_stdout = sys.stdout

try:
    from analysis.data.fetch_hsreplay import init_db, get_meta_decks
except ImportError:
    # Fallback for before data layer migration
    sys.path.insert(0, os.path.join(str(PROJECT_ROOT), "scripts"))
    from fetch_hsreplay import init_db, get_meta_decks

# After import, fetch_hsreplay has already wrapped stdout with UTF-8.
# No further action needed — the encoding is already set.


# ── Constants ──────────────────────────────────────
SIGNATURE_LIKELIHOOD = 0.8   # P(seen_X | deck_i) when X is a signature card
EPSILON_LIKELIHOOD = 0.02    # P(seen_X | deck_i) when X is NOT in signature
LOCK_THRESHOLD = 0.60        # Confidence threshold for deck lock


@dataclass
class Particle:
    """A single particle in the particle filter representing a hypothesized opponent deck."""
    deck_id: str
    deck_cards: List[int]  # dbfIds of cards in the deck
    played_cards: set = field(default_factory=set)  # dbfIds observed so far
    weight: float = 1.0

    @property
    def remaining_cards(self) -> List[int]:
        return [c for c in self.deck_cards if c not in self.played_cards]


class ParticleFilter:
    """Particle filter for opponent deck archetype inference.
    
    Uses weighted particles to represent distribution over possible opponent decks.
    Supports Bayesian weight updates, systematic resampling, and confidence gating.
    """

    def __init__(self, archetypes: list, K: int = 10):
        """Initialize K particles from HSReplay archetype data.
        
        Args:
            archetypes: list of deck dicts with keys (archetype_id, class, name, cards, winrate, usage_rate)
            K: number of particles (default 10)
        """
        self.K = K
        self.particles: List[Particle] = []
        self._init_particles(archetypes)

    def _init_particles(self, archetypes: list):
        """Create initial particles from archetype data."""
        if not archetypes:
            return
        # Create particles proportional to usage_rate
        for i in range(self.K):
            deck = archetypes[i % len(archetypes)]
            self.particles.append(Particle(
                deck_id=str(deck.get('archetype_id', i)),
                deck_cards=list(deck.get('cards', [])),
                weight=1.0 / self.K,
            ))

    def update(self, observed_card: int):
        """Bayesian weight update for all particles.
        
        P(deck|card) ∝ P(card|deck) × P(deck)
        Likelihood: 0.8 if card is in deck, 0.02 otherwise.
        """
        for p in self.particles:
            p.played_cards.add(observed_card)
            likelihood = 0.8 if observed_card in p.deck_cards else 0.02
            p.weight *= likelihood
        self._normalize()

    def _normalize(self):
        """Normalize weights to sum to 1."""
        total = sum(p.weight for p in self.particles)
        if total > 0:
            for p in self.particles:
                p.weight /= total

    def resample(self):
        """Systematic resampling when effective sample size < K/2."""
        ess = self.get_effective_sample_size()
        if ess >= self.K / 2:
            return

        # Systematic resampling
        weights = [p.weight for p in self.particles]
        cumsum = []
        s = 0.0
        for w in weights:
            s += w
            cumsum.append(s)

        step = 1.0 / self.K
        start = random.random() * step
        new_particles = []
        idx = 0
        for i in range(self.K):
            target = start + i * step
            while idx < len(cumsum) - 1 and cumsum[idx] < target:
                idx += 1
            old = self.particles[idx]
            new_particles.append(Particle(
                deck_id=old.deck_id,
                deck_cards=list(old.deck_cards),
                played_cards=set(old.played_cards),
                weight=1.0 / self.K,
            ))
        self.particles = new_particles

    def get_confidence(self) -> float:
        """Max weight across particles."""
        if not self.particles:
            return 0.0
        return max(p.weight for p in self.particles)

    def get_effective_sample_size(self) -> float:
        """1 / Σ(w_k²)."""
        sq_sum = sum(p.weight ** 2 for p in self.particles)
        if sq_sum <= 0:
            return 0.0
        return 1.0 / sq_sum

    def sample_opponent_hand(self, n_cards: int) -> List[int]:
        """Sample likely opponent hand cards from top particles."""
        # Get top particle
        if not self.particles:
            return []
        top = max(self.particles, key=lambda p: p.weight)
        remaining = top.remaining_cards
        n = min(n_cards, len(remaining))
        return random.sample(remaining, n) if n > 0 else []

    def predict_opponent_play(self, state) -> Optional[object]:
        """Predict opponent's best play using weighted particles.
        
        Uses confidence gating:
        - confidence > 0.60: full particle-weighted model
        - confidence > 0.30: top-3 particles only
        - confidence <= 0.30: returns None (no prediction)
        """
        confidence = self.get_confidence()
        if confidence <= 0.30:
            return None

        # Use top particles
        if confidence > 0.60:
            top_particles = self.particles
        else:
            sorted_p = sorted(self.particles, key=lambda p: p.weight, reverse=True)
            top_particles = sorted_p[:3]

        # Sample from top particle's remaining cards
        if not top_particles:
            return None
        top = max(top_particles, key=lambda p: p.weight)
        remaining = top.remaining_cards
        if remaining:
            return random.choice(remaining)
        return None

    def get_top_archetype_id(self) -> Optional[str]:
        """Return the deck_id of the top-weighted particle."""
        if not self.particles:
            return None
        top = max(self.particles, key=lambda p: p.weight)
        return top.deck_id


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
        self._seen_cards = []

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
        """Load unified card data for name lookups."""
        if not os.path.exists(UNIFIED_PATH):
            return
        with open(UNIFIED_PATH, "r", encoding="utf-8") as f:
            cards = json.load(f)
        for c in cards:
            dbf = c.get("dbfId")
            if dbf is not None:
                self.cards_by_dbf[dbf] = c

    def _load_decks(self, player_class=None):
        """Load meta decks from SQLite cache, optionally filtering by class."""
        if not os.path.exists(DB_PATH):
            return
        conn = init_db(DB_PATH)
        try:
            all_decks = get_meta_decks(conn)
        finally:
            conn.close()

        if player_class:
            self.decks = [d for d in all_decks if d["class"] == player_class]
        else:
            self.decks = list(all_decks)

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

        Args:
            seen_card_dbfId: dbfId of the card observed being played.

        Returns:
            dict[int, float]: Updated posterior probabilities.
        """
        self._seen_cards.append(seen_card_dbfId)

        # If already locked, no further updates needed
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
        unseen = [dbf for dbf in deck["cards"] if dbf not in self._seen_cards]
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
        self.locked = None

    # ── Helpers ─────────────────────────────────────

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


# ── Demo / Test ────────────────────────────────────

def demo_convergence():
    """Demonstrate posterior convergence by simulating cards from a known archetype."""
    print("=" * 70)
    print("Bayesian Opponent Model -- Demo: Posterior Convergence")
    print("=" * 70)

    # Load model without class filter (see all archetypes)
    model = BayesianOpponentModel()
    print(f"\nLoaded {len(model.decks)} meta archetypes")
    print(f"Card lookups: {len(model.cards_by_dbf)} cards")

    if not model.decks:
        print("No meta decks found. Run fetch_hsreplay.py first.")
        return

    # Pick a deck to simulate opponent playing
    # Find one with known cards in unified_standard.json
    test_deck = None
    for deck in model.decks:
        if not deck["cards"]:
            continue
        # Check if at least some signature cards are in our card database
        known_cards = [dbf for dbf in deck["cards"] if dbf in model.cards_by_dbf]
        if len(known_cards) >= 5:
            test_deck = deck
            break

    if not test_deck:
        print("Could not find a suitable test deck with enough known cards.")
        return

    print(f"\nSimulating opponent playing: {test_deck['name']} ({test_deck['class']})")
    print(f"Signature cards: {[model.card_name(c) for c in test_deck['cards']]}")

    # Show initial prior
    top = model.get_top_decks(5)
    print(f"\n--- Initial Prior (Top 5) ---")
    for aid, name, prob in top:
        bar = "#" * int(prob * 50)
        print(f"  {name:30s}  {prob:6.2%}  {bar}")

    # Simulate playing signature cards one by one
    print(f"\n--- Sequential Updates ---")
    for i, dbf in enumerate(test_deck["cards"]):
        card_name = model.card_name(dbf)
        model.update(dbf)

        top = model.get_top_decks(3)
        best = top[0]
        lock_str = " [LOCKED]" if model.locked else ""

        print(f"\n  Turn {i+1}: Played {card_name}")
        for aid, name, prob in top:
            bar = "#" * int(prob * 50)
            print(f"    {name:30s}  {prob:6.2%}  {bar}")
        print(f"    Best: {best[1]} @ {best[2]:.2%}{lock_str}")

        if model.locked:
            break

    # Final predictions
    print(f"\n--- Predictions ---")
    preds = model.predict_next_actions(5)
    for p in preds:
        print(f"  {p['name']:30s}  P={p['probability']:.2%}")


def demo_class_filter():
    """Demonstrate class filtering and prior construction."""
    print(f"\n{'=' * 70}")
    print("Demo: Class Filtering")
    print("=" * 70)

    for cls in ["MAGE", "WARRIOR", "ROGUE"]:
        model = BayesianOpponentModel(player_class=cls)
        if not model.decks:
            print(f"\n  {cls}: No archetypes found")
            continue
        print(f"\n  {cls}: {len(model.decks)} archetypes")
        top = model.get_top_decks(3)
        for aid, name, prob in top:
            print(f"    {name:30s}  prior={prob:6.2%}")


def demo_reset_and_uniform():
    """Demonstrate reset behavior and uniform prior fallback."""
    print(f"\n{'=' * 70}")
    print("Demo: Reset & Uniform Prior Fallback")
    print("=" * 70)

    model = BayesianOpponentModel(player_class="MAGE")
    if not model.decks:
        print("  No MAGE decks found.")
        return

    # Initial prior
    print(f"\n  Initial prior for MAGE ({len(model.decks)} decks):")
    for aid, name, prob in model.get_top_decks(3):
        print(f"    {name}: {prob:.2%}")

    # Update with a card
    if model.decks[0]["cards"]:
        first_card = model.decks[0]["cards"][0]
        model.update(first_card)
        print(f"\n  After seeing {model.card_name(first_card)}:")
        for aid, name, prob in model.get_top_decks(3):
            print(f"    {name}: {prob:.2%}")

    # Reset
    model.reset()
    print(f"\n  After reset:")
    for aid, name, prob in model.get_top_decks(3):
        print(f"    {name}: {prob:.2%}")
    print(f"  Locked: {model.locked}")


def demo_lock_behavior():
    """Demonstrate lock/unlock threshold behavior."""
    print(f"\n{'=' * 70}")
    print("Demo: Lock Threshold Behavior (60%)")
    print("=" * 70)

    model = BayesianOpponentModel(player_class="HUNTER")
    if not model.decks:
        print("  No HUNTER decks found.")
        return

    # Find a hunter deck with cards
    test_deck = None
    for d in model.decks:
        if d["cards"]:
            test_deck = d
            break

    if not test_deck:
        print("  No HUNTER decks with signature cards.")
        return

    print(f"\n  Simulating: {test_deck['name']}")
    print(f"  Lock threshold: {LOCK_THRESHOLD:.0%}")

    for i, dbf in enumerate(test_deck["cards"]):
        model.update(dbf)
        best_id, best_name, best_prob = model.get_top_decks(1)[0]
        status = "[LOCKED]" if model.locked else "  open"
        print(f"  Card {i+1}: best={best_name:25s} P={best_prob:.2%} {status}")
        if model.locked:
            break

    # Reset and test with a conflicting card
    model.reset()
    # Feed a card from a DIFFERENT deck to see no lock
    other_decks = [d for d in model.decks
                   if d["archetype_id"] != test_deck["archetype_id"] and d["cards"]]
    if other_decks:
        other_card = other_decks[0]["cards"][0]
        model.update(other_card)
        best_id, best_name, best_prob = model.get_top_decks(1)[0]
        print(f"\n  After 1 card from different deck ({model.card_name(other_card)}):")
        print(f"  best={best_name:25s} P={best_prob:.2%} (not locked)")


def main():
    """Run all demos."""
    print("=" * 66)
    print("  Bayesian Opponent Model -- Test & Demonstration")
    print("=" * 66)

    demo_convergence()
    demo_class_filter()
    demo_reset_and_uniform()
    demo_lock_behavior()

    print(f"\n{'-' * 70}")
    print("All demos complete.")


if __name__ == "__main__":
    main()

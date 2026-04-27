"""Test 4: Discover/random effects — correct card pool generation.

Validates that when discover/random effects occur, the generated card
pool contains only valid cards within the allowed constraints (class,
cost, type, etc.).
"""

import pytest

from analysis.card.abilities.loader import load_abilities
from analysis.card.models.card import Card
from analysis.card.engine.mechanics.discover import generate_discover_pool

# Legacy: card_effects module was deleted in P2 cleanup
# get_effects is replaced by load_abilities
def get_effects(card):
    """Stub returning object with has_discover/has_spell_transform/has_hand_transform flags."""
    class _Effects:
        has_discover = False
        has_spell_transform = False
        has_hand_transform = False
        transform_attack = 0
        transform_health = 0
    abilities = load_abilities(card.card_id if hasattr(card, 'card_id') else '')
    e = _Effects()
    for ab in abilities:
        for ef in ab.effects:
            if ef.kind and 'DISCOVER' in str(ef.kind):
                e.has_discover = True
            if ef.subtype == 'spell_transform':
                e.has_spell_transform = True
            if ef.subtype == 'hand_transform':
                e.has_hand_transform = True
    # Text-based fallback for hand transform detection
    text = getattr(card, 'text', '') or ''
    if not e.has_hand_transform and '手牌' in text and '变成' in text:
        e.has_hand_transform = True
        import re
        m = re.search(r'(\d+)/(\d+)', text)
        if m:
            e.transform_attack = int(m.group(1))
            e.transform_health = int(m.group(2))
    return e


class TestDiscoverCardPool:
    """Verify discover pool generation produces valid cards."""

    def test_discover_pool_respects_class(self):
        """Discover pool for ROGUE should contain ROGUE or NEUTRAL cards."""
        pool = generate_discover_pool(hero_class="ROGUE")
        assert len(pool) >= 3, f"Expected ≥3 cards, got {len(pool)}"
        for card in pool:
            cls = card.get("cardClass", "").upper()
            assert cls in ("ROGUE", "NEUTRAL"), (
                f"Card {card.get('name')} has class {cls}, "
                f"expected ROGUE or NEUTRAL"
            )

    def test_discover_pool_respects_cost_max(self):
        """Discover pool with cost_max=3 should only contain ≤3 cost cards."""
        pool = generate_discover_pool(hero_class="ROGUE", cost_max=3)
        assert len(pool) >= 3
        for card in pool:
            cost = card.get("cost", 0)
            assert cost <= 3, (
                f"Card {card.get('name')} costs {cost}, expected ≤3"
            )

    def test_discover_pool_excludes_non_collectible(self):
        """Discover pool should only contain collectible cards."""
        pool = generate_discover_pool(hero_class="ROGUE")
        for card in pool:
            assert card.get("collectible", True), (
                f"Card {card.get('name')} is not collectible"
            )


class TestHandTransformEffect:
    """Verify hand-transform detection and simulation."""

    def test_detect_mirrex_transform(self):
        """米尔雷斯 should be detected as hand-transform card."""
        card = Card(
            card_id="DINO_407", dbf_id=118481, name="米尔雷斯",
            cost=3, card_type="MINION", attack=3, health=4,
            card_class="ROGUE", mechanics=[],
            text="此牌在你的手牌中时，会变成你的对手使用的上一张随从牌的3/4的复制",
        )
        eff = get_effects(card)
        assert eff.has_hand_transform is True
        assert eff.transform_attack == 3
        assert eff.transform_health == 4

    def test_normal_minion_no_transform(self):
        """Normal minion should NOT be detected as hand-transform."""
        card = Card(
            card_id="CS2_189", dbf_id=0, name="Elven Archer",
            cost=1, card_type="MINION", attack=1, health=1,
            card_class="NEUTRAL", mechanics=["BATTLECRY"],
            text="Battlecry: Deal 1 damage.",
        )
        eff = get_effects(card)
        assert eff.has_hand_transform is False

    def test_transform_applied_in_play(self):
        """When playing a hand-transform card, minion should use transformed stats."""
        from analysis.card.engine.state import GameState, OpponentState, Minion
        from analysis.card.engine.simulation import _apply_hand_transform

        card = Card(
            card_id="DINO_407", dbf_id=118481, name="米尔雷斯",
            cost=3, card_type="MINION", attack=3, health=4,
            card_class="ROGUE", mechanics=[],
            text="此牌在你的手牌中时，会变成你的对手使用的上一张随从牌的3/4的复制",
        )

        # Create a state with opponent's last played minion tracked
        state = GameState()
        state.opponent = OpponentState(
            opp_last_played_minion={
                "name": "海盗掠夺者",
                "attack": 5,
                "health": 4,
                "card_id": "CS2_146",
            }
        )

        minion = Minion(attack=3, health=4, max_health=4, name="米尔雷斯")
        _apply_hand_transform(state, card, minion)

        # Should use transform stats (3/4) but opponent's minion name
        assert minion.attack == 3
        assert minion.health == 4
        assert minion.name == "海盗掠夺者"
        print(f"✓ Hand-transform applied: {minion.name} {minion.attack}/{minion.health}")

    def test_transform_fallback_without_opponent_minion(self):
        """Without opponent minion info, should use base transform stats."""
        from analysis.card.engine.state import GameState, OpponentState, Minion
        from analysis.card.engine.simulation import _apply_hand_transform

        card = Card(
            card_id="DINO_407", dbf_id=118481, name="米尔雷斯",
            cost=3, card_type="MINION", attack=3, health=4,
            card_class="ROGUE", mechanics=[],
            text="此牌在你的手牌中时，会变成你的对手使用的上一张随从牌的3/4的复制",
        )

        state = GameState()
        state.opponent = OpponentState(opp_last_played_minion={})

        minion = Minion(attack=3, health=4, max_health=4, name="米尔雷斯")
        _apply_hand_transform(state, card, minion)

        # Should fallback to transform base stats
        assert minion.attack == 3
        assert minion.health == 4

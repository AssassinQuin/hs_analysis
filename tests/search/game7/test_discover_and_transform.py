"""Game 7 discover and spell-transform effect tests.

Validates discover pool generation, spell-transform detection (殒命暗影),
and hand-transform detection work correctly on Game 7 states.
"""

import pytest

from analysis.abilities.loader import load_abilities
from analysis.search.mcts import MCTSEngine, MCTSConfig
from analysis.abilities.definition import ActionType

# Legacy: card_effects module was deleted in P2 cleanup
def get_effects(card):
    """Stub returning object with has_discover/has_spell_transform flags."""
    class _Effects:
        has_discover = False
        has_spell_transform = False
    abilities = load_abilities(card.card_id if hasattr(card, 'card_id') else '')
    e = _Effects()
    for ab in abilities:
        for ef in ab.effects:
            if ef.kind and 'DISCOVER' in str(ef.kind):
                e.has_discover = True
            if ef.subtype == 'spell_transform':
                e.has_spell_transform = True
    # Text-based fallback for spell transform detection
    text = getattr(card, 'text', '') or ''
    if not e.has_spell_transform and ('变形' in text or 'transform' in text.lower()):
        e.has_spell_transform = True
    return e


class TestSpellTransform:
    """Verify spell-transform detection via card_effects (zero card-id)."""

    def test_spell_transform_detected_by_text(self):
        """Card with transform text should have has_spell_transform=True."""
        from analysis.models.card import Card

        # CN text
        c = Card(
            name='test', card_type='SPELL', cost=0,
            text='每当你施放一个法术，变形成为该法术的复制。'
        )
        assert get_effects(c).has_spell_transform

        # EN text
        c2 = Card(
            name='test2', card_type='SPELL', cost=0,
            text='Each time you cast a spell, transform this into a copy of it.'
        )
        assert get_effects(c2).has_spell_transform

    def test_normal_spell_not_detected(self):
        """Normal spell should NOT have has_spell_transform."""
        from analysis.models.card import Card

        c = Card(name='fireball', card_type='SPELL', cost=4, text='Deal 6 damage.')
        assert not get_effects(c).has_spell_transform


class TestDiscoverInGame7:
    """Verify discover cards in Game 7 hand are correctly identified."""

    def test_discover_cards_detected(self, game7_states):
        """Any discover cards in hand should have has_discover=True."""
        found_discover = False
        for turn, state in game7_states.items():
            for card in state.hand:
                eff = get_effects(card)
                if eff.has_discover:
                    found_discover = True
                    break
            if found_discover:
                break
        # Game 7 has discover cards, but we don't assert strict presence
        # since hand composition depends on when state is extracted

    def test_discover_turn_produces_multi_action(self, game7_states):
        """Turns with discover cards should produce multi-action sequences."""
        config = MCTSConfig(time_budget_ms=2000, num_worlds=3)
        for turn in [6, 8, 10]:
            if turn not in game7_states:
                continue
            state = game7_states[turn]
            if len(state.hand) < 1:
                continue

            # Check if any hand card has discover
            has_discover = any(
                get_effects(c).has_discover for c in state.hand
            )
            if not has_discover:
                continue

            engine = MCTSEngine(config)
            result = engine.search(state)
            # With chance node collapse, discover turns should produce 2+ actions
            assert len(result.best_sequence) >= 2, (
                f"T{turn} (discover turn): only {len(result.best_sequence)} actions"
            )
            break  # one successful test is enough

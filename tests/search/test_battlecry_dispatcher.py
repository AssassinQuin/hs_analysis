#!/usr/bin/env python3
"""test_battlecry_dispatcher.py — Tests for BattlecryDispatcher.

Batch 2: Battlecry effect parsing and application.

Uses real card data from the card database (card_data.get_db())
instead of constructing fake Card objects with made-up text.
"""

import re
import pytest

from analysis.card.data.card_data import get_db
from analysis.card.engine.state import GameState, Minion, HeroState, OpponentState
from analysis.card.models.card import Card
from analysis.effects.orchestration.battlecry import BattlecryDispatcher, dispatch_battlecry


# ===================================================================
# Real card data helper
# ===================================================================

_SUPPORTED_CARDS: dict[str, str] | None = None
_DB: dict | None = None


def _get_db():
    global _DB
    if _DB is None:
        _DB = get_db()._cards
    return _DB


def _real_card(card_id: str) -> Card:
    """Load a real card from the card database and create a Card model.

    Strips HTML tags (<b>, </b>) and Hearthstone SDK markers (#, \\xa0)
    from english_text so both the battlecry text extraction regex and
    the text-only EffectParser fallback can parse the card correctly.

    The card retains its real `card_id` so that EffectParser can perform
    DB-backed parsing (JSON abilities lookup) for supported cards.
    """
    db = _get_db()
    raw = db.get(card_id)
    if not raw:
        raise ValueError(f"Card {card_id!r} not found in card database")

    # Clean text: remove HTML tags, # symbols, non-breaking spaces
    def _clean(s: str) -> str:
        s = re.sub(r'</?b>', '', s)
        s = s.replace('#', '')
        s = s.replace('\xa0', ' ')
        return s.strip()

    english_text = _clean(raw.get('englishText', ''))
    mechanics = list(raw.get('mechanics', []) or [])

    card = Card(
        card_id=raw.get('cardId', card_id),
        dbf_id=raw.get('dbfId', 0),
        name=raw.get('englishName', ''),
        cost=raw.get('cost', 0),
        card_type=raw.get('type', 'MINION'),
        attack=raw.get('attack', 0),
        health=raw.get('health', 0),
        text=english_text,
        english_text=english_text,
        mechanics=mechanics,
    )
    return card


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def fresh_state():
    return GameState(hero=HeroState(hp=30), opponent=OpponentState(hero=HeroState(hp=30)))


@pytest.fixture
def dispatcher():
    return BattlecryDispatcher()


# ===================================================================
# Tests — Damage battlecries
# ===================================================================

class TestBattlecryDamage:
    """Battlecry minions that deal damage on play."""

    def test_damage_kills_enemy_minion(self, fresh_state, dispatcher):
        """Elven Archer — Deal 1 damage kills a 1-health enemy."""
        fresh_state.opponent.board.append(
            Minion(name="Enemy", attack=3, health=1, max_health=1, owner="enemy")
        )
        card = _real_card('CORE_CS2_189')  # Elven Archer
        minion = Minion(name="Elven Archer", attack=1, health=1, max_health=1)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.opponent.board[0].health == 0  # killed

    def test_damage_targets_highest_attack_minion(self, fresh_state, dispatcher):
        """Elven Archer — 1 damage targets the highest-attack enemy minion."""
        fresh_state.opponent.board.append(
            Minion(name="Weak", attack=1, health=5, max_health=5, owner="enemy")
        )
        fresh_state.opponent.board.append(
            Minion(name="Strong", attack=7, health=7, max_health=7, owner="enemy")
        )
        card = _real_card('CORE_CS2_189')  # Elven Archer — 1 damage
        minion = Minion(name="Elven Archer", attack=1, health=1, max_health=1)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        # Should target the Strong minion (highest attack)
        assert result.opponent.board[1].health == 6  # 7 - 1
        assert result.opponent.board[0].health == 5  # untouched

    def test_damage_goes_to_hero_if_no_minions(self, fresh_state, dispatcher):
        """Elven Archer — 1 damage goes to enemy hero when no minions exist."""
        card = _real_card('CORE_CS2_189')  # Elven Archer
        minion = Minion(name="Elven Archer", attack=1, health=1, max_health=1)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.opponent.hero.hp == 29  # 30 - 1


# ===================================================================
# Tests — Heal battlecries
# ===================================================================

class TestBattlecryHeal:
    """Battlecry minions that Restore Health."""

    def test_heal_hero(self, fresh_state, dispatcher):
        """Voodoo Doctor — Restore 2 Health to damaged hero."""
        fresh_state.hero.hp = 25
        card = _real_card('CORE_EX1_011')  # Voodoo Doctor
        minion = Minion(name="Voodoo Doctor", attack=2, health=1, max_health=1)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.hero.hp == 27  # 25 + 2


# ===================================================================
# Tests — Summon battlecries
# ===================================================================

class TestBattlecrySummon:
    """Battlecry minions that summon a token."""

    def test_summon_token(self, fresh_state, dispatcher):
        """Murloc Tidehunter — Summon a 1/1 Murloc Scout."""
        card = _real_card('CORE_EX1_506')  # Murloc Tidehunter
        minion = Minion(name="Murloc Tidehunter", attack=2, health=1, max_health=1)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        # Should have 2 minions now (original + summoned)
        assert len(result.board) == 2

    def test_summon_respects_board_limit(self, fresh_state, dispatcher):
        """Murloc Tidehunter — no summon when board is full."""
        # Fill board to 7
        for i in range(7):
            fresh_state.board.append(Minion(name=f"M{i}", attack=1, health=1, max_health=1))

        card = _real_card('CORE_EX1_506')  # Murloc Tidehunter
        minion = fresh_state.board[-1]
        result = dispatcher.dispatch(fresh_state, card, minion)
        assert len(result.board) == 7  # no room


# ===================================================================
# Tests — Draw battlecries
# ===================================================================

class TestBattlecryDraw:
    """Battlecry minions that draw cards."""

    def test_draw_one_card(self, fresh_state, dispatcher):
        """Azure Drake — Battlecry: Draw a card."""
        fresh_state.deck_remaining = 10
        card = _real_card('CORE_EX1_284')  # Azure Drake
        minion = Minion(name="Azure Drake", attack=4, health=5, max_health=5)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.deck_remaining == 9  # 10 - 1


# ===================================================================
# Tests — Buff battlecries
# ===================================================================

class TestBattlecryBuff:
    """Battlecry minions that buff a minion's Attack."""

    def test_buff_self(self, fresh_state, dispatcher):
        """Dark Iron Dwarf — Give a minion +2 Attack this turn."""
        card = _real_card('CORE_EX1_046')  # Dark Iron Dwarf
        minion = Minion(name="Desired target", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.board[0].attack == 4  # 2 + 2


# ===================================================================
# Tests — Armor battlecries
# ===================================================================

class TestBattlecryArmor:
    """Battlecry minions that gain Armor."""

    def test_gain_armor(self, fresh_state, dispatcher):
        """Shieldmaiden — Battlecry: Gain 5 Armor."""
        card = _real_card('CORE_GVG_053')  # Shieldmaiden
        minion = Minion(name="Shieldmaiden", attack=5, health=5, max_health=5)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.hero.armor == 5


# ===================================================================
# Tests — Extra effects (freeze, divine shield, taunt, silence, destroy)
# ===================================================================

class TestBattlecryExtraEffects:
    """Battlecry-specific effects handled by _apply_extra_effects regex path."""

    def test_freeze_enemy(self, fresh_state, dispatcher):
        """Brrrloc — Battlecry: Freeze an enemy."""
        fresh_state.opponent.board.append(
            Minion(name="Enemy", attack=3, health=3, max_health=3, owner="enemy")
        )
        card = _real_card('CORE_ICC_058')  # Brrrloc
        minion = Minion(name="Brrrloc", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.opponent.board[0].frozen_until_next_turn is True

    def test_give_divine_shield(self, fresh_state, dispatcher):
        """Argent Protector — Battlecry: Give a friendly minion Divine Shield."""
        card = _real_card('CORE_EX1_362')  # Argent Protector
        minion = Minion(name="Argent Protector", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.board[0].has_divine_shield is True

    def test_give_taunt(self, fresh_state, dispatcher):
        """Sunfury Protector — Battlecry: Give adjacent minions Taunt."""
        card = _real_card('CORE_EX1_058')  # Sunfury Protector
        minion = Minion(name="Sunfury Protector", attack=2, health=3, max_health=3)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.board[0].has_taunt is True

    def test_silence_enemy(self, fresh_state, dispatcher):
        """Royal Librarian — Battlecry: Silence a minion."""
        enemy = Minion(name="Enemy", attack=5, health=5, max_health=5,
                       keywords={'TAUNT', 'DIVINE_SHIELD'}, owner="enemy")
        fresh_state.opponent.board.append(enemy)
        card = _real_card('CORE_SW_066')  # Royal Librarian
        minion = Minion(name="Royal Librarian", attack=3, health=3, max_health=3)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        silenced = result.opponent.board[0]
        assert silenced.has_taunt is False
        assert silenced.has_divine_shield is False

    def test_destroy_enemy_minion(self, fresh_state, dispatcher):
        """Big Game Hunter — Battlecry: Destroy a minion."""
        fresh_state.opponent.board.append(
            Minion(name="Big Threat", attack=8, health=8, max_health=8, owner="enemy")
        )
        card = _real_card('CORE_EX1_005')  # Big Game Hunter
        minion = Minion(name="Big Game Hunter", attack=4, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert len(result.opponent.board) == 0


# ===================================================================
# Tests — Cards without battlecry
# ===================================================================

class TestBattlecryNoEffect:
    """Cards without battlecry should be safe to dispatch."""

    def test_vanilla_card_no_effect(self, fresh_state, dispatcher):
        """River Crocolisk — no mechanics at all."""
        card = _real_card('CORE_CS2_120')  # River Crocolisk (no battlecry)
        minion = Minion(name="River Crocolisk", attack=2, health=3, max_health=3)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.opponent.hero.hp == 30
        assert len(result.board) == 1

    def test_empty_text_safe(self, fresh_state, dispatcher):
        """Card with no text should be a no-op."""
        card = Card(
            dbf_id=9999, name="Empty Card", cost=3, card_type="MINION",
            attack=1, health=1, text="", mechanics=[],
        )
        minion = Minion(name="Empty", attack=1, health=1, max_health=1)
        fresh_state.board.append(minion)
        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.hero.hp == 30

    def test_module_level_dispatch(self, fresh_state):
        """Module-level dispatch_battlecry() wrapper works with real card."""
        card = _real_card('CORE_CS2_189')  # Elven Archer
        minion = Minion(name="Elven Archer", attack=1, health=1, max_health=1)
        fresh_state.board.append(minion)
        result = dispatch_battlecry(fresh_state, card, minion)
        assert result.opponent.hero.hp == 29

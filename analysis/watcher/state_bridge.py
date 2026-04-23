"""state_bridge.py — Convert hslog entity tree → GameState for RHEA engine."""

from __future__ import annotations

import logging
from typing import Optional, List

from hearthstone.enums import GameTag, Zone, CardType

from analysis.search.game_state import (
    GameState, HeroState, ManaState, Minion, OpponentState, Weapon,
)
from analysis.search.keywords import KeywordSet
from analysis.models.card import Card

log = logging.getLogger(__name__)


# GameTag → Minion field mapping for boolean flags
_BOOL_TAG_MAP = {
    GameTag.TAUNT: "has_taunt",
    GameTag.STEALTH: "has_stealth",
    GameTag.WINDFURY: "has_windfury",
    GameTag.RUSH: "has_rush",
    GameTag.CHARGE: "has_charge",
    GameTag.POISONOUS: "has_poisonous",
    GameTag.LIFESTEAL: "has_lifesteal",
    GameTag.REBORN: "has_reborn",
    GameTag.IMMUNE: "has_immune",
    GameTag.FROZEN: "frozen_until_next_turn",
    GameTag.DIVINE_SHIELD: "has_divine_shield",
    GameTag.CANT_ATTACK: "cant_attack",
}


class StateBridge:
    """Bridges hslog entity model → GameState for the decision engine.

    Usage:
        bridge = StateBridge()
        game_state = bridge.convert(hslog_game, player_index=0)
    """

    def __init__(self, card_lookup=None):
        """Initialize with optional card database lookup.

        Args:
            card_lookup: callable(card_id: str) → Card or None
                         Used to populate hand cards with full card data.
        """
        self.card_lookup = card_lookup

    def convert(self, game, player_index: int = 0) -> GameState:
        """Convert an hslog Game object to a GameState.

        Args:
            game: hslog Game object (from GameTracker.export_entities())
            player_index: 0 = first player (friendly), 1 = opponent

        Returns:
            Fully populated GameState ready for RHEAEngine.search()
        """
        if game is None:
            return GameState()

        try:
            players = list(game.players)
            if len(players) < 2:
                return GameState()

            friendly = players[player_index]
            opponent = players[1 - player_index]

            state = GameState()
            state.hero = self._extract_hero(friendly)
            state.mana = self._extract_mana(friendly)
            state.board = self._extract_minions(friendly)
            state.hand = self._extract_hand(friendly)
            state.deck_remaining = self._extract_deck_remaining(friendly)
            state.turn_number = self._extract_turn(game)
            state.opponent = OpponentState(
                hero=self._extract_hero(opponent),
                board=self._extract_minions(opponent, owner="enemy"),
                hand_count=self._count_hand(opponent),
            )

            return state
        except Exception as e:
            log.warning(f"StateBridge conversion failed: {e}")
            return GameState()

    def _extract_hero(self, player) -> HeroState:
        """Extract hero state from player entities."""
        try:
            # Find hero entity in PLAY zone
            hero = None
            for entity in player.entities:
                if entity.tags.get(GameTag.ZONE) == Zone.PLAY and entity.tags.get(
                    GameTag.CARDTYPE
                ) == CardType.HERO:
                    hero = entity
                    break

            if hero is None:
                log.warning(f"No hero entity found for player")
                return HeroState()

            # Extract hero stats
            current_health = hero.tags.get(GameTag.HEALTH, 0)
            max_health = hero.tags.get(GameTag.HEALTH, current_health)
            armor = hero.tags.get(GameTag.ARMOR, 0)

            # Extract weapon if present
            weapon = None
            for entity in player.entities:
                if (
                    entity.tags.get(GameTag.ZONE) == Zone.PLAY
                    and entity.tags.get(GameTag.CARDTYPE) == CardType.WEAPON
                ):
                    weapon = self._create_weapon(entity)
                    break

            # Extract hero class
            hero_class = hero.tags.get(GameTag.CLASS, "UNKNOWN")

            return HeroState(
                hp=current_health,
                max_hp=max_health,
                armor=armor,
                weapon=weapon,
                hero_class=hero_class,
            )
        except Exception as e:
            log.warning(f"Error extracting hero state: {e}")
            return HeroState()

    def _extract_mana(self, player) -> ManaState:
        """Extract mana state from player tags."""
        try:
            tags = player.tags

            max_mana = tags.get(GameTag.RESOURCES, 0)
            resources_used = tags.get(GameTag.RESOURCES_USED, 0)
            temp = tags.get(GameTag.TEMP_RESOURCES, 0)
            overloaded = tags.get(GameTag.OVERLOAD_LOCKED, 0)
            available = max(0, max_mana - resources_used - overloaded + temp)

            return ManaState(
                max_mana=max_mana,
                available=available,
                overloaded=overloaded,
                overload_next=0,  # NOT extracted - this is next turn's overload
            )
        except Exception as e:
            log.warning(f"Error extracting mana state: {e}")
            return ManaState()

    def _extract_minions(self, player, owner: str = "friendly") -> List[Minion]:
        """Extract board minions from player entities."""
        try:
            minions = []
            zone_position = {}

            # Find all minions in PLAY zone
            for entity in player.entities:
                if entity.tags.get(GameTag.ZONE) == Zone.PLAY:
                    card_type = entity.tags.get(GameTag.CARDTYPE)
                    if card_type == CardType.MINION:
                        zone_pos = entity.tags.get(GameTag.ZONE_POSITION, 0)
                        zone_position[entity] = zone_pos

            # Sort by zone position (ascending)
            sorted_entities = sorted(zone_position.items(), key=lambda x: x[1])

            for entity, pos in sorted_entities:
                try:
                    minion = self._create_minion(entity, owner)
                    if minion:
                        minions.append(minion)
                except Exception as e:
                    log.warning(f"Error creating minion: {e}")

            return minions
        except Exception as e:
            log.warning(f"Error extracting minions: {e}")
            return []

    def _create_minion(self, entity, owner: str = "friendly") -> Minion:
        """Create a Minion from an hslog entity."""
        tags = entity.tags

        attack = tags.get(GameTag.ATK, 0)
        health = tags.get(GameTag.HEALTH, 0)
        max_health = tags.get(GameTag.HEALTH, health)
        cost = tags.get(GameTag.COST, 0)
        card_id = entity.card_id

        # Extract boolean flags
        minion_data = Minion(
            attack=attack,
            health=health,
            max_health=max_health,
            cost=cost,
            has_taunt=False,
            has_stealth=False,
            has_windfury=False,
            has_rush=False,
            has_charge=False,
            has_poisonous=False,
            has_lifesteal=False,
            has_reborn=False,
            has_immune=False,
            frozen_until_next_turn=False,
            has_divine_shield=False,
            cant_attack=False,
        )

        # Apply boolean flag mappings
        for tag, attr in _BOOL_TAG_MAP.items():
            if tags.get(tag, 0) != 0:
                setattr(minion_data, attr, True)

        # Check if minion can attack
        exhausted = tags.get(GameTag.EXHAUSTED, 0) != 0
        cant_attack = tags.get(GameTag.CANT_ATTACK, 0) != 0
        minion_data.can_attack = not exhausted and not cant_attack

        minion_data.owner = owner
        minion_data.card_id = card_id

        # Build KeywordSet from the boolean fields we just set
        minion_data.keywords = KeywordSet.from_minion(minion_data)

        return minion_data

    def _extract_hand(self, player) -> List[Card]:
        """Extract hand cards. Uses card_lookup if available."""
        try:
            hand_cards = []
            zone_position = {}

            # Find all cards in HAND zone
            for entity in player.entities:
                if entity.tags.get(GameTag.ZONE) == Zone.HAND:
                    card_type = entity.tags.get(GameTag.CARDTYPE)
                    if card_type is None or card_type in (CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.HERO, CardType.LOCATION):
                        zone_pos = entity.tags.get(GameTag.ZONE_POSITION, 0)
                        zone_position[entity] = zone_pos

            # Sort by zone position (ascending)
            sorted_entities = sorted(zone_position.items(), key=lambda x: x[1])

            for entity, pos in sorted_entities:
                try:
                    card = None

                    # Try to get full card data from lookup
                    if self.card_lookup is not None:
                        card = self.card_lookup(entity.card_id)

                    # If lookup failed or not provided, create minimal card
                    if card is None:
                        tags = entity.tags
                        # Convert IntEnum to string
                        raw_ct = tags.get(GameTag.CARDTYPE, CardType.MINION)
                        ct_str = {CardType.MINION: "MINION", CardType.SPELL: "SPELL", CardType.WEAPON: "WEAPON", CardType.HERO: "HERO", CardType.LOCATION: "LOCATION"}.get(raw_ct, "MINION")
                        card = Card(
                            dbf_id=getattr(entity, "dbf_id", 0),
                            name=entity.card_id or "",
                            cost=tags.get(GameTag.COST, 0),
                            card_type=ct_str,
                        )

                    hand_cards.append(card)
                except Exception as e:
                    log.warning(f"Error creating hand card: {e}")

            return hand_cards
        except Exception as e:
            log.warning(f"Error extracting hand cards: {e}")
            return []

    def _extract_deck_remaining(self, player) -> int:
        """Extract remaining deck size."""
        try:
            # Count entities in DECK zone
            deck_count = 0
            for entity in player.entities:
                if entity.tags.get(GameTag.ZONE) == Zone.DECK:
                    deck_count += 1

            # If DECK count is not available, try alternative method
            if deck_count == 0:
                # Try to use DECKSIZE tag
                deck_size_tag = player.tags.get(GameTag.DECKSIZE, 0)
                initial_decklist_tag = player.tags.get(GameTag.INITIAL_DECKLIST, 0)

                if deck_size_tag > 0 and initial_decklist_tag > 0:
                    deck_count = deck_size_tag - initial_decklist_tag

            return max(0, deck_count)
        except Exception as e:
            log.warning(f"Error extracting deck remaining: {e}")
            return 0

    def _extract_turn(self, game) -> int:
        """Extract current turn number from game entity or player tags."""
        try:
            # Try to get from game entity
            if hasattr(game, "tags"):
                turn = game.tags.get(GameTag.TURN, 1)
                return max(1, turn)

            # Try to get from players
            for player in getattr(game, "players", []):
                if hasattr(player, "tags"):
                    turn = player.tags.get(GameTag.TURN, 1)
                    return max(1, turn)

            # Default to turn 1
            return 1
        except Exception as e:
            log.warning(f"Error extracting turn number: {e}")
            return 1

    def _count_hand(self, player) -> int:
        """Count number of cards in player's hand."""
        try:
            count = 0
            for entity in player.entities:
                if entity.tags.get(GameTag.ZONE) == Zone.HAND:
                    card_type = entity.tags.get(GameTag.CARDTYPE)
                    if card_type is None or card_type in (CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.HERO, CardType.LOCATION):
                        count += 1
            return count
        except Exception as e:
            log.warning(f"Error counting hand: {e}")
            return 0

    def _create_weapon(self, entity) -> Weapon:
        """Create a Weapon from an hslog entity."""
        try:
            tags = entity.tags
            attack = tags.get(GameTag.ATK, 0)
            durability = tags.get(GameTag.DURABILITY, 0)

            return Weapon(
                attack=attack,
                health=durability,
                name=getattr(entity, "card_id", "") or "",
            )
        except Exception as e:
            log.warning(f"Error creating weapon: {e}")
            return Weapon(attack=0, health=0, name="")

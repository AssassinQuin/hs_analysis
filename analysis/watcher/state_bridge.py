"""state_bridge.py — Convert hslog entity tree → GameState for RHEA engine."""

from __future__ import annotations

import logging
from typing import Optional, List, NamedTuple, Callable, Any

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


class FieldMapping(NamedTuple):
    """Declarative mapping from a GlobalGameState field to a target field."""
    src_field: str
    dst_field: str
    transform: Callable[[Any], Any] = lambda x: x


class StateBridge:
    """Bridges hslog entity model → GameState for the decision engine.

    Usage:
        bridge = StateBridge()
        game_state = bridge.convert(hslog_game, player_index=0)
    """

    # Declarative field mappings: GlobalGameState → OpponentState
    _OPP_FIELD_MAP: List[FieldMapping] = [
        FieldMapping("opp_generated_seen", "opp_generated_count", len),
        FieldMapping("opp_secrets", "secrets", list),
        FieldMapping("opp_deck_remaining", "deck_remaining"),
        FieldMapping("opp_weapon", "opp_weapon_card_id", lambda x: x or ""),
        FieldMapping("opp_corpses", "opp_corpses"),
        FieldMapping("opp_herald_count", "opp_herald_count"),
        FieldMapping("opp_quests", "opp_quests", list),
        FieldMapping("opp_shuffled_into_deck", "opp_shuffled_into_deck", list),
        FieldMapping("opp_corrupted_cards", "opp_corrupted_cards", list),
    ]

    # Declarative field mappings: GlobalGameState → GameState (player fields)
    _PLAYER_FIELD_MAP: List[FieldMapping] = [
        FieldMapping("player_herald_count", "herald_count"),
        FieldMapping("player_corpses", "corpses"),
        FieldMapping("player_quests", "active_quests", list),
        FieldMapping("last_turn_races_player", "last_turn_races", set),
        FieldMapping("last_turn_schools_player", "last_turn_schools", set),
    ]

    def __init__(self, card_lookup=None, entity_cache=None, deck_cards: Optional[List[Card]] = None):
        """Initialize with optional card database lookup and entity cache.

        Args:
            card_lookup: callable(card_id: str) → Card or None
                         Used to populate hand cards with full card data.
                         Defaults to HSCardDB lookup if not provided.
            entity_cache: EntityCache instance from GameTracker.
                          Used to look up card_id and tags by entity_id
                          when hslog EntityTreeExporter doesn't provide them.
            deck_cards: Optional list of Card objects from the current deck.
                        Used to match anonymous hand cards (no card_id) by cost.
        """
        if card_lookup is None:
            card_lookup = self._default_card_lookup()
        self.card_lookup = card_lookup
        self.entity_cache = entity_cache
        self.deck_cards = deck_cards or []

        # Build cost-based index from deck_cards for anonymous card matching
        # cost → list of Card objects with that cost
        self._deck_cost_index: dict[int, List[Card]] = {}
        for card in self.deck_cards:
            cost = card.cost
            self._deck_cost_index.setdefault(cost, []).append(card)

    @staticmethod
    def _default_card_lookup():
        """Create a default card_lookup using HSCardDB."""
        try:
            from analysis.data.hsdb import get_db
            from analysis.models.card import Card
            _db = get_db()

            def _lookup(card_id: str):
                if not card_id:
                    return None
                raw = _db.get_card(card_id)
                if raw:
                    return Card.from_hsdb_dict(raw)
                return None
            return _lookup
        except ImportError:
            return None

    def convert(self, game, player_index: int = 0, global_state=None) -> GameState:
        """Convert an hslog Game object to a GameState.

        Args:
            game: hslog Game object (from GameTracker.export_entities())
            player_index: 0 = first player (friendly), 1 = opponent
            global_state: Optional GlobalGameState from GlobalTracker.
                          When provided, enriches GameState with opponent
                          tracking data (known cards, mechanics, secrets, etc.)

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

            # Apply board-based cost modifiers (e.g., 龙群先锋)
            self._apply_board_cost_modifiers(state)

            # Build OpponentState with basic board/hand info
            opp_state = OpponentState(
                hero=self._extract_hero(opponent),
                board=self._extract_minions(opponent, owner="enemy"),
                hand_count=self._count_hand(opponent),
            )

            # Enrich from GlobalGameState if available
            if global_state is not None:
                self._enrich_from_global_state(opp_state, state, global_state)

            state.opponent = opp_state

            state.our_playstyle = self._infer_our_playstyle(state)
            if global_state is not None:
                opp_ps = getattr(global_state, 'opp_playstyle', 'unknown')
                if opp_ps and opp_ps != 'unknown':
                    state.opp_playstyle = opp_ps

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
            hero_class = self._resolve_hero_class(hero, player)

            return HeroState(
                hp=current_health,
                max_hp=max_health,
                armor=armor,
                weapon=weapon,
                hero_class=hero_class,
            )
        except (AttributeError, KeyError) as e:
            log.warning(f"Error extracting hero state: {e}")
            return HeroState()

    def _resolve_hero_class(self, hero_entity, player) -> str:
        """Resolve hero class from entity tags, with robust fallbacks.

        Tries:
        1. GameTag.CLASS on the hero entity (handle int/enum/str)
        2. GameTag.CLASS on any HERO_POWER entity of the player
        3. card_id prefix lookup (e.g. "HERO_07" → WARLOCK)
        """
        # --- Try 1: hero entity CLASS tag ---
        cls_val = hero_entity.tags.get(GameTag.CLASS, None)
        result = self._class_val_to_str(cls_val)
        if result:
            return result

        # --- Try 2: hero power entity CLASS tag ---
        for entity in player.entities:
            if (entity.tags.get(GameTag.ZONE) == Zone.PLAY and
                    entity.tags.get(GameTag.CARDTYPE) == CardType.HERO_POWER):
                cls_val = entity.tags.get(GameTag.CLASS, None)
                result = self._class_val_to_str(cls_val)
                if result:
                    return result

        # --- Try 3: card_id prefix ---
        card_id = getattr(hero_entity, 'card_id', '') or ''
        hero_class_map = {
            "HERO_01": "WARRIOR", "HERO_02": "SHAMAN", "HERO_03": "ROGUE",
            "HERO_04": "PALADIN", "HERO_05": "HUNTER", "HERO_06": "DRUID",
            "HERO_07": "WARLOCK", "HERO_08": "MAGE", "HERO_09": "PRIEST",
            "HERO_10": "DEMONHUNTER", "HERO_11": "DEATHKNIGHT",
        }
        for prefix, cls_name in hero_class_map.items():
            if card_id.startswith(prefix):
                return cls_name

        return "UNKNOWN"

    @staticmethod
    def _class_val_to_str(cls_val) -> str:
        """Convert a CLASS tag value (enum/int/str) to a class name string."""
        if cls_val is None:
            return ""
        # Hearthstone CardClass enum
        if hasattr(cls_val, 'name'):
            return cls_val.name
        # Integer value
        if isinstance(cls_val, int):
            try:
                from hearthstone.enums import CardClass
                return CardClass(cls_val).name
            except (ValueError, ImportError):
                return ""
        # Already a string
        if isinstance(cls_val, str) and cls_val not in ("", "UNKNOWN"):
            return cls_val
        return ""

    def _extract_mana(self, player) -> ManaState:
        """Extract mana state from player tags."""
        try:
            tags = player.tags

            max_mana = tags.get(GameTag.RESOURCES, 0)
            resources_used = tags.get(GameTag.RESOURCES_USED, 0)
            temp = tags.get(GameTag.TEMP_RESOURCES, 0)
            overloaded = tags.get(GameTag.OVERLOAD_LOCKED, 0)
            available = max(0, max_mana - resources_used - overloaded + temp)

            log.debug(
                f"Mana extraction: max={max_mana} used={resources_used} "
                f"temp={temp} overloaded={overloaded} → available={available}"
            )

            return ManaState(
                max_mana=max_mana,
                available=available,
                overloaded=overloaded,
                overload_next=0,
            )
        except (AttributeError, KeyError) as e:
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
                except (AttributeError, KeyError, TypeError) as e:
                    log.warning(f"Error creating minion: {e}")

            return minions
        except (AttributeError, KeyError) as e:
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

        # Resolve name from card database if card_id is known but name is empty
        if card_id and not getattr(minion_data, 'name', ''):
            try:
                card_obj = self.card_lookup(card_id)
                if card_obj and card_obj.name:
                    minion_data.name = card_obj.name
            except Exception:
                pass

        # Build KeywordSet from the boolean fields we just set
        minion_data.keywords = KeywordSet.from_minion(minion_data)

        # Auto-attach trigger enchantments from registry
        if minion_data.name:
            try:
                from analysis.search.trigger_registry import get_triggers_for_minion
                triggers = get_triggers_for_minion(minion_data.name)
                if triggers:
                    minion_data.enchantments = getattr(minion_data, 'enchantments', []) + triggers
            except ImportError:
                pass

        return minion_data

    def _apply_board_cost_modifiers(self, state: GameState) -> None:
        """Apply cost-modifying auras from board minions to mana state.
        
        Checks for known cost-reduction effects on friendly board minions
        and adds appropriate ManaModifiers.
        """
        try:
            for minion in state.board:
                name = getattr(minion, 'name', '')
                
                # ── 龙群先锋 / Naralex, Dragon Pioneer ──
                # "你每个回合使用的第一张龙牌法力值消耗为（1）点。"
                # Add a first_dragon modifier that sets cost to 1
                if name in ('龙群先锋', 'Naralex, Dragon Pioneer',
                            'Naralex Dragon Pioneer'):
                    state.mana.add_modifier(
                        modifier_type="aura",
                        value=1,  # cost becomes 1 (not -1)
                        scope="first_dragon",
                    )
        except Exception as e:
            log.debug(f"Board cost modifier check failed: {e}")

    def _extract_hand(self, player) -> List[Card]:
        """Extract hand cards. Uses entity_cache for card_id when hslog doesn't provide it."""
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

                    # Try to get card_id: first from hslog entity, then from entity_cache
                    card_id = entity.card_id
                    if (not card_id) and self.entity_cache is not None:
                        entity_id = entity.tags.get(GameTag.ENTITY_ID, 0)
                        if entity_id:
                            cached_id = self.entity_cache.get_card_id(entity_id)
                            if cached_id:
                                card_id = cached_id

                    # Try HSCardDB lookup with resolved card_id
                    if card_id and self.card_lookup is not None:
                        card = self.card_lookup(card_id)

                    # If lookup failed or not provided, try deck card matching
                    if card is None and not card_id and self._deck_cost_index:
                        # Anonymous card — try to match by cost from deck
                        tags = entity.tags
                        cache_tags = {}
                        if self.entity_cache is not None:
                            entity_id = tags.get(GameTag.ENTITY_ID, 0)
                            if entity_id:
                                cache_tags = self.entity_cache.get_tags(entity_id)

                        cost_val = cache_tags.get(GameTag.COST)
                        if cost_val is None:
                            cost_val = tags.get(GameTag.COST, 0)

                        candidates = self._deck_cost_index.get(int(cost_val), [])
                        if len(candidates) == 1:
                            # Unique cost match — use it
                            card = Card(
                                card_id=candidates[0].card_id,
                                dbf_id=candidates[0].dbf_id,
                                name=candidates[0].name,
                                cost=int(cost_val),
                                card_type=candidates[0].card_type,
                                attack=candidates[0].attack,
                                health=candidates[0].health,
                                card_class=candidates[0].card_class,
                            )

                    # If still no match, create card from merged tags
                    if card is None:
                        tags = entity.tags
                        # Merge tags from entity_cache if available
                        cache_tags = {}
                        if self.entity_cache is not None:
                            entity_id = tags.get(GameTag.ENTITY_ID, 0)
                            if entity_id:
                                cache_tags = self.entity_cache.get_tags(entity_id)

                        # Resolve tags: cache tags override entity tags (cache is more complete)
                        def _tag(key, default=0):
                            v = cache_tags.get(key)
                            if v is not None:
                                return v
                            return tags.get(key, default)

                        # Convert IntEnum to string
                        raw_ct = _tag(GameTag.CARDTYPE, CardType.MINION)
                        ct_str = {CardType.MINION: "MINION", CardType.SPELL: "SPELL",
                                  CardType.WEAPON: "WEAPON", CardType.HERO: "HERO",
                                  CardType.LOCATION: "LOCATION"}.get(raw_ct, "MINION")

                        card = Card(
                            card_id=card_id or "",
                            dbf_id=0,
                            name=card_id or "",
                            cost=int(_tag(GameTag.COST, 0)),
                            card_type=ct_str,
                            attack=int(_tag(GameTag.ATK, 0)),
                            health=int(_tag(GameTag.HEALTH, 0)),
                        )

                    hand_cards.append(card)
                except (AttributeError, KeyError, TypeError) as e:
                    log.warning(f"Error creating hand card: {e}")

            return hand_cards
        except (AttributeError, KeyError) as e:
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
        except (AttributeError, KeyError) as e:
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
        except (AttributeError, KeyError) as e:
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
        except (AttributeError, KeyError) as e:
            log.warning(f"Error counting hand: {e}")
            return 0

    @staticmethod
    def _infer_our_playstyle(state: GameState) -> str:
        """Infer our deck archetype from hand composition.

        Uses mana cost distribution of hand cards as a proxy for deck archetype.
        Falls back to 'unknown' if hand is too small.
        """
        hand = state.hand
        if not hand or len(hand) < 3:
            return "unknown"

        low = 0
        mid = 0
        high = 0
        total_cost = 0
        n = 0
        for c in hand:
            cost = getattr(c, "cost", 0)
            if not isinstance(cost, (int, float)):
                continue
            total_cost += cost
            n += 1
            if cost <= 2:
                low += 1
            elif cost <= 4:
                mid += 1
            else:
                high += 1

        if n < 3:
            return "unknown"

        avg = total_cost / n
        low_pct = low / n
        mid_pct = mid / n
        high_pct = high / n

        if avg <= 2.0 and low_pct >= 0.55:
            return "aggro"
        if avg <= 2.8 and low_pct >= 0.40 and high_pct <= 0.20:
            return "tempo"
        if avg >= 4.0 and high_pct >= 0.30:
            return "control"
        if low_pct >= 0.30 and mid_pct >= 0.25:
            return "midrange"

        return "unknown"

    def _enrich_from_global_state(self, opp_state: OpponentState,
                                   game_state: GameState, global_state) -> None:
        """Populate GameState with tracking data from GlobalGameState.

        Args:
            opp_state: OpponentState to enrich with opponent tracking data.
            game_state: GameState to enrich with player mechanics.
            global_state: GlobalGameState from GlobalTracker.
        """
        try:
            # Opponent known cards — complex per-field serialization (kept explicit)
            if global_state.opp_known_cards:
                opp_state.opp_known_cards = [
                    {"card_id": kc.card_id, "turn_seen": kc.turn_seen,
                     "source": kc.source.value if hasattr(kc.source, 'value') else str(kc.source),
                     "card_type": kc.card_type}
                    for kc in global_state.opp_known_cards
                ]

            # Opponent secrets triggered — complex per-field serialization (kept explicit)
            if global_state.opp_secrets_triggered:
                opp_state.opp_secrets_triggered = [
                    {"card_id": kc.card_id, "turn_seen": kc.turn_seen}
                    for kc in global_state.opp_secrets_triggered
                ]

            # Apply declarative opponent field mappings
            self._apply_field_map(self._OPP_FIELD_MAP, opp_state, global_state)

            # Player mechanics from GlobalGameState → MechanicsState (special case)
            from analysis.search.mechanics_state import MechanicsState
            game_state._mechanics = MechanicsState.from_global_state(global_state)

            # Apply declarative player field mappings
            self._apply_field_map(self._PLAYER_FIELD_MAP, game_state, global_state)

        except Exception as e:
            log.warning(f"Error enriching from global state: {e}")

    @staticmethod
    def _apply_field_map(field_map: List[FieldMapping], target, source) -> None:
        """Apply a list of FieldMapping entries from source to target."""
        for mapping in field_map:
            value = getattr(source, mapping.src_field)
            setattr(target, mapping.dst_field, mapping.transform(value))

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
        except (AttributeError, KeyError) as e:
            log.warning(f"Error creating weapon: {e}")
            return Weapon(attack=0, health=0, name="")

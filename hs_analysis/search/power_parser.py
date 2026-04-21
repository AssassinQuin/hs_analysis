import os
from hslog.parser import LogParser
from hslog.export import EntityTreeExporter
from hearthstone.enums import GameTag, Zone, CardType


class _SafeEntityTreeExporter(EntityTreeExporter):
    def handle_full_entity(self, packet):
        if packet.entity is None:
            return None
        return super().handle_full_entity(packet)


def parse_power_log(file_path):
    if not os.path.exists(file_path):
        return None

    parser = LogParser()

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                parser.read_line(line)
            except Exception:
                pass

    if not parser.games:
        return None

    packet_tree = parser.games[0]
    exporter = _SafeEntityTreeExporter(packet_tree)
    exporter.export()

    return exporter.game


def extract_game_state(game, player_index=0):
    from hs_analysis.search.game_state import (
        GameState, HeroState, ManaState, Minion, OpponentState
    )

    player = game.players[player_index]
    entities = list(player.entities)

    hero_entities = [
        e for e in entities
        if e.tags.get(GameTag.ZONE) == Zone.PLAY
        and e.tags.get(GameTag.CARDTYPE) == CardType.HERO
    ]
    hero_entity = hero_entities[0] if hero_entities else None

    hero_state = HeroState(
        hp=hero_entity.tags.get(GameTag.HEALTH, 30) if hero_entity else 30,
        max_hp=hero_entity.tags.get(GameTag.HEALTH, 30) if hero_entity else 30,
        armor=hero_entity.tags.get(GameTag.ARMOR, 0) if hero_entity else 0,
        hero_class="",
    )

    mana_state = ManaState(
        available=(
            player.tags.get(GameTag.RESOURCES, 0)
            - player.tags.get(GameTag.RESOURCES_USED, 0)
        ),
        overloaded=player.tags.get(GameTag.OVERLOAD_LOCKED, 0),
        max_mana=player.tags.get(GameTag.RESOURCES, 0),
    )

    minion_entities = [
        e for e in entities
        if e.tags.get(GameTag.ZONE) == Zone.PLAY
        and e.tags.get(GameTag.CARDTYPE) == CardType.MINION
    ]

    minions = []
    for m in minion_entities:
        exhausted = bool(m.tags.get(GameTag.EXHAUSTED, 0))
        cant_attack = bool(m.tags.get(GameTag.CANT_ATTACK, 0))
        minions.append(Minion(
            dbf_id=0,
            name=m.card_id or "",
            attack=m.tags.get(GameTag.ATK, 0),
            health=m.tags.get(GameTag.HEALTH, 1),
            max_health=m.tags.get(GameTag.HEALTH, 1),
            cost=m.tags.get(GameTag.COST, 0),
            can_attack=not exhausted and not cant_attack,
            has_divine_shield=bool(m.tags.get(GameTag.DIVINE_SHIELD, 0)),
            has_taunt=bool(m.tags.get(GameTag.TAUNT, 0)),
            has_stealth=bool(m.tags.get(GameTag.STEALTH, 0)),
            has_windfury=bool(m.tags.get(GameTag.WINDFURY, 0)),
            has_rush=bool(m.tags.get(GameTag.RUSH, 0)),
            has_charge=bool(m.tags.get(GameTag.CHARGE, 0)),
            has_poisonous=bool(m.tags.get(GameTag.POISONOUS, 0)),
            has_lifesteal=bool(m.tags.get(GameTag.LIFESTEAL, 0)),
            has_reborn=bool(m.tags.get(GameTag.REBORN, 0)),
            has_immune=bool(m.tags.get(GameTag.IMMUNE, 0)),
            frozen_until_next_turn=bool(m.tags.get(GameTag.FROZEN, 0)),
            owner="friendly",
        ))

    hand_entities = [
        e for e in entities
        if e.tags.get(GameTag.ZONE) == Zone.HAND
    ]
    hand = [e.card_id or "" for e in hand_entities]

    return hero_state, mana_state, minions, hand

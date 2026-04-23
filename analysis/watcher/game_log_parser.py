# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import List, Optional

from hearthstone.enums import GameTag, Zone, CardType, PlayState
from hslog.parser import LogParser
from hslog.export import EntityTreeExporter

from analysis.config import PROJECT_ROOT
from analysis.models.game_record import (
    PlayerInfo, DeckInfo, CardSighting, GameRecord,
)
from analysis.utils.hero_class import hero_card_to_class, class_to_cn

log = logging.getLogger(__name__)


class _SafeEntityTreeExporter(EntityTreeExporter):
    def handle_full_entity(self, packet):
        if packet.entity is None:
            return None
        return super().handle_full_entity(packet)


_HERO_SKILL_SUFFIXES = ("hp", "bp", "dbp", "ebp")

_RE_DECK_HEADER = re.compile(r"^###\s+(.+)$")
_RE_DECK_ID = re.compile(r"^#\s+Deck ID:\s+(\d+)$")
_RE_DECK_CODE = re.compile(r"^(AAE[A-Za-z0-9/+=]+)$")
_RE_FINDING_GAME = re.compile(r"^Finding Game With Deck:")


def parse_decks_log(path: str) -> list:
    decks = []
    current = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            parts = line.split(" ", 2)
            if len(parts) < 3:
                continue
            ts_str, msg = parts[1], parts[2]

            m = _RE_DECK_HEADER.match(msg)
            if m:
                current = {"name": m.group(1).strip()}
                continue
            m = _RE_DECK_ID.match(msg)
            if m and current:
                current["deck_id"] = m.group(1)
                continue
            m = _RE_DECK_CODE.match(msg)
            if m and current:
                current["code"] = m.group(1)
                continue
            if _RE_FINDING_GAME.match(msg) and current and "code" in current:
                current["finding_time"] = ts_str
                decks.append(current.copy())
                current = {}
    return decks


def _get_hero_card_id(player_game) -> str:
    for e in player_game.entities:
        if not hasattr(e, "card_id"):
            continue
        cid = e.card_id
        if not cid or not cid.startswith("HERO_"):
            continue
        if any(cid.endswith(s) for s in _HERO_SKILL_SUFFIXES):
            continue
        zone = e.tags.get(GameTag.ZONE)
        if zone == Zone.PLAY:
            return cid
    for e in player_game.entities:
        if not hasattr(e, "card_id"):
            continue
        cid = e.card_id
        if not cid or not cid.startswith("HERO_"):
            continue
        if any(cid.endswith(s) for s in _HERO_SKILL_SUFFIXES):
            continue
        ct = e.tags.get(GameTag.CARDTYPE)
        if ct == CardType.HERO:
            return cid
    return ""


def _is_played_card(entity) -> bool:
    if not hasattr(entity, "card_id"):
        return False
    card_id = entity.card_id
    if not card_id:
        return False
    if card_id.startswith("HERO_"):
        return False
    if card_id.startswith("MUDAN_") or card_id.startswith("GBL_"):
        return False
    if card_id.startswith("TIME_000ta") or card_id.startswith("TIME_000tb"):
        return False
    ct = entity.tags.get(GameTag.CARDTYPE)
    if ct in (CardType.HERO, CardType.ENCHANTMENT, CardType.GAME, CardType.PLAYER):
        return False
    return True


def _build_player_info(player_game, is_me: bool, db) -> PlayerInfo:
    hero_cid = _get_hero_card_id(player_game)
    hero_class = hero_card_to_class(hero_cid)
    name = getattr(player_game, "name", "") or ""

    pi = PlayerInfo(
        name=name,
        player_id=player_game.tags.get(GameTag.PLAYER_ID, 0),
        hero_card_id=hero_cid,
        hero_class=hero_class,
        hero_class_cn=class_to_cn(hero_class),
        is_me=is_me,
    )

    seen_card_ids = set()
    for e in player_game.entities:
        if not _is_played_card(e):
            continue
        cid = e.card_id
        if not cid or cid in seen_card_ids:
            continue
        seen_card_ids.add(cid)

        sighting = CardSighting(card_id=cid, card_name=cid)
        if db:
            card_data = db.get_card(cid)
            if card_data:
                sighting.card_name = card_data.get("name", cid) or cid
                sighting.cost = card_data.get("cost", 0)
                sighting.cardClass = card_data.get("cardClass", "")
                sighting.card_type = card_data.get("type", "")
                sighting.collectible = card_data.get("collectible", False)
        pi.played_cards.append(sighting)

    return pi


def parse_games(log_path: str) -> List[GameRecord]:
    parser = LogParser()
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                parser.read_line(line)
            except Exception:
                log.debug("parse_games: failed to parse one line", exc_info=True)

    if not parser.games:
        return []

    db = None
    try:
        from analysis.data.hsdb import get_db as _get_db
        db = _get_db(load_xml=False, build_indexes=False)
    except Exception:
        log.debug("parse_games: failed to load hsdb", exc_info=True)

    games = []
    for gi, packet_tree in enumerate(parser.games):
        try:
            exporter = _SafeEntityTreeExporter(packet_tree)
            exporter.export()
            game = exporter.game
        except Exception:
            continue

        if not game or not hasattr(game, "players") or len(game.players) < 2:
            continue

        p0, p1 = game.players[0], game.players[1]

        my_idx = 0
        n0 = getattr(p0, "name", None) or ""
        n1 = getattr(p1, "name", None) or ""
        if "#" in n1 and ("#" not in n0 or n0 == "UNKNOWN HUMAN PLAYER"):
            my_idx = 1

        me_game = game.players[my_idx]
        opp_game = game.players[1 - my_idx]

        result = "UNKNOWN"
        my_state = me_game.tags.get(GameTag.PLAYSTATE)
        if my_state == PlayState.WON:
            result = "WON"
        elif my_state in (PlayState.LOST, PlayState.CONCEDED):
            result = "LOST"

        me = _build_player_info(me_game, True, db)
        opp = _build_player_info(opp_game, False, db)

        games.append(GameRecord(
            game_index=gi,
            me=me,
            opponent=opp,
            result=result,
        ))

    return games


def assign_decks(games: List[GameRecord], deck_entries: list) -> None:
    unique_decks = {}
    for d in deck_entries:
        did = d.get("deck_id", "?")
        if did not in unique_decks:
            unique_decks[did] = d

    decoded_decks = []
    for did, d in unique_decks.items():
        decoded_decks.append(DeckInfo.from_deck_code(d["name"], did, d["code"]))

    for game in games:
        game_class = game.me.hero_class
        for deck_info in reversed(decoded_decks):
            if deck_info.hero_class == game_class:
                game.me.deck = deck_info
                break


def parse_log_dir(log_dir: str) -> dict:
    log_dir = Path(log_dir)

    deck_entries = []
    decks_log = log_dir / "Decks.log"
    if decks_log.exists():
        deck_entries = parse_decks_log(str(decks_log))

    power_log = log_dir / "Power.log"
    games = []
    if power_log.exists():
        games = parse_games(str(power_log))

    if games and deck_entries:
        assign_decks(games, deck_entries)

    return {
        "log_dir": str(log_dir),
        "deck_entries": deck_entries,
        "games": games,
    }

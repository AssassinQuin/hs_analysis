"""game_replayer.py — Power.log 逐行回放 + RHEA 抉择分析

逐行读取 Power.log，自行维护 entity 状态，在每个决策点快照并运行 RHEA。
"""

import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Any, Dict, List

from analysis.search.game_state import GameState, HeroState, ManaState, Minion, Weapon, OpponentState
from analysis.search.rhea_engine import RHEAEngine, enumerate_legal_actions, Action
from analysis.models.card import Card
from analysis.watcher.global_tracker import GlobalTracker, CardSource

# GameTag numeric values (from hearthstone.enums)
TAG_RESOURCES = 26
TAG_RESOURCES_USED = 25
TAG_MAXRESOURCES = 37
TAG_TURN = 20
TAG_STEP = 19
TAG_ZONE = 49
TAG_CARDTYPE = 202
TAG_COST = 54
TAG_ATK = 47
TAG_HEALTH = 71
TAG_ARMOR = 292
TAG_ZONE_POSITION = 341
TAG_CONTROLLER = 3
TAG_EXHAUSTED = 424
TAG_TAUNT = 238
TAG_DIVINE_SHIELD = 191
TAG_CHARGE = 188
TAG_RUSH = 187
TAG_WINDFURY = 189
TAG_STEALTH = 225
TAG_POISONOUS = 237
TAG_LIFESTEAL = 2145  # correct enum value
TAG_FROZEN = 260
TAG_REBORN = 2185
TAG_OVERLOAD_LOCKED = 393
TAG_TEMP_RESOURCES = 295
TAG_OVERLOAD_OWED = 394
TAG_IMMUNE = 477
TAG_HERO_POWER_USED = 426  # might not exist
TAG_SPELL_POWER = 215

# Zone values
ZONE_PLAY = 1
ZONE_DECK = 2
ZONE_HAND = 3
ZONE_GRAVEYARD = 5
ZONE_SECRET = 7
ZONE_SETASIDE = 6

# CardType values
CT_MINION = 4
CT_SPELL = 5
CT_WEAPON = 7
CT_HERO = 3
CT_HERO_POWER = 10
CT_LOCATION = 6
CT_PLAYER = 2

# Step values
STEP_MAIN_READY = 9
STEP_MAIN_START = 10
STEP_MAIN_ACTION = 11
STEP_MAIN_END = 12


@dataclass
class Entity:
    """Lightweight entity for tracking state."""
    id: int = 0
    card_id: str = ""
    controller: int = 0
    zone: int = 0
    zone_position: int = 0
    card_type: int = 0
    cost: int = 0
    atk: int = 0
    health: int = 0
    armor: int = 0
    exhausted: bool = False
    taunt: bool = False
    divine_shield: bool = False
    charge: bool = False
    rush: bool = False
    windfury: bool = False
    stealth: bool = False
    poisonous: bool = False
    lifesteal: bool = False
    frozen: bool = False
    reborn: bool = False
    immune: bool = False
    spell_power: int = 0


@dataclass
class PlayerState:
    resources: int = 0
    resources_used: int = 0
    overload_locked: int = 0
    temp_resources: int = 0
    max_mana: int = 0
    name: str = ""


@dataclass
class TurnDecision:
    turn_number: int = 0
    player_name: str = ""
    player_turn: int = 0
    hero_hp: int = 0
    hero_armor: int = 0
    mana_available: int = 0
    mana_max: int = 0
    board_count: int = 0
    hand_count: int = 0
    hand_cards: list = field(default_factory=list)  # [{name, cost, type}]
    board_minions: list = field(default_factory=list)  # [{name, atk, health, keywords}]
    opp_hero_hp: int = 30
    opp_armor: int = 0
    opp_board_count: int = 0
    opp_board_minions: list = field(default_factory=list)
    opp_hand_count: int = 0
    opp_deck_remaining: int = 0
    opp_known_hand_cards: list = field(default_factory=list)  # [{card_id, name, source}]
    opp_generated_played: int = 0  # Total generated cards opponent has played
    opp_secrets: list = field(default_factory=list)  # Current opponent secrets
    player_global_stats: str = ""  # Summary of player global stats
    legal_actions_count: int = 0
    action_breakdown: dict = field(default_factory=dict)
    rhea_best_score: float = 0.0
    rhea_best_actions: list = field(default_factory=list)
    rhea_generations: int = 0
    rhea_time_ms: float = 0.0
    decision_quality: str = ""  # "好"/"差"/"一般" with reasoning
    error: str = ""


class GameReplayer:
    def __init__(self, log_dir="logs", player_name="湫然#51704", engine_params=None):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.player_name = player_name
        self.engine_params = engine_params or {"pop_size": 20, "max_gens": 40, "time_limit": 200.0}

        # Entity tracking
        self.entities: dict[int, Entity] = {}
        self.players: dict[int, PlayerState] = {}  # controller_id -> PlayerState
        self.controller_map: dict[int, int] = {}  # entity_id -> controller_id
        self.game_turn = 0
        self.current_step = 0
        self.our_controller = 0
        self.opp_controller = 0
        self._player_entities: dict[int, int] = {}  # entity_id -> controller_id
        self._player_name_map: dict[str, int] = {}  # player_name -> controller_id
        self._player_entity_to_pid: dict[int, int] = {}  # entity_id -> player_id
        self._first_player_entity: int = 0  # entity_id of first player

        # Card ID to Chinese name lookup (load from card data)
        self._card_name_cache = {}

        # Track current entity being defined for nested tags
        self._current_full_entity: int = 0

        # Global game state tracker
        self.global_tracker = GlobalTracker()

        # Results
        self.decisions: list[TurnDecision] = []

        # Logging
        self._setup_loggers()

    def _setup_loggers(self):
        ts = time.strftime("%Y%m%d_%H%M%S")
        # Main replay log — everything
        self.log_main = logging.getLogger(f"replay.main.{ts}")
        fh = logging.FileHandler(self.log_dir / f"replay_{ts}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        self.log_main.addHandler(fh)
        self.log_main.setLevel(logging.DEBUG)

        # Decisions log — per-turn analysis
        self.log_decisions = logging.getLogger(f"replay.decisions.{ts}")
        fh2 = logging.FileHandler(self.log_dir / f"decisions_{ts}.log", encoding="utf-8")
        fh2.setFormatter(logging.Formatter("%(message)s"))
        self.log_decisions.addHandler(fh2)
        self.log_decisions.setLevel(logging.INFO)

        # Errors log
        self.log_errors = logging.getLogger(f"replay.errors.{ts}")
        fh3 = logging.FileHandler(self.log_dir / f"errors_{ts}.log", encoding="utf-8")
        fh3.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        self.log_errors.addHandler(fh3)
        self.log_errors.setLevel(logging.WARNING)

    def _load_card_names(self):
        """Load card_id → Chinese name mapping from card data files.

        Loads collectible, standard, and wild pools for full coverage
        including generated/token cards.
        """
        name_map = {}
        import json
        for path in [
            Path("card_data/240397/zhCN/cards.collectible.json"),
            Path("card_data/240397/unified_standard.json"),
            Path("card_data/240397/unified_wild.json"),
        ]:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        for card in data:
                            cid = card.get("id", "")
                            name = card.get("name", "") or card.get("zhName", "")
                            if cid and name:
                                name_map[cid] = name
                    elif isinstance(data, dict):
                        # unified format might be different
                        pass
                except:
                    pass

        # Also try HSCardDB for non-collectible (token) cards
        try:
            from analysis.data.hsdb import get_db
            db = get_db()
            for cid, card_data in db._cards.items():
                if cid and cid not in name_map:
                    name = card_data.get("name", "") or card_data.get("englishName", "")
                    if name:
                        name_map[cid] = name
        except Exception:
            pass

        return name_map

    def replay_file(self, path: str) -> list[TurnDecision]:
        """Replay Power.log line by line with full state tracking."""
        self._card_name_cache = self._load_card_names()
        self.global_tracker.on_game_start()

        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                self._process_line(line)

        self._save_summary()
        return self.decisions

    def _process_line(self, line: str):
        """Process a single Power.log line."""
        # Only process DebugPrintPower and PowerTaskList lines
        if 'GameState.DebugPrintPower()' not in line and 'PowerTaskList.DebugPrintPower()' not in line:
            return

        # Player definition: Player EntityID=2 PlayerID=1
        m_player = re.match(r'.*Player EntityID=(\d+) PlayerID=(\d+)', line)
        if m_player:
            entity_id = int(m_player.group(1))
            player_id = int(m_player.group(2))
            self._player_entity_to_pid[entity_id] = player_id
            self._current_full_entity = entity_id  # Track for nested tags
            return

        # FULL_ENTITY (Creating or Updating)
        # Creating format: "FULL_ENTITY - Creating ID=123 CardID=XXX"
        # Updating format: "FULL_ENTITY - Updating [entityName=... id=123 ...] CardID=XXX"
        m = re.match(r'.*FULL_ENTITY - Creating ID=(\d+) CardID=(\S*)', line)
        if not m:
            m = re.match(r'.*FULL_ENTITY - Updating \[.*?id=(\d+)\s.*?\] CardID=(\S*)', line)
        if m:
            entity_id = int(m.group(1))
            card_id = m.group(2) or ""
            if entity_id in self.entities:
                # Update existing entity (e.g., opponent reveal)
                if card_id:
                    self.entities[entity_id].card_id = card_id
            else:
                self.entities[entity_id] = Entity(id=entity_id, card_id=card_id)
            self._current_full_entity = entity_id  # Track for nested tags
            # Notify global tracker of entity birth
            entity = self.entities[entity_id]
            self.global_tracker.on_full_entity(
                entity_id=entity_id,
                card_id=card_id,
                controller=entity.controller,
                zone=entity.zone,
                card_type=entity.card_type,
                cost=entity.cost,
            )
            return

        # SHOW_ENTITY - reveals card_id for hidden entities
        # Format 1: Entity=63 CardID=TLC_460 (simple numeric)
        # Format 2: Entity=[entityName=UNKNOWN ENTITY [cardType=INVALID] id=63 ...] CardID=TLC_460 (bracketed with nested [])
        m = re.match(r'.*SHOW_ENTITY - Updating Entity=(\d+) CardID=(\S+)', line)
        if not m:
            m = re.match(r'.*SHOW_ENTITY - Updating.*?id=(\d+).*?CardID=(\S+)', line)
        if m:
            entity_id = int(m.group(1))
            card_id = m.group(2)
            if entity_id in self.entities:
                self.entities[entity_id].card_id = card_id
            else:
                self.entities[entity_id] = Entity(id=entity_id, card_id=card_id)
            self._current_full_entity = entity_id  # Track for nested tags
            # Notify global tracker of card reveal (key for opponent hand tracking)
            entity = self.entities[entity_id]
            self.global_tracker.on_show_entity(
                entity_id=entity_id,
                card_id=card_id,
                controller=entity.controller,
                zone=entity.zone,
                card_type=entity.card_type,
                cost=entity.cost,
            )
            return

        # TAG_CHANGE — handle both simple Entity=18 and complex Entity=[entityName=... id=89 ...]
        m = re.match(r'.*TAG_CHANGE Entity=(\[[^\]]*\]|\S+) tag=(\w+) value=(\S+)', line)
        if m:
            entity_str = m.group(1)
            tag_name = m.group(2)
            value_str = m.group(3).strip()
            self._handle_tag_change(entity_str, tag_name, value_str, line)
            return

        # Tag line within FULL_ENTITY/Player block (indented)
        m_tag = re.match(r'.*DebugPrintPower\(\) -\s+tag=(\w+) value=(\S+)', line)
        if m_tag and self._current_full_entity > 0:
            tag_name = m_tag.group(1)
            value_str = m_tag.group(2).strip()
            entity_id = self._current_full_entity
            if entity_id in self.entities:
                self._apply_entity_tag(self.entities[entity_id], tag_name, value_str)
            elif entity_id in self._player_entity_to_pid:
                # Player entity nested tags — extract MAXRESOURCES
                pid = self._player_entity_to_pid[entity_id]
                if tag_name == 'MAXRESOURCES' and pid in self.players:
                    self.players[pid].max_mana = self._parse_value(value_str)
            return

    def _handle_tag_change(self, entity_str: str, tag_name: str, value_str: str, raw_line: str):
        """Handle a TAG_CHANGE packet."""
        # STEP and TURN are game-level tags (Entity=GameEntity), handle directly
        if tag_name == 'STEP':
            self._handle_step_change(value_str, raw_line)
            return
        if tag_name == 'TURN':
            # Only track game-level turn (Entity=GameEntity or Entity=1),
            # NOT player-level turns (Entity=湫然#51704 tag=TURN value=N)
            if entity_str in ('GameEntity', '1'):
                self._handle_turn_change(value_str)
            return

        # Reset current entity tracking - we've hit a non-nested tag
        self._current_full_entity = 0

        # Resolve entity for player/entity-level tags
        entity = self._resolve_entity(entity_str)
        if entity is None:
            return

        # STEP/TURN/FIRST_PLAYER use string values, ZONE also uses string in TAG_CHANGE
        if tag_name in ('STEP', 'TURN', 'FIRST_PLAYER'):
            value = value_str
        elif tag_name == 'ZONE':
            zone_map = {
                'PLAY': ZONE_PLAY, 'DECK': ZONE_DECK, 'HAND': ZONE_HAND,
                'GRAVEYARD': ZONE_GRAVEYARD, 'SECRET': ZONE_SECRET, 'SETASIDE': ZONE_SETASIDE,
            }
            value = zone_map.get(value_str, self._parse_value(value_str))
        else:
            value = self._parse_value(value_str)

        # Map tag name to our tracking
        tag_map = {
            'RESOURCES': ('resources', lambda e, v: self._update_player_tag(e, 'resources', v)),
            'RESOURCES_USED': ('resources_used', lambda e, v: self._update_player_tag(e, 'resources_used', v)),
            'MAXRESOURCES': ('max_mana', lambda e, v: self._update_player_tag(e, 'max_mana', v)),
            'TURN': ('turn', lambda e, v: self._handle_turn_change(v)),
            'STEP': ('step', lambda e, v: self._handle_step_change(v)),
            'ZONE': ('zone', lambda e, v: self._update_entity_tag(e, 'zone', v)),
            'ZONE_POSITION': ('zone_position', lambda e, v: self._update_entity_tag(e, 'zone_position', v)),
            'CONTROLLER': ('controller', lambda e, v: self._update_controller(e, v)),
            'CARDTYPE': ('card_type', lambda e, v: self._update_entity_tag(e, 'card_type', v)),
            'COST': ('cost', lambda e, v: self._update_entity_tag(e, 'cost', v)),
            'ATK': ('atk', lambda e, v: self._update_entity_tag(e, 'atk', v)),
            'HEALTH': ('health', lambda e, v: self._update_entity_tag(e, 'health', v)),
            'ARMOR': ('armor', lambda e, v: self._update_entity_tag(e, 'armor', v)),
            'EXHAUSTED': ('exhausted', lambda e, v: self._update_entity_tag(e, 'exhausted', bool(v))),
            'TAUNT': ('taunt', lambda e, v: self._update_entity_tag(e, 'taunt', bool(v))),
            'DIVINE_SHIELD': ('divine_shield', lambda e, v: self._update_entity_tag(e, 'divine_shield', bool(v))),
            'CHARGE': ('charge', lambda e, v: self._update_entity_tag(e, 'charge', bool(v))),
            'RUSH': ('rush', lambda e, v: self._update_entity_tag(e, 'rush', bool(v))),
            'WINDFURY': ('windfury', lambda e, v: self._update_entity_tag(e, 'windfury', bool(v))),
            'STEALTH': ('stealth', lambda e, v: self._update_entity_tag(e, 'stealth', bool(v))),
            'POISONOUS': ('poisonous', lambda e, v: self._update_entity_tag(e, 'poisonous', bool(v))),
            'LIFESTEAL': ('lifesteal', lambda e, v: self._update_entity_tag(e, 'lifesteal', bool(v))),
            'FROZEN': ('frozen', lambda e, v: self._update_entity_tag(e, 'frozen', bool(v))),
            'REBORN': ('reborn', lambda e, v: self._update_entity_tag(e, 'reborn', bool(v))),
            'IMMUNE': ('immune', lambda e, v: self._update_entity_tag(e, 'immune', bool(v))),
            'SPELL_POWER': ('spell_power', lambda e, v: self._update_entity_tag(e, 'spell_power', v)),
            'FIRST_PLAYER': ('first_player', lambda e, v: self._handle_first_player(e, v)),
            'OVERLOAD_OWED': ('overload_owed', lambda e, v: self._handle_overload_owed(e, v)),
        }

        handler = tag_map.get(tag_name)
        if handler:
            handler[1](entity, value)

    def _resolve_entity(self, entity_str: str):
        """Resolve entity string to entity ID or player controller."""
        # Handle complex bracketed entity strings: [entityName=... id=89 ...]
        if entity_str.startswith('['):
            m_id = re.search(r'id=(\d+)', entity_str)
            if m_id:
                return ('entity', int(m_id.group(1)))
            return None

        if entity_str == 'GameEntity':
            return None
        # Check player name map first
        if entity_str in self._player_name_map:
            return ('player', self._player_name_map[entity_str])
        # Known player names
        if entity_str == self.player_name:
            # Lazy init if FIRST_PLAYER not yet seen
            if self.our_controller == 0:
                return None  # skip until we know the mapping
            return ('player', self.our_controller)
        if entity_str == 'UNKNOWN HUMAN PLAYER':
            if self.opp_controller == 0:
                return None
            return ('player', self.opp_controller)
        # Try as numeric entity ID
        try:
            return ('entity', int(entity_str))
        except ValueError:
            return None

    def _parse_value(self, value_str: str) -> int:
        try:
            return int(value_str)
        except ValueError:
            return 0

    def _apply_entity_tag(self, entity: Entity, tag_name: str, value_str: str):
        """Apply a tag from FULL_ENTITY/SHOW_ENTITY nested tags."""
        tag_map = {
            'CONTROLLER': 'controller',
            'ZONE': 'zone',
            'ZONE_POSITION': 'zone_position',
            'CARDTYPE': 'card_type',
            'COST': 'cost',
            'ATK': 'atk',
            'HEALTH': 'health',
            'ARMOR': 'armor',
            'EXHAUSTED': 'exhausted',
            'TAUNT': 'taunt',
            'DIVINE_SHIELD': 'divine_shield',
            'CHARGE': 'charge',
            'RUSH': 'rush',
            'WINDFURY': 'windfury',
            'STEALTH': 'stealth',
            'POISONOUS': 'poisonous',
            'LIFESTEAL': 'lifesteal',
            'FROZEN': 'frozen',
            'REBORN': 'reborn',
            'IMMUNE': 'immune',
            'SPELL_POWER': 'spell_power',
        }

        # Handle string-valued tags in FULL_ENTITY blocks
        if tag_name == 'ZONE':
            zone_map = {
                'PLAY': ZONE_PLAY,
                'DECK': ZONE_DECK,
                'HAND': ZONE_HAND,
                'GRAVEYARD': ZONE_GRAVEYARD,
                'SECRET': ZONE_SECRET,
                'SETASIDE': ZONE_SETASIDE,
            }
            value = zone_map.get(value_str, 0)
        elif tag_name == 'CARDTYPE':
            cardtype_map = {
                'GAME': 0,
                'PLAYER': CT_PLAYER,
                'HERO': CT_HERO,
                'MINION': CT_MINION,
                'SPELL': CT_SPELL,
                'WEAPON': CT_WEAPON,  # Not seen but include
                'HERO_POWER': CT_HERO_POWER,
                'LOCATION': CT_LOCATION,
            }
            value = cardtype_map.get(value_str, 0)
        else:
            value = self._parse_value(value_str)

        attr = tag_map.get(tag_name)
        if attr:
            if isinstance(getattr(entity, attr, None), bool):
                setattr(entity, attr, bool(value))
            else:
                setattr(entity, attr, value)

    def _update_player_tag(self, entity, attr: str, value: int):
        """Update player state for a tag change."""
        if isinstance(entity, tuple) and entity[0] == 'player':
            controller_id = entity[1]
            if controller_id not in self.players:
                self.players[controller_id] = PlayerState(name=f"Player{controller_id}")
            setattr(self.players[controller_id], attr, value)

    def _update_entity_tag(self, entity, attr: str, value: int):
        """Update entity state for a tag change."""
        if isinstance(entity, tuple) and entity[0] == 'entity':
            entity_id = entity[1]
            if entity_id in self.entities:
                old_value = getattr(self.entities[entity_id], attr, 0)
                setattr(self.entities[entity_id], attr, value)
                # Track zone changes for global tracker
                if attr == 'zone' and old_value != value:
                    e = self.entities[entity_id]
                    self.global_tracker.on_zone_change(
                        entity_id=entity_id,
                        controller=e.controller,
                        old_zone=old_value,
                        new_zone=value,
                        card_id=e.card_id,
                        card_type=e.card_type,
                    )

    def _handle_first_player(self, entity, value):
        """Detect first player assignment."""
        if isinstance(entity, tuple) and entity[0] == 'entity':
            entity_id = entity[1]
            self._first_player_entity = entity_id
            # Map entity_id -> player_id
            pid = self._player_entity_to_pid.get(entity_id, 0)
            if pid > 0:
                self.our_controller = pid
                self.opp_controller = 3 - pid
                self.players[self.our_controller] = PlayerState(name=self.player_name)
                self.players[self.opp_controller] = PlayerState(name="UNKNOWN HUMAN PLAYER")
                self._player_name_map[self.player_name] = self.our_controller
                self._player_name_map["UNKNOWN HUMAN PLAYER"] = self.opp_controller
                self.global_tracker.set_controllers(self.our_controller, self.opp_controller)
                self.log_main.info(f"🎮 我方: {self.player_name} (PlayerID={self.our_controller}, 先手)")
        elif isinstance(entity, tuple) and entity[0] == 'player':
            # Already resolved to player - this means player name matched
            pass

    def _update_controller(self, entity, value: int):
        """Update controller mapping."""
        if isinstance(entity, tuple) and entity[0] == 'entity':
            entity_id = entity[1]
            self.controller_map[entity_id] = value

    def _handle_overload_owed(self, entity, value):
        """Handle OVERLOAD_OWED tag — track overload for global state."""
        if isinstance(entity, tuple) and entity[0] == 'player':
            controller_id = entity[1]
            self.global_tracker.on_overload_change(controller_id, int(value))

    def _handle_turn_change(self, value):
        """Handle TURN tag change."""
        try:
            self.game_turn = int(value)
            self.global_tracker.on_turn_change(self.game_turn)
        except (ValueError, TypeError):
            pass

    def _handle_step_change(self, value: str, source: str = ""):
        """Handle STEP tag change. MAIN_ACTION is the decision point."""
        self.current_step = value

        if value == 'MAIN_ACTION':
            # Only process from GameState to avoid duplicates (PowerTaskList repeats)
            if source and 'PowerTaskList' in source:
                return

            # First player (PlayerID=our_controller if we're first) plays on odd game turns
            # Since FIRST_PLAYER entity has our controller id, we ARE the first player
            is_our_turn = (self.game_turn % 2 == 1)

            if is_our_turn:
                self._analyze_decision_point()
            else:
                self._collect_opponent_turn_info()

    def _analyze_decision_point(self):
        """Build GameState from tracked entities and run RHEA."""
        try:
            # Find our player
            our_player = None
            opp_player = None

            for controller_id, player_state in self.players.items():
                if player_state.name == self.player_name:
                    our_player = player_state
                else:
                    opp_player = player_state

            if not our_player:
                self.log_errors.error(f"无法找到玩家 {self.player_name}")
                return

            # Find our controller
            for controller_id, player_state in self.players.items():
                if player_state.name == self.player_name:
                    self.our_controller = controller_id
                    break

            # Find opponent controller
            for controller_id, player_state in self.players.items():
                if player_state.name != self.player_name:
                    self.opp_controller = controller_id
                    break

            # Extract player entities
            our_entities = []
            opp_entities = []

            for entity_id, entity in self.entities.items():
                controller = entity.controller
                if controller == self.our_controller:
                    our_entities.append(entity)
                elif controller == self.opp_controller:
                    opp_entities.append(entity)

            # Extract hero HP/armor
            our_hero_hp = 30
            our_hero_armor = 0
            opp_hero_hp = 30
            opp_hero_armor = 0

            for entity in our_entities:
                if entity.card_type == CT_HERO:
                    our_hero_hp = entity.health
                    our_hero_armor = entity.armor
                elif entity.card_type == CT_MINION:
                    pass  # minions on board

            for entity in opp_entities:
                if entity.card_type == CT_HERO:
                    opp_hero_hp = entity.health
                    opp_hero_armor = entity.armor

            # Extract board minions
            our_board = []
            opp_board = []

            for entity in our_entities:
                if entity.zone == ZONE_PLAY and entity.card_type == CT_MINION:
                    keywords = []
                    if entity.taunt: keywords.append("嘲讽")
                    if entity.divine_shield: keywords.append("圣盾")
                    if entity.charge: keywords.append("冲锋")
                    if entity.rush: keywords.append("突袭")
                    if entity.windfury: keywords.append("风怒")
                    if entity.stealth: keywords.append("潜行")
                    if entity.poisonous: keywords.append("剧毒")
                    if entity.frozen: keywords.append("冻结")
                    if entity.reborn: keywords.append("亡语")

                    our_board.append({
                        'name': self._card_name(entity.card_id),
                        'atk': entity.atk,
                        'health': entity.health,
                        'keywords': keywords,
                    })

            for entity in opp_entities:
                if entity.zone == ZONE_PLAY and entity.card_type == CT_MINION:
                    opp_board.append({
                        'name': self._card_name(entity.card_id),
                        'atk': entity.atk,
                        'health': entity.health,
                        'keywords': [],
                    })

            # Extract hand cards
            our_hand = []

            for entity in our_entities:
                if entity.zone == ZONE_HAND:
                    # Card type filtering
                    if entity.card_type == CT_MINION:
                        type_str = "随从"
                    elif entity.card_type == CT_SPELL:
                        type_str = "法术"
                    elif entity.card_type == CT_WEAPON:
                        type_str = "武器"
                    elif entity.card_type == CT_HERO:
                        type_str = "英雄牌"
                    elif entity.card_type == CT_LOCATION:
                        type_str = "地点"
                    elif entity.card_type == CT_HERO_POWER:
                        type_str = "英雄技能"
                    else:
                        type_str = "未知"

                    our_hand.append({
                        'name': self._card_name(entity.card_id),
                        'cost': entity.cost,
                        'type': type_str,
                    })

            # Extract mana state
            # In Hearthstone: RESOURCES = current mana crystals (1-10, increases each turn)
            # MAXRESOURCES = absolute cap (always 10)
            # RESOURCES_USED = mana spent this turn
            mana_max = our_player.resources
            mana_used = our_player.resources_used
            mana_temp = our_player.temp_resources
            mana_overload = our_player.overload_locked
            mana_available = max(0, mana_max - mana_used - mana_overload + mana_temp)

            # Count opponent board
            opp_board_count = 0
            for entity in opp_entities:
                if entity.zone == ZONE_PLAY and entity.card_type == CT_MINION:
                    opp_board_count += 1

            # Count opponent deck (FIXED: count ZONE_DECK only, not total-PLAY)
            opp_deck_remaining = self.global_tracker.count_opp_deck(opp_entities)
            opp_hand_count = self.global_tracker.get_opp_hand_count(opp_entities)

            # Update opponent weapon/location tracking
            self.global_tracker.update_opp_weapon(opp_entities)
            self.global_tracker.update_opp_locations(opp_entities)

            # Build summary
            summary = {
                'turn_number': self.game_turn,
                'player_name': self.player_name,
                'player_turn': len([d for d in self.decisions if d.turn_number == self.game_turn]) + 1,
                'hero_hp': our_hero_hp,
                'hero_armor': our_hero_armor,
                'mana_max': mana_max,
                'mana_available': mana_available,
                'mana_used': mana_used,
                'mana_temp': mana_temp,
                'mana_overload': mana_overload,
                'board_count': len(our_board),
                'hand_count': len(our_hand),
                'hand_cards': our_hand[:8],  # limit to first 8
                'board_minions': our_board[:6],  # limit to first 6
                'opp_hero_hp': opp_hero_hp,
                'opp_hero_armor': opp_hero_armor,
                'opp_board_count': opp_board_count,
                'opp_hand_count': opp_hand_count,
                'opp_deck_remaining': opp_deck_remaining,
                'opp_known_hand': self.global_tracker.get_opp_known_hand(),
                'opp_generated_count': len(self.global_tracker.state.opp_generated_seen),
            }

            self.log_main.info("=" * 70)
            self.log_main.info(f"🎯 回合 {self.game_turn} (湫然#51704)")
            self.log_main.info("=" * 70)
            self.log_main.info(f"状态: 英雄 HP={our_hero_hp}/{30} 护甲={our_hero_armor} | "
                             f"法力 {mana_available}/{mana_max} (已用{mana_used}, "
                             f"临时{mana_temp}, 超载{mana_overload}) | "
                             f"场面 {len(our_board)}随从 | 手牌 {len(our_hand)}张")
            self.log_main.info(f"  场面:")
            for i, m in enumerate(our_board[:6], 1):
                kw = f" ({' '.join(m['keywords'])})" if m['keywords'] else ""
                self.log_main.info(f"    [{i}] {m['name']} {m['atk']}/{m['health']}{kw}")
            self.log_main.info(f"  手牌:")
            if not our_hand:
                self.log_main.info(f"    (空 — 卡牌可能在本决策点后加入)")
            for i, c in enumerate(our_hand[:8], 1):
                self.log_main.info(f"    [{i}] {c['name']} ({c['cost']}费·{c['type']})")
            self.log_main.info(f"对手: HP={opp_hero_hp} 护甲={opp_hero_armor} | "
                             f"场面 {opp_board_count}随从 | 手牌 {opp_hand_count}张 | "
                             f"牌库 {opp_deck_remaining}张")

            # Log opponent known hand cards
            opp_known = self.global_tracker.get_opp_known_hand()
            if opp_known:
                known_str = ", ".join(self._card_name(cid) for _, cid in opp_known)
                self.log_main.info(f"  对手已知手牌: {known_str}")

            # Log opponent generated cards played so far
            if self.global_tracker.state.opp_generated_seen:
                gen_str = ", ".join(self._card_name(cid)
                                    for cid in self.global_tracker.state.opp_generated_seen)
                self.log_main.info(f"  对手衍生牌: {gen_str}")

            # Log opponent secrets
            if self.global_tracker.state.opp_secrets:
                sec_str = ", ".join(self._card_name(cid)
                                    for cid in self.global_tracker.state.opp_secrets)
                self.log_main.info(f"  对手奥秘: {sec_str}")

            # Build GameState
            game_state = self._build_game_state(
                our_entities=our_entities,
                our_player=our_player,
                opp_entities=opp_entities,
                opp_player=opp_player,
            )

            if not game_state or not game_state.hero:
                self.log_errors.error(f"无法构建 GameState")
                return

            # Enumerate legal actions
            legal_actions = enumerate_legal_actions(game_state)

            # Count action types
            action_breakdown = {}
            for action in legal_actions:
                action_breakdown[action.action_type] = action_breakdown.get(action.action_type, 0) + 1

            # Build action descriptions
            action_descriptions = []
            for i, action in enumerate(legal_actions[:15]):  # limit to first 15
                desc = action.describe(game_state)
                action_descriptions.append(f"  {i+1:2d}. {desc}")

            self.log_main.info(f"⚖️ 合法动作: {len(legal_actions)} 个")
            for desc in action_descriptions:
                self.log_main.info(desc)

            # Run RHEA
            self.log_main.info("")
            self.log_main.info("🔍 运行 RHEA 分析...")
            t0 = time.perf_counter()

            try:
                rhea_engine = RHEAEngine(**self.engine_params)
                search_result = rhea_engine.search(game_state)

                t1 = time.perf_counter()
                rhea_time_ms = (t1 - t0) * 1000.0

                # Evaluate decision quality
                decision_quality = self._evaluate_decision(
                    game_state=game_state,
                    search_result=search_result,
                    legal_actions=legal_actions,
                    summary=summary,
                )

                # Log results
                self.log_decisions.info("=" * 70)
                self.log_decisions.info(f"回合 {self.game_turn} (湫然#51704)")
                self.log_decisions.info("=" * 70)
                self.log_decisions.info(f"状态: 英雄 HP={our_hero_hp}/{30} 护甲={our_hero_armor} | "
                                      f"法力 {mana_available}/{mana_max} | "
                                      f"场面 {len(our_board)}随从 | 手牌 {len(our_hand)}张")
                self.log_decisions.info(f"对手: HP={opp_hero_hp} | 场面 {opp_board_count}随从")
                self.log_decisions.info(f"合法动作: {len(legal_actions)} 个 {action_breakdown}")

                for desc in action_descriptions:
                    self.log_decisions.info(desc)

                self.log_decisions.info("")
                self.log_decisions.info(f"RHEA 搜索: {rhea_time_ms:.1f}ms, {search_result.generations_run} 代")
                self.log_decisions.info(f"最佳适应度: {search_result.best_fitness:+.2f}")

                self.log_decisions.info("")
                self.log_decisions.info("最佳序列:")
                for i, action in enumerate(search_result.best_chromosome):
                    self.log_decisions.info(f"  {i+1}. {action.describe(game_state)}")

                self.log_decisions.info("")
                self.log_decisions.info(f"抉择分析: {decision_quality['rating']}")
                for reason in decision_quality['reasons']:
                    self.log_decisions.info(f"  - {reason}")
                self.log_decisions.info("=" * 70)

                # Store decision
                decision = TurnDecision(
                    turn_number=self.game_turn,
                    player_name=self.player_name,
                    player_turn=len([d for d in self.decisions if d.turn_number == self.game_turn]) + 1,
                    hero_hp=our_hero_hp,
                    hero_armor=our_hero_armor,
                    mana_available=mana_available,
                    mana_max=mana_max,
                    board_count=len(our_board),
                    hand_count=len(our_hand),
                    hand_cards=[{
                        'name': c['name'],
                        'cost': c['cost'],
                        'type': c['type'],
                    } for c in our_hand[:8]],
                    board_minions=[{
                        'name': m['name'],
                        'atk': m['atk'],
                        'health': m['health'],
                        'keywords': m['keywords'],
                    } for m in our_board[:6]],
                    opp_hero_hp=opp_hero_hp,
                    opp_armor=opp_hero_armor,
                    opp_board_count=opp_board_count,
                    opp_board_minions=[{
                        'name': m['name'],
                        'atk': m['atk'],
                        'health': m['health'],
                    } for m in opp_board[:7]],
                    opp_hand_count=opp_hand_count,
                    opp_deck_remaining=opp_deck_remaining,
                    opp_known_hand_cards=[
                        {"card_id": cid, "name": self._card_name(cid)}
                        for _, cid in self.global_tracker.get_opp_known_hand()
                    ],
                    opp_generated_played=len(self.global_tracker.state.opp_generated_seen),
                    opp_secrets=list(self.global_tracker.state.opp_secrets),
                    player_global_stats=self.global_tracker.player_summary_str(self._card_name),
                    legal_actions_count=len(legal_actions),
                    action_breakdown=action_breakdown,
                    rhea_best_score=search_result.best_fitness,
                    rhea_best_actions=[action.describe(game_state) for action in search_result.best_chromosome],
                    rhea_generations=search_result.generations_run,
                    rhea_time_ms=rhea_time_ms,
                    decision_quality=decision_quality['rating'],
                    error="",
                )
                self.decisions.append(decision)

            except Exception as e:
                self.log_errors.error(f"RHEA 搜索失败: {e}", exc_info=True)
                self.decisions.append(TurnDecision(
                    turn_number=self.game_turn,
                    player_name=self.player_name,
                    player_turn=len([d for d in self.decisions if d.turn_number == self.game_turn]) + 1,
                    hero_hp=our_hero_hp,
                    hero_armor=our_hero_armor,
                    mana_available=mana_available,
                    mana_max=mana_max,
                    board_count=len(our_board),
                    hand_count=len(our_hand),
                    opp_hero_hp=opp_hero_hp,
                    opp_armor=opp_hero_armor,
                    opp_board_count=opp_board_count,
                    opp_board_minions=[],
                    opp_hand_count=opp_hand_count,
                    opp_deck_remaining=opp_deck_remaining,
                    opp_secrets=list(self.global_tracker.state.opp_secrets),
                    legal_actions_count=len(legal_actions),
                    action_breakdown=action_breakdown,
                    rhea_best_score=0.0,
                    rhea_best_actions=[],
                    rhea_generations=0,
                    rhea_time_ms=0.0,
                    decision_quality="❌ 错误",
                    error=str(e),
                ))

        except Exception as e:
            self.log_errors.error(f"分析回合 {self.game_turn} 时出错: {e}", exc_info=True)

    def _collect_opponent_turn_info(self):
        """Collect and log opponent state during their turn for decision support."""
        try:
            # Find opponent player state
            opp_player = None
            for controller_id, player_state in self.players.items():
                if player_state.name != self.player_name:
                    opp_player = player_state
                    break
            if not opp_player:
                return

            # Find opponent controller
            opp_controller = None
            for controller_id, player_state in self.players.items():
                if player_state.name != self.player_name:
                    opp_controller = controller_id
                    break
            if opp_controller is None:
                return

            # Collect opponent entities
            opp_entities = [e for e in self.entities.values() if e.controller == opp_controller]

            # Opponent hero
            opp_hero_hp = 30
            opp_hero_armor = 0
            opp_hero_class = self.global_tracker.state.opp_hero_class or "未知"
            for entity in opp_entities:
                if entity.card_type == CT_HERO:
                    opp_hero_hp = entity.health
                    opp_hero_armor = entity.armor
                    break

            # Opponent board
            opp_board = []
            for entity in opp_entities:
                if entity.zone == ZONE_PLAY and entity.card_type == CT_MINION:
                    opp_board.append({
                        'name': self._card_name(entity.card_id),
                        'atk': entity.atk,
                        'health': entity.health,
                    })

            # Opponent hand count & deck
            opp_hand_count = self.global_tracker.get_opp_hand_count(opp_entities)
            opp_deck_remaining = self.global_tracker.count_opp_deck(opp_entities)

            # Update opponent weapon/location tracking
            self.global_tracker.update_opp_weapon(opp_entities)
            self.global_tracker.update_opp_locations(opp_entities)

            # Log opponent turn info
            self.log_main.info(f"📋 对手回合 {self.game_turn}: "
                             f"HP={opp_hero_hp} 护甲={opp_hero_armor} "
                             f"职业={opp_hero_class} | "
                             f"场面 {len(opp_board)}随从 | "
                             f"手牌 {opp_hand_count}张 | "
                             f"牌库 {opp_deck_remaining}张")

            # Log opponent board minions if any
            if opp_board:
                for i, m in enumerate(opp_board[:7], 1):
                    self.log_main.info(f"    对手随从[{i}]: {m['name']} {m['atk']}/{m['health']}")

            # Log opponent known hand cards
            opp_known = self.global_tracker.get_opp_known_hand()
            if opp_known:
                known_str = ", ".join(self._card_name(cid) for _, cid in opp_known)
                self.log_main.info(f"    对手已知手牌: {known_str}")

            # Log opponent generated cards played so far
            if self.global_tracker.state.opp_generated_seen:
                gen_str = ", ".join(self._card_name(cid)
                                    for cid in self.global_tracker.state.opp_generated_seen)
                self.log_main.info(f"    对手衍生牌: {gen_str}")

            # Log opponent secrets
            if self.global_tracker.state.opp_secrets:
                sec_str = ", ".join(self._card_name(cid)
                                    for cid in self.global_tracker.state.opp_secrets)
                self.log_main.info(f"    对手奥秘: {sec_str}")

            # Log opponent weapon
            if self.global_tracker.state.opp_weapon:
                w = self.global_tracker.state.opp_weapon
                self.log_main.info(f"    对手武器: {self._card_name(w['card_id'])} {w['atk']}/{w['durability']}")

            # Log opponent locations
            for loc in self.global_tracker.state.opp_locations:
                self.log_main.info(f"    对手地标: {self._card_name(loc['card_id'])} "
                                 f"HP={loc['current_hp']} CD={loc['cooldown']}")

        except Exception as e:
            self.log_errors.error(f"收集对手回合 {self.game_turn} 信息时出错: {e}", exc_info=True)

    def _build_game_state(
        self,
        our_entities: List[Entity],
        our_player: PlayerState,
        opp_entities: List[Entity],
        opp_player: PlayerState,
    ) -> Optional[GameState]:
        """Build GameState from our tracked entities."""
        try:
            # Extract our hero
            our_hero = None
            for entity in our_entities:
                if entity.card_type == CT_HERO:
                    our_hero = entity
                    break

            if our_hero is None:
                return None

            # Extract mana — RESOURCES = current mana crystals (1-10)
            max_mana = our_player.resources
            resources_used = our_player.resources_used
            temp = our_player.temp_resources if hasattr(our_player, 'temp_resources') else 0
            overloaded = our_player.overload_locked if hasattr(our_player, 'overload_locked') else 0
            available = max(0, max_mana - resources_used - overloaded + temp)

            # Extract board minions
            board = []
            for entity in our_entities:
                if entity.zone == ZONE_PLAY and entity.card_type == CT_MINION:
                    keywords = []
                    if entity.taunt: keywords.append('TAUNT')
                    if entity.divine_shield: keywords.append('DIVINE_SHIELD')
                    if entity.charge: keywords.append('CHARGE')
                    if entity.rush: keywords.append('RUSH')
                    if entity.windfury: keywords.append('WINDFURY')
                    if entity.stealth: keywords.append('STEALTH')
                    if entity.poisonous: keywords.append('POISONOUS')
                    if entity.frozen: keywords.append('FROZEN')
                    if entity.reborn: keywords.append('REBORN')

                    board.append(Minion(
                        attack=entity.atk,
                        health=entity.health,
                        max_health=entity.health,
                        cost=entity.cost,
                        has_taunt=entity.taunt,
                        has_stealth=entity.stealth,
                        has_windfury=entity.windfury,
                        has_rush=entity.rush,
                        has_charge=entity.charge,
                        has_poisonous=entity.poisonous,
                        has_lifesteal=False,
                        has_reborn=entity.reborn,
                        has_immune=entity.immune,
                        frozen_until_next_turn=entity.frozen,
                        has_divine_shield=entity.divine_shield,
                        cant_attack=entity.exhausted,
                        name=self._card_name(entity.card_id) or "",
                        can_attack=not entity.exhausted,
                    ))

            # Extract hand cards
            hand = []
            for entity in our_entities:
                if entity.zone == ZONE_HAND:
                    # Map card type
                    if entity.card_type == CT_MINION:
                        ct = "MINION"
                    elif entity.card_type == CT_SPELL:
                        ct = "SPELL"
                    elif entity.card_type == CT_WEAPON:
                        ct = "WEAPON"
                    elif entity.card_type == CT_HERO:
                        ct = "HERO"
                    elif entity.card_type == CT_LOCATION:
                        ct = "LOCATION"
                    elif entity.card_type == CT_HERO_POWER:
                        ct = "HERO_POWER"
                    else:
                        ct = "MINION"

                    hand.append(Card(
                        dbf_id=0,
                        name=self._card_name(entity.card_id) or "",
                        cost=entity.cost,
                        card_type=ct,
                    ))

            # Extract hero state
            hero = HeroState(
                hp=our_hero.health,
                max_hp=our_hero.health,
                armor=our_hero.armor,
                weapon=None,
                hero_class="PRIEST",  # Unknown, but needed
            )

            # Extract mana state
            mana = ManaState(
                max_mana=max_mana,
                available=available,
                overloaded=overloaded,
                overload_next=0,
            )

            # Extract opponent state
            opp_hero = None
            for entity in opp_entities:
                if entity.card_type == CT_HERO:
                    opp_hero = entity
                    break

            opp_board = []
            for entity in opp_entities:
                if entity.zone == ZONE_PLAY and entity.card_type == CT_MINION:
                    opp_board.append(Minion(
                        attack=entity.atk,
                        health=entity.health,
                        max_health=entity.health,
                        cost=entity.cost,
                        has_taunt=entity.taunt,
                        has_stealth=entity.stealth,
                        has_windfury=entity.windfury,
                        has_rush=entity.rush,
                        has_charge=entity.charge,
                        has_poisonous=entity.poisonous,
                        has_lifesteal=False,
                        has_reborn=entity.reborn,
                        has_immune=entity.immune,
                        frozen_until_next_turn=entity.frozen,
                        has_divine_shield=entity.divine_shield,
                        cant_attack=entity.exhausted,
                        name=self._card_name(entity.card_id) or "",
                        can_attack=not entity.exhausted,
                    ))

            # Count deck remaining
            deck_remaining = 0
            for entity in our_entities:
                if entity.zone == ZONE_DECK:
                    deck_remaining += 1

            # Count opponent deck remaining (FIXED: ZONE_DECK only)
            opp_deck_remaining = self.global_tracker.count_opp_deck(opp_entities)

            # Create game state
            game_state = GameState(
                turn_number=self.game_turn,
                hero=hero,
                mana=mana,
                board=board,
                hand=hand,
                deck_remaining=deck_remaining,
                opponent=OpponentState(
                    hero=HeroState(
                        hp=opp_hero.health if opp_hero else 30,
                        max_hp=30,
                        armor=opp_hero.armor if opp_hero else 0,
                        weapon=None,
                        hero_class="UNKNOWN",
                    ),
                    board=opp_board,
                    hand_count=len([e for e in opp_entities if e.zone == ZONE_HAND]),
                    deck_remaining=opp_deck_remaining,
                    opp_known_cards=[
                        {"card_id": kc.card_id, "turn_seen": kc.turn_seen,
                         "source": kc.source.value, "card_type": kc.card_type}
                        for kc in self.global_tracker.state.opp_known_cards
                    ],
                    opp_generated_count=len(self.global_tracker.state.opp_generated_seen),
                    opp_secrets_triggered=[
                        {"card_id": kc.card_id, "turn_seen": kc.turn_seen}
                        for kc in self.global_tracker.state.opp_secrets_triggered
                    ],
                    secrets=list(self.global_tracker.state.opp_secrets),
                ),
            )

            return game_state

        except Exception as e:
            self.log_errors.error(f"构建 GameState 失败: {e}", exc_info=True)
            return None

    def _evaluate_decision(
        self,
        game_state: GameState,
        search_result,
        legal_actions,
        summary,
    ) -> dict:
        """Evaluate decision quality with Chinese explanations.

        Multi-factor evaluation:
        1. Lethal detection (RHEA score ≥ 5000 = lethal found)
        2. Mana efficiency
        3. Board control assessment
        4. Action diversity analysis
        5. RHEA score interpretation
        """
        reasons = []
        positive_reasons = []
        mana_available = summary['mana_available']
        mana_max = summary['mana_max']
        mana_used = summary['mana_used']
        rhea_score = search_result.best_fitness if search_result else 0.0
        opp_hp = summary.get('opp_hero_hp', 30)
        opp_armor = summary.get('opp_hero_armor', 0)
        our_hp = summary.get('hero_hp', 30)
        board_count = summary.get('board_count', 0)
        hand_count = summary.get('hand_count', 0)

        # 1. Lethal detection
        is_lethal = rhea_score >= 5000
        if is_lethal:
            total_atk = sum(m.get('atk', 0) for m in summary.get('board_minions', []))
            reasons.append(f"🔴 致命检测! 场攻={total_atk} vs 对手HP={opp_hp}+{opp_armor}护甲, "
                         f"RHEA找到斩杀方案 (分数={rhea_score:.1f})")

        # 2. Mana efficiency (only evaluate if not lethal)
        if not is_lethal and mana_max > 0:
            mana_efficiency = (mana_max - (mana_max - mana_available)) / mana_max
            spent = mana_max - mana_available
            if mana_available == 0 and spent == mana_max:
                positive_reasons.append(f"法力完美利用: {spent}/{mana_max}")
            elif mana_available > 0 and spent > 0:
                if mana_available <= 1:
                    positive_reasons.append(f"法力利用充分: 用{spent}/{mana_max}, 仅剩{mana_available}")
                elif mana_available > mana_max * 0.5:
                    reasons.append(f"法力剩余较多: {mana_available}/{mana_max} 未使用 "
                                 f"(浪费{mana_available}费)")
                else:
                    positive_reasons.append(f"法力利用合理: 用{spent}/{mana_max}")
            elif spent == 0 and hand_count > 0:
                reasons.append(f"未使用任何法力 ({mana_available}/{mana_max}), "
                             f"手牌有{hand_count}张可用")

        # 3. Board control assessment
        if not is_lethal:
            our_board = summary.get('board_minions', [])
            opp_board_count = summary.get('opp_board_count', 0)

            if board_count == 0 and opp_board_count > 0:
                reasons.append(f"场面劣势: 我方0随从 vs 对方{opp_board_count}随从")
            elif board_count > opp_board_count + 2:
                positive_reasons.append(f"场面优势: {board_count} vs {opp_board_count}随从")
            elif opp_board_count > board_count + 2:
                reasons.append(f"场面落后: {board_count} vs {opp_board_count}随从, 考虑清场")

        # 4. Action diversity
        if legal_actions:
            action_types = set()
            for a in legal_actions:
                action_types.add(a.action_type)

            if len(action_types) <= 2 and hand_count > 3:
                reasons.append(f"可用操作较少 ({len(action_types)}种), "
                             f"但手牌{hand_count}张 — 可能是费用不匹配")
            elif len(action_types) >= 4:
                positive_reasons.append(f"策略选择丰富: {len(action_types)}种操作可选")

        # 5. RHEA score interpretation (non-lethal context)
        if not is_lethal and rhea_score != 0.0:
            if rhea_score > 50:
                positive_reasons.append(f"RHEA评估积极 (分数={rhea_score:.1f})")
            elif rhea_score < -50:
                reasons.append(f"RHEA评估消极 (分数={rhea_score:.1f}), 局势不利")
            elif abs(rhea_score) <= 10:
                positive_reasons.append(f"局势平稳 (RHEA分数={rhea_score:.1f})")

        # 6. Health pressure
        if not is_lethal:
            if our_hp <= 10:
                reasons.append(f"⚠️ 血量危险: HP={our_hp}, 需要优先防守")
            elif opp_hp <= 15 and board_count > 0:
                positive_reasons.append(f"对手血量低 (HP={opp_hp}), 有进攻压力")

        # Determine rating
        has_issues = len(reasons) > 0
        has_positives = len(positive_reasons) > 0

        if is_lethal:
            rating = "🔴 致命"
        elif not has_issues and has_positives:
            rating = "✅ 合理"
        elif has_issues and has_positives:
            rating = "⚠️ 次优"
        elif has_issues and not has_positives:
            if len(reasons) >= 3:
                rating = "❌ 错误"
            else:
                rating = "⚠️ 次优"
        else:
            rating = "✅ 合理"

        return {
            'rating': rating,
            'reasons': reasons + [f"✓ {r}" for r in positive_reasons],
        }

    def _card_name(self, card_id: str) -> str:
        """Get Chinese name for a card_id."""
        if not card_id:
            return "未知"
        return self._card_name_cache.get(card_id, card_id)

    def _save_summary(self):
        """Save game_summary.json with all decisions."""
        ts = time.strftime("%Y%m%d_%H%M%S")
        summary_path = self.log_dir / f"game_summary_{ts}.json"

        summary = {
            "player_name": self.player_name,
            "num_decisions": len(self.decisions),
            "decisions": [{
                'turn_number': d.turn_number,
                'player_name': d.player_name,
                'player_turn': d.player_turn,
                'hero_hp': d.hero_hp,
                'hero_armor': d.hero_armor,
                'mana_available': d.mana_available,
                'mana_max': d.mana_max,
                'board_count': d.board_count,
                'hand_count': d.hand_count,
                'hand_cards': d.hand_cards,
                'board_minions': d.board_minions,
                'opp_hero_hp': d.opp_hero_hp,
                'opp_armor': d.opp_armor,
                'opp_board_count': d.opp_board_count,
                'opp_board_minions': d.opp_board_minions,
                'opp_hand_count': getattr(d, 'opp_hand_count', 0),
                'opp_deck_remaining': getattr(d, 'opp_deck_remaining', 0),
                'opp_known_hand_cards': getattr(d, 'opp_known_hand_cards', []),
                'opp_generated_played': getattr(d, 'opp_generated_played', 0),
                'opp_secrets': getattr(d, 'opp_secrets', []),
                'player_global_stats': getattr(d, 'player_global_stats', ''),
                'legal_actions_count': d.legal_actions_count,
                'action_breakdown': d.action_breakdown,
                'rhea_best_score': d.rhea_best_score,
                'rhea_best_actions': d.rhea_best_actions,
                'rhea_generations': d.rhea_generations,
                'rhea_time_ms': d.rhea_time_ms,
                'decision_quality': d.decision_quality,
                'error': d.error,
            } for d in self.decisions],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        self.log_main.info(f"💾 保存摘要: {summary_path}")
        return summary_path

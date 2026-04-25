"""game_tracker.py — 基于hslog的增量式Power.log解析器

逐行读取Power.log，实时追踪游戏状态变化。
检测游戏开始/结束/回合切换等事件。

特性：
- hslog LogParser 处理协议层
- 内置 EntityCache 直接解析 SHOW_ENTITY / TAG_CHANGE 行，
  补充 hslog EntityTreeExporter 不暴露的 card_id 和 tags
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any
import re
from hslog.parser import LogParser
from hslog.export import EntityTreeExporter
from hearthstone.enums import GameTag, Zone, CardType, Step, State


class _SafeEntityTreeExporter(EntityTreeExporter):
    """安全的实体树导出器，跳过entity为None的包"""

    def handle_full_entity(self, packet):
        if packet.entity is None:
            return None
        return super().handle_full_entity(packet)


class EntityCache:
    """轻量级实体标签缓存，直接从 Power.log 文本行解析。

    解决 hslog EntityTreeExporter 不暴露 card_id / COST / ATK / HEALTH 的问题。
    通过 SHOW_ENTITY 和 TAG_CHANGE 行维护 entity_id → {card_id, tags} 映射。
    """

    def __init__(self):
        # entity_id → {"card_id": str, "tags": {GameTag: int}}
        self._entities: Dict[int, Dict[str, Any]] = {}
        self._re_show = re.compile(
            r"SHOW_ENTITY\s+-\s+Updating\s+Entity=.*?id=(\d+).*?CardID=(\S+)"
        )
        self._re_full = re.compile(
            r"FULL_ENTITY\s+-\s+Creating\s+ID=(\d+)\s+CardID=(\S*)"
        )
        self._re_tag = re.compile(r"tag=(\w+)\s+value=(\S+)")
        self._re_tag_numeric = re.compile(r"tag=(\d+)\s+value=(\S+)")

    def feed_line(self, line: str) -> None:
        """处理一行 Power.log，更新实体缓存。"""
        # SHOW_ENTITY — reveals card_id + tags for a previously hidden entity
        m = self._re_show.search(line)
        if m:
            entity_id = int(m.group(1))
            card_id = m.group(2)
            self._ensure_entity(entity_id)
            self._entities[entity_id]["card_id"] = card_id
            return

        # FULL_ENTITY with non-empty CardID — initial deck/hand cards
        m = self._re_full.search(line)
        if m:
            entity_id = int(m.group(1))
            card_id = m.group(2)
            if card_id:  # Only store if CardID is present
                self._ensure_entity(entity_id)
                self._entities[entity_id]["card_id"] = card_id
            return

        # TAG_CHANGE — update individual tag for entity
        # Lines like: "tag=COST value=3" inside a SHOW_ENTITY/FULL_ENTITY block
        # or "TAG_CHANGE Entity=[... id=5 ...] tag=COST value=3"
        # We only parse indented tag lines (they belong to the current entity block)
        stripped = line.strip()
        if stripped.startswith("tag=") and "value=" in stripped:
            tag_m = self._re_tag.match(stripped)
            if not tag_m:
                tag_m = self._re_tag_numeric.match(stripped)
            if tag_m:
                tag_name = tag_m.group(1)
                value_str = tag_m.group(2)
                # We don't know which entity this belongs to from the line alone
                # This is handled by _current_block_entity tracking in GameTracker
                return

    def feed_tag(self, entity_id: int, tag_name: str, value_str: str) -> None:
        """记录一个实体的标签。由 GameTracker.feed_line 在解析块时调用。"""
        self._ensure_entity(entity_id)

        # 解析标签
        tag_key = self._resolve_tag(tag_name)
        if tag_key is None:
            return

        # 解析值
        try:
            if value_str.isdigit():
                value = int(value_str)
            elif value_str.startswith("-") and value_str[1:].isdigit():
                value = int(value_str)
            else:
                value = value_str
        except (ValueError, IndexError):
            value = value_str

        self._entities[entity_id]["tags"][tag_key] = value

    def get_card_id(self, entity_id: int) -> Optional[str]:
        """获取实体的卡牌ID。"""
        ent = self._entities.get(entity_id)
        if ent is None:
            return None
        return ent.get("card_id")

    def get_tag(self, entity_id: int, tag) -> Any:
        """获取实体的标签值。"""
        ent = self._entities.get(entity_id)
        if ent is None:
            return None
        return ent.get("tags", {}).get(tag)

    def get_tags(self, entity_id: int) -> Dict:
        """获取实体的所有标签。"""
        ent = self._entities.get(entity_id)
        if ent is None:
            return {}
        return ent.get("tags", {})

    def get_entity(self, entity_id: int) -> Optional[Dict]:
        """获取完整的实体数据。"""
        return self._entities.get(entity_id)

    def _ensure_entity(self, entity_id: int) -> None:
        if entity_id not in self._entities:
            self._entities[entity_id] = {"card_id": "", "tags": {}}

    @staticmethod
    def _resolve_tag(tag_name: str):
        """将标签名称或数字解析为 GameTag 枚举。"""
        try:
            return GameTag[tag_name]
        except (KeyError, ValueError):
            pass
        try:
            return GameTag(int(tag_name))
        except (ValueError, TypeError):
            pass
        return None

    def reset(self) -> None:
        """清空缓存（游戏结束时调用）。"""
        self._entities.clear()


class GameTracker:
    """通过增量解析Power.log追踪炉石游戏状态。

    使用方式：通过 feed_line() 逐行喂入日志，通过属性查询当前状态。
    自动检测游戏开始/结束转换。
    """

    def __init__(self, deck_provider=None):
        """Initialize GameTracker.

        Args:
            deck_provider: Optional DeckProvider instance for deck lookup.
                           When provided, enables current_deck property.
        """
        self._parser = LogParser()
        self._game_count = 0
        self._in_game = False
        self._current_game_entities = None  # 已导出的实体树
        self._last_event_type = None
        self._last_turn = 0
        self._fired_turn = -1  # 上一次触发 turn_start 的回合号
        self._last_step = "UNKNOWN"
        self._re_game_turn = re.compile(r"tag=TURN value=(\d+)")
        self._re_game_step = re.compile(r"tag=STEP value=([A-Z_0-9]+)")

        # Timestamp tracking for deck matching
        self._game_start_timestamp: Optional[str] = None  # HH:MM:SS of current game start
        self._re_timestamp = re.compile(r"^\w\s+(\d{2}:\d{2}:\d{2})")

        # Entity cache — directly parses SHOW_ENTITY / TAG_CHANGE lines
        self.entity_cache = EntityCache()

        # Block tracking for tag parsing
        self._current_block_entity_id: Optional[int] = None
        self._re_entity_id = re.compile(r"id=(\d+)")
        self._re_show_entity = re.compile(r"SHOW_ENTITY")
        self._re_full_entity = re.compile(r"FULL_ENTITY")
        # Match indented tag lines like "        tag=COST value=3"
        # or full lines like "D 08:39:22... -         tag=COST value=3"
        self._re_indented_tag = re.compile(r"\s+-\s+tag=(\w+)\s+value=(\S+)")

        # TAG_CHANGE with entity id
        self._re_tag_change = re.compile(
            r"TAG_CHANGE\s+Entity=.*?id=(\d+).*?tag=(\w+)\s+value=(\S+)"
        )

        # Deck provider
        self.deck_provider = deck_provider

    def feed_line(self, line: str) -> Optional[str]:
        """喂入一行Power.log内容，返回事件类型或None。

        Returns:
            "game_start" — 新游戏开始
            "game_end" — 当前游戏结束
            "turn_start" — 新回合开始
            "action" — 游戏动作已处理
            None — 行被忽略/空行
        """
        if not line or not line.strip():
            self._last_event_type = None
            return None

        try:
            self._parser.read_line(line)

            # ── Entity cache parsing (direct line parsing) ──
            self._parse_entity_cache_line(line)

            # ── STEP tracking ──
            step_match = self._re_game_step.search(line)
            if step_match is not None:
                raw_step = step_match.group(1)
                if raw_step.isdigit():
                    try:
                        self._last_step = Step(int(raw_step)).name
                    except Exception:
                        self._last_step = "UNKNOWN"
                else:
                    self._last_step = raw_step

            current_game_count = len(self._parser.games)

            if not self._in_game and current_game_count > self._game_count:
                # 新游戏开始
                self._in_game = True
                self._game_count = current_game_count
                self._last_turn = 0
                self._last_step = "UNKNOWN"
                self._fired_turn = -1
                self.entity_cache.reset()
                # Extract timestamp for deck matching
                ts_m = self._re_timestamp.search(line)
                if ts_m:
                    self._game_start_timestamp = ts_m.group(1)
                else:
                    self._game_start_timestamp = None
                self._last_event_type = "game_start"
                return "game_start"

            # 检测游戏结束
            if self._in_game:
                if "Entity=GameEntity" in line and "tag=STATE value=COMPLETE" in line:
                    self._in_game = False
                    self._last_step = "UNKNOWN"
                    self._last_event_type = "game_end"
                    return "game_end"

                # 跟踪 TURN 编号 (不触发事件，只记录)
                if "Entity=GameEntity" in line and "tag=TURN value=" in line:
                    m = self._re_game_turn.search(line)
                    if m is not None:
                        turn = int(m.group(1))
                        if turn > self._last_turn:
                            self._last_turn = turn

                # 检测决策点: STEP=MAIN_ACTION 时触发
                if (self._last_step == "MAIN_ACTION"
                    and "tag=STEP" in line
                    and "value=MAIN_ACTION" in line
                    and self._fired_turn != self._last_turn):
                    self._fired_turn = self._last_turn
                    self._last_event_type = "turn_start"
                    return "turn_start"

            self._last_event_type = "action"
            return "action"

        except Exception:
            self._last_event_type = None
            return None

    def _parse_entity_cache_line(self, line: str) -> None:
        """解析 SHOW_ENTITY / FULL_ENTITY / TAG_CHANGE 行，更新 entity_cache 和 GlobalTracker。"""
        stripped = line.strip()

        # SHOW_ENTITY line — start of a new block
        if self._re_show_entity.search(stripped):
            m = self._re_entity_id.search(stripped)
            if m:
                eid = int(m.group(1))
                self._current_block_entity_id = eid
                # Extract CardID
                card_m = re.search(r"CardID=(\S+)", stripped)
                if card_m:
                    self.entity_cache._ensure_entity(eid)
                    self.entity_cache._entities[eid]["card_id"] = card_m.group(1)
            return

        # FULL_ENTITY line — start of a new block
        if self._re_full_entity.search(stripped):
            m = self._re_entity_id.search(stripped)
            if m:
                eid = int(m.group(1))
                self._current_block_entity_id = eid
                card_m = re.search(r"CardID=(\S*)", stripped)
                if card_m and card_m.group(1):
                    self.entity_cache._ensure_entity(eid)
                    self.entity_cache._entities[eid]["card_id"] = card_m.group(1)
            return

        # Indented tag line (belongs to current SHOW_ENTITY/FULL_ENTITY block)
        # Skip if it's a TAG_CHANGE line (those have their own handler)
        if self._current_block_entity_id is not None:
            tag_m = self._re_indented_tag.search(stripped)
            if tag_m and "TAG_CHANGE" not in stripped and "Entity=" not in stripped.split("tag=")[0]:
                tag_name = tag_m.group(1)
                value_str = tag_m.group(2)
                self.entity_cache.feed_tag(self._current_block_entity_id, tag_name, value_str)
                return

        # TAG_CHANGE with entity id in line
        tc_m = self._re_tag_change.search(stripped)
        if tc_m:
            eid = int(tc_m.group(1))
            tag_name = tc_m.group(2)
            value_str = tc_m.group(3)
            self.entity_cache.feed_tag(eid, tag_name, value_str)
            return

        # Non-indented non-tag line ends the current block
        if not stripped.startswith("tag=") and not stripped.startswith("D ") and stripped:
            # Check if it's a new block type
            if any(kw in stripped for kw in ("BLOCK_START", "BLOCK_END",
                                              "CREATE_GAME", "Player ",
                                              "GameEntity")):
                self._current_block_entity_id = None

    def feed_lines(self, lines: List[str]) -> List[str]:
        """批量喂入多行，返回事件类型列表"""
        events = []
        for line in lines:
            event = self.feed_line(line)
            if event is not None:
                events.append(event)
        return events

    def load_file(self, path: str) -> List[str]:
        """加载并解析完整的Power.log文件，返回事件类型列表"""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            return self.feed_lines([line.rstrip("\n") for line in lines])
        except Exception as e:
            return []

    @property
    def in_game(self) -> bool:
        """当前是否在追踪一场活跃的游戏"""
        return self._in_game

    @property
    def game_count(self) -> int:
        """已解析的游戏总数"""
        return self._game_count

    @property
    def current_game(self):
        """当前游戏的hslog Game对象，未在游戏中返回None"""
        if not self._in_game or not self._parser.games:
            return None
        return self._parser.games[-1]

    def export_entities(self):
        """导出当前游戏的实体树，返回包含完整实体访问的游戏对象"""
        if not self._parser.games:
            return None

        packet_tree = self._parser.games[-1]
        exporter = _SafeEntityTreeExporter(packet_tree)
        exporter.export()
        self._current_game_entities = exporter.game

        return self._current_game_entities

    def get_current_turn(self) -> int:
        """获取当前回合数"""
        return self._last_turn

    def get_step(self) -> str:
        """获取当前游戏阶段（BEGIN_MULLIGAN, MAIN_READY, MAIN_ACTION等）"""
        if not self._in_game:
            return "NOT_STARTED"
        return self._last_step or "UNKNOWN"

    @property
    def game_start_timestamp(self) -> Optional[str]:
        """当前游戏的开始时间戳 (HH:MM:SS)，未在游戏中返回None"""
        return self._game_start_timestamp

    @property
    def current_deck(self):
        """当前游戏的牌组信息 (DeckInfo)，需要 deck_provider 且匹配成功。"""
        if self.deck_provider is None or self._game_start_timestamp is None:
            return None
        return self.deck_provider.get_deck_for_game(self._game_start_timestamp)

    @property
    def deck_cards(self):
        """当前游戏牌组的展开卡牌列表 (List[Card])，每张牌按数量展开。"""
        if self.deck_provider is None or self._game_start_timestamp is None:
            return []
        return self.deck_provider.get_deck_cards(self._game_start_timestamp)



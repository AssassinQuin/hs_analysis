"""game_tracker.py — 基于hslog的增量式Power.log解析器

逐行读取Power.log，实时追踪游戏状态变化。
检测游戏开始/结束/回合切换等事件。

与 power_parser.py 的区别：
- 本模块：逐行增量解析，用于实时追踪（DecisionLoop）
- power_parser.py：一次性加载完整日志，用于离线分析（搜索树初始状态）
"""

from __future__ import annotations

from typing import Optional, List
from hslog.parser import LogParser
from hslog.export import EntityTreeExporter
from hearthstone.enums import GameTag, Zone, CardType, Step, State


class _SafeEntityTreeExporter(EntityTreeExporter):
    """安全的实体树导出器，跳过entity为None的包"""

    def handle_full_entity(self, packet):
        if packet.entity is None:
            return None
        return super().handle_full_entity(packet)


class GameTracker:
    """通过增量解析Power.log追踪炉石游戏状态。

    使用方式：通过 feed_line() 逐行喂入日志，通过属性查询当前状态。
    自动检测游戏开始/结束转换。
    """

    def __init__(self):
        self._parser = LogParser()
        self._game_count = 0
        self._in_game = False
        self._current_game_entities = None  # 已导出的实体树
        self._last_event_type = None

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

            current_game_count = len(self._parser.games)

            if not self._in_game and current_game_count > self._game_count:
                # 新游戏开始
                self._in_game = True
                self._game_count = current_game_count
                self._last_event_type = "game_start"
                return "game_start"

            # 检测游戏结束
            if self._in_game:
                if self._parser.games and self._parser.games[-1].tags.get(GameTag.STATE) == State.COMPLETE:
                    self._in_game = False
                    self._last_event_type = "game_end"
                    return "game_end"

                # 检测新回合
                if self._parser.games and self._parser.games[-1].tags.get(GameTag.STEP) != self._current_step():
                    new_step = self._current_step()
                    if new_step != self._current_step():
                        self._last_event_type = "turn_start"
                        return "turn_start"

            self._last_event_type = "action"
            return "action"

        except Exception:
            self._last_event_type = None
            return None

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

    @property
    def current_player(self):
        """第一个（友方）玩家的hslog Player对象"""
        game = self.current_game
        if game is None or not game.players:
            return None
        return game.players[0]

    @property
    def current_opponent(self):
        """对手的hslog Player对象"""
        game = self.current_game
        if game is None or len(game.players) < 2:
            return None
        return game.players[1]

    def export_entities(self):
        """导出当前游戏的实体树，返回包含完整实体访问的游戏对象"""
        game = self.current_game
        if game is None:
            return None

        packet_tree = self._parser.games[0] if self._parser.games else None
        if packet_tree is None:
            return None
        exporter = _SafeEntityTreeExporter(packet_tree)
        exporter.export()
        self._current_game_entities = exporter.game

        return self._current_game_entities

    def get_current_turn(self) -> int:
        """获取当前回合数"""
        game = self.current_game
        if game is None:
            return 0
        return game.tags.get(GameTag.TURN, 0)

    def get_step(self) -> str:
        """获取当前游戏阶段（BEGIN_MULLIGAN, MAIN_READY, MAIN_ACTION等）"""
        game = self.current_game
        if game is None:
            return "NOT_STARTED"
        step = game.tags.get(GameTag.STEP)
        return Step(step).name if step is not None else "UNKNOWN"

    def _current_step(self) -> Optional[int]:
        """获取当前STEP标签的原始数值"""
        game = self.current_game
        if game is None:
            return None
        return game.tags.get(GameTag.STEP)

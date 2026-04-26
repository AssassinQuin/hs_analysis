"""power_parser.py — 批量 Power.log 解析器

使用 hslog 库解析完整的 Power.log 文件，提取游戏状态。
主要用于搜索树（RHEA）的初始状态构建和离线回放。

与 game_tracker.py 的区别：
- 本模块：一次性加载完整日志文件，用于离线分析
- game_tracker.py：逐行增量解析，用于实时追踪

注意：_SafeEntityTreeExporter 在本模块和 game_tracker.py 中有重复定义，
后续应合并到公共工具模块中。
"""

import os
import logging
from hslog.parser import LogParser
from hslog.export import EntityTreeExporter
from hearthstone.enums import GameTag, Zone, CardType

log = logging.getLogger(__name__)


class _SafeEntityTreeExporter(EntityTreeExporter):
    """安全的实体树导出器，跳过 entity 为 None 的包"""

    def handle_full_entity(self, packet):
        if packet.entity is None:
            return None
        return super().handle_full_entity(packet)


def parse_power_log(file_path):
    """解析 Power.log 文件，返回第一场游戏的导出实体树。

    Args:
        file_path: Power.log 文件的完整路径

    Returns:
        导出的游戏对象（包含完整实体访问），无游戏或文件不存在时返回 None
    """
    if not os.path.exists(file_path):
        return None

    parser = LogParser()

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                parser.read_line(line)
            except Exception:
                log.debug("parse_power_log: failed to parse one line", exc_info=True)

    if not parser.games:
        return None

    packet_tree = parser.games[0]
    exporter = _SafeEntityTreeExporter(packet_tree)
    exporter.export()

    return exporter.game


def extract_game_state(game, player_index=0):
    """从 hslog 导出的游戏对象中提取结构化游戏状态。

    提取内容包括：英雄状态、法力状态、场上随从列表、手牌卡牌ID列表。

    Args:
        game: hslog 导出的游戏对象
        player_index: 玩家索引（0=先手, 1=后手）

    Returns:
        (hero_state, mana_state, minions, hand) 四元组
    """
    from analysis.engine.state import (
        GameState, HeroState, ManaState, Minion, OpponentState
    )

    player = game.players[player_index]
    entities = list(player.entities)

    # 提取英雄实体（场上 + 英雄类型）
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

    # 提取法力状态
    mana_state = ManaState(
        available=(
            player.tags.get(GameTag.RESOURCES, 0)
            - player.tags.get(GameTag.RESOURCES_USED, 0)
        ),
        overloaded=player.tags.get(GameTag.OVERLOAD_LOCKED, 0),
        max_mana=player.tags.get(GameTag.RESOURCES, 0),
    )

    # 提取场上随从
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

    # 提取手牌（仅卡牌ID）
    hand_entities = [
        e for e in entities
        if e.tags.get(GameTag.ZONE) == Zone.HAND
    ]
    hand = [e.card_id or "" for e in hand_entities]

    return hero_state, mana_state, minions, hand

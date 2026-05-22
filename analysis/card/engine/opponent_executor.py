"""engine/opponent_executor.py — v2 SpellDesc 对手能力执行器。

将 card_abilities_v2.json 的 SpellDesc 递归树应用于对手上下文。
friendly = 对手侧, enemy = 我方侧。

提取自 simulation.py，被其对***手模拟函数调用。
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

from analysis.card.engine.state import Minion
from analysis.card.models.card import Card


# ═══════════════════════════════════════════════════════════════════
# 对手抽牌
# ═══════════════════════════════════════════════════════════════════


def opponent_draw_card(state: "GameState") -> "GameState":
    """对手模拟回合中抽一张牌。"""
    if state.opponent.deck_remaining <= 0:
        # Simplified fatigue
        state.opponent.hero.hp -= max(1, state.turn_number // 5)
    else:
        state.opponent.deck_remaining -= 1
        if len(state.opponent.hand) < 10:
            state.opponent.hand.append(Card(
                dbf_id=-1,
                name="Opponent Draw",
                cost=0,
                card_type="SPELL",
            ))
    return state


# ═══════════════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════════════


def _resolve_value(desc) -> int:
    """从 SpellDesc 解析数值（支持 int / {"base": N, ...} 格式）。"""
    v = desc.value
    if v is None:
        return 0
    if isinstance(v, dict):
        return int(v.get('base', 0))
    return int(v)


def _get_targets(target_str: str, s: "GameState", source=None):
    """根据目标选择器返回 (targets_list)。

    opponent 上下文映射:
      friendly = 对手侧 (s.opponent.hero / s.opponent.board)
      enemy    = 我方侧 (s.hero / s.board)
    """
    t = (target_str or '').upper()

    if t in ('ALL_ENEMY_CHARACTERS', 'ENEMY_CHARACTERS', 'ALL_ENEMY'):
        targets = []
        if s.hero.hp > 0:
            targets.append(s.hero)
        targets.extend(s.board[:])
        return targets
    if t in ('ALL_ENEMY_MINIONS', 'ENEMY_MINIONS'):
        return list(s.board)
    if t == 'RANDOM_ENEMY_MINION':
        return [random.choice(s.board)] if s.board else []
    if t in ('RANDOM_ENEMY_CHARACTER', 'RANDOM_ENEMY'):
        pool = []
        if s.hero.hp > 0:
            pool.append(s.hero)
        pool.extend(s.board)
        return [random.choice(pool)] if pool else []

    if t in ('ALL_FRIENDLY_CHARACTERS', 'FRIENDLY_CHARACTERS', 'ALL_FRIENDLY'):
        targets = []
        if s.opponent.hero.hp > 0:
            targets.append(s.opponent.hero)
        targets.extend(s.opponent.board[:])
        return targets
    if t in ('ALL_FRIENDLY_MINIONS', 'FRIENDLY_MINIONS'):
        return list(s.opponent.board)
    if t == 'SELF':
        return [source] if source is not None else []

    if t in ('ALL_CHARACTERS', 'ALL'):
        targets = []
        if s.hero.hp > 0:
            targets.append(s.hero)
        targets.extend(s.board[:])
        if s.opponent.hero.hp > 0:
            targets.append(s.opponent.hero)
        targets.extend(s.opponent.board[:])
        return targets
    if t in ('ALL_MINIONS',):
        return list(s.board) + list(s.opponent.board)

    # TARGET / 默认 → 对我方英雄造成伤害
    return [s.hero]


def _apply_damage(target, damage: int) -> None:
    """对 HeroState 或 Minion 施加伤害。"""
    if hasattr(target, 'hp'):  # HeroState
        absorbed = min(getattr(target, 'armor', 0), damage)
        target.armor -= absorbed
        target.hp -= (damage - absorbed)
    elif hasattr(target, 'health'):  # Minion
        target.health -= damage


# ═══════════════════════════════════════════════════════════════════
# SpellDesc 递归执行器
# ═══════════════════════════════════════════════════════════════════


def opponent_execute_spell_desc(
    desc, s: "GameState", source=None
) -> "GameState":
    """递归执行 SpellDesc，效果应用于对手上下文。

    修改 s 就地，同时返回 s 以支持链式调用。
    """
    if desc is None:
        return s

    sc = desc.spell_class

    # ── MetaSpell: 递归执行子法术 ──
    if sc == 'MetaSpell':
        for sub in (desc.spells or []):
            opponent_execute_spell_desc(sub, s, source)
        return s

    # ── DamageSpell ──
    if sc == 'DamageSpell':
        dmg = _resolve_value(desc)
        if dmg <= 0:
            return s
        for t in _get_targets(desc.target or '', s, source):
            _apply_damage(t, dmg)
        return s

    # ── BuffSpell ──
    if sc == 'BuffSpell':
        atk = desc.attack_bonus or 0
        hp = desc.health_bonus or 0
        if atk == 0 and hp == 0:
            return s
        for t in _get_targets(desc.target or 'SELF', s, source):
            if hasattr(t, 'attack') and hasattr(t, 'health') and hasattr(t, 'max_health'):
                t.attack += atk
                t.health += hp
                t.max_health += hp
        return s

    # ── SummonSpell ──
    if sc == 'SummonSpell':
        if len(s.opponent.board) >= 7:
            return s
        card_id = getattr(desc, 'card_id', None) or None
        if card_id:
            from analysis.card.data.card_data import get_db
            card_data = get_db().get_card(card_id)
            if card_data:
                new_m = Minion(
                    name=card_data.get("name", "Token"),
                    attack=card_data.get("attack", 1),
                    health=card_data.get("health", 1),
                    max_health=card_data.get("health", 1),
                    owner="enemy",
                    can_attack=False,
                )
                s.opponent.board.append(new_m)
                return s
        # fallback: generic 1/1 token
        token_names = ("", "Token", "Summoned")
        new_m = Minion(
            name=getattr(desc, 'name', random.choice(token_names)),
            attack=desc.attack_bonus or 1,
            health=desc.health_bonus or 1,
            max_health=desc.health_bonus or 1,
            owner="enemy",
            can_attack=False,
        )
        s.opponent.board.append(new_m)
        return s

    # ── DiscoverSpell ──
    if sc == 'DiscoverSpell':
        if len(s.opponent.hand) < 10:
            # 使用与友好侧相同的池解析，从真实卡牌中随机选一张
            from analysis.card.spells.effects import DiscoverSpell as FriendlyDiscover
            pool = getattr(desc, 'pool', None) or ""
            card_id = getattr(desc, 'card_id', None) or ""
            card_data = None
            if card_id:
                from analysis.card.data.card_data import get_db
                card_data = get_db().get_card(card_id)
            elif pool:
                candidates = FriendlyDiscover._resolve_pool(pool, s)
                if candidates:
                    card_data = random.choice(candidates)
            if card_data:
                s.opponent.hand.append(Card.from_hsdb_dict(card_data))
            else:
                # 保底：1费中立白板
                s.opponent.hand.append(Card(
                    dbf_id=-1,
                    name="Discovered",
                    cost=1,
                    card_type="MINION",
                    attack=1,
                    health=1,
                ))
        return s

    # ── TakeControlSpell ──
    if sc == 'TakeControlSpell':
        if not s.board:
            return s
        # 解析 target：如果是 RANDOM_ENEMY_MINION 则随机，否则默认取第一个
        t = (getattr(desc, 'target', None) or '').upper()
        if t == 'RANDOM_ENEMY_MINION':
            targets = [random.choice(s.board)]
        elif t in ('ENEMY_MINIONS', 'ALL_ENEMY_MINIONS'):
            targets = list(s.board)
        elif t == 'TARGET':
            # TARGET 在对手上下文中取一个随机敌方随从
            targets = [random.choice(s.board)]
        else:
            # 默认行为：选最高攻击
            targets = [max(s.board, key=lambda m: m.attack)]
        for target in targets:
            if target in s.board:
                s.board.remove(target)
                target.owner = "enemy"
                target.can_attack = False
                if len(s.opponent.board) < 7:
                    s.opponent.board.append(target)
        return s

    # ── AddToHandSpell ──
    if sc == 'AddToHandSpell':
        if len(s.opponent.hand) >= 10:
            return s
        if source is not None and hasattr(source, 'copy'):
            src_copy = source.copy()
            if hasattr(src_copy, 'cost') and hasattr(src_copy, 'name'):
                s.opponent.hand.append(src_copy)
                return s
        s.opponent.hand.append(Card(
            dbf_id=-random.randint(10000, 99999),
            name="Copy",
            cost=0,
            card_type="SPELL",
        ))
        return s

    # ── DrawSpell ──
    if sc in ('DrawSpell',):
        count = desc.count or _resolve_value(desc)
        if count <= 0:
            count = 1
        for _ in range(count):
            opponent_draw_card(s)
        return s

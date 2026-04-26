"""
游戏状态容器 — 统一模拟引擎的数据层。
从 analysis/search/game_state.py 迁移而来。
Phase 1 新增：graveyard, cards_drawn_this_turn, spells_cast_this_turn
"""

from __future__ import annotations

import copy
import dataclasses
import logging
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

from analysis.abilities.keywords import KeywordSet

if TYPE_CHECKING:
    from analysis.search.mechanics_state import MechanicsState
    from analysis.search.zone_manager import ZoneManager

log = logging.getLogger(__name__)


@dataclass
class Weapon:
    """已装备的武器"""

    attack: int = 0
    health: int = 0  # 耐久度
    name: str = ""


@dataclass
class Minion:
    """场上的随从"""

    dbf_id: int = 0
    name: str = ""
    attack: int = 0
    health: int = 0
    max_health: int = 0
    cost: int = 0
    can_attack: bool = False
    has_divine_shield: bool = False
    has_taunt: bool = False
    has_stealth: bool = False
    has_windfury: bool = False
    has_rush: bool = False
    has_charge: bool = False
    has_poisonous: bool = False
    has_lifesteal: bool = False  # 吸血：造成的伤害恢复英雄生命
    has_reborn: bool = False  # 复生：死亡时以1/1复活
    has_immune: bool = False  # 免疫：防止所有伤害
    cant_attack: bool = False  # 不能攻击（如看守者）
    is_dormant: bool = False  # 休眠：苏醒前不能攻击
    dormant_turns_remaining: int = 0  # 休眠随从剩余苏醒回合数
    has_magnetic: bool = False  # 磁力：附着到友方机械
    has_invoke: bool = False  # 祈求：祈求迦拉克隆机制
    has_corrupt: bool = False  # 堕落：打出更高费用卡牌时升级
    has_spellburst: bool = False  # 法术迸发：施放法术时触发
    is_outcast: bool = False  # 流放：从最左/最右打出时的额外效果
    race: str = ""  # 随从种族（野兽、恶魔、机械、龙等）
    spell_school: str = ""  # 法术学派（用于法术相关交互）
    spell_power: int = 0  # 法术伤害+N
    has_attacked_once: bool = False  # 风怒第一次攻击追踪
    frozen_until_next_turn: bool = False  # 冰冻效果
    has_ward: bool = False  # 护盾（可被攻击次数+1）
    has_mega_windfury: bool = False  # 超级风怒（可攻击4次）
    card_id: str = ""
    keywords: KeywordSet = field(default_factory=KeywordSet)
    turn_played: int = 0
    enchantments: list = field(default_factory=list)
    owner: str = "friendly"  # "friendly" 或 "enemy"
    card_ref: object = None  # 可选：引用源 Card 对象
    abilities: list = field(default_factory=list)

    @classmethod
    def from_card(cls, card, owner: str = "friendly", turn_played: int = 0) -> "Minion":
        """从静态卡牌定义创建场上就绪的随从"""
        mechanics = set(getattr(card, "mechanics", []) or [])
        return cls(
            dbf_id=getattr(card, "dbf_id", 0),
            name=getattr(card, "name", ""),
            attack=getattr(card, "attack", 0),
            health=getattr(card, "health", 0),
            max_health=getattr(card, "health", 0),
            cost=getattr(card, "cost", 0),
            race=getattr(card, "race", ""),
            spell_school=getattr(card, "spell_school", ""),
            card_id=getattr(card, "card_id", "") if hasattr(card, "card_id") else "",
            can_attack="CHARGE" in mechanics,
            has_charge="CHARGE" in mechanics,
            has_rush="RUSH" in mechanics,
            has_taunt="TAUNT" in mechanics,
            has_divine_shield="DIVINE_SHIELD" in mechanics,
            has_windfury="WINDFURY" in mechanics,
            has_stealth="STEALTH" in mechanics,
            has_poisonous="POISONOUS" in mechanics,
            has_lifesteal="LIFESTEAL" in mechanics,
            has_reborn="REBORN" in mechanics,
            has_immune="IMMUNE" in mechanics,
            cant_attack="CANT_ATTACK" in mechanics,
            owner=owner,
            turn_played=turn_played,
            card_ref=card,
            abilities=getattr(card, 'abilities', []),
        )

    def copy(self) -> "Minion":
        """浅拷贝随从（enchantments 列表浅拷贝，其余字段直接复制）"""
        new = dataclasses.replace(self, enchantments=list(self.enchantments))
        # Preserve dynamic attributes not in dataclass fields
        # (e.g. trigger_type, trigger_effect, english_text injected by token summon)
        for attr in ('trigger_type', 'trigger_effect', 'english_text', 'abilities'):
            val = getattr(self, attr, None)
            if val is not None:
                setattr(new, attr, val)
        return new

    @property
    def is_friendly(self) -> bool:
        return self.owner == "friendly"

    @property
    def is_enemy(self) -> bool:
        return self.owner == "enemy"

    @property
    def can_attack_now(self) -> bool:
        """当前是否可以攻击（综合考量风怒、冻结、休眠等）"""
        if not self.can_attack or self.cant_attack or self.is_dormant:
            return False
        if self.frozen_until_next_turn:
            return False
        if self.has_windfury:
            return not self.has_attacked_once or self.attack > 0
        return not self.has_attacked_once

    @property
    def is_taunted(self) -> bool:
        return self.has_taunt

    @property
    def total_stats(self) -> int:
        return self.attack + self.health


@dataclass
class HeroState:
    """英雄 + 武器状态"""

    hp: int = 30
    max_hp: int = 30
    armor: int = 0
    hero_class: str = ""
    weapon: Optional[Weapon] = None
    hero_power_used: bool = False
    imbue_level: int = 0  # 灌注等级
    is_immune: bool = False
    hero_power_cost: int = 2
    hero_power_damage: int = 0
    is_hero_card: bool = False  # 是否已替换为英雄牌

    def copy(self) -> "HeroState":
        """拷贝英雄状态，含武器深拷贝"""
        weapon = dataclasses.replace(self.weapon) if self.weapon is not None else None
        return dataclasses.replace(self, weapon=weapon)


@dataclass
class ManaModifier:
    """法力费用修正器（如'下个法术-2'）"""
    modifier_type: str
    value: int
    scope: str  # "next_spell" / "next_minion" / "this_turn"
    used: bool = False


@dataclass
class ManaState:
    """法力可用状态"""

    available: int = 0
    overloaded: int = 0  # 本回合被锁的法力
    max_mana: int = 0
    overload_next: int = 0  # 下回合将被锁的法力
    max_mana_cap: int = 10
    modifiers: List[ManaModifier] = field(default_factory=list)

    def copy(self) -> "ManaState":
        """拷贝法力状态，含修饰器列表深拷贝"""
        return dataclasses.replace(
            self,
            modifiers=[dataclasses.replace(mod) for mod in self.modifiers],
        )

    def effective_cost(self, card) -> int:
        """计算卡牌经过修正器后的实际费用"""
        from analysis.models.card import Card

        base = card.cost if isinstance(card, Card) else int(card)
        card_type = (
            getattr(card, "card_type", "").upper() if isinstance(card, Card) else ""
        )
        for mod in self.modifiers:
            if mod.used:
                continue
            if mod.scope == "next_spell" and card_type == "SPELL":
                base = max(0, base - mod.value)
            elif mod.scope == "next_minion" and card_type == "MINION":
                base = max(0, base - mod.value)
            elif mod.scope == "this_turn":
                base = max(0, base - mod.value)
            elif mod.scope == "next_combo_card":
                # 狐人老千等：下一张连击牌减费
                mechanics = getattr(card, "mechanics", []) or []
                if "COMBO" in mechanics:
                    base = max(0, base - mod.value)
            elif mod.scope == "first_dragon":
                # 龙群先锋等效果：本回合第一张龙牌费用变为 N
                # 检查卡牌种族是否为龙族
                race = getattr(card, "race", "").upper() if isinstance(card, Card) else ""
                if race == "DRAGON":
                    # 费用直接设为 mod.value（而非减去），因为效果是"变为1"
                    base = mod.value
        return base

    def consume_modifiers(self, card) -> None:
        """消耗与该卡牌匹配的费用修正器"""
        from analysis.models.card import Card

        card_type = (
            getattr(card, "card_type", "").upper() if isinstance(card, Card) else ""
        )
        race = (
            getattr(card, "race", "").upper() if isinstance(card, Card) else ""
        )
        for mod in self.modifiers:
            if mod.used:
                continue
            if mod.scope == "next_spell" and card_type == "SPELL":
                mod.used = True
                return
            if mod.scope == "next_minion" and card_type == "MINION":
                mod.used = True
                return
            if mod.scope == "this_turn":
                mod.used = True
                return
            if mod.scope == "first_dragon" and race == "DRAGON":
                mod.used = True
                return
            mechanics = getattr(card, "mechanics", []) or []
            if mod.scope == "next_combo_card" and "COMBO" in mechanics:
                mod.used = True
                return

    def add_modifier(self, modifier_type: str, value: int, scope: str) -> None:
        """添加一个法力费用修正器"""
        self.modifiers.append(
            ManaModifier(
                modifier_type=modifier_type,
                value=value,
                scope=scope,
            )
        )


@dataclass
class OpponentState:
    """对手可见/推断状态"""

    hero: HeroState = field(default_factory=HeroState)
    board: List[Minion] = field(default_factory=list)
    hand: list = field(default_factory=list)  # 推断的对手手牌（贝叶斯采样填充）
    hand_count: int = 0
    secrets: list = field(default_factory=list)
    deck_remaining: int = 15
    locked_deck_id: Optional[int] = None  # 贝叶斯锁定的卡组ID
    deck_confidence: float = 0.0
    opp_known_cards: list = field(default_factory=list)  # 已知的对手卡牌列表
    opp_generated_count: int = 0  # 对手已打出的衍生牌数量
    opp_secrets_triggered: list = field(default_factory=list)  # 对手已触发的奥秘

    # ---- 对手累计机制 (from GlobalTracker) ----
    opp_corpses: int = 0  # 对手残骸资源
    opp_herald_count: int = 0  # 对手兆示计数
    opp_quests: list = field(default_factory=list)  # 对手活跃任务
    opp_shuffled_into_deck: list = field(default_factory=list)  # 洗入对手牌库的已知牌
    opp_corrupted_cards: list = field(default_factory=list)  # 对手已腐蚀升级的牌
    opp_weapon_card_id: str = ""  # 对手当前武器card_id
    opp_cost_modifiers: list = field(default_factory=list)  # 对手费用修正 [(modifier_type, value, scope), ...]
    opp_last_played_minion: dict = field(default_factory=dict)  # {"name":str, "attack":int, "health":int, "card_id":str} — 对手最后打出的随从

    def copy(self) -> "OpponentState":
        """拷贝对手状态，含所有可变容器和嵌套英雄"""
        return dataclasses.replace(
            self,
            hero=self.hero.copy(),
            board=[m.copy() for m in self.board],
            hand=list(self.hand),
            secrets=list(self.secrets),
            opp_known_cards=list(self.opp_known_cards),
            opp_secrets_triggered=list(self.opp_secrets_triggered),
            opp_quests=list(self.opp_quests),
            opp_shuffled_into_deck=list(self.opp_shuffled_into_deck),
            opp_corrupted_cards=list(self.opp_corrupted_cards),
            opp_cost_modifiers=list(self.opp_cost_modifiers),
            opp_last_played_minion=dict(self.opp_last_played_minion),
        )


@dataclass
class GameState:
    """AI决策用的完整游戏状态

    支持 deep-copy 用于搜索树分支。
    Phase 1 新增字段：graveyard, cards_drawn_this_turn, spells_cast_this_turn
    """

    hero: HeroState = field(default_factory=HeroState)
    mana: ManaState = field(default_factory=ManaState)
    board: List[Minion] = field(default_factory=list)
    locations: list = field(default_factory=list)  # 地点列表
    hand: list = field(default_factory=list)  # 手牌（Card 列表）
    deck_list: Optional[List] = (
        None  # 牌库剩余卡牌（用于抽牌概率计算）
    )
    deck_remaining: int = 15
    opponent: OpponentState = field(default_factory=OpponentState)
    turn_number: int = 1
    our_playstyle: str = "unknown"
    opp_playstyle: str = "unknown"
    cards_played_this_turn: list = field(default_factory=list)
    fatigue_damage: int = 0
    herald_count: int = 0  # 兆示机制计数器
    last_turn_races: set = field(default_factory=set)  # 延系：上回合打出的种族
    last_turn_schools: set = field(
        default_factory=set
    )  # 延系：上回合打出的法术学派
    active_quests: list = field(default_factory=list)  # 活跃任务追踪
    corpses: int = 0  # DK残骸资源
    kindred_double_next: bool = False  # 延系：下次延系触发两次
    last_played_card: dict | None = (
        None  # 上次打出的卡牌（用于符文/条件检查）
    )
    _defer_deaths: bool = (
        False  # 阶段死亡延迟：推迟死亡结算到阶段结束
    )
    _pending_dead_friendly: list = field(
        default_factory=list
    )  # 延迟死亡的友方随从
    _pending_dead_enemy: list = field(
        default_factory=list
    )  # 延迟死亡的敌方随从
    _mechanics: Optional[object] = (
        None  # MechanicsState（延迟初始化，Phase 2集成）
    )
    _zones: Optional[object] = (
        None  # tuple[ZoneManager, ZoneManager]（延迟初始化，Phase 3集成）
    )

    # ── Phase 1 新增字段 ──
    graveyard: List = field(default_factory=list)                    # 已死亡随从（复活用）
    cards_drawn_this_turn: int = 0          # 本回合抽牌数
    spells_cast_this_turn: int = 0          # 本回合施法数

    # ------------------------------------------------------------------
    # ZoneManager 访问（Phase 3集成）
    # ------------------------------------------------------------------

    @property
    def zones(self):
        """(友方ZoneManager, 敌方ZoneManager) 元组

        首次访问时从传统列表字段延迟初始化。
        """
        if self._zones is None:
            from analysis.search.zone_manager import ZoneManager
            friendly = ZoneManager(
                hand=list(self.hand),
                board=list(self.board) + list(self.locations),
                deck=list(self.deck_list) if self.deck_list else [],
                secrets=[],
            )
            enemy = ZoneManager(
                board=list(self.opponent.board),
                secrets=list(self.opponent.secrets),
            )
            self._zones = (friendly, enemy)
        return self._zones

    @zones.setter
    def zones(self, value):
        self._zones = value

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    # Pre-computed fields list (avoid repeated dataclasses.fields() reflection)
    _FIELDS = None

    def copy(self) -> "GameState":
        """Fast copy: cached fields + minimal allocation.

        Hot path optimization:
        - Caches dataclasses.fields() to avoid per-call reflection
        - Skips isinstance() checks for known field types
        - Nested dataclasses use their own .copy() methods

        IMPORTANT: Card objects in `hand` and `deck_list` are shared by
        reference (NOT deep-copied) for performance.  Card objects MUST be
        treated as immutable — simulation code must never mutate a Card
        instance in-place.  If mutation is needed, replace the Card in the
        list with a new instance.
        """
        # Lazy-init fields cache
        if GameState._FIELDS is None:
            GameState._FIELDS = dataclasses.fields(self)

        kwargs: dict = {}
        for f in GameState._FIELDS:
            name = f.name
            val = getattr(self, name)

            # 懒初始化缓存 → 重置
            if name in ("_mechanics", "_zones"):
                kwargs[name] = None
                continue

            # 死亡延迟 → 重置为默认值
            if name == "_defer_deaths":
                kwargs[name] = False
                continue
            if name == "_pending_dead_friendly":
                kwargs[name] = []
                continue
            if name == "_pending_dead_enemy":
                kwargs[name] = []
                continue

            # None 或不可变标量
            if val is None or isinstance(val, (int, float, str, bool)):
                kwargs[name] = val
                continue

            # KeywordSet (frozenset) — 不可变
            if isinstance(val, KeywordSet):
                kwargs[name] = val
                continue

            # 嵌套 dataclass: HeroState, ManaState, OpponentState
            if dataclasses.is_dataclass(val) and not isinstance(val, type):
                kwargs[name] = val.copy() if hasattr(val, 'copy') else dataclasses.replace(val)
                continue

            # 列表 / 字典 / 集合
            if isinstance(val, list):
                # 含 dataclass 元素时递归 copy
                if val and dataclasses.is_dataclass(val[0]):
                    kwargs[name] = [
                        item.copy() if hasattr(item, 'copy')
                        else dataclasses.replace(item)
                        for item in val
                    ]
                else:
                    # Card 对象等非-dataclass: 共享引用（Card 必须是不可变的）
                    kwargs[name] = list(val)
            elif isinstance(val, dict):
                kwargs[name] = dict(val)
            elif isinstance(val, set):
                kwargs[name] = set(val)
            elif isinstance(val, tuple):
                kwargs[name] = val  # tuple 不可变
            else:
                kwargs[name] = val

        return GameState(**kwargs)

    def is_lethal(self) -> bool:
        """对手英雄 HP + 护甲 <= 0 时为 True"""
        opp = self.opponent.hero
        return (opp.hp + opp.armor) <= 0

    def board_full(self) -> bool:
        """友方场上有7个随从时为 True"""
        return len(self.board) >= 7

    def location_full(self) -> bool:
        """友方地点已满（上限2个）时为 True"""
        return len(self.locations) >= 2

    # -- MechanicsState 访问（Phase 2集成）-----------------------

    @property
    def mechanics(self):
        """延迟初始化的 MechanicsState（用于机制特定状态）"""
        if self._mechanics is None:
            from analysis.search.mechanics_state import MechanicsState
            self._mechanics = MechanicsState()
        return self._mechanics

    @mechanics.setter
    def mechanics(self, value):
        self._mechanics = value

    def has_taunt_on_board(self) -> bool:
        """友方是否有嘲讽随从"""
        return any(m.has_taunt for m in self.board)

    def get_total_attack(self) -> int:
        """友方随从攻击力总和 + 武器攻击力"""
        total = sum(m.attack for m in self.board)
        if self.hero.weapon is not None:
            total += self.hero.weapon.attack
        return total

    def flush_deaths(self) -> "GameState":
        """处理所有待定的死亡（最外层阶段死亡延迟）

        在 END_TURN 或阶段完成时调用。依次执行：
        1. 亡语结算
        2. 复生处理
        3. 移除死亡随从
        4. 残骸获取
        5. 光环重算
        """
        # 1. 亡语结算 — expected failures: missing deathrattle module, bad card data
        try:
            from analysis.engine.mechanics.deathrattle import resolve_deaths
            self = resolve_deaths(self)
        except (ImportError, AttributeError, TypeError, IndexError) as e:
            dead_names = [getattr(m, 'name', '?') for m in self.board if m.health <= 0]
            log.warning("flush_deaths: 亡语结算失败 (dead=%s): %s", dead_names, e)

        # 2. 复生处理
        for m in list(self.board):
            if m.health <= 0 and m.has_reborn:
                m.has_reborn = False
                m.health = 1
                m.max_health = 1
                m.has_attacked_once = False
                m.can_attack = False
                m.has_divine_shield = False
                m.has_stealth = False
                m.has_taunt = False

        for m in list(self.opponent.board):
            if m.health <= 0 and m.has_reborn:
                m.has_reborn = False
                m.health = 1
                m.max_health = 1

        self.board = [m for m in self.board if m.health > 0]
        self.opponent.board = [m for m in self.opponent.board if m.health > 0]

        # 3. 残骸获取 — expected failures: missing corpse module
        try:
            from analysis.search.corpse import gain_corpses, has_double_corpse_gen
            amount = 2 if has_double_corpse_gen(self) else 1
            self = gain_corpses(self, amount)
        except (ImportError, AttributeError, TypeError) as e:
            log.debug("flush_deaths: 残骸获取跳过: %s", e)

        # 4. 光环重算 — expected failures: missing aura module, invalid minion
        try:
            from analysis.engine.aura import recompute_auras
            self = recompute_auras(self)
        except (ImportError, AttributeError, TypeError, IndexError) as e:
            board_names = [getattr(m, 'name', '?') for m in self.board]
            log.debug("flush_deaths: 光环重算跳过 (board=%s): %s", board_names, e)

        self._defer_deaths = False
        return self

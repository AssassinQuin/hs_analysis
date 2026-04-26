"""global_tracker.py — 全局游戏状态追踪器

跨回合追踪双方的关键信息：
- 对手手牌（从打出/揭示的卡牌推断）
- 牌库数量（精确计数 ZONE_DECK）
- 衍生牌 vs 牌库牌区分
- 残骸(Corpse)计数
- 法术学派 / 种族统计
- 卡牌类型统计（随从/法术/武器等各打出多少）
- 疲劳计数（§8.3）
- 过载追踪（§2.2）
- 抽牌/爆牌追踪（§8.2）
- 先后手/硬币追踪（§1.7）
- 英雄职业检测
- 对手武器/地点追踪
- 本回合出牌记录（延系等需要）
- 奥秘/任务/兆示追踪

设计原则：
- 只记录"已知"信息，不推测未知
- 衍生牌通过出生区域检测（SETASIDE/HAND 出生 = 衍生）
- 文件保持简洁，可被 GameReplayer / DecisionLoop 共用
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from analysis.constants.hs_enums import (
    ZONE_PLAY, ZONE_DECK, ZONE_HAND, ZONE_GRAVEYARD,
    ZONE_SETASIDE, ZONE_SECRET,
    CT_HERO, CT_MINION, CT_SPELL, CT_ENCHANTMENT,
    CT_WEAPON, CT_HERO_POWER, CT_LOCATION,
)
from analysis.watcher.secret_probability import SecretProbabilityModel
from analysis.watcher.tracker_types import (
    CardSource, KnownCard, OppHandIntel, SideStats, GlobalGameState,
)
from analysis.watcher.tracker_rules import (
    TrackingContext, TrackerRuleDispatcher,
    ShuffleTrackerRule, CorruptTrackerRule,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 全局追踪器
# ---------------------------------------------------------------------------

class GlobalTracker:
    """处理Power.log事件以维护GlobalGameState。

    用法::

        gt = GlobalTracker()
        # 在行处理器中调用:
        gt.on_full_entity(entity_id, card_id, controller, zone, ...)
        gt.on_show_entity(entity_id, card_id, controller, zone, ...)
        gt.on_zone_change(entity_id, controller, old_zone, new_zone, ...)
        gt.on_turn_change(turn)
        # 在决策点:
        state = gt.state
    """

    # 向后兼容：重新导出常量为类属性
    ZONE_PLAY = ZONE_PLAY
    ZONE_DECK = ZONE_DECK
    ZONE_HAND = ZONE_HAND
    ZONE_GRAVEYARD = ZONE_GRAVEYARD
    ZONE_SETASIDE = ZONE_SETASIDE
    ZONE_SECRET = ZONE_SECRET

    CT_HERO = CT_HERO
    CT_MINION = CT_MINION
    CT_SPELL = CT_SPELL
    CT_ENCHANTMENT = CT_ENCHANTMENT
    CT_WEAPON = CT_WEAPON
    CT_HERO_POWER = CT_HERO_POWER
    CT_LOCATION = CT_LOCATION

    # 已知的硬币卡牌ID
    COIN_CARD_IDS = {"GAME_005", "TB_BlingBrawl_Coin", "NEW1_008t"}

    # Standard deck rules: max copies per rarity
    _MAX_COPIES = {
        'COMMON': 2, 'RARE': 2, 'EPIC': 2,
        'LEGENDARY': 1, 'FREE': 2,
    }

    def __init__(self, our_controller: int = 0, opp_controller: int = 0):
        self.state = GlobalGameState()
        self.our_controller = our_controller
        self.opp_controller = opp_controller

        # 实体出生追踪 — 记录实体首次出现的时机和位置
        self._entity_birth: Dict[int, _EntityBirth] = {}
        # 卡牌数据库引用，用于种族/学派查询（延迟加载）
        self._card_db = None

        # 对手打出的每张牌的次数追踪（用于检测衍生牌）
        self._opp_card_play_count = {}  # card_id → count

        # 贝叶斯对手模型（延迟初始化）
        self._bayesian_model = None
        self._bayesian_initialized = False
        self._secret_model: Optional['SecretProbabilityModel'] = None

        # 区域转换分发表: (old_zone, new_zone) → handler
        self._zone_handlers: Dict[Tuple[int, int], callable] = {
            (self.ZONE_HAND, self.ZONE_PLAY): self._on_zone_hand_to_play,
            (self.ZONE_DECK, self.ZONE_HAND): self._on_zone_deck_to_hand,
            (self.ZONE_DECK, self.ZONE_GRAVEYARD): self._on_zone_deck_to_graveyard,
            (self.ZONE_SETASIDE, self.ZONE_HAND): self._on_zone_setaside_to_hand,
            (self.ZONE_SETASIDE, self.ZONE_PLAY): self._on_zone_setaside_to_play,
            (self.ZONE_PLAY, self.ZONE_GRAVEYARD): self._on_zone_play_to_graveyard,
            (self.ZONE_PLAY, self.ZONE_HAND): self._on_zone_return_to_hand,
            (self.ZONE_SECRET, self.ZONE_HAND): self._on_zone_return_to_hand,
            (self.ZONE_HAND, self.ZONE_SECRET): self._on_zone_hand_to_secret,
            (self.ZONE_SECRET, self.ZONE_GRAVEYARD): self._on_zone_secret_resolved,
            (self.ZONE_SECRET, self.ZONE_SETASIDE): self._on_zone_secret_resolved,
        }

        # 可插拔追踪规则
        self._rule_dispatcher = TrackerRuleDispatcher()
        self._rule_dispatcher.register(ShuffleTrackerRule())
        self._rule_dispatcher.register(CorruptTrackerRule())

    def set_controllers(self, our: int, opp: int):
        self.our_controller = our
        self.opp_controller = opp

    def on_game_start(self):
        """为新游戏重置状态"""
        self.state = GlobalGameState()
        self._entity_birth.clear()
        self._card_db = None
        self._bayesian_model = None
        self._bayesian_initialized = False
        self._secret_model = None
        self._opp_card_play_count.clear()

    # ---------------------------------------------------------------
    # 延迟加载卡牌数据库
    # ---------------------------------------------------------------

    def _get_card_db(self):
        """延迟加载HSCardDB，用于卡牌元数据（种族、学派等）"""
        if self._card_db is None:
            try:
                from analysis.data.card_data import get_db
                self._card_db = get_db()
            except ImportError:
                logger.warning("HSCardDB unavailable, race/school tracking disabled")
        return self._card_db

    def _card_metadata(self, card_id: str) -> Dict:
        """从数据库获取卡牌元数据，返回包含race/school/class等的字典"""
        db = self._get_card_db()
        if db is None:
            return {}
        card = db.get_card(card_id)
        if card is None:
            return {}
        return card

    # ---------------------------------------------------------------
    # 实体生命周期
    # ---------------------------------------------------------------

    def on_full_entity(self, entity_id: int, card_id: str, controller: int,
                       zone: int, card_type: int = 0, cost: int = 0):
        """解析到 FULL_ENTITY - Creating 时调用"""
        birth = _EntityBirth(
            entity_id=entity_id,
            card_id=card_id,
            controller=controller,
            initial_zone=zone,
            card_type=card_type,
            cost=cost,
        )
        self._entity_birth[entity_id] = birth

        # 追踪对手初始牌库大小
        if controller == self.opp_controller and zone == self.ZONE_DECK:
            if card_type not in (2,):  # 排除PLAYER类型
                self.state.opp_initial_deck_size += 1

        # 从英雄实体检测英雄职业
        if card_type == self.CT_HERO and card_id:
            meta = self._card_metadata(card_id)
            hero_class = meta.get("cardClass", "")
            if controller == self.our_controller:
                self.state.player_hero_class = hero_class
            elif controller == self.opp_controller:
                self.state.opp_hero_class = hero_class

        # 检测硬币实体
        if card_id in self.COIN_CARD_IDS:
            self.state.coin_entity_id = entity_id

    def on_show_entity(self, entity_id: int, card_id: str, controller: int,
                       zone: int, card_type: int = 0, cost: int = 0):
        """解析到 SHOW_ENTITY 揭示隐藏实体时调用。

        对于对手直接揭示到PLAY/SECRET区域的卡牌（典型情况——对手打出
        一张牌，我们看到它出现），我们将其追踪为"已打出"的卡牌，
        因为对手的 HAND→PLAY 区域变化对我们不可见。
        """
        if controller == self.opp_controller:
            # 追踪规则分发（Corrupt升级检测等由 CorruptTrackerRule 处理）
            self._rule_dispatcher.dispatch_show_entity(
                entity_id, card_id, controller, zone,
                card_type, self.state, is_opp=True,
            )

            self.state.opp_hand_card_ids[entity_id] = (card_id, zone)

            # 将对手揭示到PLAY/SECRET的卡牌追踪为"已打出"
            # 对手的HAND→PLAY不可见，直接通过SHOW_ENTITY出现在最终区域
            if zone == self.ZONE_PLAY and card_type not in (self.CT_ENCHANTMENT,):
                # 跳过附魔（type 6）— 它们是增益效果，不是打出的卡牌
                self._on_card_played(entity_id, controller, card_id, card_type)
                # 检测洗入牌库的牌被打出 → 标记为 GENERATED
                if card_id and card_id in self.state.opp_shuffled_into_deck:
                    self._mark_shuffled_card_played(card_id)
            elif zone == self.ZONE_SECRET:
                self.state.opp_secrets.append(card_id)
                self._on_card_played(entity_id, controller, card_id, card_type)
                # 更新奥秘概率模型
                self._ensure_secret_model()
                if self._secret_model and card_id:
                    self._secret_model.exclude(card_id)

            # 为对手揭示到PLAY/SECRET的卡牌喂入贝叶斯模型
            # 检测衍生牌：来源为GENERATED 或 超过标准牌库张数限制
            if zone in (self.ZONE_PLAY, self.ZONE_SECRET) and card_id:
                card_source = self._classify_source(entity_id, card_id)
                is_generated = (card_source == CardSource.GENERATED 
                               or self._is_over_copy_limit(card_id))
                if not self._bayesian_initialized:
                    self._init_bayesian_model(self.state.opp_hero_class)
                if is_generated:
                    # 衍生牌：记录但不更新后验
                    self.feed_bayesian_generated_update(card_id)
                else:
                    # 牌库牌：正常更新后验
                    self.feed_bayesian_update(card_id)

            # 为对手揭示到HAND的卡牌喂入贝叶斯模型 (Tracking/发现效果/Mulligan)
            # 同样需要区分来源和张数限制
            if zone == self.ZONE_HAND and card_id:
                card_source = self._classify_source(entity_id, card_id)
                is_generated = (card_source == CardSource.GENERATED
                               or self._is_over_copy_limit(card_id))
                if not self._bayesian_initialized:
                    self._init_bayesian_model(self.state.opp_hero_class)
                if is_generated:
                    self.feed_bayesian_generated_update(card_id)
                else:
                    self.feed_bayesian_hand_update(card_id)
                # 记录已知手牌（无论来源，用于 Determinizer 采样）
                self._record_known_hand_card(card_id)

        if entity_id in self._entity_birth:
            self._entity_birth[entity_id].card_id = card_id

        # 从揭示的英雄卡牌检测职业
        if card_type == self.CT_HERO and card_id:
            meta = self._card_metadata(card_id)
            hero_class = meta.get("cardClass", "")
            if controller == self.our_controller and not self.state.player_hero_class:
                self.state.player_hero_class = hero_class
            elif controller == self.opp_controller and not self.state.opp_hero_class:
                self.state.opp_hero_class = hero_class

    def on_zone_change(self, entity_id: int, controller: int,
                       old_zone: int, new_zone: int,
                       card_id: str = "", card_type: int = 0):
        """实体ZONE标签变化时调用。

        区域转换通过 _zone_handlers 分发表自动路由。
        以下转换在分发后独立处理（不属于互斥分支）：
        - 任意 -> DECK: 洗入牌库（爆牌鱼、污染等）
        - HAND -> * (硬币): 硬币使用检测
        """
        is_opp = (controller == self.opp_controller)

        # 区域变化时更新opp_hand_card_ids中的zone
        # 保留card_id但更新zone，以便get_opp_known_hand()能正确过滤
        # 注意：不在此处检查is_opp——controller可能已变化
        # （例如对手卡牌在回合开始时转移到玩家牌库）
        if entity_id in self.state.opp_hand_card_ids:
            card_id = self.state.opp_hand_card_ids[entity_id][0]
            self.state.opp_hand_card_ids[entity_id] = (card_id, new_zone)

        # 区域转换分发
        handler = self._zone_handlers.get((old_zone, new_zone))
        if handler is not None:
            handler(entity_id, controller, card_id, card_type, is_opp)

        # 追踪规则分发（跨切面关注点：洗入牌库等）
        ctx = TrackingContext(
            entity_id=entity_id, controller=controller,
            old_zone=old_zone, new_zone=new_zone,
            card_id=card_id, card_type=card_type,
            is_opp=is_opp, state=self.state,
        )
        self._rule_dispatcher.dispatch_zone_change(ctx)

        # 硬币使用：检测硬币法术从HAND离开
        if (old_zone == self.ZONE_HAND and
            card_id in self.COIN_CARD_IDS):
            self.state.coin_used = True

    # ── 区域转换处理器 ─────────────────────────────────────────

    def _on_zone_hand_to_play(self, entity_id, controller, card_id, card_type, is_opp):
        """打出卡牌: HAND -> PLAY"""
        self._on_card_played(entity_id, controller, card_id, card_type)

    def _on_zone_deck_to_hand(self, entity_id, controller, card_id, card_type, is_opp):
        """抽牌: DECK -> HAND (§8.2)"""
        stats = self.state.opp_stats if is_opp else self.state.player_stats
        stats.cards_drawn += 1

    def _on_zone_deck_to_graveyard(self, entity_id, controller, card_id, card_type, is_opp):
        """爆牌: DECK -> GRAVEYARD（手牌满时）(§8.2)"""
        stats = self.state.opp_stats if is_opp else self.state.player_stats
        stats.cards_milled += 1
        stats.cards_drawn += 1  # 算作一次抽牌

    def _on_zone_setaside_to_hand(self, entity_id, controller, card_id, card_type, is_opp):
        """衍生牌进入手牌: SETASIDE -> HAND"""
        pass  # 实体出生记录已标记为衍生

    def _on_zone_setaside_to_play(self, entity_id, controller, card_id, card_type, is_opp):
        """衍生随从登场: SETASIDE -> PLAY"""
        pass  # 召唤的衍生随从不算"打出"

    def _on_zone_play_to_graveyard(self, entity_id, controller, card_id, card_type, is_opp):
        """随从死亡/武器摧毁: PLAY -> GRAVEYARD"""
        if is_opp and card_id:
            self.state.opp_graveyard_seen.append(card_id)
        if not is_opp and card_id:
            self.state.player_minions_died.append(card_id)

    def _on_zone_return_to_hand(self, entity_id, controller, card_id, card_type, is_opp):
        """打出的卡牌回手（弹回/召回）: PLAY/SECRET -> HAND"""
        if is_opp and card_id:
            self.state.opp_returned_to_hand_seen.append(card_id)

    def _on_zone_hand_to_secret(self, entity_id, controller, card_id, card_type, is_opp):
        """打出奥秘: HAND -> SECRET (§7)"""
        if is_opp and card_id:
            self.state.opp_secrets.append(card_id)
        self._on_card_played(entity_id, controller, card_id, card_type)

    def _on_zone_secret_resolved(self, entity_id, controller, card_id, card_type, is_opp):
        """奥秘触发/过期: SECRET -> GRAVEYARD/SETASIDE"""
        if is_opp and card_id:
            if card_id in self.state.opp_secrets:
                self.state.opp_secrets.remove(card_id)
            self.state.opp_secrets_triggered.append(KnownCard(
                card_id=card_id,
                turn_seen=self.state.current_turn,
                source=self._classify_source(entity_id, card_id),
                card_type="SPELL",
            ))
            # 更新奥秘概率模型
            if self._secret_model and card_id:
                self._secret_model.exclude(card_id)

    def _on_card_played(self, entity_id: int, controller: int,
                        card_id: str, card_type: int):
        """记录一张卡牌被打出（HAND -> PLAY 或 HAND -> SECRET）"""
        is_opp = (controller == self.opp_controller)
        source = self._classify_source(entity_id, card_id)

        # 查询卡牌元数据获取种族/学派
        meta = self._card_metadata(card_id) if card_id else {}
        spell_school = meta.get("spellSchool", "")
        race = meta.get("race", "")

        # 构建已知卡牌记录
        known = KnownCard(
            card_id=card_id,
            turn_seen=self.state.current_turn,
            source=source,
            from_zone="HAND",
            card_type=self._card_type_name(card_type),
            cost=self._entity_birth.get(entity_id, _EntityBirth()).cost,
            spell_school=spell_school,
            race=race,
        )

        # 更新统计
        stats = self.state.opp_stats if is_opp else self.state.player_stats
        self._update_play_stats(stats, card_id, card_type, source, meta)

        # 追踪本回合打出的卡牌
        if is_opp:
            self.state.cards_played_this_turn_opp.append(card_id)
            self.state.opp_known_cards.append(known)
            # 追踪打出次数（用于检测超过牌库限制的衍生牌）
            self._opp_card_play_count[card_id] = self._opp_card_play_count.get(card_id, 0) + 1
            if source == CardSource.GENERATED or self._is_over_copy_limit(card_id):
                self.state.opp_generated_seen.add(card_id)
                # Override source to GENERATED if over copy limit
                if source != CardSource.GENERATED:
                    known.source = CardSource.GENERATED
        else:
            self.state.cards_played_this_turn_player.append(card_id)
            self.state.player_cards_played_history.append(card_id)
            if source == CardSource.GENERATED:
                self.state.player_generated_seen.add(card_id)

        # 注意：opp_hand_card_ids的清理在on_zone_change()中
        # 当任何卡牌离开HAND区域时处理，此处无需移除。

    def _classify_source(self, entity_id: int, card_id: str) -> CardSource:
        """判断卡牌来源是牌库还是衍生。

        启发式规则：
        1. 实体出生在DECK区域 → 牌库牌
        2. 实体出生在SETASIDE或HAND（非初始） → 衍生牌
        3. 查卡牌数据库：非可收集 = 衍生
        """
        birth = self._entity_birth.get(entity_id)
        if birth:
            if birth.initial_zone == self.ZONE_DECK:
                return CardSource.DECK
            if birth.initial_zone == self.ZONE_SETASIDE:
                return CardSource.GENERATED
            # HAND区域的非牌库卡牌（如衍生到手牌）
            if birth.initial_zone == self.ZONE_HAND:
                return CardSource.GENERATED

        # 兜底：查卡牌数据库的可收集性
        if card_id:
            meta = self._card_metadata(card_id)
            if meta:
                if not meta.get("collectible", False):
                    return CardSource.GENERATED
                return CardSource.DECK

        return CardSource.UNKNOWN

    def _mark_shuffled_card_played(self, card_id: str):
        """Mark a shuffled card as played — it was generated, not from original deck.
        
        Removes the card from shuffled tracking and ensures it's in
        the generated set so it doesn't affect deck inference.
        """
        self.state.opp_generated_seen.add(card_id)
        # Remove from shuffled list (it's been played)
        if card_id in self.state.opp_shuffled_into_deck:
            self.state.opp_shuffled_into_deck.remove(card_id)
        # Remove from known shuffled cards
        self.state.opp_shuffled_known_cards.pop(card_id, None)
        
        log.debug(
            "Shuffled card played (marked GENERATED): %s",
            card_id,
        )

    def _is_over_copy_limit(self, card_id: str) -> bool:
        """检查对手是否打出了超过标准牌库限制的同一张牌。
        
        Standard rules: max 2 copies (common/rare/epic), 1 copy (legendary).
        If opponent plays a 3rd+ copy, it must be GENERATED.
        
        Args:
            card_id: Hearthstone card_id string
            
        Returns:
            True if this card has been played more times than a deck allows.
        """
        count = self._opp_card_play_count.get(card_id, 0)
        if count == 0:
            return False
        
        # Check rarity from card metadata
        meta = self._card_metadata(card_id) if card_id else {}
        rarity = meta.get('rarity', 'COMMON').upper()
        max_copies = self._MAX_COPIES.get(rarity, 2)
        
        return count >= max_copies

    def _card_type_name(self, card_type: int) -> str:
        """将数字卡牌类型转换为字符串"""
        _map = {4: "MINION", 5: "SPELL", 7: "WEAPON", 3: "HERO",
                6: "LOCATION", 10: "HERO_POWER"}
        return _map.get(card_type, "UNKNOWN")

    def _update_play_stats(self, stats: SideStats, card_id: str,
                           card_type: int, source: CardSource, meta: Dict):
        """更新打出卡牌后的单方统计"""
        if card_type == self.CT_MINION:
            stats.minions_played += 1
        elif card_type == self.CT_SPELL:
            stats.spells_played += 1
        elif card_type == self.CT_WEAPON:
            stats.weapons_played += 1
        elif card_type == self.CT_HERO:
            stats.heroes_played += 1
        elif card_type == self.CT_LOCATION:
            stats.locations_played += 1

        if source == CardSource.GENERATED:
            stats.generated_cards_played += 1
        elif source == CardSource.DECK:
            stats.deck_cards_played += 1

        # 种族追踪 (§9.3 延系需要)
        if meta:
            race = meta.get("race", "")
            if race:
                for r in race.split():
                    stats.races_played[r] = stats.races_played.get(r, 0) + 1

            # 法术学派追踪
            school = meta.get("spellSchool", "")
            if school:
                stats.spell_schools[school] = stats.spell_schools.get(school, 0) + 1

    # ---------------------------------------------------------------
    # 回合/游戏事件
    # ---------------------------------------------------------------

    def on_turn_change(self, turn: int):
        """游戏TURN标签变化时调用"""
        # 切换回合前，保存当前回合的种族/学派（延系需要）
        if turn != self.state.current_turn:
            # 轮转：当前回合的数据变为"上回合"（我们是玩家）
            player_stats = self.state.player_stats
            if player_stats.races_played:
                self.state.last_turn_races_player = set(player_stats.races_played.keys())
            if player_stats.spell_schools:
                self.state.last_turn_schools_player = set(player_stats.spell_schools.keys())

            # 清除本回合打出卡牌的追踪
            if turn % 2 == 1:  # 我方回合开始
                self.state.cards_played_this_turn_player.clear()
            else:
                self.state.cards_played_this_turn_opp.clear()

        self.state.current_turn = turn

    def on_corpse_change(self, controller: int, total_corpses: int):
        """残骸(Corpse)总量变化时调用"""
        if controller == self.opp_controller:
            self.state.opp_corpses = total_corpses
        else:
            self.state.player_corpses = total_corpses

    def on_overload_change(self, controller: int, overload_next: int):
        """OVERLOAD_OWED标签变化时调用 (§2.2)"""
        stats = self.state.opp_stats if controller == self.opp_controller else self.state.player_stats
        stats.overload_next = overload_next

    def on_herald_change(self, controller: int, count: int):
        """兆示计数器变化时调用"""
        if controller == self.opp_controller:
            self.state.opp_herald_count = count
        else:
            self.state.player_herald_count = count

    def on_fatigue_change(self, controller: int, fatigue_damage: int):
        """FATIGUE标签变化时调用 (§8.3)"""
        stats = self.state.opp_stats if controller == self.opp_controller else self.state.player_stats
        stats.fatigue_damage = fatigue_damage
        stats.times_fatigued += 1

    def on_first_player(self, is_our_player: bool):
        """检测到FIRST_PLAYER时调用 (§1.7)"""
        self.state.is_first_player = is_our_player

    # ---------------------------------------------------------------
    # 牌库计数追踪
    # ---------------------------------------------------------------

    def count_opp_deck(self, opp_entities: list) -> int:
        """统计对手在DECK区域的实体数"""
        count = sum(1 for e in opp_entities if getattr(e, 'zone', 0) == self.ZONE_DECK)
        self.state.opp_deck_remaining = count
        return count

    def count_player_deck(self, our_entities: list) -> int:
        """统计我方在DECK区域的实体数"""
        return sum(1 for e in our_entities if getattr(e, 'zone', 0) == self.ZONE_DECK)

    # ---------------------------------------------------------------
    # 对手手牌/武器/地点追踪
    # ---------------------------------------------------------------

    def get_opp_hand_count(self, opp_entities: list) -> int:
        """统计对手在HAND区域的实体数"""
        return sum(1 for e in opp_entities if getattr(e, 'zone', 0) == self.ZONE_HAND)

    def get_opp_known_hand(self) -> List[Tuple[int, str]]:
        """返回对手已知手牌的 (entity_id, card_id) 列表。

        仅返回当前在HAND区域的卡牌——过滤已打出、弃牌或
        移到其他区域的卡牌。
        """
        return [
            (eid, card_id)
            for eid, (card_id, zone) in self.state.opp_hand_card_ids.items()
            if zone == self.ZONE_HAND
        ]

    def get_opp_hand_intelligence(self, name_fn=None, hand_count: int = 0) -> OppHandIntel:
        """返回结构化的对手手牌情报。

        三个层级：
        1. confirmed_hand (100%): 在HAND区域揭示的卡牌（SHOW_ENTITY→HAND）
        2. deck_cards_played: 已打出的原始牌库卡牌（现已在墓地）
        3. generated_cards: 已打出/发现的衍生牌
        """
        name_fn = name_fn or (lambda cid: cid)
        state = self.state

        confirmed_raw = self.get_opp_known_hand()
        confirmed_hand = [name_fn(cid) for _, cid in confirmed_raw]

        played_deck = []
        played_gen = []
        for kc in state.opp_known_cards:
            name = name_fn(kc.card_id) if kc.card_id else "未知"
            if kc.source == CardSource.DECK:
                played_deck.append(name)
            elif kc.source == CardSource.GENERATED:
                played_gen.append(name)

        secrets_active = [name_fn(cid) for cid in state.opp_secrets]
        secrets_triggered = [name_fn(kc.card_id) for kc in state.opp_secrets_triggered]
        returned_to_hand = [name_fn(cid) for cid in state.opp_returned_to_hand_seen]
        graveyard_cards = [name_fn(cid) for cid in state.opp_graveyard_seen]
        probable = self.get_opp_probable_hand(name_fn=name_fn, prob_threshold=0.5)

        return OppHandIntel(
            confirmed_hand=confirmed_hand,
            returned_to_hand=returned_to_hand,
            graveyard_cards=graveyard_cards,
            probable_hand_over_50=probable,
            secrets_active=secrets_active,
            secrets_triggered=secrets_triggered,
            deck_cards_played=played_deck,
            generated_cards=played_gen,
            hand_count=hand_count,
            deck_count=state.opp_deck_remaining,
            confirmed_pct=0,
        )

    def get_opp_probable_hand(self, name_fn=None, prob_threshold: float = 0.5) -> List[str]:
        """返回概率 >= 阈值的对手可能手牌"""
        name_fn = name_fn or (lambda cid: cid)
        bs = self.get_bayesian_state()
        preds = bs.get("predicted_next", []) or []
        result: List[str] = []
        for p in preds:
            prob = float(p.get("probability", 0.0) or 0.0)
            if prob >= prob_threshold:
                name = p.get("name") or ""
                # 贝叶斯模型可能直接返回名称；保留优雅的回退
                result.append(name if name else name_fn(str(p.get("dbfId", ""))))
        return result

    def get_opp_card_breakdown(self, card_name_fn=None) -> Dict:
        """生成所有已揭示对手卡牌的分类统计。

        返回字典包含：
            - deck_cards_played: 原始牌库中打出的卡牌名称列表
            - generated_cards_played: 衍生卡牌名称列表
            - known_hand: 对手当前HAND区域的卡牌名称列表
            - total_played: 总打出卡牌数
            - total_generated: 总衍生卡牌数
            - type_counts: 类型统计 {MINION: n, SPELL: n, WEAPON: n, HERO: n, LOCATION: n}
            - school_counts: 法术学派分布
            - race_counts: 种族分布
        """
        name_fn = card_name_fn or (lambda cid: cid)
        state = self.state
        stats = state.opp_stats

        # 按来源分类已打出的卡牌
        deck_cards = []
        generated_cards = []
        for kc in state.opp_known_cards:
            name = name_fn(kc.card_id) if kc.card_id else "未知"
            if kc.source == CardSource.DECK:
                deck_cards.append(name)
            elif kc.source == CardSource.GENERATED:
                generated_cards.append(name)
            else:
                # UNKNOWN — 视为牌库牌（保守估计）
                deck_cards.append(name)

        # 已知手牌（已按区域过滤）
        known_hand = [name_fn(cid) for _, cid in self.get_opp_known_hand()]

        return {
            "deck_cards_played": deck_cards,
            "generated_cards_played": generated_cards,
            "known_hand": known_hand,
            "total_played": len(state.opp_known_cards),
            "total_generated": len(state.opp_generated_seen),
            "type_counts": {
                "随从": stats.minions_played,
                "法术": stats.spells_played,
                "武器": stats.weapons_played,
                "英雄": stats.heroes_played,
                "地点": stats.locations_played,
            },
            "school_counts": dict(stats.spell_schools),
            "race_counts": dict(stats.races_played),
        }

    # ---------------------------------------------------------------
    # 贝叶斯对手模型集成
    # ---------------------------------------------------------------

    def _ensure_card_db(self):
        """延迟加载卡牌数据库，用于dbfId查询"""
        if self._card_db is None:
            from analysis.data.card_data import get_db
            self._card_db = get_db()
        return self._card_db

    def _ensure_secret_model(self):
        """基于对手英雄职业初始化奥秘概率模型"""
        if self._secret_model is not None:
            return
        opp_cls = self.state.opp_hero_class
        if opp_cls:
            self._secret_model = SecretProbabilityModel(opp_cls)

    def _init_bayesian_model(self, opponent_class: str = None):
        """Initialize Bayesian opponent model from HSReplay cache or deck_codes.txt.

        Args:
            opponent_class: Optional class filter (e.g. 'ROGUE', 'WARLOCK')
        """
        if self._bayesian_initialized:
            return
        self._bayesian_initialized = True

        try:
            from analysis.utils.bayesian_opponent import BayesianOpponentModel
            from analysis.data.fetch_hsreplay import init_db, build_archetype_db_from_deck_codes
            from analysis.config import HSREPLAY_CACHE_DB
            import os

            # 尝试从已有缓存加载
            if os.path.exists(str(HSREPLAY_CACHE_DB)):
                conn = init_db(str(HSREPLAY_CACHE_DB))
                try:
                    from analysis.data.fetch_hsreplay import get_meta_decks
                    decks = get_meta_decks(conn)
                    if not decks:
                        # 缓存存在但为空——从卡组代码构建
                        build_archetype_db_from_deck_codes(conn)
                finally:
                    conn.close()
            else:
                # 无缓存——从卡组代码构建
                conn = init_db(str(HSREPLAY_CACHE_DB))
                try:
                    build_archetype_db_from_deck_codes(conn)
                finally:
                    conn.close()

            self._bayesian_model = BayesianOpponentModel(player_class=opponent_class)
            if not self._bayesian_model.decks:
                self._bayesian_model = None  # No data available
        except Exception:
            self._bayesian_model = None

    def feed_bayesian_update(self, card_id: str):
        """Feed an observed opponent card to the Bayesian model.

        Converts card_id → dbfId and updates the model posterior.
        Called automatically from on_show_entity() for opponent cards.
        """
        if self._bayesian_model is None:
            return
        db = self._ensure_card_db()
        dbf = db.card_id_to_dbf(card_id)
        if dbf is not None:
            self._bayesian_model.update(dbf)

    def feed_bayesian_hand_update(self, card_id: str):
        """Update Bayesian model from a card seen in opponent's hand.

        Uses lower confidence than play observations.

        Args:
            card_id: Hearthstone card_id string (e.g. "EX1_001")
        """
        if self._bayesian_model is None:
            return
        db = self._ensure_card_db()
        dbf = db.card_id_to_dbf(card_id)
        if dbf is not None:
            self._bayesian_model.update_from_hand(dbf)

    def feed_bayesian_generated_update(self, card_id: str):
        """Record a GENERATED-source card observation in Bayesian model.
        
        Generated cards (discover, create, shuffle effects) do NOT
        indicate deck composition. We record them for exclusion but
        do NOT update posteriors.
        
        Args:
            card_id: Hearthstone card_id string
        """
        if self._bayesian_model is None:
            return
        db = self._ensure_card_db()
        dbf = db.card_id_to_dbf(card_id)
        if dbf is not None:
            self._bayesian_model.update_generated(dbf)
    
    def _record_known_hand_card(self, card_id: str):
        """Record a card definitively seen in opponent's hand.
        
        Called when a card is revealed in HAND zone (Tracking,
        Discover, card text effects). These cards are known-certain
        for hand sampling.
        
        Args:
            card_id: Hearthstone card_id string
        """
        if self._bayesian_model is None:
            return
        db = self._ensure_card_db()
        dbf = db.card_id_to_dbf(card_id)
        if dbf is not None:
            self._bayesian_model.record_known_hand_card(dbf, self.state.current_turn)

    def get_bayesian_state(self) -> Dict:
        """Get current Bayesian inference state.

        Returns dict with:
            - archetype_name: str or None — locked archetype name
            - locked_deck_id: int or None — locked archetype ID
            - deck_confidence: float — max posterior probability
            - top_decks: list of (id, name, prob) — top 3 archetypes
            - predicted_next: list of dicts — predicted next cards
        """
        if self._bayesian_model is None:
            return {
                "archetype_name": None,
                "locked_deck_id": None,
                "deck_confidence": 0.0,
                "top_decks": [],
                "predicted_next": [],
            }

        locked = self._bayesian_model.locked
        top = self._bayesian_model.get_top_decks(3)
        preds = self._bayesian_model.predict_next_actions(3)

        from analysis.utils.bayesian_opponent import classify_playstyle
        archetype_name = self._bayesian_model._deck_name(locked[0]) if locked else None
        playstyle = classify_playstyle(archetype_name) if archetype_name else "unknown"

        return {
            "archetype_name": archetype_name,
            "locked_deck_id": locked[0] if locked else None,
            "deck_confidence": locked[1] if locked else (top[0][2] if top else 0.0),
            "top_decks": [(aid, name, round(prob, 4)) for aid, name, prob in top],
            "predicted_next": preds,
            "playstyle": playstyle,
        }

    def get_secret_report(self) -> Dict:
        """获取奥秘概率报告，用于日志和决策"""
        if not self._secret_model:
            return {"active_secrets": len(self.state.opp_secrets),
                    "model": "uninitialized"}
        
        probs = self._secret_model.get_probabilities()
        most_likely = self._secret_model.get_most_likely(3)
        attack_risk = self._secret_model.get_attack_risk()
        spell_risk = self._secret_model.get_spell_risk()
        
        return {
            "active_secrets": len(self.state.opp_secrets),
            "known_secrets": list(self.state.opp_secrets),
            "triggered_secrets": len(self.state.opp_secrets_triggered),
            "remaining_pool": len(probs),
            "most_likely": [(cid, name, f"{p:.1%}") for cid, name, p in most_likely],
            "attack_risk": f"{attack_risk:.2f}",
            "spell_risk": f"{spell_risk:.2f}",
            "summary": self._secret_model.get_summary(),
        }

    def update_opp_weapon(self, opp_entities: list):
        """从PLAY区域更新对手武器状态"""
        for e in opp_entities:
            if (getattr(e, 'zone', 0) == self.ZONE_PLAY and
                getattr(e, 'card_type', 0) == self.CT_WEAPON):
                self.state.opp_weapon = getattr(e, 'card_id', '')
                self.state.opp_weapon_atk = getattr(e, 'atk', 0)
                self.state.opp_weapon_durability = getattr(e, 'health', 0)
                return
        # 未找到武器——清除
        self.state.opp_weapon = ""
        self.state.opp_weapon_atk = 0
        self.state.opp_weapon_durability = 0

    def update_opp_locations(self, opp_entities: list):
        """从PLAY区域更新对手地点状态"""
        self.state.opp_locations = [
            getattr(e, 'card_id', '')
            for e in opp_entities
            if (getattr(e, 'zone', 0) == self.ZONE_PLAY and
                getattr(e, 'card_type', 0) == self.CT_LOCATION)
        ]

    # ---------------------------------------------------------------
    # 摘要输出（用于日志）
    # ---------------------------------------------------------------

    def opp_summary_str(self, opp_entities: list, card_name_fn=None) -> str:
        """生成人类可读的对手状态摘要字符串"""
        deck = self.count_opp_deck(opp_entities)
        hand = self.get_opp_hand_count(opp_entities)
        known_hand = self.get_opp_known_hand()

        parts = [f"手牌={hand}张", f"牌库={deck}张"]

        if known_hand:
            name_fn = card_name_fn or (lambda cid: cid)
            known_str = ", ".join(name_fn(cid) for _, cid in known_hand)
            parts.append(f"已知手牌: [{known_str}]")

        if self.state.opp_generated_seen:
            parts.append(f"衍生牌={len(self.state.opp_generated_seen)}张")

        if self.state.opp_secrets:
            parts.append(f"奥秘={len(self.state.opp_secrets)}个")

        if self.state.opp_weapon:
            name_fn = card_name_fn or (lambda cid: cid)
            parts.append(f"武器={name_fn(self.state.opp_weapon)} {self.state.opp_weapon_atk}/{self.state.opp_weapon_durability}")

        if self.state.opp_hero_class:
            parts.append(f"职业={self.state.opp_hero_class}")

        stats = self.state.opp_stats
        total_played = (stats.minions_played + stats.spells_played +
                       stats.weapons_played + stats.heroes_played)
        if total_played > 0:
            parts.append(f"已出牌={total_played}(衍生{stats.generated_cards_played})")

        if stats.fatigue_damage > 0:
            parts.append(f"疲劳={stats.fatigue_damage}")

        if stats.cards_milled > 0:
            parts.append(f"爆牌={stats.cards_milled}")

        return " | ".join(parts)

    def player_summary_str(self, card_name_fn=None) -> str:
        """生成人类可读的玩家全局统计字符串"""
        parts = []
        stats = self.state.player_stats
        if stats.generated_cards_played > 0:
            parts.append(f"衍生牌={stats.generated_cards_played}张")
        if self.state.player_generated_seen:
            names = []
            for cid in self.state.player_generated_seen:
                n = card_name_fn(cid) if card_name_fn else cid
                names.append(n)
            if names:
                parts.append(f"衍生牌列表={','.join(names)}")
        if self.state.player_corpses > 0:
            parts.append(f"残骸={self.state.player_corpses}")
        if self.state.player_herald_count > 0:
            parts.append(f"兆示={self.state.player_herald_count}")
        if stats.spell_schools:
            top_schools = sorted(stats.spell_schools.items(), key=lambda x: -x[1])[:3]
            parts.append(f"学派={','.join(f'{k}:{v}' for k,v in top_schools)}")
        if stats.overload_next > 0:
            parts.append(f"过载={stats.overload_next}")
        if stats.fatigue_damage > 0:
            parts.append(f"疲劳={stats.fatigue_damage}")

        if not parts:
            return ""
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# 内部辅助类
# ---------------------------------------------------------------------------

@dataclass
class _EntityBirth:
    """实体首次出现在游戏中的记录"""
    entity_id: int = 0
    card_id: str = ""
    controller: int = 0
    initial_zone: int = 0
    card_type: int = 0
    cost: int = 0

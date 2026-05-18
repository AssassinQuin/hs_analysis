# -*- coding: utf-8 -*-
"""card_effect_inference.py — 卡牌效果推断引擎

解析卡牌效果文本，推断对手可能的手牌组成。

核心能力：
1. 条件触发推断: "如果你手持龙牌" → 推断持有龙族卡牌
2. 衍生牌推断: 打出某张牌后产生的衍生牌，追踪其来源
3. 手牌变换追踪: 某些卡牌会改变手牌（Tracking、Mulligan等）
4. 卡牌揭示追踪: 通过窥牌效果看到的卡牌
5. 打出时机推断: 对手在特定回合打出特定费用/类型的牌，更新概率

推断规则分类：
- CONDITIONAL_HOLD: 持有特定种族/学派的牌
- GENERATE_CARD: 生成特定类型的衍生牌
- REVEAL_CARD: 揭示对手手牌中的牌
- MODIFY_HAND: 修改手牌（抽牌、弃牌、换牌）
- PLAY_TIMING: 根据打出时机推断卡牌类型

与 DynamicProbabilityEngine 的集成：
- 推断结果作为 HandConstraint 传递给概率引擎
- 推断的衍生牌来源影响 generated_cards 追踪
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── 推断结果数据结构 ──────────────────────────────────────────

@dataclass
class InferenceResult:
    """单条推断结果。"""
    inference_type: str  # "conditional_hold" | "derived_card" | "reveal" | "hand_modify" | "play_timing"
    card_id: str = ""  # 触发推断的卡牌
    inferred_card_id: str = ""  # 推断出的卡牌
    inferred_race: str = ""  # 推断出的种族
    inferred_school: str = ""  # 推断出的法术学派
    probability: float = 0.0  # 推断置信度
    turn: int = 0
    source_description: str = ""  # 人类可读的推断描述
    evidence_cards: List[str] = field(default_factory=list)
    derive_type: str = ""  # "discover" | "generate" | "shuffle" | "transform" | "corrupt"


@dataclass
class DerivedCardRecord:
    """衍生卡牌记录。"""
    card_id: str  # 衍生卡牌的 card_id
    source_card_id: str  # 产生此衍生牌的原始卡牌
    turn: int  # 产生回合
    derive_type: str  # "discover" | "generate" | "shuffle" | "transform" | "corrupt"
    probability: float = 1.0  # 衍生概率（discover 是 1/3 等）


@dataclass
class PlayTimingInference:
    """打出时机推断。"""
    card_id: str = ""
    cost: int = 0
    turn_played: int = 0
    card_type: str = ""
    inference: str = ""  # 描述性推断
    implied_cost_range: Tuple[int, int] = (0, 10)


# ── 卡牌效果推断引擎 ──────────────────────────────────────────

class CardEffectInferenceEngine:
    """卡牌效果推断引擎。

    解析卡牌效果文本和历史打出记录，推断对手手牌组成。
    所有推断都转化为 HandConstraint 供 DynamicProbabilityEngine 使用。

    用法::

        engine = CardEffectInferenceEngine()
        engine.record_card_played(card_id, turn, source)
        engine.record_derived_card(derived_id, source_card_id, turn, derive_type)
        inferences = engine.get_inferences()
        constraints = engine.get_constraints()
    """

    def __init__(self):
        self._card_db = None
        self._played_cards: List[Dict] = []  # 已打出的卡牌记录
        self._derived_cards: List[DerivedCardRecord] = []  # 衍生卡牌记录
        self._revealed_cards: List[Dict] = []  # 揭示的手牌记录
        self._inferences: List[InferenceResult] = []  # 推断结果缓存
        self._dirty: bool = True  # 缓存是否需要重新计算

    def _ensure_card_db(self):
        if self._card_db is None:
            try:
                from analysis.data.card_data import get_db
                self._card_db = get_db()
            except Exception as e:
                logger.warning("无法加载卡牌数据库: %s", e)

    def record_card_played(
        self,
        card_id: str,
        turn: int,
        source: str = "deck",
        card_type: str = "",
        cost: int = 0,
    ):
        """记录对手打出的卡牌。"""
        self._played_cards.append({
            "card_id": card_id,
            "turn": turn,
            "source": source,
            "card_type": card_type,
            "cost": cost,
        })
        self._dirty = True

        # 分析打出效果
        self._analyze_play_effects(card_id, turn, source)

    def record_derived_card(
        self,
        derived_card_id: str,
        source_card_id: str,
        turn: int,
        derive_type: str = "generate",
    ):
        """记录衍生卡牌。

        Args:
            derived_card_id: 衍生出的卡牌 ID
            source_card_id: 产生此衍生牌的原始卡牌 ID
            turn: 产生回合
            derive_type: "discover" | "generate" | "shuffle" | "transform" | "corrupt"
        """
        self._derived_cards.append(DerivedCardRecord(
            card_id=derived_card_id,
            source_card_id=source_card_id,
            turn=turn,
            derive_type=derive_type,
        ))
        self._dirty = True

    def record_revealed_card(
        self,
        card_id: str,
        entity_id: int,
        turn: int,
    ):
        """记录对手被揭示的手牌。"""
        self._revealed_cards.append({
            "card_id": card_id,
            "entity_id": entity_id,
            "turn": turn,
        })
        self._dirty = True

    def _analyze_play_effects(self, card_id: str, turn: int, source: str):
        """分析打出的卡牌效果，生成推断。

        核心逻辑：当对手打出某张牌时，检查其效果文本，
        如果效果有条件触发（如"如果你手持龙牌"），则推断手牌。
        """
        self._ensure_card_db()
        if self._card_db is None:
            return

        card = self._card_db.get_card(card_id)
        if not card:
            return

        text = card.get("text", "") or ""
        mechanics = card.get("mechanics", []) or []

        # 1. 条件持有推断
        self._infer_conditional_hold(card_id, text, turn)

        # 2. 衍生牌推断
        self._infer_derived_cards(card_id, text, mechanics, turn)

        # 3. 打出时机推断
        self._infer_play_timing(card_id, card, turn)

    def _infer_conditional_hold(self, card_id: str, text: str, turn: int):
        """推断条件持有效果。

        当对手打出带有"如果你手持X"效果的牌且效果触发时，
        推断对手手牌中有对应种族/学派的牌。
        """
        # 中文条件效果 — races from hs_enums, schools from hs_enums
        from analysis.constants.hs_enums import RACE_ZH_MAP, SCHOOL_ZH_MAP

        # Build CN patterns from unified mappings
        _CN_PATTERNS = {}
        # Race patterns: "龙牌" → DRAGON, "野兽" → BEAST, etc.
        _RACE_SUFFIX = "牌"
        for cn, en in RACE_ZH_MAP.items():
            if en != "ALL":  # Skip "全部"
                _CN_PATTERNS[cn + _RACE_SUFFIX] = en
        # School patterns: "火焰法术" → FIRE, "冰霜法术" → FROST, etc.
        _SCHOOL_SUFFIX = "法术"
        for cn, en in SCHOOL_ZH_MAP.items():
            _CN_PATTERNS[cn + _SCHOOL_SUFFIX] = en

        # 英文条件效果
        _EN_PATTERNS = {
            "holding a dragon": "DRAGON",
            "holding a beast": "BEAST",
            "holding a demon": "DEMON",
            "holding a murloc": "MURLOC",
            "holding an elemental": "ELEMENTAL",
            "holding a mech": "MECHANICAL",
            "holding a pirate": "PIRATE",
            "fire spell": "FIRE",
            "frost spell": "FROST",
            "holy spell": "HOLY",
            "shadow spell": "SHADOW",
            "arcane spell": "ARCANE",
            "nature spell": "NATURE",
            "fel spell": "FEL",
        }

        text_lower = text.lower()

        for pattern, value in _CN_PATTERNS.items():
            if pattern in text:
                # 判断是种族还是学派
                if value in ("DRAGON", "BEAST", "DEMON", "MURLOC",
                             "ELEMENTAL", "MECHANICAL", "PIRATE"):
                    self._inferences.append(InferenceResult(
                        inference_type="conditional_hold",
                        card_id=card_id,
                        inferred_race=value,
                        probability=1.0,  # 效果触发了=100%确定
                        turn=turn,
                        source_description=f"对手打出 {card_id}，效果'如果你手持{pattern}'触发，推断持有{pattern}",
                    ))
                else:
                    self._inferences.append(InferenceResult(
                        inference_type="conditional_hold",
                        card_id=card_id,
                        inferred_school=value,
                        probability=1.0,
                        turn=turn,
                        source_description=f"对手打出 {card_id}，效果'如果你手持{pattern}'触发，推断持有{pattern}",
                    ))

        for pattern, value in _EN_PATTERNS.items():
            if pattern in text_lower:
                if value in ("DRAGON", "BEAST", "DEMON", "MURLOC",
                             "ELEMENTAL", "MECHANICAL", "PIRATE"):
                    self._inferences.append(InferenceResult(
                        inference_type="conditional_hold",
                        card_id=card_id,
                        inferred_race=value,
                        probability=1.0,
                        turn=turn,
                        source_description=f"Opponent played {card_id}, 'if holding {pattern}' triggered",
                    ))
                else:
                    self._inferences.append(InferenceResult(
                        inference_type="conditional_hold",
                        card_id=card_id,
                        inferred_school=value,
                        probability=1.0,
                        turn=turn,
                        source_description=f"Opponent played {card_id}, 'if holding {pattern}' triggered",
                    ))

    def _infer_derived_cards(
        self, card_id: str, text: str, mechanics: list, turn: int
    ):
        """推断衍生牌的产生。

        当对手打出 Discover/Generate 等效果的牌时，
        推断可能产生的衍生牌。
        """
        has_discover = "DISCOVER" in [m.upper() for m in mechanics]
        has_generate = any(
            kw in text for kw in ["召唤", "Summon", "生成", "Create", "发现", "Discover"]
        )

        if has_discover:
            self._inferences.append(InferenceResult(
                inference_type="derived_card",
                card_id=card_id,
                derive_type="discover",
                probability=1.0 / 3.0,  # Discover 是 3 选 1
                turn=turn,
                source_description=f"对手打出 {card_id}，可能产生 Discover 衍生牌 (1/3 概率每种)",
            ))

    def _infer_play_timing(self, card_id: str, card: dict, turn: int):
        """根据打出时机推断手牌信息。

        例如：
        - 对手在 T1 打出1费牌 → 可能有更多1费牌
        - 对手一直不出牌到 T5 → 可能有高费牌
        - 对手在满手牌时不出牌 → 可能有无法出的牌
        """
        cost = card.get("cost", 0)

        # 迟延出牌推断: 如果对手在高回合才出低费牌，
        # 可能之前一直在等费用或抽牌
        if turn >= 5 and cost <= 2:
            self._inferences.append(InferenceResult(
                inference_type="play_timing",
                card_id=card_id,
                probability=0.3,
                turn=turn,
                source_description=f"对手在 T{turn} 才打出 {cost}费牌，可能之前手牌不佳",
            ))

    def get_inferences(self) -> List[InferenceResult]:
        """获取所有推断结果。"""
        return list(self._inferences)

    def get_constraints(self) -> List[Dict]:
        """获取所有推断结果转化为约束条件。"""
        constraints = []
        for inf in self._inferences:
            if inf.inference_type == "conditional_hold":
                if inf.inferred_race:
                    constraints.append({
                        "type": "holds_race",
                        "value": inf.inferred_race,
                        "card_id": inf.card_id,
                        "turn": inf.turn,
                        "confidence": inf.probability,
                    })
                elif inf.inferred_school:
                    constraints.append({
                        "type": "holds_school",
                        "value": inf.inferred_school,
                        "card_id": inf.card_id,
                        "turn": inf.turn,
                        "confidence": inf.probability,
                    })
            elif inf.inference_type == "derived_card":
                constraints.append({
                    "type": "derived_from",
                    "source_card_id": inf.card_id,
                    "derive_type": getattr(inf, "derive_type", "generate"),
                    "probability": inf.probability,
                    "turn": inf.turn,
                })
        return constraints

    def get_derived_card_sources(self) -> Dict[str, List[DerivedCardRecord]]:
        """获取每个原始卡牌产生的衍生牌记录。"""
        sources: Dict[str, List[DerivedCardRecord]] = defaultdict(list)
        for dc in self._derived_cards:
            sources[dc.source_card_id].append(dc)
        return dict(sources)

    def get_play_timing_inferences(self) -> List[PlayTimingInference]:
        """获取打出时机推断。"""
        timing_inferences = []
        for inf in self._inferences:
            if inf.inference_type == "play_timing":
                timing_inferences.append(PlayTimingInference(
                    card_id=inf.card_id,
                    cost=0,  # 需要从卡牌数据库查询
                    turn_played=inf.turn,
                    inference=inf.source_description,
                ))
        return timing_inferences

    def reset(self):
        """重置所有推断状态。"""
        self._played_cards.clear()
        self._derived_cards.clear()
        self._revealed_cards.clear()
        self._inferences.clear()
        self._dirty = True

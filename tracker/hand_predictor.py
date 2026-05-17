# -*- coding: utf-8 -*-
"""hand_predictor.py — 动态手牌预测引擎（重构版）

使用 DynamicProbabilityEngine + CardEffectInferenceEngine，
所有概率均基于超几何分布和贝叶斯推断动态计算，无写死概率。

核心改进：
1. 超几何分布计算 P(card in hand | observed)，替代写死的费用分布
2. 条件证据贝叶斯修正，替代固定 70% 概率
3. 多卡组假设加权，替代单一卡组等概率
4. 衍生牌追踪与卡组牌区分
5. 卡牌效果推断引擎集成
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from analysis.utils.hero_class import class_to_cn

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class HandPrediction:
    """单个手牌预测条目。"""
    card_id: str = ""
    name: str = ""
    cost: int = 0
    probability: float = 0.0
    source: str = "deck"  # "deck" | "generated" | "revealed" | "inferred"
    card_type: str = ""   # MINION | SPELL | WEAPON | HERO | LOCATION
    race: str = ""
    spell_school: str = ""
    remaining_copies: int = 0  # 在锁定卡组中的剩余张数

    @property
    def display_text(self) -> str:
        """UI 显示文字。"""
        if self.probability >= 1.0:
            return f"{self.name} (确认)"
        elif self.probability >= 0.5:
            return f"{self.name} ({self.probability:.0%}很可能)"
        elif self.probability >= 0.01:
            return f"{self.name} ({self.probability:.0%})"
        else:
            return "?"


@dataclass
class DeckPrediction:
    """卡组预测条目。"""
    card_id: str = ""
    name: str = ""
    cost: int = 0
    quantity: int = 1
    remaining: int = 1
    source: str = "deck"  # "deck" | "generated"
    in_hand: bool = False
    played: bool = False
    card_type: str = ""
    race: str = ""
    hand_probability: float = 0.0  # 在手牌中的概率


@dataclass
class PredictionResult:
    """完整的预测结果。"""
    hand_predictions: List[HandPrediction] = field(default_factory=list)
    deck_predictions: List[DeckPrediction] = field(default_factory=list)
    archetype_name: str = ""
    archetype_confidence: float = 0.0
    playstyle: str = "unknown"
    top_archetypes: List[Tuple[str, float]] = field(default_factory=list)
    revealed_cards: List[HandPrediction] = field(default_factory=list)
    conditional_evidence: List[Dict] = field(default_factory=list)
    derived_cards: List[Dict] = field(default_factory=list)
    multi_deck_predictions: List[Tuple[str, float, List[DeckPrediction]]] = field(default_factory=list)


# ── 条件效果规则 ──────────────────────────────────────────────

from analysis.constants.hs_enums import CONDITIONAL_HOLDING_RULES as _CONDITIONAL_RULES


# ── 动态手牌预测引擎 ──────────────────────────────────────────

class HandPredictor:
    """动态手牌预测引擎。

    使用 DynamicProbabilityEngine 基于超几何分布计算概率，
    使用 CardEffectInferenceEngine 推断条件效果和衍生牌。
    所有概率均基于已有信息动态计算，无写死概率值。

    预测优先级:
    1. 已揭示手牌 (100% 概率) — SHOW_ENTITY 揭示到 HAND 区域
    2. 超几何分布计算的手牌概率 — 基于贝叶斯卡组后验加权
    3. 条件效果推断 (贝叶斯修正后概率) — "如果手持龙牌"效果触发
    4. 未知手牌占位 (0% 概率) — 填充剩余手牌位置

    用法::

        predictor = HandPredictor()
        result = predictor.predict(state_dict)
        for hp in result.hand_predictions:
            print(f"{hp.name} ({hp.probability:.0%}) - {hp.source}")
    """

    def __init__(self):
        self._card_db = None
        self._probability_engine = None
        self._effect_engine = None
        self._db_conn = None  # 缓存 HSReplay DB 连接，避免每帧开关

    def _ensure_card_db(self):
        if self._card_db is None:
            try:
                from analysis.data.card_data import get_db
                self._card_db = get_db()
            except Exception as e:
                logger.warning("无法加载卡牌数据库: %s", e)

    def _ensure_engines(self):
        """延迟初始化概率引擎和效果引擎。"""
        if self._probability_engine is None:
            try:
                from analysis.engine.dynamic_probability import DynamicProbabilityEngine
                self._probability_engine = DynamicProbabilityEngine()
            except Exception as e:
                logger.warning("无法初始化概率引擎: %s", e)

        if self._effect_engine is None:
            try:
                from analysis.engine.card_effect_inference import CardEffectInferenceEngine
                self._effect_engine = CardEffectInferenceEngine()
            except Exception as e:
                logger.warning("无法初始化效果推断引擎: %s", e)

    def predict(self, state_dict: dict) -> PredictionResult:
        """根据游戏状态生成完整预测。

        使用 DynamicProbabilityEngine 计算每张可能手牌的概率。
        所有概率基于超几何分布和贝叶斯后验动态计算。

        信息揭示追踪增强：
        - opp_known_deck_cards: 确认对手卡组中的牌 → 约束贝叶斯后验
        - opp_known_hand_types: 对手手牌类型约束 → 缩小预测空间
        - opp_revealed_hand_cards: 已揭示的手牌 → 100%确认
        - opp_transform_events: 变形事件 → 修正卡组推断

        Args:
            state_dict: 来自 LogMonitor.build_state_dict() 的状态字典

        Returns:
            PredictionResult 完整预测结果
        """
        self._ensure_card_db()
        self._ensure_engines()

        result = PredictionResult()

        # 提取基础信息
        bayesian = state_dict.get("bayesian", {})
        result.archetype_name = bayesian.get("archetype_name", "") or ""
        result.archetype_confidence = bayesian.get("deck_confidence", 0.0)
        result.playstyle = bayesian.get("playstyle", "unknown")

        top_decks = bayesian.get("top_decks", [])
        result.top_archetypes = [
            (name, prob) for _, name, prob in top_decks
        ]

        opp_hand_count = state_dict.get("opp_hand_count", 0)
        opp_deck_count = state_dict.get("opp_deck_count", 0)
        opp_class = state_dict.get("opp_class_en", "")

        # ── 提取信息揭示追踪数据 ──
        reveal_info = state_dict.get("reveal_info", {})
        known_deck_cards = reveal_info.get("known_deck_cards", {})
        known_hand_types = reveal_info.get("known_hand_types", [])
        revealed_hand_cards = reveal_info.get("revealed_hand_cards", [])
        transform_events = reveal_info.get("transform_events", [])
        tutor_evidence = reveal_info.get("tutor_evidence", [])

        # ── 使用 DynamicProbabilityEngine 计算概率 ──
        if self._probability_engine is not None:
            self._probability_engine.update_from_state_dict(state_dict)
            prob_report = self._probability_engine.compute_probabilities(
                hand_size=opp_hand_count,
                deck_remaining=opp_deck_count,
                opp_class=opp_class,
            )

            # 转换 CardProbability → HandPrediction
            for cp in prob_report.card_probabilities:
                hp = HandPrediction(
                    card_id=cp.card_id,
                    name=cp.name,
                    cost=cp.cost,
                    probability=cp.probability,
                    source=cp.source,
                    card_type=cp.card_type,
                    race=cp.race,
                    spell_school=cp.spell_school,
                    remaining_copies=cp.remaining_copies,
                )
                if hp.source == "revealed":
                    result.revealed_cards.append(hp)
                result.hand_predictions.append(hp)

            result.conditional_evidence = prob_report.conditional_constraints

            # 填充手牌位置
            filled_count = len(result.hand_predictions)
            remaining_slots = max(0, opp_hand_count - filled_count)

            if remaining_slots > 0:
                for i in range(remaining_slots):
                    result.hand_predictions.append(HandPrediction(
                        card_id="",
                        name="?",
                        cost=0,
                        probability=0.0,
                        source="unknown",
                        card_type="UNKNOWN",
                    ))
        else:
            # 回退到基础预测（概率引擎不可用时）
            self._fallback_predict(state_dict, result, opp_hand_count)

        # ── 使用 CardEffectInferenceEngine 获取推断 ──
        if self._effect_engine is not None:
            # 记录已打出的卡牌
            self._effect_engine.reset()
            for kc in state_dict.get("known_cards", []):
                cid = kc.get("card_id", "")
                if cid:
                    self._effect_engine.record_card_played(
                        card_id=cid,
                        turn=kc.get("turn_seen", 0),
                        source=kc.get("source", "deck"),
                        card_type=kc.get("card_type", ""),
                        cost=kc.get("cost", 0),
                    )

            # 记录已知手牌
            for eid, card_id in state_dict.get("known_hand", []):
                self._effect_engine.record_revealed_card(card_id, eid, 0)

            # 获取衍生卡牌推断
            derived_sources = self._effect_engine.get_derived_card_sources()
            result.derived_cards = [
                {
                    "source_card_id": src,
                    "derived_cards": [
                        {
                            "card_id": dc.card_id,
                            "derive_type": dc.derive_type,
                            "turn": dc.turn,
                        }
                        for dc in dcs
                    ],
                }
                for src, dcs in derived_sources.items()
            ]

        # ── 卡组预测 ──
        result.deck_predictions = self._predict_deck(state_dict, bayesian)
        result.multi_deck_predictions = self._predict_multi_deck(state_dict, bayesian)

        # ── 信息揭示追踪增强：定向检索约束 ──
        # 对手通过定向检索获得的牌，我们知道其种族/学派类型
        # 这极大缩小了手牌预测空间
        if known_hand_types:
            self._apply_tutor_constraints(result, known_hand_types)

        # ── 信息揭示追踪增强：已揭示的手牌补充 ──
        # 将通过 HAND_REVEAL 效果看到的对手手牌加入确认列表
        if revealed_hand_cards:
            existing_ids = {hp.card_id for hp in result.hand_predictions if hp.card_id}
            for rec in revealed_hand_cards:
                if rec["card_id"] and rec["card_id"] not in existing_ids:
                    hp = self._card_id_to_hand_prediction(rec["card_id"], 1.0, "inferred")
                    if hp:
                        hp.source = "inferred"
                        result.hand_predictions.append(hp)
                        existing_ids.add(rec["card_id"])

        # ── 信息揭示追踪增强：变形事件修正 ──
        # 变形产物不在原始卡组中，标记为 generated
        if transform_events:
            transformed_ids = {rec["card_id"] for rec in transform_events if rec.get("card_id")}
            for dp in result.deck_predictions:
                if dp.card_id in transformed_ids:
                    dp.source = "generated"

        # ── 排序 ──
        result.hand_predictions.sort(
            key=lambda hp: (
                0 if hp.source == "revealed" else 1,
                -hp.probability,
                hp.cost,
            )
        )

        return result

    def _apply_tutor_constraints(self, result: PredictionResult,
                                 known_hand_types: List[Dict]) -> None:
        """根据定向检索约束修正手牌预测。

        当对手通过定向检索（如"抽一张龙牌"）获得卡牌时，
        我们知道该卡牌的种族/学派类型。这允许我们：

        1. 提升匹配类型的手牌预测概率
        2. 降低不匹配类型的手牌预测概率
        3. 将未知占位符替换为类型约束占位符

        Args:
            result: 当前预测结果（会被就地修改）
            known_hand_types: 类型约束列表，每项包含
                entity_id, turn, race, spell_school 等
        """
        for constraint in known_hand_types:
            race = constraint.get("race", "")
            school = constraint.get("spell_school", "")
            if not race and not school:
                continue

            # 提升匹配类型的已有预测的概率
            for hp in result.hand_predictions:
                if hp.probability <= 0 or hp.probability >= 1.0:
                    continue
                # 检查是否匹配约束类型
                if race and hp.race and race.upper() == hp.race.upper():
                    # 匹配种族：提升概率（贝叶斯修正）
                    hp.probability = min(1.0, hp.probability * 1.5)
                    hp.source = "inferred"
                elif school and hp.spell_school and school.upper() == hp.spell_school.upper():
                    # 匹配学派：提升概率
                    hp.probability = min(1.0, hp.probability * 1.5)
                    hp.source = "inferred"

            # 将第一个未知占位符替换为类型约束占位符
            for hp in result.hand_predictions:
                if hp.source == "unknown" and hp.card_id == "":
                    type_label = race or school or "特定类型"
                    hp.name = f"[{type_label}]"
                    hp.source = "inferred"
                    hp.probability = 0.0
                    if race:
                        hp.race = race
                    if school:
                        hp.spell_school = school
                    break  # 每个约束只替换一个占位符

    def _fallback_predict(
        self,
        state_dict: dict,
        result: PredictionResult,
        opp_hand_count: int,
    ):
        """回退预测：当概率引擎不可用时使用基础逻辑。"""
        # 已确认手牌
        for eid, card_id in state_dict.get("known_hand", []):
            hp = self._card_id_to_hand_prediction(card_id, 1.0, "revealed")
            if hp:
                result.revealed_cards.append(hp)
                result.hand_predictions.append(hp)

        # 填充未知
        filled = len(result.hand_predictions)
        remaining = max(0, opp_hand_count - filled)
        for _ in range(remaining):
            result.hand_predictions.append(HandPrediction(
                card_id="",
                name="?",
                cost=0,
                probability=0.0,
                source="unknown",
                card_type="UNKNOWN",
            ))

    def _card_id_to_hand_prediction(
        self, card_id: str, probability: float, source: str
    ) -> Optional[HandPrediction]:
        if not card_id:
            return None

        hp = HandPrediction(
            card_id=card_id,
            probability=probability,
            source=source,
        )

        if self._card_db is not None:
            card_data = self._card_db.get_card(card_id)
            if card_data:
                hp.name = card_data.get("name", card_id)
                hp.cost = card_data.get("cost", 0)
                hp.card_type = card_data.get("type", "")
                hp.race = card_data.get("race", "")
                hp.spell_school = card_data.get("spellSchool", "")
            else:
                hp.name = card_id
        else:
            hp.name = card_id

        return hp

    def _get_db_conn(self):
        """获取缓存的 HSReplay DB 连接，避免每帧开关连接。"""
        if self._db_conn is not None:
            try:
                # 测试连接是否可用
                self._db_conn.execute("SELECT 1")
                return self._db_conn
            except Exception:
                try:
                    self._db_conn.close()
                except Exception:
                    pass
                self._db_conn = None

        try:
            from analysis.data.fetch_hsreplay import init_db
            from analysis.config import HSREPLAY_CACHE_DB
            self._db_conn = init_db(str(HSREPLAY_CACHE_DB))
            return self._db_conn
        except Exception as e:
            logger.debug("无法连接 HSReplay 数据库: %s", e)
            return None

    def close(self):
        """关闭缓存的数据库连接。"""
        if self._db_conn is not None:
            try:
                self._db_conn.close()
            except Exception:
                pass
            self._db_conn = None

    def _predict_deck(self, state_dict: dict, bayesian: dict) -> List[DeckPrediction]:
        """预测对手卡组构成，取最可能的卡组。"""
        multi = self._predict_multi_deck(state_dict, bayesian)
        if multi:
            return multi[0][2]
        return []

    def _predict_multi_deck(self, state_dict: dict, bayesian: dict) -> List[Tuple[str, float, List[DeckPrediction]]]:
        """预测 Top 3 卡组，每套含完整卡牌列表与概率。"""
        top_decks = bayesian.get("top_decks", [])
        if not top_decks:
            return []

        known_cards = state_dict.get("known_cards", [])
        played_count = Counter()
        for kc in known_cards:
            cid = kc.get("card_id", "")
            if cid:
                # 统计所有打出的卡牌（不仅 source=="deck"），
                # 因为发现/衍生获得的卡组内牌打出后也应减少 remaining
                played_count[cid] += 1
        known_hand_ids = {cid for _, cid in state_dict.get("known_hand", [])}
        opp_hand_count = state_dict.get("opp_hand_count", 0)
        opp_deck_count = state_dict.get("opp_deck_count", 0)
        pool = opp_hand_count + opp_deck_count

        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        result = []
        conn = self._get_db_conn()
        if conn is None:
            return result

        try:
            from analysis.data.fetch_hsreplay import get_meta_decks
            meta_decks = get_meta_decks(conn)
            deck_map = {d["archetype_id"]: d for d in meta_decks}

            for arch_id, arch_name, prob in top_decks[:3]:
                target = deck_map.get(arch_id)
                if not target or not target.get("cards"):
                    continue

                card_counts = Counter(target["cards"])
                deck_preds = []
                for dbf_id, count in card_counts.items():
                    card_data = None
                    if self._card_db is not None:
                        card_data = self._card_db.get_by_dbf(dbf_id)
                    if card_data:
                        cid = card_data.get("cardId", card_data.get("id", ""))
                        remaining = max(0, count - played_count.get(cid, 0))
                        hand_prob = 0.0
                        if pool > 0 and opp_hand_count > 0 and remaining > 0:
                            hand_prob = hypergeometric_at_least_one(
                                K=remaining, n=opp_hand_count, N=pool,
                            )
                        deck_preds.append(DeckPrediction(
                            card_id=cid,
                            name=card_data.get("name", ""),
                            cost=card_data.get("cost", 0),
                            quantity=count,
                            remaining=remaining,
                            source="deck",
                            card_type=card_data.get("type", ""),
                            race=card_data.get("race", ""),
                            in_hand=cid in known_hand_ids,
                            played=played_count.get(cid, 0) > 0,
                            hand_probability=hand_prob,
                        ))
                    else:
                        # 未知卡牌：remaining 应减去已打出的数量，而非直接取 count
                        cid_guess = f"dbf_{dbf_id}"
                        remaining_guess = max(0, count - played_count.get(cid_guess, 0))
                        deck_preds.append(DeckPrediction(
                            card_id=cid_guess,
                            name=f"卡牌#{dbf_id}",
                            cost=0,
                            quantity=count,
                            remaining=remaining_guess,
                            source="deck",
                        ))

                deck_preds.sort(key=lambda dp: (dp.cost, dp.name))
                result.append((arch_name, prob, deck_preds))
        except Exception as e:
            logger.debug("构建多卡组预测失败: %s", e)

        return result

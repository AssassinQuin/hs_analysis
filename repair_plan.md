# 修复计划：对手手牌预测精度优化

## 概述

基于根因分析（P0-P3）的逐项修复方案。按优先级排序。

---

## P0 — 收紧预测数量（Precision 低）

**问题**: 预测输出平均 29 张/回合，但对手只有 3-10 张手牌，导致 Precision 仅 10.2%。

**根因分析**:
- `HandPredictor.predict()` 返回全部概率 >0 的卡牌，不做数量截断
- 验证脚本 `validate_hand_predictions.py:330` 只按 `> 0.01`（1%）过滤，仍保留大量低概率误报
- `opp_hand_count` 在 prediction time 已知（`hand_predictor.py:193`），但未被用于截断

### 修复方案 A（推荐 — 改动最小，效果最大）

在 `hand_predictor.py` 的 `predict()` 末尾（排序后、返回前）添加截断逻辑：

```python
# 在 line 380 (result.hand_predictions.sort) 之后、line 382 (return result) 之前插入
if opp_hand_count > 0 and len(result.hand_predictions) > opp_hand_count:
    # 1. 分离 revealed 卡牌（100% 确定）和概率预测
    revealed_cards = [hp for hp in result.hand_predictions if hp.source == "revealed"]
    prob_cards = [hp for hp in result.hand_predictions if hp.source != "revealed"]

    # 2. 保留所有 revealed 卡牌（这些是已知事实）
    # 3. 概率预测只保留概率最高的 top K 张
    remaining_slots = max(0, opp_hand_count - len(revealed_cards))
    prob_sorted = sorted(prob_cards, key=lambda hp: -hp.probability)
    result.hand_predictions = revealed_cards + prob_sorted[:remaining_slots]
```

**影响评估**:
- ✅ Precision 大幅提升（预测数与实际手牌数匹配）
- ⚠️ Recall 可能略降（极端情况下，真值卡牌排名靠后被截断）
- ✅ UI 显示更清晰、更真实

**可选变体 — 缓存更多候选**:
- 截断时额外保留 top K×2 到 `result.extended_candidates`（供 UI 或调试展开用）
- 不影响 Precision 指标，但保留扩展能力

### 验证脚本同步修改

`validate_hand_predictions.py:330` 中的过滤逻辑需同步：
```python
# 在验证时，也采用 opp_hand_count 截断（而非仅 >1% 过滤）
preds = sorted(
    [p for p in result.hand_predictions if p.probability > 0.01],
    key=lambda p: (-p.probability, p.cost),
)
if opp_hand_count > 0:
    preds = preds[:opp_hand_count]
```

### 文件清单
| 文件 | 修改内容 |
|------|---------|
| `tracker/hand_predictor.py` | line 374-382 之间插入预测数截断 |
| `scripts/validate_hand_predictions.py` | line 330 附近添加 opp_hand_count 截断 |

---

## P1 — 扩展卡组池

**问题**: HSReplay 缓存中仅 2 个 MAGE 卡组（"Zoo Warlock" + "Custom_MAGE_16"），且大量 dbfId 无法解析。

### 子问题 1a: 卡组池太少

**根因**:
- `fetch_hsreplay.py:373` 从 `standard_ccp_signature_core.components` 提取卡组签名，但 HSReplay API 可能对 MAGE 只返回了少量 archetype
- `HSREPLAY_ARCHETYPES_URL` = `https://hsreplay.net/api/v1/archetypes/` — 此端点可能过期
- 缓存位于 `card_data/{build}/hsreplay_cache.db`，可能未及时刷新

**修复**:
1. **验证 API 端点**: 手动调用 `fetch_hsreplay.main()` 确认 archetype API 返回状态
2. **增加 fallback 广度**: 在 `fetch_hsreplay.py` 中添加 `?game_type=RANKED_STANDARD` 参数到 archetypes URL（如果未传）
3. **补充 MAGE 卡组**: 在 `deck_codes.txt` 中添加更多 MAGE 标准构筑卡组（至少 5-10 个不同 archetype）
4. **自动刷新机制**: 在 `tracker/app.py` 启动时检查缓存时效，超过 CACHE_DAYS（默认 7）自动触发刷新

### 子问题 1b: dbfId 无法解析为卡牌名

**根因**:
- `card_data.py:652-656` 在 `CardDB._index_card()` 中构建 `dbf_lookup` 映射
- 部分 dbfId 在 HSReplay 签名中但不在 card_data 的 JSON 中（可能是非收集卡牌或已退环境的卡）

**修复**:
1. **日志完善**: 在 `BayesianOpponent.card_name()` 添加 warn 日志，记录无法解析的 dbfId
2. **兜底映射**: 当 dbfId 无法解析时，使用 `str(dbfId)` 作为 fallback 名字（而非 None），避免签名匹配静默失败
3. **检查数据集完整性**: 确认 `card_data/242566/` 覆盖所有在用的 dbfId

### 文件清单
| 文件 | 修改内容 |
|------|---------|
| `analysis/data/fetch_hsreplay.py` | 确认 API 端点 + 添加 game_type 参数 + 自动刷新逻辑 |
| `analysis/utils/bayesian_opponent.py` | `card_name()` 添加 warn 日志 + fallback |
| `deck_codes.txt` | 补充 MAGE 标准构筑卡组 |
| `analysis/config.py` | 可选：调整 CACHE_DAYS |

---

## P2 — 调整高费卡持牌概率

**问题**: 8 费法术"焚火林地"从 T2 到 T23 概率被 unplayed_affordable 证据持续压低，不符合预期。

**根因**:
- `world_model.py:212-219` 中 `_compute_unplayed_pass_lr()` 对高费卡（cost > mana）给出 LR 1.0-4.0（提升概率），逻辑正确
- `world_model.py:624-648` 中 partial_play 分支对高费卡仅给出 LR 1.0 + 0.2×hold_bias（最多 1.2）
- **核心问题**: 当 mana ≥ cost 后（T8+），低费分支 LR = 0.3 - cost×0.03 → 8 费卡 LR = 0.06（强烈降权）
- **累计效应**: 多回合证据以乘法累积。`dynamic_probability.py:1042-1059` 中对所有匹配的 LR 做乘法。10 回合降权后 `0.06^10 ≈ 10^{-12}` → 几乎归零

### 修复方案

**方案 A (核心 — LR 衰减机制)**

在 `dynamic_probability.py` 的 `_apply_world_model_evidence()` 中，添加证据时效衰减：

```python
# 对 older turns 的证据施加衰减权重
# 当前回合 evidence 权重 = 1.0
# N 回合前 evidence 权重 = decay_rate^N
EVIDENCE_DECAY = 0.7  # 每回合衰减 30%

# 在合并 LR 之前：
for ev in evidence_list:
    turns_ago = current_turn - ev.turn
    if turns_ago > 0:
        # 旧的证据影响减弱
        decay = EVIDENCE_DECAY ** turns_ago
        effective_lr = 1.0 + (ev.likelihood - 1.0) * decay
    else:
        effective_lr = ev.likelihood
```

**方案 B (辅助 — LR 下限保护)**

在 `_compute_unplayed_pass_lr()` 中增加 LR 下限：
```python
# 当前: lr = max(0.1, 0.3 - card_cost * 0.03)
# 8 费 → 0.06
# 改为:
lr = max(0.3, 0.5 - card_cost * 0.02)  
# 8 费 → 0.34（不再极端降权）
```

**方案 C (辅助 — 高费正面证据加强)**

在 partial_play 分支中，对 `cost > available_mana` 的高费卡加强 LR：
```python
# 当前: lr = 1.0 + 0.2 * hold_bias  (max 1.2)
# 改为:
excess = (card_cost - available_mana)  # 差额法力
lr = 1.0 + min(2.0, 0.3 * hold_bias + excess * 0.15)
# 8 费 T3 (3 mana) → LR ≈ 1.0 + 0.3 + 0.75 = 2.05
```

**方案 D (辅助 — 超几何基线上调)**

`dynamic_probability.py:848-856` 中的 hypergeometric 基线使用 `K=remaining_copies, n=hand_size, N=pool_size`。对高费非关键卡，可小幅上调 baseline：
- 这是最后的调参手段，优先级最低

### 文件清单
| 文件 | 修改内容 |
|------|---------|
| `analysis/engine/dynamic_probability.py` | 添加 LR 时效衰减（方案 A） |
| `analysis/engine/world_model.py` | 方案 B `_compute_unplayed_pass_lr` LR 下限 + 方案 C partial_play 高费增强 |

---

## P3 — Discover 追踪加入 known_hand

**问题**: "梦魇之王萨维斯" 是 Discover 衍生物，不在对手原始牌库中，系统完全无法预测。

**根因**:
- `GlobalTracker` 未解析 Discover 事件的 `SHOW_ENTITY` 数据（3 选 1 的 temporary zone）
- `CardEffectInferenceEngine.record_derived_card()` 方法已存在但从未从 Power.log 管道调用
- Discover 选择后的卡牌只作为 GENERATED 标记，未被加入 `known_hand` 或 `opp_hand_candidates`

### 修复方案

**步骤 1: 解析 Discover 事件（GlobalTracker）**

在 `analysis/watcher/global_tracker.py` 中：
1. 追踪 `SHOW_ENTITY` 事件中 zone=TEMPORARY 或 zone=SETASIDE 的实体（这是 Discover 选项的常见 zone）
2. 发现一个 entity 从 temporary/set-aside zone 移动到 HAND zone → 这就是被选中的 Discover 卡
3. 记录到 `self._opp_discovered_cards: List[Tuple[str, int]]`（card_id, turn）

需要在 `on_zone_change()` 或 `on_show_entity()` 中添加处理逻辑。

**步骤 2: 传递到预测管道**

在 `tracker/hand_predictor.py` 的 `predict()` 中：
1. 从 state_dict 读取 `opp_discovered_cards`
2. 对每张 Discover 卡，调用 `self._effect_engine.record_derived_card(card_id, source_card_id, turn, "discover")`
3. 将 Discover 卡加入概率引擎的 generated_cards 集合（确保它们不被 deck-only 过滤去掉）
4. 将 Discover 卡加入 `result.hand_predictions`（如果概率>阈值）

**步骤 3: 加入候选池**

在 `analysis/utils/deck_pool_tracker.py` 中：
1. 已有 `_generated` 集合，把 Discover 卡加入该集合
2. `fill_unknown_hand()` 会从 available pool 采样，需确保 generated 卡被考虑

### 文件清单
| 文件 | 修改内容 |
|------|---------|
| `analysis/watcher/global_tracker.py` | 添加 Discover 事件追踪（SHOW_ENTITY zone 变化检测） |
| `analysis/watcher/tracker_types.py` | 可选：添加 `opp_discovered_cards` 类型字段 |
| `tracker/hand_predictor.py` | 在 predict() 中读取 Discover 卡并注入管道 |
| `analysis/engine/card_effect_inference.py` | 确保 record_derived_card 被调用 |
| `analysis/utils/deck_pool_tracker.py` | 确保 Discover 卡加入 _generated 集合 |

---

## 实施顺序

| 优先级 | 项目 | 预估工时 | 风险 | 独立可测 |
|--------|------|---------|------|---------|
| P0 | 预测数截断 | 0.5h | 低 | ✅ |
| P1a | 扩展卡组池（deck_codes.txt 补充） | 0.5h | 低 | ✅ |
| P1b | dbfId 解析修复 | 0.5h | 低 | ✅ |
| P2 | 高费卡概率调整 | 1h | 中 | ✅ |
| P3 | Discover 追踪 | 3h | 高 | ✅（需 Power.log 测试数据） |

## 验证方法

参见 `test_plan.md`

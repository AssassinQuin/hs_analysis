# 测试计划：对手手牌预测精度优化

## 测试策略总览

| 层级 | 覆盖内容 | 工具 |
|------|---------|------|
| L0 — 单元测试 | 单函数/单方法行为验证 | `pytest` |
| L1 — 集成测试 | 修改后的管道端到端 | `pytest` + mock |
| L2 — 验证回放 | 在真实日志上跑完整验证 | `validate_hand_predictions.py` |
| L3 — 对比验证 | 改前 vs 改后指标对比 | 定制对比脚本 |

---

## P0 — 预测数截断测试

### L0 单元测试

**文件**: `tests/tracker/test_hand_predictor.py`（新建，或追加到已有测试文件）

**测试用例 1**: 截断逻辑基本功能
```python
def test_trim_predictions_to_hand_count():
    """当 opp_hand_count < 总预测数时，正确截断到 opp_hand_count 张。"""
    predictor = HandPredictor()
    state = build_state_with_opp_hand_count(5)  # 已知手牌 5 张
    result = predictor.predict(state)
    assert len(result.hand_predictions) == 5
```

**测试用例 2**: revealed 卡牌优先保留
```python
def test_trim_preserves_revealed():
    """截断时 revealed 卡牌（source="revealed"）优先保留。"""
    state = build_state_with_revealed_cards(3)  # 3 张 revealed
    state["opp_hand_count"] = 4
    result = predictor.predict(state)
    revealed = [hp for hp in result.hand_predictions if hp.source == "revealed"]
    assert len(revealed) == 3  # 全部保留
    assert len(result.hand_predictions) == 4
```

**测试用例 3**: opp_hand_count = 0 时不截断
```python
def test_no_trim_when_hand_count_zero():
    """opp_hand_count 为 0（未知）时，返回所有预测不截断。"""
    state = build_state_with_opp_hand_count(0)
    result = predictor.predict(state)
    # 应该输出全部 > 0 的预测（不截断）
```

**测试用例 4**: 预测数少于 opp_hand_count 时不截断
```python
def test_no_trim_when_fewer_predictions():
    """总预测数 < opp_hand_count 时不做截断（保留全部）。"""
    state = build_state_with_opp_hand_count(20)
    state = force_few_predictions(state)
    result = predictor.predict(state)
    # 全量保留，不做空填充
```

**测试用例 5**: 按概率排序正确
```python
def test_trim_orders_by_probability():
    """截断后保留概率最高的卡牌。"""
    state = build_state_with_opp_hand_count(3)
    result = predictor.predict(state)
    non_revealed = [hp for hp in result.hand_predictions if hp.source != "revealed"]
    for i in range(len(non_revealed) - 1):
        assert non_revealed[i].probability >= non_revealed[i+1].probability
```

### L2 验证回放测试

在改前和改后分别运行验证脚本，对比 Precision 指标：

```bash
# 改前（基线）
python scripts/validate_hand_predictions.py --log logs/game5.power.log --gt ground_truth.json
# → 输出: Precision 10.2%, Recall xx%, F1 xx%

# 改后
python scripts/validate_hand_predictions.py --log logs/game5.power.log --gt ground_truth.json
# → 预期: Precision 大幅提升（可能到 30-50%），Recall 轻微下降
```

**关键指标**:
| 指标 | 改前 | 预期改后 | 说明 |
|------|------|---------|------|
| Precision | 10.2% | ≥ 30% | 预测数接近实际手牌数 |
| Recall | (基线) | 降幅 ≤ 15% | 检查真值卡是否被截断 |
| F1 | (基线) | 应提升 | 综合指标 |
| avg predictions/turn | ~29 | ≤ opp_hand_count | 核心改进 |

### L3 对比验证

**手动检查**: 选择一个已知手牌的游戏，对比改前改后的预测列表，确认：
- 真值卡牌仍在 top-N 内（高 recall）
- 低概率噪声被截断（高 precision）

---

## P1 — 扩展卡组池测试

### L0 单元测试

**文件**: `tests/data/test_fetch_hsreplay.py` + `tests/utils/test_bayesian_opponent.py`

**测试用例 1.1**: API 返回解码
```python
def test_archetype_api_response():
    """验证 fetch_hsreplay.main() 正确解析 HSReplay archetypes 响应。"""
    # mock API 返回
    decks = run_fetch(mock=True)
    mage_decks = [d for d in decks if d["class"] == "MAGE"]
    assert len(mage_decks) >= 5  # 预期 MAGE 至少有 5 个 archetype
```

**测试用例 1.2**: dbfId 解析 fallback
```python
def test_card_name_fallback():
    """无法解析 dbfId 时使用 str(dbfId) 作为 fallback。"""
    model = BayesianOpponentModel()
    name = model.card_name(999999)  # 不存在的 dbfId
    assert name == "999999"  # 不应返回 None
```

**测试用例 1.3**: deck_codes.txt 补充生效
```python
def test_deck_codes_mage_decks():
    """deck_codes.txt 中的 MAGE 卡组被正确加载。"""
    model = BayesianOpponentModel()
    mage_decks = [d for d in model.decks if d["class"] == "MAGE"]
    assert len(mage_decks) >= 3  # 至少有 3 个 MAGE 卡组（含 deck_codes.txt）
```

### L2 集成测试

```bash
# 1. 手动刷新 HSReplay 缓存
python scripts/run_fetch.py --force

# 2. 检查缓存的 Archetype 数量
python -c "
import sqlite3
db = sqlite3.connect('card_data/242566/hsreplay_cache.db')
rows = db.execute('SELECT class, COUNT(*) FROM meta_decks GROUP BY class').fetchall()
for cls, cnt in rows:
    print(f'{cls}: {cnt}')
"
# → 预期: MAGE 至少有 5+ archetype

# 3. 运行验证脚本确认 dbfId 解析日志
python scripts/validate_hand_predictions.py --log logs/game5.power.log --verbose 2>&1 | grep "dbfId"
# → 预期: 无 dbfId 解析失败警告（或只有合理的少数几个）
```

---

## P2 — 高费卡概率调整测试

### L0 单元测试

**文件**: `tests/engine/test_world_model.py`（追加）

**测试用例 2.1**: 高费卡早回合正向证据
```python
def test_high_cost_card_early_turns_boost():
    """T1-T7 对手法力不足时，高费卡应获得正向 LR（概率提升）。"""
    # pass turn, T3, 3 mana, cost=8
    lr = _compute_unplayed_pass_lr(available_mana=3, hand_size=5, pool_size=25, card_cost=8)
    assert lr > 1.0  # 应提升概率
```

**测试用例 2.2**: LR 衰减机制
```python
def test_lr_decay_older_evidence():
    """旧回合的 unplayed_affordable 证据影响力应随时间衰减。"""
    engine = DynamicProbabilityEngine()
    # T3 的证据在 T10 时影响力应为初始的 decay^(7) 倍
    evidence = BehaviorEvidence(
        evidence_type="unplayed_affordable",
        turn=3,
        inferred_tags={"cost": "8"},
        likelihood=0.1,  # 强烈降权
    )
    # 在 T10 应用
    decayed_lr = engine._decay_evidence(evidence, current_turn=10)
    expected_lr = 1.0 + (0.1 - 1.0) * (0.7 ** 7)  # 0.7^7 ≈ 0.082
    assert abs(decayed_lr - expected_lr) < 0.01
```

**测试用例 2.3**: LR 下限保护
```python
def test_lr_floor_protection():
    """unplayed_affordable LR 不应低于下限（避免多回合累积归零）。"""
    lr = _compute_unplayed_pass_lr(available_mana=10, hand_size=5, pool_size=25, card_cost=8)
    assert lr >= 0.3  # 下限保护
```

**测试用例 2.4**: partial_play 高费加强
```python
def test_partial_play_high_cost_boost():
    """partial_play 时高费卡应有更强正向 LR。"""
    # T3, 3 mana used 2, cost=8
    lr = _compute_high_cost_partial_play_lr(available_mana=3, unused_mana=1, card_cost=8)
    assert lr > 1.5  # 应有明显提升（原方案仅 1.0-1.2）
```

### L2 验证回放测试

```bash
# 改前
python scripts/validate_hand_predictions.py --log logs/game5.power.log --gt ground_truth.json
# 记录 P(焚火林地) 在各回合的走势

# 改后——注意 T2-T7 概率应提升，T8+ 不应极端降权
python scripts/validate_hand_predictions.py --log logs/game5.power.log --gt ground_truth.json
```

**关键指标**:
- 焚火林地的预测概率在 T8+ 不应低于 5%（原 T23 时归零）
- 整体 Precision 不应因此下降超过 3%

---

## P3 — Discover 追踪测试

### L0 单元测试

**文件**: `tests/watcher/test_global_tracker.py`（追加）+ `tests/engine/test_card_effect_inference.py`（追加）

**测试用例 3.1**: Discover SHOW_ENTITY 解析
```python
def test_discover_event_tracking():
    """GlobalTracker 正确识别 Discover 事件的 SHOW_ENTITY 和 zone 变化。"""
    tracker = GlobalTracker()
    # 模拟 Discover: SHOW_ENTITY (3 options, zone=TEMPORARY)
    tracker.on_show_entity(entity_id=101, card_id="OPTION_1", zone="TEMPORARY")
    tracker.on_show_entity(entity_id=102, card_id="OPTION_2", zone="TEMPORARY")
    tracker.on_show_entity(entity_id=103, card_id="OPTION_3", zone="TEMPORARY")
    # 模拟选择: entity 102 移动到 HAND
    tracker.on_zone_change(entity_id=102, from_zone="TEMPORARY", to_zone="HAND")
    assert 102 in tracker._opp_discovered_entities
    assert len(tracker.get_opp_discovered_cards()) == 1
```

**测试用例 3.2**: 多级 Discover 追踪
```python
def test_discover_chain():
    """Discover 出的卡本身带 Discover，链式追踪。"""
    tracker = GlobalTracker()
    # 对手打出 A，A 触发 Discover（生成 B），B 本身也有 Discover（生成 C）
    # 确保 C 也被追踪
```

**测试用例 3.3**: 已存在方法验证
```python
def test_record_derived_called():
    """CardEffectInferenceEngine.record_derived_card() 在 Discover 事件中被正确调用。"""
    engine = CardEffectInferenceEngine()
    # 模拟系统调用
    engine.record_derived_card(derived_card_id="DREAM_05", source_card_id="DREAM_01", turn=5, derive_type="discover")
    derived = engine.get_derived_card_sources()
    assert "DREAM_05" in derived
    assert derived["DREAM_05"]["derive_type"] == "discover"
```

**测试用例 3.4**: Discover 卡在预测结果中出现
```python
def test_discover_card_in_predictions():
    """Discover 获得的卡牌出现在 hand_predictions 中。"""
    state = build_state_with_discovered_card(card_id="DREAM_05", turn=5)
    result = predictor.predict(state)
    dream_card = [hp for hp in result.hand_predictions if hp.card_id == "DREAM_05"]
    assert len(dream_card) == 1
    assert dream_card[0].probability > 0.3
```

### L2 验证回放测试

需要一条包含 Discover 事件的 Power.log（game5 或 game7 可能包含）。

```bash
# 跑验证脚本，检查"梦魇之王萨维斯"是否出现在预测中
python scripts/validate_hand_predictions.py --log logs/game5.power.log --gt ground_truth.json --verbose 2>&1 | grep "萨维斯\|SAVAGE"
```

### L3 对比验证

- **手动检查**: 在 replay_game 或 UI overlay 中确认 Discover 卡牌出现
- **Edge case**: 对手打出的 Discover 卡本身是衍生卡 → 确保不重复计数
- **Edge case**: Discover 选择后被偷/摧毁 → 确认追踪不影响

---

## 回归测试

所有改动跑完整测试套件：

```bash
# 全量单测
pytest -x --timeout=60

# 引擎相关
pytest tests/engine/ -x --timeout=60

# watcher 相关
pytest tests/watcher/ -x --timeout=60

# tracker 相关
pytest tests/tracker/ -x --timeout=60
```

## A/B 对比框架

在同一个 Power.log + ground truth 上运行改前改后逻辑：

```bash
# 1. 保存改前基线
git stash
python scripts/validate_hand_predictions.py --log logs/game5.power.log --gt truth.json --output baseline.json

# 2. 应用改动后对比
git stash pop
python scripts/validate_hand_predictions.py --log logs/game5.power.log --gt truth.json --output after.json

# 3. 对比
python scripts/compare_predictions.py --baseline baseline.json --after after.json
```

对比脚本输出应包含：

| 回合 | 改前预测数 | 改后预测数 | 改前 Precision | 改后 Precision | 改前 Recall | 改后 Recall |
|------|-----------|-----------|---------------|---------------|------------|------------|
| T3   | 32        | 6         | 9.4%          | 50.0%         | 75%        | 75%        |
| T5   | 28        | 5         | 10.7%         | 60.0%         | 80%        | 80%        |
| ...  | ...       | ...       | ...           | ...           | ...        | ...        |
| **平均** | **~29** | **~N** | **10.2%** | **≥30%** | **xx%** | **xx%** |

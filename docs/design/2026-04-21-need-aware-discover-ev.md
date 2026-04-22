# Need-Aware Discover EV — 实现计划

> 日期: 2026-04-21
> 设计文档: `thoughts/shared/designs/2026-04-21-need-aware-discover-ev-design.md`
> 预计工时: 6-8h

## Batch 1: NeedAnalyzer + CardClassifier (独立，可并行)

### Task 1.1: NeedAnalyzer
- **文件**: `hs_analysis/search/engine_v11/models/need_analyzer.py`
- **实现**: NeedProfile dataclass + NeedAnalyzer.analyze(state)
- **规则**:
  - survival = min(1.0, enemy_damage_bound / hero_eff_hp)
  - removal = min(1.0, sum(enemy.attack * health) / 100)
  - tempo = 1 - len(board) / 7
  - damage = min(1.0, max_damage_bound / opp_hp)
  - draw = 0.8 if hand_count < 3 else 0.2
- **验证**: 测试不同场面状态的需求输出

### Task 1.2: CardClassifier
- **文件**: `hs_analysis/search/engine_v11/models/card_classifier.py`
- **实现**: 基于卡牌文本 regex 分类 → heal/removal/tempo/damage/draw/utility
- **关键词**:
  - heal: 恢复, 回血, 治疗, Restore, Heal
  - removal: 消灭, 摧毁, Destroy, 对...造成伤害, AoE 关键词
  - tempo: 召唤, Summon, 随从属性
  - damage: 造成.*伤害, Deal.*damage, 英雄技能伤害
  - draw: 抽牌, Draw, 发现, Discover
- **验证**: 测试典型卡牌分类正确性

## Batch 2: PoolSimulator + OrderStatistics (依赖 Batch 1 的 NeedAnalyzer)

### Task 2.1: PoolSimulator
- **文件**: `hs_analysis/search/engine_v11/models/pool_simulator.py`
- **实现**: simulate_card(card, state, evaluator) → float
- **流程**: copy state → append card → simulate play → FactorGraph evaluate → score
- **超时保护**: 单张牌模拟 >2ms 降级到 SIV 静态分
- **验证**: 已知场面 + 已知牌 → 预期分数范围

### Task 2.2: OrderStatistics
- **文件**: `hs_analysis/search/engine_v11/models/order_statistics.py`
- **实现**: expected_max_of_k(sorted_scores, k=3) → float
- **策略**: n≤50 精确计算, n>50 Monte Carlo 200次
- **精确公式**: E[max] = Σ x_i * C(rank-1, k-1) / C(n, k)
- **验证**: 简单列表手算验证, 边界(空列表, k>n, k=1)

## Batch 3: DiscoverModelV2 + TacticalPlanner 集成 (依赖 Batch 1+2)

### Task 3.1: DiscoverModelV2
- **文件**: `hs_analysis/search/engine_v11/models/discover_model_v2.py`
- **实现**: DiscoverEVResult + DiscoverModelV2.compute_ev(pool, state, evaluator)
- **流程**:
  1. NeedAnalyzer.analyze(state) → needs
  2. PoolSimulator.simulate_card(每张池牌) → scores
  3. OrderStatistics.expected_max_of_k(scores, k=3) → EV
  4. CardClassifier.classify(top_cards) → categories
  5. 组装 DiscoverEVResult
- **验证**: 完整流程测试 + 空池/单张池/大池

### Task 3.2: TacticalPlanner 扩展
- **文件**: `hs_analysis/search/engine_v11/tactical.py` (修改)
- **修改**: 在 `_enumerate_card_combos` 的 combo 评估中：
  - 检测打出的是否为发现牌
  - 如果是 → 用 DiscoverModelV2.compute_ev() 获取 EV
  - 将 EV 作为 combo 的附加分数参与排序
- **验证**: 发现牌 combo vs 非发现牌 combo 对比测试

## Batch 4: 测试 + 文档更新

### Task 4.1: 完整测试套件
- **文件**: `hs_analysis/search/engine_v11/test_discover_v2.py`
- **测试数**: ~37 个测试（6 批次覆盖所有组件）
- **验证**: 运行全量测试确保无回归

### Task 4.2: 更新 PROJECT_STATE.md + DECISIONS.md
- 标记 V11 Discover EV 为 DONE
- 追加 D028 决策记录

## 风险

| 风险 | 缓解措施 |
|------|---------|
| 池过大导致超时 (>100ms) | 池 >200 截取；单牌 >2ms 降级；结果缓存 |
| 发现牌文本无"发现"关键词 | 保留 V10 的 _parse_discover_constraint 作为 fallback |
| FactorGraph 评估异常 | try/except 降级到静态评分 |

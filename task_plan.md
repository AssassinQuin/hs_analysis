# 手牌预测增强计划: 5 步改进

## 目标
将系统从约70%完成度推向完整实现，聚焦于 deck_codes 集成、逐位预测、衍生牌追踪、UI优化

## 阶段

### Phase 1: 🟢 deck_codes.txt 作为一等贝叶斯候选
- 文件: `analysis/utils/bayesian_opponent.py`
- 始终加载 deck_codes.txt（不只在 HSReplay 为空时）
- 新增 `_merge_deck_sources()` 去重合并
- `build_prior()` 给 deck_codes 卡组 1.5x 先验加成
- 标记 `_deck_source`

### Phase 2: 🟢 衍生牌来源/位置追踪
- 文件: `tracker_types.py`, `global_tracker.py`, `log_monitor.py`, `hand_predictor.py`, `game_state.py`
- 新增 `GeneratedCardRecord` 数据结构
- 追踪 entity_id → 源卡 → 位置 → 回合
- 传播到预测结果

### Phase 3: 🟢 逐位手牌预测追踪
- 文件: `tracker_types.py`, `global_tracker.py`, `log_monitor.py`, `dynamic_probability.py`, `hand_predictor.py`, `game_state.py`
- 新增 `opp_hand_positions: Dict[int, int]`
- 提取 ZONE_POSITION 标签
- 新增 `PositionPrediction` 数据类
- `compute_position_predictions()` 方法

### Phase 4: 🟢 增强型 MCTS（deck_codes 约束）
- 文件: `dynamic_probability.py`, `opponent_hand_mcts.py`, `global_tracker.py`
- 当 top-1 是 deck_codes 卡组时独占使用其卡牌列表
- 传递 `_deck_source` 到 DynamicProbabilityEngine（通过 bayesian_state.top_deck_sources）
- HandSampler 在 deck_codes 独占模式下跳过 observed card 扩展

### Phase 5: 🟢 UI 逐位显示 + 衍生牌标注
- 文件: `overlay_ui.py`
- 按手牌位置遍历显示（_refresh_hand 使用 position_predictions）
- 位置编号标记（小手写数字在水晶与卡名之间）
- 衍生牌来源标注（右侧橙色「衍生」标签）

## 依赖关系
Phase 1 → Phase 4 (deck_source 标记)
Phase 2 → Phase 5 (衍生牌数据)
Phase 3 → Phase 5 (位置数据)
Phase 1, 2, 3 可部分并行

## 验证
每步完成后运行:
- `pytest tests/`
- `python scripts/validate_hand_predictions.py Power.log --ground-truth gt.json`

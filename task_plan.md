# 修复计划: Power.log 5 个 Bug

## 目标
依次修复 deep_powerlog_analysis.py 发现的 5 个 bug，每个 bug 附带单元测试。

## 阶段

### Phase 1: 🔴 随机效果追踪 (card_effect_inference.py)
- 添加 random damage/summon/target 模式到 CardEffectInferenceEngine
- 确保 RANDOM 关键字卡牌被检测出效果类型
- 添加单元测试

### Phase 2: 🔴 HSReplay 卡组推断为空 (dynamic_probability.py)
- 调查 MAGE 职业为何匹配不到任何卡组
- 修复 HSReplay 数据加载或匹配逻辑
- 添加集成测试

### Phase 3: 🟡 初始牌库大小未知 (tracker / global_tracker)
- 追踪对手初始牌库大小（根据职业默认30张，或从游戏事件推断）
- 确保概率计算有正确基准
- 添加测试

### Phase 4: 🟡 墓地来源传递 (log_monitor.py / tracker_types)
- build_state_dict() 传递 KnownCard.source 到 graveyard 条目
- 添加测试

### Phase 5: 🟢 known_cards 去重 (log_monitor.py)
- build_state_dict() 输出去重 known_cards
- 或 global_tracker 中 controller correction 时防止重复追加
- 添加测试

## 依赖关系
Phase 1-5 独立，可串行执行。

## 测试策略
- 每个 Bug 修复：输出型测试（纯函数逻辑）+ 状态型测试（跟踪器状态变化）
- 优先 table-driven 覆盖边界
- Mock 只在外部边界（HSReplay API 等）

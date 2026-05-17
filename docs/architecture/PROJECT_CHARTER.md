---
version: 1.0
created: 2026-04-19
last_changed: 2026-04-19
---

# Project Charter: hs_analysis

## Mission
炉石传说卡牌数值分析工具包 — 用数学模型量化卡牌价值，支持游戏内实时决策建议。

## Core Requirements

### R1: 数据管线
- 从 iyingdi + HearthstoneJSON + HSReplay 多源获取卡牌数据
- 构建统一数据库，支持标准/狂野两种格式
- O(1) 多维度索引（mechanic/type/class/race/school/cost/format）
- **验收标准**: 1000+ 卡牌入库，索引查询 < 1ms

### R2: 多版本评分引擎
- V2: 基础幂律曲线 + 关键词分层 (L1-L5)
- V7: 扩展关键词 + 种族/学派协同 + HSReplay Rankings 校准
- V8: 7个上下文修正因子（回合曲线、类型上下文、池质量等）
- L6: 真实世界综合评分
- **验收标准**: 每个版本生成评分报告，MAE 持续降低

### R3: RHEA 进化搜索引擎
- 基于进化算法搜索最优出牌方案
- 自适应参数、阶段检测、时间预算控制
- **验收标准**: 75ms 内返回候选方案

### R4: V9 层叠决策管线
- 致命检测 → 增强 RHEA → 对手模拟 → 风险评估 → 选择
- 贝叶斯对手建模
- **验收标准**: 层叠管线完整可用，每层有独立测试

### R5: 测试覆盖
- 每个核心模块有独立测试文件
- **验收标准**: 140+ 测试通过

## Technical Constraints
- Python 3.10+ (type hints, dataclasses)
- 依赖: NumPy, SciPy, openpyxl (仅3个)
- 无 GUI，无实时游戏注入（仅分析工具包）
- 数据文件 JSON 格式，SQLite 仅用于缓存
- 所有路径通过 config.py 集中管理

## Out of Scope
- 实时游戏客户端集成（HDT 插件是 P2 远期目标）
- GUI / Web 界面
- 非 Python 语言实现
- 多人游戏支持
- 商业化 / 发行

## Change Log
| Date | Version | Change | Reason |
|------|---------|--------|--------|
| 2026-04-19 | 1.0 | Initial charter | Project kickoff |

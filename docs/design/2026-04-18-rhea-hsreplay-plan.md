---
date: 2026-04-18
task_id: P002
title: "RHEA 搜索引擎 + HSReplay L6 集成"
status: pending
priority: critical
depends_on: [P001-V2-model-complete]
phase: rhea-hsreplay
---

# P002: RHEA 搜索引擎 + HSReplay L6 集成实施计划

## 总览

基于设计文档 `thoughts/shared/designs/2026-04-18-rhea-hsreplay-redesign.md`，实施两大功能：
1. HSReplay 单卡实战数据集成（L6 层）
2. RHEA 进化搜索引擎替代 Beam Search

## 依赖关系

```
T006-data-fetcher ──→ T007-l6-scoring ──→ T009-composite-evaluator ──→ T010-rhea-engine ──→ T011-decision-presenter
                                                                    ↗
                                     T008-bayesian-opponent ────────┘
```

T006 → T007 串行（L6 需要数据）
T006 + T008 可部分并行
T009 需要等 T007 + T008
T010 需要等 T009
T011 需要等 T010

---

## T006: HSReplay 数据获取器 + SQLite 缓存

### 目标
搭建 HSReplay API 数据管道，每日获取单卡统计并缓存到 SQLite。

### 执行步骤

#### Step 1: SQLite 数据库初始化
- 创建 `hs_cards/hsreplay_cache.db`
- 表结构: `card_stats(dbfId INTEGER, fetch_date TEXT, winrate REAL, deck_winrate REAL, play_rate REAL, keep_rate REAL, avg_turns REAL, class_stats TEXT)`
- 唯一约束: `(dbfId, fetch_date)`
- 索引: `dbfId`, `fetch_date`

#### Step 2: HSReplay API 数据获取脚本
- 创建 `scripts/fetch_hsreplay.py`
- 使用 `urllib.request`（与项目风格一致）
- API Key: `089b2bc6-3c26-4aab-adbe-bcfd5bb48671`
- 端点: `https://hsreplay.net/api/v1/cards/?game_type=RANKED_STANDARD`
- 请求头包含 API Key 和 User-Agent
- 超时 60 秒
- JSON 响应解析 → 提取每张卡的 winrate / play_rate / keep_rate / avg_turns

#### Step 3: 数据写入与缓存逻辑
- 写入 SQLite，按日期分桶
- 保留 30 天历史数据
- `DELETE FROM card_stats WHERE fetch_date < date('now', '-30 days')`
- 如果 API 失败，使用最近一天缓存

#### Step 4: 验证
- 运行脚本，确认数据库有数据
- 抽样检查：已知热门卡（如星际征途）winrate 应 > 50%
- 确认降级逻辑工作（断网时使用缓存）

### 产出物
- `scripts/fetch_hsreplay.py` — 数据获取脚本
- `hs_cards/hsreplay_cache.db` — SQLite 缓存数据库

### 验收标准
- [ ] 脚本可独立运行，能从 HSReplay 拉取数据
- [ ] SQLite 数据库正确缓存
- [ ] API 失败时降级到缓存无报错
- [ ] 已知热门卡数据合理

### 技术约束
- 使用 `urllib`（非 requests），与项目一致
- 使用 `sqlite3`（标准库）
- API Key 存储在脚本常量中

---

## T007: L6 实战数据评分层

### 目标
基于 HSReplay 缓存数据，计算 L6a CPI / L6b Tempo / L6c Meta 修正值。

### 执行步骤

#### Step 1: L6a Card Power Index 计算
- 在 `scripts/` 下创建 `l6_real_world.py`
- `calc_cpi(card_dbfId, hsreplay_data) → float`
- 公式: `CPI = 0.5 × norm(winrate) + 0.3 × norm(deck_winrate) + 0.2 × norm(play_rate)`
- 归一化: min-max 到 [0, 1]，基于当前标准卡池
- 返回 [0, 1] 范围的 CPI 值

#### Step 2: L6b Tempo Efficiency
- `calc_tempo_bonus(card_dbfId, hsreplay_data) → float`
- 对比卡牌实际打出回合的平均胜率 vs 同费用卡平均胜率
- `tempo_bonus = max(0, winrate_at_actual_turn - avg_winrate_at_same_cost)`
- 范围: [-0.5, +0.5]

#### Step 3: L6c Meta Context
- `calc_meta_factor(card_dbfId, hsreplay_data) → float`
- 统计卡牌出现在多少个热门卡组中
- `meta_factor = 1.0 + 0.1 × log10(deck_count_card_appears_in + 1)`
- 范围: [1.0, ~1.3]

#### Step 4: V2+L6 融合
- `adjusted_score(v2_score, card_dbfId, hsreplay_data) → float`
- `result = v2_score × (1 - θ) + CPI × θ × v2_max_score`
- `θ = 0.3`（30% 权重给实战数据）
- 新卡（无数据）: `θ = 0`，完全依赖 V2

#### Step 5: L6 报告生成
- 对所有 1015 卡计算 L6 修正后排名
- 输出对比报告: V2 排名 vs L6 修正排名
- 标注排名变化 > 20 位的卡（需人工审查）

### 产出物
- `scripts/l6_real_world.py` — L6 评分层
- `hs_cards/l6_scoring_report.json` — L6 修正评分结果

### 验收标准
- [ ] CPI 计算正确，已知强力卡 CPI > 0.7
- [ ] 无数据的卡 θ=0，分数不变
- [ ] V2 前 20 名卡 L6 排名变化 < 10 位
- [ ] 排名变化 > 20 位的卡有合理原因（实战表现差异）

---

## T008: 增强版贝叶斯对手推断模型

### 目标
实现基于 HSReplay 热门卡组的贝叶斯对手推断。

### 执行步骤

#### Step 1: 热门卡组数据获取
- 扩展 `fetch_hsreplay.py`，增加获取 Top 5 卡组功能
- 端点: HSReplay 的 archetype/deck 数据
- 缓存到 SQLite: `meta_decks(archetype_id, class, cards_json, winrate, usage_rate, fetch_date)`
- 每日刷新

#### Step 2: 贝叶斯推断引擎
- 创建 `scripts/bayesian_opponent.py`
- 先验: `P(deck_i) = usage_rate_i / Σ usage_rates`
- 更新: `P(deck_i | seen_X) = P(seen_X | deck_i) × P(deck_i) / P(seen_X)`
- `P(seen_X | deck_i) = count(X in deck_i) / 30`
- 锁定阈值: `max_i P(deck_i) > 0.60`

#### Step 3: 对手动作预测
- 基于锁定卡组，预测对手可能的下回合动作
- 输出: `top_n_predicted_actions` 及其概率

#### Step 4: 验证
- 模拟对手打出系列卡，验证推断收敛
- 测试锁定/解锁逻辑

### 产出物
- `scripts/bayesian_opponent.py` — 贝叶斯推断模块

### 验收标准
- [ ] 给定 5 张对手出卡，能收敛到正确卡组
- [ ] 锁定/解锁逻辑正确
- [ ] 无 HSReplay 数据时降级到均匀先验

---

## T009: 综合状态评估器

### 目标
融合 V2 (L1-L5) + L6 + 子模型 A-G 的综合评估函数。

### 执行步骤

#### Step 1: GameState 数据结构
- 创建 `scripts/game_state.py`
- 定义 GameState dataclass:
  - `hero`: HP, armor, class, weapon
  - `mana`: available, overloaded, max
  - `board`: list of Minion (attack, health, keywords, enchantments, can_attack)
  - `hand`: list of Card (dbfId, cost, v2_score, l6_adjusted_score)
  - `deck_remaining`: int
  - `opponent`: hero HP/armor, board, hand_count, secrets, deck_remaining
  - `shared`: turn_number, cards_played_this_turn
- 提供 `copy()` 方法用于搜索分支

#### Step 02: 子模型评分函数
- 创建 `scripts/submodel_evaluator.py`
- Sub-Model A (Board): `eval_board(state) → float`
  - `friendly_value = Σ minion_V2 × survival_weight`
  - `enemy_threat = Σ enemy_minion_value × threat_multiplier`
  - `board_advantage = friendly_value - enemy_threat`
- Sub-Model B (Threat): `eval_threat(state) → float`
  - 对手场面威胁值 + 英雄血量危险度
  - `lethal_threat` 计算（直接伤害能否击杀）
- Sub-Model C (Lingering): `eval_lingering(state) → float`
  - 持续效果折现: `0.85^turns_ahead`
- Sub-Model D (Trigger): `eval_trigger(state) → float`
  - 随机效果 EV: P(trigger) × value

#### Step 03: CompositeEvaluator
- 创建 `scripts/composite_evaluator.py`
- `evaluate(state, v2_scores, l6_scores, meta_data) → float`
- 公式: `V = w_v2 × V2_adj + w_board × board + w_threat × threat + w_lingering × lingering + w_trigger × trigger`
- 初始权重: 全部设为 1.0（后续由 RHEA 自然选择隐式优化）
- 提供 `evaluate_delta(state_before, state_after) → float` 用于适应度计算

#### Step 04: 验证
- 构造简单局面，验证评分合理性
- 空场面 vs 有场面，评分应有明显差异
- 对手低血量时 threat 应显著升高

### 产出物
- `scripts/game_state.py` — 游戏状态数据结构
- `scripts/submodel_evaluator.py` — 子模型评估函数
- `scripts/composite_evaluator.py` — 综合评估器

### 验收标准
- [ ] GameState 可正确 copy 用于搜索分支
- [ ] 空场面 vs 满场面评分差异 > 50%
- [ ] 对手 5 HP 时 threat 显著高于 30 HP
- [ ] 评估单次 < 5ms

---

## T010: RHEA 进化搜索引擎

### 目标
实现 Rolling Horizon Evolutionary Algorithm，在合法动作空间搜索最优动作序列。

### 执行步骤

#### Step 1: 动作编码与枚举
- 创建 `scripts/rhea_engine.py`
- Chromosome 编码: `[Action, Action, ...]`
- Action 类型: `PLAY(card_idx, position)`, `ATTACK(src_idx, target_idx)`, `HERO_POWER(target)`, `END_TURN`
- `enumerate_legal_actions(state) → List[Action]`
- 约束: 法力值足够、目标合法、场面未满、手牌有卡

#### Step 2: 轻量状态模拟
- `apply_action(state, action) → new_state`
- 不需要完整游戏引擎，只需:
  - 扣除法力、移出手牌、放置场面
  - 处理战吼效果（使用 Tier 1 EV 查表）
  - 处理攻击（计算伤害）
  - 结算死亡（移除 HP<=0 随从）
- 不处理复杂链式效果（依赖 Tier 1 预计算 EV）

#### Step 3: RHEA 核心
- 初始化种群: 50 个随机合法染色体
- 适应度: `fitness(chromo) = evaluate(state_after) - evaluate(state_before)`
- 选择: 锦标赛选择 (tournament=5)
- 交叉: 均匀交叉，两个父代产生一个子代
- 变异: 随机替换一个基因为合法动作 (rate = 1/N)
- 精英保留: Top 2 直接进入下一代
- 终止条件: 75 秒或 200 代

#### Step 04: 统计树优化（可选增强）
- 每个动作节点维护 `{total_evals, avg_fitness, variance}`
- 收敛时（方差 < 阈值）跳过评估
- UCB 选择算子（来自 Sakurai 2023）作为增强选项

#### Step 05: 验证
- 构造"obvious play"局面（如只有一个正确选择），验证 10 代内收敛
- 构造"lethal check"局面，验证能找到斩杀线
- 性能: 95% 决策在 30 秒内完成

### 产出物
- `scripts/rhea_engine.py` — RHEA 搜索引擎

### 验收标准
- [ ] Obvious play 局面 10 代内找到最优解
- [ ] Lethal check 局面能发现斩杀
- [ ] 95% 决策 < 30 秒
- [ ] 内存峰值 < 10 MB

---

## T011: 决策展示器 + 集成测试

### 目标
整合所有组件，提供用户友好的决策展示。

### 执行步骤

#### Step 1: DecisionPresenter
- 创建 `scripts/decision_presenter.py`
- 输入: RHEA 搜索结果（最优染色体 + 种群 Top 3）
- 输出格式:
  - 推荐动作序列（中文描述）
  - EV 估计值
  - 置信度（Top-1 vs Top-2 适应度差距）
  - 备选方案

#### Step 02: 集成测试脚本
- 创建 `scripts/test_integration.py`
- 测试场景:
  - 简单局面: 空场面，手上有 1 张 3 费随从
  - 中等局面: 双方各有 2-3 个随从，手上有解场+站场选择
  - 复杂局面: 对手 12 HP，我方手上有直伤，需判断打脸还是控场
  - Lethal 局面: 需要精确计算斩杀

#### Step 03: 端到端 Pipeline 测试
- 加载数据 → 评估 → 搜索 → 展示，全链路运行
- 记录每个环节耗时
- 输出决策质量评估

### 产出物
- `scripts/decision_presenter.py` — 决策展示器
- `scripts/test_integration.py` — 集成测试

### 验收标准
- [ ] 推荐动作有中文描述，可读性好
- [ ] Lethal 局面 100% 正确识别
- [ ] 端到端总耗时 < 30 秒
- [ ] 各环节有性能报告

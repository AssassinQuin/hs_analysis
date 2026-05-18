# 包重构实施计划

> 基于 `thoughts/shared/designs/2026-04-19-package-restructure-design.md`

## 执行策略

**分 7 个阶段，每阶段内可并行，阶段间有依赖。**
目标：零功能回归，44 个测试持续通过。

---

## Phase 0: 基础设施（无依赖，可立即执行）

### 任务 0.1: 创建包骨架

创建以下空包结构（所有 `__init__.py` 文件）：

```
hs_analysis/__init__.py          # __version__ = "0.1.0"
hs_analysis/models/__init__.py
hs_analysis/data/__init__.py
hs_analysis/scorers/__init__.py
hs_analysis/evaluators/__init__.py
hs_analysis/search/__init__.py
hs_analysis/utils/__init__.py
```

### 任务 0.2: 创建 pyproject.toml

```toml
[project]
name = "hs-analysis"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["numpy", "scipy", "openpyxl"]

[project.optional-dependencies]
dev = ["pytest"]
```

### 任务 0.3: 创建 config.py

核心配置模块：
- `PROJECT_ROOT = Path(__file__).parent.parent` 
- `DATA_DIR = PROJECT_ROOT / "hs_cards"`  (暂不改名，避免断裂)
- `HSREPLAY_API_KEY = os.environ.get("HSREPLAY_API_KEY", "")` 
- 所有路径用 pathlib.Path
- 评分参数默认值

### 任务 0.4: 创建 .env.example

```
HSREPLAY_API_KEY=your_key_here
```

### 任务 0.5: 创建 .gitignore 补充

添加 `.env` 到 .gitignore

---

## Phase 1: 统一数据模型（依赖 Phase 0）

### 任务 1.1: 创建 models/card.py

- 定义 `@dataclass Card`，统一字段名
- 工厂方法：`from_hsjson()`, `from_iyingdi()`, `from_unified()`
- 字段映射表解决 `dbfId`/`dbf_id`/`gameid` 混乱

### 任务 1.2: 迁移 game_state.py 的 Card dataclass

- `game_state.py` 中现有的 Card dataclass 移至 `models/card.py`
- `game_state.py` 改为从 `hs_analysis.models.card import Card`
- 保持原有 Card 的所有字段（v2_score, l6_score, v7_score, text）

---

## Phase 2: 共享评分常量（依赖 Phase 0）

### 任务 2.1: 创建 scorers/constants.py

从 `v2_scoring_engine.py` 和 `v7_scoring_engine.py` 提取共享常量：
- `KEYWORD_TIERS` / `TIER_BASES` / `CLASS_MULTIPLIER`
- `EFFECT_PATTERNS` (V2 的 19 个 + V7 扩展的 9 个)
- `CONDITION_DEFS` (V2 的 29 个 + V7 扩展的 8 个)
- V7 扩展用 `V2_PATTERNS | V7_EXTRA_PATTERNS` 合并

### 任务 2.2: 创建 scorers/vanilla_curve.py

从 `v2_vanilla_curve.py` 提取，使用 config.py 的路径。

---

## Phase 3: 迁移核心模块（依赖 Phase 1）

### 任务 3.1: 迁移 game_state.py → search/game_state.py

- 移除 `sys.path.insert` hack
- Card dataclass 引用改为 `from hs_analysis.models.card import Card`
- GameState, Minion, Weapon, HeroState 等保持不变

### 任务 3.2: 迁移 score_provider.py → utils/score_provider.py

- 使用 config.py 的路径
- 消除 `dbfId`/`dbf_id` 字段名适配代码（通过统一 Card 模型解决）

### 任务 3.3: 迁移 spell_simulator.py → utils/spell_simulator.py

- 正常包导入

### 任务 3.4: 迁移 bayesian_opponent.py → utils/bayesian_opponent.py

- 使用 config.py 路径
- 正常包导入

---

## Phase 4: 迁移评分引擎（依赖 Phase 2 + 3）

### 任务 4.1: 重构 v2_scoring_engine.py → scorers/v2_engine.py

- 从 `scorers/constants.py` 导入常量（删除本地重复声明）
- 从 `scorers/vanilla_curve.py` 导入曲线拟合
- 使用 config.py 路径
- 保持 `if __name__ == "__main__"` 自测

### 任务 4.2: 重构 v7_scoring_engine.py → scorers/v7_engine.py

- 从 `scorers/constants.py` 导入常量
- 从 `scorers/vanilla_curve.py` 导入（不再重新声明）
- ~400 行重复代码消除
- 使用 config.py 路径

### 任务 4.3: 迁移 v8_contextual_scorer.py → scorers/v8_contextual.py

- 使用 config.py 的 DATA_DIR
- 保持 singleton 模式
- 正常包导入

### 任务 4.4: 迁移 l6_real_world.py

- 合并到 v7_engine.py 或独立为 scorers/l6_real_world.py
- 使用共享常量

---

## Phase 5: 迁移评估器 + 搜索引擎（依赖 Phase 3 + 4）

### 任务 5.1: 迁移 submodel_evaluator.py → evaluators/submodel.py

- 正常包导入 game_state, card

### 任务 5.2: 迁移 composite_evaluator.py → evaluators/composite.py

- 删除 `sys.path.insert` hack
- 删除 inline fallback（不再需要，包导入保证可用）
- 正常包导入

### 任务 5.3: 迁移 multi_objective_evaluator.py → evaluators/multi_objective.py

- 正常包导入

### 任务 5.4: 迁移 rhea_engine.py → search/rhea_engine.py

- 删除 `sys.path.insert` hack
- 正常包导入所有依赖

---

## Phase 6: 数据源层 + CLI 薄壳（依赖 Phase 5）

### 任务 6.1: 迁移 fetch_hsreplay.py → data/fetch_hsreplay.py

- API key 从 config.py 读取（不再硬编码）
- 路径用 config.py

### 任务 6.2: 迁移 fetch_iyingdi_full.py → data/fetch_iyingdi.py

- 删除 `D:/code/game/...` 硬编码
- 输出路径用 config.py

### 任务 6.3: 迁移 fetch_hsjson.py → data/fetch_hsjson.py

- 配置外部化

### 任务 6.4: 迁移 build_unified_db.py → data/build_unified_db.py

- 删除 Windows 硬编码路径
- 使用 config.py + pathlib

### 任务 6.5: CLI 薄壳

在 scripts/ 创建入口脚本：
- `run_fetch.py` → `from hs_analysis.data.fetch_hsreplay import main; main()`
- `run_score_v2.py` → `from hs_analysis.scorers.v2_engine import main; main()`
- `run_score_v7.py` → `from hs_analysis.scorers.v7_engine import main; main()`
- `run_rhea.py` → `from hs_analysis.search.rhea_engine import main; main()`

---

## Phase 7: 测试验证 + 清理（依赖 Phase 6）

### 任务 7.1: 迁移测试文件到 tests/

- 所有 test_*.py 移到 tests/
- 更新导入路径为 `from hs_analysis.xxx import ...`

### 任务 7.2: 运行全量测试

- 确认 44 个测试通过
- 端到端 pipeline 验证

### 任务 7.3: Git 提交 + 清理

- 删除 scripts/ 中已迁移的旧文件
- 更新 README.md
- 最终提交

---

## 并行执行机会

```
Phase 0 (全部可并行)
  ├── 0.1 包骨架
  ├── 0.2 pyproject.toml
  ├── 0.3 config.py
  ├── 0.4 .env.example
  └── 0.5 .gitignore

Phase 1 + Phase 2 (可并行)
  ├── 1.1-1.2 Card 模型
  └── 2.1-2.2 共享常量 + 白板曲线

Phase 3 (3.1-3.4 可并行)
Phase 4 (4.1-4.4 可并行)
Phase 5 (5.1-5.4 可并行)
Phase 6 (6.1-6.5 可并行)
Phase 7 (顺序执行)
```

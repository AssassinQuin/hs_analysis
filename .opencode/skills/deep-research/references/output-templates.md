# Output Templates

Templates for each research output artifact.

## Template: 项目知识总结.md

```markdown
# 项目知识总结: {Topic}

> 提取日期: {date}
> 涉及文件数: {count}
> 知识覆盖度: 高/中/低

## 1. 现有实现概况

### 核心模块
| 模块 | 文件路径 | 行数 | 功能 |
|------|---------|------|------|
| ... | ... | ... | ... |

### 关键类/函数
- `ClassName` [file:path:L{line}]: 简要描述
- `function_name()` [file:path:L{line}]: 简要描述

## 2. 可复用组件

### 直接复用
| 组件 | 来源 | 复用方式 |
|------|------|---------|
| ... | [file:path] | 作为...使用 |

### 需适配复用
| 组件 | 来源 | 适配需求 |
|------|------|---------|
| ... | [file:path] | 需要... |

## 3. 设计决策与约束

- **决策**: {description}
  - 原因: {rationale}
  - 来源: [file:path] 或 [doc:document]
  - 影响: {impact}

## 4. 已知局限

- {limitation} [file:path]
- ...

## 5. 知识空白（需外部研究补充）

1. **{gap_1}**: 项目中无相关实现，需研究...
2. **{gap_2}**: 现有实现不完整，需了解...
```

## Template: 外部研究资料.md

```markdown
# 外部研究资料: {Topic}

> 检索日期: {date}
> 信息源数量: {count}
> 验证状态: 已交叉验证/待验证

## 学术/技术来源

### [S1] {Title}
- **来源**: {Author/Organization}
- **URL**: {url}
- **类型**: 论文/博客/文档/代码仓库
- **检索日期**: YYYY-MM-DD
- **关键发现**:
  - Finding 1
  - Finding 2
- **与项目的关联**: ...
- **可信度**: 高/中/低

### [S2] ...

## 综合分析

### 核心共识（多来源一致）
- ...

### 分歧观点
- ...

### 对本项目的启示
- ...
```

## Template: 信息源索引.md

```markdown
# 信息源索引: {Topic}

## 项目内部源

| ID | 类型 | 位置 | 描述 |
|----|------|------|------|
| P1 | 代码 | analysis/search/rhea/engine.py | RHEA引擎核心 |
| P2 | 文档 | docs/design/xxx.md | 设计文档 |
| P3 | 测试 | tests/search/test_xxx.py | 行为规格 |

## 外部源

| ID | 类型 | 标题 | URL | 访问日期 | 可信度 |
|----|------|------|-----|---------|--------|
| S1 | 论文 | ... | {url} | YYYY-MM-DD | 高 |
| S2 | 博客 | ... | {url} | YYYY-MM-DD | 中 |
| S3 | 仓库 | ... | {url} | YYYY-MM-DD | 高 |

## 引用映射

文档中的 `[S1]` → 信息源索引中的 S1 条目
文档中的 `[P1]` → 信息源索引中的 P1 条目
```

## Template: 总结报告.md

```markdown
# {Topic} 调研总结报告

> 生成日期: {date}
> 研究范围: {scope}
> 信息源: 项目内部 {n} 个 + 外部 {m} 个

## 一、研究背景与目标

### 1.1 研究动机
{Why this research is needed}

### 1.2 研究目标
{What this research aims to answer}

### 1.3 研究范围
{Scope boundaries}

## 二、现有项目基础

### 2.1 相关模块
{Summary from 项目知识总结}

### 2.2 可复用资产
{Components that can be reused}

### 2.3 约束条件
{Limitations that must be respected}

## 三、外部研究综合

### 3.1 核心理论
{Key concepts from literature}

### 3.2 实践经验
{What others have done}

### 3.3 工具与框架
{Available tools/libraries}

## 四、方案设计

### 4.1 方案概述
{High-level approach}

### 4.2 架构设计
{Architecture details}

### 4.3 关键技术决策
{Decisions with rationale}

### 4.4 实现路径
{Step-by-step plan}

## 五、风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| ... | ... | ... | ... |

## 六、实施建议

### 优先级排序
1. ...
2. ...

### 里程碑
- M1: ... ({timeframe})
- M2: ...

## 七、信息源

### 项目内部
- [P1] {description} — {path}
- [P2] {description} — {path}

### 外部
- [S1] {title} — {url}
- [S2] {title} — {url}

---
> 本报告由 deep-research skill 生成，所有信息源均已验证。
```

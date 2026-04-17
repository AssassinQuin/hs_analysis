# Agent Init — 炉石传说卡牌数值数学建模

## 项目定位

本项目通过**数学建模**量化《炉石传说》卡牌价值，目标是建立一套可计算的卡牌评估体系，辅助游戏中的决策收益分析。

## 技术栈

- **语言**: Python 3.x
- **依赖**: requests（HTTP）, 标准库 json/urllib/collections
- **数据存储**: JSON 文件（hs_cards/ 目录）, SQLite（mydatabase.db）
- **数据源**: 暴雪国服 API, HearthstoneJSON API

## 核心数学模型

### 白板测试（Vanilla Test）

```
期望属性 = 法力消耗 × 2 + 1
属性偏差 = (攻击 + 生命) - 期望属性
```

- 偏差 > 0：属性低于预期（特效占用了"预算"）
- 偏差 < 0：属性高于预期（超模）
- 偏差 = 0：恰好达标

### 关键词价值量化

每个关键词有经验分值（正/负），用于量化特效的总贡献：
- 高价值：圣盾(+2), 冲锋(+2), 发现(+2)
- 中价值：战吼(+1.5), 亡语(+1.5), 突袭(+1.5), 吸血(+1.5), 风怒(+1.5)
- 低价值：嘲讽(+1), 潜行(+1), 法术伤害(+1)
- 负面：过载(-1)

### 综合评分

```
总评分 = 关键词加成 - 属性偏差
```

评分越高 → 卡牌额外价值越大。

## 项目结构约定

```
scripts/          → 所有 Python 脚本（采集、分析、测试）
hs_cards/         → JSON 数据 + 图片资源
thoughts/shared/  → 设计文档和思考笔记
```

## 数据文件说明

| 文件 | 用途 |
|------|------|
| hs_cards/all_standard_legendaries.json | 暴雪 API 采集的全量传说卡（按职业分组） |
| hs_cards/standard_legendaries_v2.json | 传说卡数据（v2 修正版） |
| hs_cards/legendaries_simple_v2.json | 精简版卡牌列表（id/name/class/mana/atk/hp） |
| hs_cards/standard_legendaries_analysis.json | **核心产出** — 带评分的完整分析结果 |
| hs_cards/card_list.json | 卡牌摘要列表 |

## 脚本用途

| 脚本 | 功能 |
|------|------|
| scrape_hs_cards.py | 暴雪国服 API 数据采集 + 图片下载 |
| fetch_hsjson.py | HearthstoneJSON API 数据获取 |
| rescrape_legendaries.py | 传说卡重采（修正过滤条件） |
| full_analysis.py | **核心脚本** — 完整数学建模 + 评分 |
| analyze_cards.py | 基础统计分析 |
| check_rarity.py | 稀有度分布检查 |
| show_slugs.py | 卡牌 slug 查看 |
| explore_api.py | API 端点探测 |
| test_api.py | API 参数测试 |
| test_api_endpoints.py | API 端点连通测试 |

## 开发约定

- 脚本都放在 `scripts/` 目录
- 数据文件只读不手动修改，通过脚本生成
- 图片目录（images/、crops/）不纳入版本控制
- 分析结果以 JSON 格式保存到 `hs_cards/`
- 设计文档放在 `thoughts/shared/`

## 扩展方向

- 多 rarity 分析（非传说卡的基准线）
- 职业特色价值差异
- 卡组协同效应建模
- 回合节奏曲线分析
- 期望值 vs 实际胜率关联

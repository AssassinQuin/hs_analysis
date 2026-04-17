# 炉石传说卡牌数值数学建模

> 通过数学建模量化卡牌价值，建立游戏决策收益分析体系

## 项目简介

本项目以《炉石传说》（Hearthstone）标准模式传说卡牌为研究对象，建立一套完整的**卡牌数值评估数学模型**。核心思路是将卡牌的关键词、属性、费用等要素量化为可计算的数值，从而：

- **评估单卡价值**：一张卡是否"超模"或"亏模"
- **比较卡牌间收益**：同等费用下哪张卡收益更高
- **辅助决策分析**：为构筑和抉择提供数据支撑

## 数学模型

### 白板测试（Vanilla Test）

基准公式：**期望属性 = 法力消耗 × 2 + 1**

一张 N 费的"白板"（无特效）随从，其攻击力 + 生命值之和应接近 `2N + 1`。偏差部分即为特效的"隐性价值"。

### 关键词价值模型

每个关键词被赋予一个经验分值，用于量化特效对卡牌总价值的贡献：

| 关键词 | 分值 | 说明 |
|--------|------|------|
| 圣盾 | 2.0 | 等效一次额外存活 |
| 冲锋 | 2.0 | 即时场面影响力 |
| 发现 | 2.0 | 灵活选牌的价值 |
| 战吼 | 1.5 | 入场效果平均价值 |
| 亡语 | 1.5 | 延迟收益 |
| 突袭 | 1.5 | 当回合解场能力 |
| 吸血 | 1.5 | 生存恢复 |
| 风怒 | 1.5 | 双倍输出潜力 |
| 嘲讽 | 1.0 | 场控防御 |
| 潜行 | 1.0 | 保证一回合存活 |
| 过载 | -1.0 | 负面效果惩罚 |

### 综合评分公式

```
总评分 = 关键词加成 - 属性偏差

属性偏差 = (攻击 + 生命) - (法力 × 2 + 1)
关键词加成 = Σ (每个关键词的经验分值)
```

**评分越高，卡牌的"额外价值"越大。**

## 项目结构

```
game/
├── scripts/                    # 工具脚本目录
│   ├── scrape_hs_cards.py      # 暴雪国服 API 数据采集
│   ├── fetch_hsjson.py         # HearthstoneJSON API 数据获取
│   ├── rescrape_legendaries.py # 传说卡牌重新采集（修正版）
│   ├── analyze_cards.py        # 基础卡牌数据分析
│   ├── full_analysis.py        # 完整数学建模分析
│   ├── check_rarity.py         # 稀有度分布检查
│   ├── show_slugs.py           # 卡牌 slug 查看工具
│   ├── explore_api.py          # API 端点探索
│   ├── test_api.py             # API 参数测试
│   └── test_api_endpoints.py   # API 端点连通性测试
├── hs_cards/                   # 卡牌数据目录
│   ├── all_standard_legendaries.json   # 全量传说卡牌（按职业分组）
│   ├── standard_legendaries_v2.json    # 传说卡牌数据（v2 修正版）
│   ├── legendaries_simple_v2.json      # 传说卡牌精简数据
│   ├── standard_legendaries_analysis.json  # 带评分的完整分析结果
│   ├── card_list.json                  # 卡牌摘要列表
│   ├── images/                 # 卡牌原图
│   └── crops/                  # 卡牌裁切图
└── mydatabase.db               # 本地数据库
```

## 数据来源

- **暴雪国服 API**：`https://webapi.blizzard.cn/hs-cards-api-server/api` — 提供中文卡牌数据、图片
- **HearthstoneJSON**：`https://api.hearthstonejson.com/v1/latest/zhCN/` — 社区维护的完整卡牌数据

## 分析维度

### 统计分析

- 法力曲线分布
- 攻击力 / 生命值分布
- 职业分布统计
- 关键词词频统计
- 扩展包卡牌数量对比

### 价值分析

- 白板测试偏差计算
- 关键词价值量化
- 综合评分排名（Top 20 / Bottom 10）
- 费用梯度下的平均属性趋势

## 使用方式

```bash
# 1. 采集卡牌数据
python scripts/scrape_hs_cards.py

# 2. 运行完整分析
python scripts/full_analysis.py

# 3. 基础数据分析
python scripts/analyze_cards.py
```

## 依赖

- Python 3.x
- `requests` — HTTP 请求（数据采集脚本）
- 标准库：`json`, `urllib`, `collections`

## 许可

本项目仅供学习研究，卡牌数据版权归 Blizzard Entertainment 所有。

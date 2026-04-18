---
date: 2026-04-18
task_id: T001
title: "V2 非线性白板曲线拟合"
status: pending
priority: critical
depends_on: []
phase: model-v2
---

# T001: V2 非线性白板曲线拟合

## 目标

用幂律曲线 `expected_stats(mana) = a * mana^b + c` 替换线性 `2N+1`，使白板测试更贴合实际数据。

## 背景

V1 模型的线性公式在高费段严重偏离：
- 9 费：实际均值 13.8 vs 期望 19 (deficit -5.2)
- 10 费：实际均值 17.0 vs 期望 21 (deficit -4.0)

高费随从将大量属性预算让渡给特效，线性模型无法反映这一规律。

## 执行步骤

### Step 1: 数据准备
- 读取 `hs_cards/standard_legendaries_analysis.json`
- 筛选 `type == "MINION"` 且 `cost < 99`
- 提取每张卡的 (mana, attack, health)
- 按 mana 聚合计算平均属性和

### Step 2: 曲线拟合
- 定义模型函数 `f(mana) = a * mana^b + c`
- 用 `scipy.optimize.curve_fit` 拟合参数 a, b, c
- 设置合理初值：p0 = [2.5, 0.85, 0.5]（基于目视估计）

### Step 3: 验证与对比
- 计算新曲线在各 mana 点的残差
- 对比旧 2N+1 模型的残差
- 输出对比表格
- 确认拟合残差均值 < 1.0

### Step 4: 编写脚本
- 创建 `scripts/v2_vanilla_curve.py`
- 脚本功能：读取数据 → 拟合 → 输出参数 → 对比报告
- 导出参数到 `hs_cards/v2_curve_params.json`

### Step 5: 运行与验证
- 独立运行脚本确认无报错
- 检查参数合理性（b 应在 0.7-0.95 之间）

## 产出物

- `scripts/v2_vanilla_curve.py` — 拟合脚本
- `hs_cards/v2_curve_params.json` — 曲线参数

## 验收标准

- [ ] 拟合残差均值 < 1.0
- [ ] 参数 b 在 0.65-0.95 范围内（符合亚线性预期）
- [ ] 脚本可独立运行无报错
- [ ] 输出包含新旧模型对比表

## 技术约束

- 使用 scipy（如未安装需 `pip install scipy`）
- 不依赖外部 API
- Python 3.x 兼容

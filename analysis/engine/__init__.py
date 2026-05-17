# -*- coding: utf-8 -*-
"""analysis.engine — 动态概率引擎模块

模块组成：
- dynamic_probability: 超几何分布 + 贝叶斯卡组推断的手牌概率引擎
- card_effect_inference: 卡牌效果推断引擎（条件持有、衍生牌、打出时机）
- world_model: 世界推断驱动的概率调整系统（贝叶斯似然比替代硬编码）
"""

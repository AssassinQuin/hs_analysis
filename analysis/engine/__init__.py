# -*- coding: utf-8 -*-
"""analysis.engine — 动态概率引擎模块

模块组成：
- dynamic_probability: 超几何分布 + 贝叶斯卡组推断的手牌概率引擎
- card_effect_inference: 卡牌效果推断引擎（条件持有、衍生牌、打出时机）
- world_model: 世界推断驱动的概率调整系统（贝叶斯似然比，作为回退方案）
- opponent_hand_mcts: MCTS世界节点模拟的手牌概率推断（主方案，替代硬编码）
- mcts_uct: 纯 action-space MCTS UCT 树搜索
- world_branch: 世界/粒子数据结构
- observation_matcher: 实际事件 vs 世界预测的比对
- particle_filter: 加权世界管理 + 重采样
- mcts_world_tracker: POMDP 粒子滤波 + MCTS 混合编排器
- world_tracker_output: 概率输出格式化
"""

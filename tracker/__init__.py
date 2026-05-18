# -*- coding: utf-8 -*-
"""tracker — Hearthstone 卡牌游戏追踪器叠加窗口应用

提供实时 Power.log 解析、对手手牌预测、卡组推断和半透明叠加 UI。

模块:
    log_monitor      — Power.log 实时监控
    hsreplay_updater — HSReplay 卡组数据库更新器
    hand_predictor   — 增强手牌预测引擎
    game_state       — 完整游戏状态管理器
    card_images      — 卡牌图像管理器
    overlay_ui       — PyQt5 叠加窗口
    app              — 主应用入口
"""

__version__ = "1.0.0"

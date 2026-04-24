#!/usr/bin/env python3
"""CLI 入口: 卡牌数据更新工具.

Usage:
    python scripts/run_card_updater.py status        # 查看数据状态
    python scripts/run_card_updater.py fetch          # 拉取最新卡牌
    python scripts/run_card_updater.py fetch --force  # 强制重新下载
    python scripts/run_card_updater.py import xxx.json # 导入外部JSON
    python scripts/run_card_updater.py rebuild        # 重构数据库
    python scripts/run_card_updater.py update         # 一键更新 + 重构
    python scripts/run_card_updater.py update --force # 强制一键更新
"""
from analysis.data.card_updater import main

if __name__ == "__main__":
    main()

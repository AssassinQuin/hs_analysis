# -*- coding: utf-8 -*-
"""app.py — 炉石传说追踪器主应用入口

初始化所有组件、启动 Power.log 监控、HSReplay 更新器，
创建并显示叠加 UI，运行主事件循环。

用法:
    python -m tracker.app
    python tracker/app.py
    python tracker/app.py --log /path/to/Power.log
    python tracker/app.py --offline /path/to/Power.log
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TrackerApp:
    """追踪器主应用。

    整合所有组件:
    - LogMonitor: Power.log 实时监控
    - HSReplayUpdater: HSReplay 数据更新
    - HandPredictor: 对手手牌预测
    - GameStateManager: 游戏状态管理
    - CardImageManager: 卡牌图像管理
    - OverlayWindow: 叠加 UI

    用法::

        app = TrackerApp()
        app.run()
    """

    def __init__(
        self,
        log_path: Optional[str] = None,
        offline_path: Optional[str] = None,
        verbose: bool = False,
    ):
        self._log_path = log_path
        self._offline_path = offline_path
        self._verbose = verbose

        # 组件（延迟初始化）
        self._qt_app = None
        self._log_monitor = None
        self._hsreplay_updater = None
        self._hand_predictor = None
        self._game_state_manager = None
        self._image_manager = None
        self._overlay = None

    def run(self):
        """运行主应用。"""
        self._setup_logging()

        logger.info("=" * 50)
        logger.info("炉石传说追踪器 v1.0")
        logger.info("=" * 50)

        try:
            from PyQt5.QtWidgets import QApplication
        except ImportError:
            logger.error("PyQt5 未安装，请运行: pip install PyQt5")
            print("错误: PyQt5 未安装。请运行: pip install PyQt5")
            sys.exit(1)

        # 创建 Qt 应用
        self._qt_app = QApplication(sys.argv)
        self._qt_app.setQuitOnLastWindowClosed(True)

        # 初始化组件
        self._init_components()

        # 连接信号
        self._connect_signals()

        # 离线模式：加载已有日志
        if self._offline_path:
            self._run_offline()
        else:
            # 实时模式：启动监控
            self._start_live()

        # 运行 Qt 事件循环
        logger.info("启动事件循环")
        exit_code = self._qt_app.exec_()

        # 清理
        self._cleanup()
        sys.exit(exit_code)

    def _setup_logging(self):
        """配置日志。"""
        level = logging.DEBUG if self._verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    def _init_components(self):
        """初始化所有组件。"""
        logger.info("初始化组件…")

        # 1. 卡牌图像管理器
        from tracker.card_images import CardImageManager
        self._image_manager = CardImageManager()

        # 2. 游戏状态管理器
        from tracker.game_state import GameStateManager
        self._game_state_manager = GameStateManager()

        # 3. 手牌预测引擎
        from tracker.hand_predictor import HandPredictor
        self._hand_predictor = HandPredictor()

        # 4. 日志监控器
        from tracker.log_monitor import LogMonitor
        self._log_monitor = LogMonitor(
            log_path=self._log_path,
            poll_interval=0.1,
        )

        # 5. HSReplay 更新器
        from tracker.hsreplay_updater import HSReplayUpdater
        self._hsreplay_updater = HSReplayUpdater(update_interval_hours=24.0)

        # 6. 叠加 UI
        from tracker.overlay_ui import OverlayWindow
        self._overlay = OverlayWindow(
            image_manager=self._image_manager,
        )

        logger.info("组件初始化完成")

    def _connect_signals(self):
        """连接信号和槽。"""
        monitor = self._log_monitor

        # 游戏事件 → UI 更新
        monitor.game_started.connect(self._on_game_started)
        monitor.game_ended.connect(self._on_game_ended)
        monitor.turn_changed.connect(self._on_turn_changed)
        monitor.state_updated.connect(self._on_state_updated)
        monitor.log_error.connect(self._on_log_error)

        # HSReplay 更新
        updater = self._hsreplay_updater
        updater.update_finished.connect(self._on_hsreplay_updated)
        updater.update_error.connect(self._on_hsreplay_error)

    def _start_live(self):
        """启动实时监控。"""
        logger.info("启动实时监控模式")

        # 启动 HSReplay 更新器
        self._hsreplay_updater.start()

        # 启动日志监控
        self._log_monitor.start()

        # 显示叠加窗口
        self._overlay.show()
        self._overlay.start_refresh()

        logger.info("实时监控已启动，等待游戏…")

    def _run_offline(self):
        """运行离线模式（分析已有日志）。"""
        logger.info("离线模式: 分析 %s", self._offline_path)

        # 加载已有日志
        self._log_monitor.load_existing_log(self._offline_path)

        # 显示叠加窗口
        self._overlay.show()
        self._overlay.start_refresh()

        # 立即更新状态
        state_dict = self._log_monitor.build_state_dict()
        prediction = self._hand_predictor.predict(state_dict)
        self._game_state_manager.update(state_dict, prediction)
        self._overlay.update_state(self._game_state_manager.state)
        self._overlay._do_refresh()

        logger.info("离线分析完成")

    # ── 信号处理 ───────────────────────────────────────────────

    def _on_game_started(self, info: dict):
        """游戏开始。"""
        logger.info("游戏开始: %s vs %s", info.get("player_class"), info.get("opp_class"))
        # 重置游戏状态
        self._game_state_manager.reset()

    def _on_game_ended(self):
        """游戏结束。"""
        logger.info("游戏结束")

    def _on_turn_changed(self, turn: int):
        """回合切换。"""
        logger.info("回合 %d", turn)

    def _on_state_updated(self, state_dict: dict):
        """游戏状态更新。"""
        try:
            prediction = self._hand_predictor.predict(state_dict)
            self._game_state_manager.update(state_dict, prediction)
            self._overlay.update_state(self._game_state_manager.state)
        except Exception as e:
            logger.exception("状态更新失败: %s", e)

    def _on_log_error(self, error_msg: str):
        """日志错误。"""
        logger.error("日志错误: %s", error_msg)

    def _on_hsreplay_updated(self, result: dict):
        """HSReplay 数据更新完成。"""
        logger.info("HSReplay 更新完成: %d 原型, %d 卡牌统计",
                     result.get("archetype_count", 0),
                     result.get("card_stat_count", 0))

    def _on_hsreplay_error(self, error_msg: str):
        """HSReplay 更新失败。"""
        logger.warning("HSReplay 更新失败: %s", error_msg)

    # ── 清理 ───────────────────────────────────────────────────

    def _cleanup(self):
        """清理资源。"""
        logger.info("清理资源…")

        if self._log_monitor is not None:
            self._log_monitor.stop()

        if self._hsreplay_updater is not None:
            self._hsreplay_updater.stop()

        if self._overlay is not None:
            self._overlay.stop_refresh()

        logger.info("清理完成")


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="炉石传说追踪器 — 对手手牌预测叠加工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--log", "-l",
        help="Power.log 文件路径（自动检测则不需要指定）",
    )
    parser.add_argument(
        "--offline", "-o",
        help="离线模式: 分析指定的 Power.log 文件",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出",
    )

    args = parser.parse_args()

    # 确保项目根目录在 sys.path 中
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    app = TrackerApp(
        log_path=args.log,
        offline_path=args.offline,
        verbose=args.verbose,
    )
    app.run()


if __name__ == "__main__":
    main()

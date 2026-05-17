# -*- coding: utf-8 -*-
"""app.py — 炉石传说追踪器主应用入口

初始化所有组件、启动 Power.log 监控、HSReplay 更新器，
创建并显示叠加 UI，运行主事件循环。

日志路径优先级:
    1. 命令行 --log / --offline 参数
    2. cfg/live.cfg [log] paths 配置
    3. 自动检测 (%LOCALAPPDATA%/Blizzard/Hearthstone/Logs 等)
    4. 项目根目录下的 Power.log / Hearthstone_*/ 子目录

用法:
    python -m tracker.app                          # 实时模式，从 cfg/live.cfg 或自动检测
    python tracker/app.py                          # 同上
    python tracker/app.py --log /path/to/Power.log # 指定 Power.log
    python tracker/app.py --offline /path/to/Power.log  # 离线分析
"""

from __future__ import annotations

import argparse
import configparser
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional, List
from PyQt5.QtCore import QTimer

logger = logging.getLogger(__name__)


# ── 配置文件日志路径解析 ──────────────────────────────────────

def _resolve_log_paths_from_config() -> List[Path]:
    """从 cfg/live.cfg [log] paths 中解析候选日志路径。

    配置格式见 cfg/live.cfg 中的注释，支持:
      - Power.log 文件路径
      - 含 Power.log 的目录路径
      - Logs 根目录（自动选最新一局）

    Returns:
        按优先级排列的 Path 列表（只包含存在的路径）
    """
    project_root = Path(__file__).resolve().parent.parent
    cfg_path = project_root / "cfg" / "live.cfg"

    if not cfg_path.exists():
        return []

    cp = configparser.ConfigParser(interpolation=None)
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            cp.read_file(f)
    except Exception:
        return []

    if not cp.has_section("log") or not cp.has_option("log", "paths"):
        return []

    raw = cp.get("log", "paths")
    candidates: List[Path] = []

    for line in raw.replace(";", "\n").replace(",", "\n").splitlines():
        line = line.strip()
        if not line:
            continue

        # 展开 ~ 和环境变量
        line = os.path.expanduser(line)
        line = os.path.expandvars(line)
        p = Path(line)

        if not p.exists():
            continue

        if p.is_file() and p.name.lower() == "power.log":
            # 直接是 Power.log 文件
            candidates.append(p)
        elif p.is_dir():
            power_log = p / "Power.log"
            if power_log.exists():
                # 目录内有 Power.log
                candidates.append(power_log)
            else:
                # 可能是 Logs 根目录，找最新子目录
                sub_dirs = sorted(
                    [d for d in p.iterdir() if d.is_dir() and (d / "Power.log").exists()],
                    key=lambda d: d.stat().st_mtime,
                    reverse=True,
                )
                if sub_dirs:
                    candidates.append(sub_dirs[0] / "Power.log")

    return candidates


def _find_power_log(cli_path: Optional[str] = None) -> Optional[Path]:
    """按优先级查找 Power.log。

    优先级:
        1. 命令行指定路径
        2. cfg/live.cfg [log] paths
        3. 自动检测（Windows/macOS/Linux 标准位置）
        4. 项目根目录下的 Power.log / Hearthstone_*/ 子目录

    Returns:
        Power.log 的 Path 或 None
    """
    # 1. 命令行指定
    if cli_path:
        p = Path(cli_path)
        if p.exists():
            return p
        logger.warning("命令行指定的路径不存在: %s", cli_path)

    # 2. cfg/live.cfg 配置
    config_paths = _resolve_log_paths_from_config()
    if config_paths:
        logger.info("从 cfg/live.cfg 找到日志路径: %s", config_paths[0])
        return config_paths[0]

    # 3. 自动检测
    try:
        from tracker.log_monitor import find_power_log_path
        detected = find_power_log_path()
        if detected:
            logger.info("自动检测到日志路径: %s", detected)
            return detected
    except Exception:
        pass

    return None


# ── 追踪器主应用 ──────────────────────────────────────────────

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
        self._load_config()

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

        # 解析日志路径
        resolved = _find_power_log(self._log_path or self._offline_path)
        if resolved:
            logger.info("使用日志路径: %s", resolved)
            if self._offline_path:
                self._offline_path = str(resolved)
            else:
                self._log_path = str(resolved)
        else:
            logger.warning("未找到 Power.log，将在游戏启动后自动检测")

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

    def _load_config(self):
        """加载 cfg/live.cfg 配置。"""
        try:
            from analysis.config import load_live_config
            cfg = load_live_config()
            if cfg.get("cfg_loaded"):
                logger.info("配置已加载: latest_game_only=%s", cfg.get("latest_game_only"))
        except Exception as e:
            logger.debug("加载配置文件失败: %s", e)

    def _init_components(self):
        """初始化所有组件。"""
        logger.info("初始化组件…")

        # 0. 启动时更新最新卡组代码（静默，失败不影响启动）
        self._update_deck_codes_on_startup()

        # 1. 卡牌图像管理器
        from tracker.card_images import CardImageManager
        self._image_manager = CardImageManager()

        # 2. 游戏状态管理器
        from tracker.game_state import GameStateManager
        self._game_state_manager = GameStateManager()

        # 3. 手牌预测引擎
        from tracker.hand_predictor import HandPredictor
        self._hand_predictor = HandPredictor()

        # 4. 日志监控器 — 使用解析后的日志路径
        from tracker.log_monitor import LogMonitor
        self._log_monitor = LogMonitor(
            log_path=self._log_path,
            poll_interval=0.1,
        )

        # 5. HSReplay 更新器
        from tracker.hsreplay_updater import HSReplayUpdater
        self._hsreplay_updater = HSReplayUpdater(update_interval_hours=24.0)

        # 7. 卡组文件热更新监视器
        self._deck_codes_mtime: float = 0.0
        self._deck_watch_timer = QTimer(self._qt_app) if self._qt_app else None
        if self._deck_watch_timer:
            self._deck_watch_timer.timeout.connect(self._check_deck_codes_update)
            self._deck_watch_timer.setInterval(5000)  # 每5秒检查一次

        # 6. 叠加 UI
        from tracker.overlay_ui import OverlayWindow
        self._overlay = OverlayWindow(
            image_manager=self._image_manager,
        )

        logger.info("组件初始化完成")

    def _update_deck_codes_on_startup(self):
        """启动时静默更新最新卡组代码。

        在后台线程中执行，不阻塞 UI 初始化。
        如果更新失败（网络问题等），不影响正常启动。
        """
        import threading
        from pathlib import Path

        # 检查是否需要更新：如果上次更新在 12 小时内，跳过
        deck_codes_path = Path(__file__).resolve().parent.parent / "deck_codes.txt"
        update_flag = deck_codes_path.parent / ".deck_codes_last_update"

        if update_flag.exists():
            try:
                last_update = float(update_flag.read_text().strip())
                if time.time() - last_update < 43200:  # 12 小时
                    logger.info("卡组代码在 12 小时内已更新，跳过")
                    return
            except (ValueError, OSError):
                pass

        def _do_update():
            try:
                from scripts.update_deck_codes import update_deck_codes
                success = update_deck_codes(max_per_class=7, max_decks=21, backup=True)
                if success:
                    update_flag.write_text(str(time.time()))
                    logger.info("卡组代码更新完成")
                else:
                    logger.info("卡组代码更新失败，使用现有数据")
            except Exception as e:
                logger.info("卡组代码更新异常: %s，使用现有数据", e)

        t = threading.Thread(target=_do_update, daemon=True)
        t.start()
        logger.info("卡组代码更新已在后台启动")

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

        # 启动卡组文件监视
        if self._deck_watch_timer:
            deck_codes_path = Path(__file__).resolve().parent.parent / "deck_codes.txt"
            if deck_codes_path.exists():
                self._deck_codes_mtime = deck_codes_path.stat().st_mtime
            self._deck_watch_timer.start()

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
        # 不直接调用 _refresh()，定时器已启动会自动刷新

        logger.info("离线分析完成")

    # ── 信号处理 ───────────────────────────────────────────────

    def _on_game_started(self, info: dict):
        """游戏开始。"""
        logger.info("游戏开始: %s vs %s", info.get("player_class"), info.get("opp_class"))
        # 重置游戏状态
        self._game_state_manager.reset()
        # 立即同步新状态到 overlay，避免窗口引用旧实例
        self._overlay.update_state(self._game_state_manager.state)

    def _on_game_ended(self):
        """游戏结束。更新 UI 显示最终状态，然后重置。"""
        logger.info("游戏结束")
        # 重置游戏状态管理器，清空所有追踪数据
        self._game_state_manager.reset()
        # 推送空状态到 overlay，使其显示为"等待新游戏"
        self._overlay.update_state(self._game_state_manager.state)

    def _on_turn_changed(self, turn: int):
        """回合切换。"""
        logger.info("回合 %d", turn)

    def _on_state_updated(self, state_dict: dict):
        """游戏状态更新。"""
        try:
            prediction = self._hand_predictor.predict(state_dict)
            self._game_state_manager.update(state_dict, prediction)
            self._overlay.update_state(self._game_state_manager.state)
            # 不直接调用 _refresh()，因为 start_refresh() 已启动定时器
            # 定时器会自动触发 _refresh()，此处只需更新数据源
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

    def _check_deck_codes_update(self):
        """定时检查 deck_codes.txt 是否更新，如有变化则重新加载卡组数据。"""
        try:
            deck_codes_path = Path(__file__).resolve().parent.parent / "deck_codes.txt"
            if not deck_codes_path.exists():
                return
            mtime = deck_codes_path.stat().st_mtime
            if mtime <= self._deck_codes_mtime:
                return
            self._deck_codes_mtime = mtime
            logger.info("检测到 deck_codes.txt 更新，重新加载卡组数据")
            # 重新加载 DeckProvider 的卡组数据
            from analysis.data.deck_provider import DeckProvider
            if hasattr(self, '_log_monitor') and hasattr(self._log_monitor, 'game_tracker'):
                old_provider = self._log_monitor.game_tracker.deck_provider
                new_provider = DeckProvider()
                new_provider.load_deck_codes(str(deck_codes_path))
                self._log_monitor.game_tracker.deck_provider = new_provider
                logger.info("卡组数据热更新完成，加载 %d 个卡组", len(new_provider._decks) if hasattr(new_provider, '_decks') else 0)
        except Exception as e:
            logger.debug("卡组热更新检查失败: %s", e)

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

        if hasattr(self, '_deck_watch_timer') and self._deck_watch_timer is not None:
            self._deck_watch_timer.stop()

        logger.info("清理完成")


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="炉石传说追踪器 — 对手手牌预测叠加工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
日志路径查找优先级:
  1. --log / --offline 命令行参数
  2. cfg/live.cfg [log] paths 配置
  3. 自动检测系统标准位置 (Windows/macOS/Linux)
  4. 项目根目录下的 Power.log

示例:
  python -m tracker.app                          # 实时模式
  python -m tracker.app --offline Power.log      # 离线分析
  python -m tracker.app --log "E:\\battle\\Hearthstone\\Logs\\Power.log"
        """,
    )
    parser.add_argument(
        "--log", "-l",
        help="Power.log 文件路径（不指定则从 cfg/live.cfg 或自动检测）",
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

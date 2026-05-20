#!/usr/bin/env python3
"""diagnostic_app.py — Power.log 诊断 Web App

用法:
    python tracker/diagnostic_app.py [--log /path/to/Power.log] [--port 5000]

在浏览器打开 http://localhost:5000 查看诊断仪表盘
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import flask

# ── 确保项目根在 sys.path ──
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from tracker.diagnostic_engine import (
    analyze_power_log,
    AnalysisResult,
    TurnSnapshot,
)

logger = logging.getLogger(__name__)

# ── Flask App ──────────────────────────────────────────────
app = flask.Flask(
    __name__,
    template_folder=str(_project_root / "tracker" / "templates"),
    static_folder=str(_project_root / "tracker" / "static"),
)

# ── 全局分析缓存 ──────────────────────────────────────────
_analysis_lock = threading.Lock()
_analysis_result: Optional[AnalysisResult] = None
_analysis_progress: Dict = {"status": "idle", "message": ""}
_analysis_running: bool = False


# ═══════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════

@app.route("/")
def index():
    """主仪表盘"""
    return flask.render_template(
        "diagnostic.html",
        result=_analysis_result,
        progress=_analysis_progress,
        running=_analysis_running,
    )


@app.route("/api/status")
def api_status():
    """分析状态 API"""
    with _analysis_lock:
        return flask.jsonify({
            "running": _analysis_running,
            "progress": _analysis_progress,
            "has_result": _analysis_result is not None,
            "turn_count": _analysis_result.total_turns if _analysis_result else 0,
            "error_count": _analysis_result.total_errors if _analysis_result else 0,
        })


@app.route("/api/result")
def api_result():
    """完整分析结果 API"""
    with _analysis_lock:
        if _analysis_result is None:
            return flask.jsonify({"error": "No analysis result"}), 404
        return flask.jsonify(_serialize_result(_analysis_result))


@app.route("/api/turn/<int:turn_num>")
def api_turn(turn_num: int):
    """单回合数据 API"""
    with _analysis_lock:
        if _analysis_result is None:
            return flask.jsonify({"error": "No analysis result"}), 404
        for t in _analysis_result.turns:
            if t.turn_number == turn_num:
                return flask.jsonify(_serialize_turn(t))
        return flask.jsonify({"error": f"Turn {turn_num} not found"}), 404


@app.route("/api/raw_lines/<int:turn_num>")
def api_raw_lines(turn_num: int):
    """单回合原始 Power.log 行"""
    with _analysis_lock:
        if _analysis_result is None:
            return flask.jsonify({"error": "No analysis result"}), 404
        lines = _analysis_result.raw_lines_by_turn.get(turn_num, [])
        return flask.jsonify({"turn": turn_num, "lines": lines, "count": len(lines)})


@app.route("/api/start_analysis", methods=["POST"])
def api_start_analysis():
    """启动分析（后台线程）"""
    global _analysis_running, _analysis_result

    with _analysis_lock:
        if _analysis_running:
            return flask.jsonify({"error": "Analysis already running"}), 409

        data = flask.request.get_json(silent=True) or {}
        log_path = data.get("log_path", str(_project_root / "Power.log"))
        run_mcts = data.get("run_mcts", True)
        mcts_budget = data.get("mcts_budget_ms", 2000.0)

        _analysis_running = True
        _analysis_progress = {"status": "starting", "message": "初始化分析..."}

        def _run():
            global _analysis_running, _analysis_result
            try:
                def _progress(status, current, total):
                    with _analysis_lock:
                        _analysis_progress["status"] = status
                        _analysis_progress["current"] = current
                        _analysis_progress["total"] = total
                        _analysis_progress["message"] = f"{status}: {current}/{total}"

                result = analyze_power_log(
                    log_path,
                    run_mcts=run_mcts,
                    mcts_budget_ms=mcts_budget,
                    progress_callback=_progress,
                )
                with _analysis_lock:
                    _analysis_result = result
                    _analysis_progress = {"status": "done", "message": "分析完成"}
            except Exception as e:
                with _analysis_lock:
                    _analysis_progress = {"status": "error", "message": str(e)}
            finally:
                with _analysis_lock:
                    _analysis_running = False

        threading.Thread(target=_run, daemon=True).start()
        return flask.jsonify({"status": "started"})


def _serialize_result(r: AnalysisResult) -> Dict:
    """AnalysisResult → JSON-safe dict"""
    return {
        "log_path": r.log_path,
        "game_info": r.game_info,
        "total_turns": r.total_turns,
        "total_errors": r.total_errors,
        "errors": r.errors[:20],
        "turns": [_serialize_turn(t) for t in r.turns],
    }


def _serialize_turn(t: TurnSnapshot) -> Dict:
    return {
        "turn_number": t.turn_number,
        "player": t.player,
        "opponent": t.opponent,
        "player_plays": t.player_plays,
        "opp_plays": t.opp_plays,
        "mcts_action_stats": t.mcts_action_stats,
        "mcts_best_seq": t.mcts_best_seq,
        "mcts_iterations": t.mcts_iterations,
        "mcts_nodes": t.mcts_nodes,
        "mcts_elapsed_ms": t.mcts_elapsed_ms,
        "hand_predictions": t.hand_predictions,
        "archetype_name": t.archetype_name,
        "archetype_confidence": t.archetype_confidence,
        "mcts_top_predictions": t.mcts_top_predictions,
        "simulation_checks": t.simulation_checks,
    }


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    import argparse
    parser = argparse.ArgumentParser(description="Power.log 诊断 Web App")
    parser.add_argument("--log", default=None, help="Power.log 路径")
    parser.add_argument("--port", type=int, default=5000, help="端口 (默认 5000)")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    args = parser.parse_args()

    # 自动选择日志路径
    log_path = args.log
    if log_path is None:
        default_log = _project_root / "Power.log"
        if default_log.exists():
            log_path = str(default_log)

    # 如果指定了日志，自动开始分析
    if log_path:
        logger.info("日志路径: %s", log_path)
        # 启动时自动分析
        threading.Thread(target=lambda: _auto_analyze(log_path), daemon=True).start()
    else:
        logger.info("未指定日志路径，使用页面上的加载功能")

    print(f"\n  → 打开 http://{args.host}:{args.port} 查看诊断仪表盘\n")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


def _auto_analyze(log_path: str):
    """启动时自动分析。"""
    global _analysis_running, _analysis_result
    with _analysis_lock:
        _analysis_running = True
        _analysis_progress = {"status": "starting", "message": f"分析 {Path(log_path).name} ..."}

    try:
        def _progress(status, current, total):
            with _analysis_lock:
                _analysis_progress["status"] = status
                _analysis_progress["current"] = current
                _analysis_progress["total"] = total
                _analysis_progress["message"] = f"{status}: {current}/{total}"

        result = analyze_power_log(
            log_path,
            run_mcts=True,
            mcts_budget_ms=2000.0,
            progress_callback=_progress,
        )
        with _analysis_lock:
            _analysis_result = result
            _analysis_progress = {"status": "done", "message": f"分析完成: {result.total_turns} 回合"}
        logger.info("分析完成: %d 回合, %d 错误", result.total_turns, result.total_errors)
    except Exception as e:
        with _analysis_lock:
            _analysis_progress = {"status": "error", "message": str(e)}
        logger.error("分析失败: %s", e)
    finally:
        with _analysis_lock:
            _analysis_running = False


if __name__ == "__main__":
    main()

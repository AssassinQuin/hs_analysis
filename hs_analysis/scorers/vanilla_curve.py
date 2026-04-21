# -*- coding: utf-8 -*-
"""L1: 白板曲线拟合 (Vanilla Curve Fitting)

Power-law curve: expected_stats(mana) = a * mana^b + c
Replaces the linear 2N+1 model for better high-mana accuracy.

Uses paths from hs_analysis.config.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import List, Tuple

import numpy as np
from scipy.optimize import curve_fit

from hs_analysis.config import (
    DATA_DIR,
    CURVE_PARAMS_PATH,
)


# ── 数学模型 ──────────────────────────────────────────

def power_law(mana, a, b, c):
    """Power-law curve: a * mana^b + c"""
    return a * np.power(mana, b) + c


def linear_model(mana):
    """Linear baseline: 2N + 1"""
    return 2 * mana + 1


# ── 曲线拟合 ──────────────────────────────────────────

def fit_vanilla_curve(cards: list,
                      p0: list = None,
                      bounds: tuple = None) -> np.ndarray:
    """在所有随从上拟合白板曲线.

    Parameters
    ----------
    cards : list
        卡牌列表 (字典格式).
    p0 : list, optional
        初始参数猜测.
    bounds : tuple, optional
        参数边界.

    Returns
    -------
    popt : np.ndarray
        拟合参数 [a, b, c].
    """
    if p0 is None:
        p0 = [3.0, 0.7, 0]
    if bounds is None:
        bounds = ([0.1, 0.3, -5], [10, 1.5, 10])

    minions = [c for c in cards if c.get("type") == "MINION" and 0 < c.get("cost", 99) < 99]

    by_mana = defaultdict(list)
    for c in minions:
        stat_sum = c.get("attack", 0) + c.get("health", 0)
        by_mana[c["cost"]].append(stat_sum)

    mana_arr = np.array(sorted(by_mana.keys()), dtype=float)
    avg_arr = np.array([np.mean(by_mana[int(m)]) for m in mana_arr])
    count_arr = np.array([len(by_mana[int(m)]) for m in mana_arr])
    weight_arr = np.sqrt(count_arr)

    popt, pcov = curve_fit(
        power_law, mana_arr, avg_arr, p0=p0,
        sigma=1.0 / weight_arr, absolute_sigma=True,
        bounds=bounds, maxfev=10000,
    )
    perr = np.sqrt(np.diag(pcov))
    a, b, c = popt

    pred_v2 = power_law(mana_arr, *popt)
    pred_v1 = linear_model(mana_arr)
    res_v2 = avg_arr - pred_v2
    res_v1 = avg_arr - pred_v1

    print(f"\n{'=' * 70}")
    print(f"L1 VANILLA CURVE FIT ({len(minions)} minions, {len(mana_arr)} mana buckets)")
    print(f"{'=' * 70}")
    print(f"  Formula: {a:.3f} * mana^{b:.3f} + ({c:.3f})")
    print(f"  Mana range: {int(mana_arr[0])}-{int(mana_arr[-1])}")
    print(f"  MAE: {np.mean(np.abs(res_v2)):.2f} (V1 was {np.mean(np.abs(res_v1)):.2f})")
    print(f"  RMSE: {np.sqrt(np.mean(res_v2**2)):.2f} (V1 was {np.sqrt(np.mean(res_v1**2)):.2f})")

    return popt


def save_curve_params(popt: np.ndarray, output_path: str = None) -> dict:
    """保存曲线参数到 JSON 文件."""
    if output_path is None:
        output_path = str(CURVE_PARAMS_PATH)
    a, b, c = popt
    params = {
        "model": "power_law",
        "formula": "a * mana^b + c",
        "parameters": {
            "a": round(float(a), 6),
            "b": round(float(b), 6),
            "c": round(float(c), 6),
        },
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    print(f"  Parameters saved to: {output_path}")
    return params


def load_curve_params(path: str = None) -> tuple:
    """加载曲线参数."""
    if path is None:
        path = str(CURVE_PARAMS_PATH)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    p = data["parameters"]
    return (p["a"], p["b"], p["c"])


def main():
    """独立运行: 从分析数据拟合曲线."""
    data_path = str(DATA_DIR / "standard_legendaries_analysis.json")
    output_path = str(CURVE_PARAMS_PATH)

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    legendaries = data["legendaries"]
    minions = [c for c in legendaries if c.get("type") == "MINION" and c.get("cost", 0) < 99]

    print(f"Total legendaries: {len(legendaries)}")
    print(f"Minions (cost < 99): {len(minions)}")

    by_mana = defaultdict(list)
    for c in minions:
        mana = c.get("cost", 0)
        stat_sum = c.get("attack", 0) + c.get("health", 0)
        by_mana[mana].append(stat_sum)

    mana_values = sorted(by_mana.keys())
    mana_arr = np.array(mana_values, dtype=float)
    avg_stats_arr = np.array([np.mean(by_mana[m]) for m in mana_values])
    count_arr = np.array([len(by_mana[m]) for m in mana_values])

    p0 = [2.5, 0.85, 0.5]
    bounds = ([0.1, 0.3, -5.0], [10.0, 1.5, 10.0])

    popt, pcov = curve_fit(power_law, mana_arr, avg_stats_arr, p0=p0, bounds=bounds, maxfev=10000)
    a, b, c = popt
    perr = np.sqrt(np.diag(pcov))

    print(f"\n{'=' * 70}")
    print("FITTED PARAMETERS (power-law: a * mana^b + c)")
    print(f"{'=' * 70}")
    print(f"  a = {a:.4f} +/- {perr[0]:.4f}")
    print(f"  b = {b:.4f} +/- {perr[1]:.4f}")
    print(f"  c = {c:.4f} +/- {perr[2]:.4f}")

    predicted_v2 = power_law(mana_arr, *popt)
    predicted_v1 = linear_model(mana_arr)
    residuals_v2 = avg_stats_arr - predicted_v2
    residuals_v1 = avg_stats_arr - predicted_v1

    print(f"\n{'=' * 70}")
    print(f"  {'Mana':>4s} | {'N':>3s} | {'Actual':>7s} | {'V1(2N+1)':>9s} | {'V1 Res':>7s} | {'V2 Pred':>7s} | {'V2 Res':>7s} | {'Improve':>7s}")
    print(f"  {'-' * 4} | {'-' * 3} | {'-' * 7} | {'-' * 9} | {'-' * 7} | {'-' * 7} | {'-' * 7} | {'-' * 7}")

    for i, mana in enumerate(mana_values):
        actual = avg_stats_arr[i]
        v1_pred = predicted_v1[i]
        v2_pred = predicted_v2[i]
        v1_res = residuals_v1[i]
        v2_res = residuals_v2[i]
        improvement = abs(v1_res) - abs(v2_res)
        print(f"  {mana:4d} | {count_arr[i]:3d} | {actual:7.1f} | {v1_pred:9.1f} | {v1_res:+7.1f} | {v2_pred:7.1f} | {v2_res:+7.1f} | {improvement:+7.1f}")

    v2_mean_res = np.mean(np.abs(residuals_v2))
    v1_mean_res = np.mean(np.abs(residuals_v1))
    v2_rmse = np.sqrt(np.mean(residuals_v2 ** 2))
    v1_rmse = np.sqrt(np.mean(residuals_v1 ** 2))

    print(f"\n{'=' * 70}")
    print("MODEL COMPARISON SUMMARY")
    print(f"{'=' * 70}")
    print(f"  V1 (2N+1):  MAE = {v1_mean_res:.2f}, RMSE = {v1_rmse:.2f}")
    print(f"  V2 (power): MAE = {v2_mean_res:.2f}, RMSE = {v2_rmse:.2f}")
    print(f"  MAE improvement: {((v1_mean_res - v2_mean_res) / v1_mean_res * 100):.1f}%")

    print(f"\n{'=' * 70}")
    print("VALIDATION CHECKS")
    print(f"{'=' * 70}")

    checks = {
        "b in [0.65, 0.95] (sublinear)": 0.65 <= b <= 0.95,
        "Mean |residual| < 1.0": v2_mean_res < 1.0,
        "RMSE < V1 RMSE": v2_rmse < v1_rmse,
    }

    all_pass = True
    for desc, result in checks.items():
        status = "PASS" if result else "FAIL"
        if not result:
            all_pass = False
        print(f"  [{status}] {desc}")

    params = {
        "model": "power_law",
        "formula": "a * mana^b + c",
        "parameters": {"a": round(a, 6), "b": round(b, 6), "c": round(c, 6)},
        "fit_quality": {
            "mae": round(float(v2_mean_res), 4),
            "rmse": round(float(v2_rmse), 4),
            "v1_mae": round(float(v1_mean_res), 4),
            "v1_rmse": round(float(v1_rmse), 4),
        },
        "data_source": {
            "file": "standard_legendaries_analysis.json",
            "minion_count": len(minions),
            "mana_buckets": len(mana_values),
        },
        "validation": {desc: bool(result) for desc, result in checks.items()},
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    print(f"\nParameters saved to: {output_path}")

    if all_pass:
        print("\nAll validation checks PASSED.")
    else:
        print("\nSome validation checks FAILED — review parameters.")
        sys.exit(1)


if __name__ == "__main__":
    main()

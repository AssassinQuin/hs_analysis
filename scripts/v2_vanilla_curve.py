# -*- coding: utf-8 -*-
"""
T001: V2 Non-linear Vanilla Curve Fitting
Power-law curve: expected_stats(mana) = a * mana^b + c
Replaces the linear 2N+1 model for better high-mana accuracy.
"""
import json
import sys
from collections import defaultdict

import numpy as np
from scipy.optimize import curve_fit

DATA_PATH = "D:/code/game/hs_cards/standard_legendaries_analysis.json"
OUTPUT_PATH = "D:/code/game/hs_cards/v2_curve_params.json"


def power_law(mana, a, b, c):
    return a * np.power(mana, b) + c


def linear_model(mana):
    return 2 * mana + 1


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
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

    print(f"\nMana cost buckets: {len(mana_values)}")
    print(f"Mana range: {min(mana_values)} - {max(mana_values)}")

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

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    print(f"\nParameters saved to: {OUTPUT_PATH}")

    if all_pass:
        print("\nAll validation checks PASSED.")
    else:
        print("\nSome validation checks FAILED — review parameters.")
        sys.exit(1)


if __name__ == "__main__":
    main()

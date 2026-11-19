"""Анализ сырых прогонов: описательные статистики, тесты, размеры эффекта, графики.

Единица наблюдения — один прогон (run), а не отдельный кадр или запрос.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
PROCESSED = ROOT / "results" / "processed"
FIGURES = ROOT / "results" / "figures"
RNG = np.random.default_rng(20261119)


def configure(raw: str, tag: str) -> None:
    global RAW, PROCESSED, FIGURES
    RAW = ROOT / raw
    PROCESSED = ROOT / "results" / "processed" / tag
    FIGURES = ROOT / "results" / "figures" / tag

METRICS = [
    "fps_mean",
    "frame_p50_ms",
    "frame_p95_ms",
    "frame_p99_ms",
    "jank_pct",
    "lcp_ms",
    "fcp_ms",
    "ttfb_ms",
    "load_ms",
    "first_frame_ms",
    "transfer_bytes",
    "interaction_proxy_ms",
    "main_thread_busy_pct",
    "cls",
]


def load_runs() -> pd.DataFrame:
    rows = []
    for metrics_path in sorted(RAW.glob("*.metrics.json")):
        run_id = metrics_path.name.replace(".metrics.json", "")
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        manifest_path = RAW / f"{run_id}.manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        )
        spec = manifest.get("spec", {})
        info = payload.get("info", {})
        row = {
            "run_id": run_id,
            "block": spec.get("block"),
            "render": spec.get("render"),
            "transport": spec.get("transport"),
            "mode": spec.get("mode"),
            "rep": spec.get("rep"),
            "seed": spec.get("seed"),
            "valid": bool(payload.get("valid")),
            "offline_ok": payload.get("offline_ok"),
            "error": payload.get("error"),
            "draw_calls": info.get("draw_calls"),
            "triangles": info.get("triangles"),
            "gpu": (info.get("gpu") or {}).get("renderer"),
            "started_at": manifest.get("started_at"),
            "duration_s": payload.get("duration_s"),
        }
        for metric in METRICS:
            row[metric] = payload.get(metric)
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    frame["started_at"] = pd.to_datetime(frame["started_at"], utc=True, errors="coerce")
    frame = frame.sort_values(["started_at", "run_id"]).reset_index(drop=True)
    frame["run_index"] = frame.index
    frame["order"] = np.arange(1, len(frame) + 1)
    return frame


def bootstrap_median_ci(values: np.ndarray, iterations: int = 5000) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    if values.size < 2:
        return (math.nan, math.nan)
    idx = RNG.integers(0, values.size, size=(iterations, values.size))
    medians = np.median(values[idx], axis=1)
    return (float(np.percentile(medians, 2.5)), float(np.percentile(medians, 97.5)))


def bootstrap_ratio_ci(
    a: np.ndarray, b: np.ndarray, iterations: int = 5000
) -> tuple[float, float]:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 2 or b.size < 2:
        return (math.nan, math.nan)
    ia = RNG.integers(0, a.size, size=(iterations, a.size))
    ib = RNG.integers(0, b.size, size=(iterations, b.size))
    ratio = np.median(a[ia], axis=1) / np.median(b[ib], axis=1)
    return (float(np.percentile(ratio, 2.5)), float(np.percentile(ratio, 97.5)))


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size == 0 or b.size == 0:
        return math.nan
    diff = np.subtract.outer(a, b)
    return float(np.sign(diff).mean())


def effect_label(delta: float) -> str:
    magnitude = abs(delta)
    if math.isnan(magnitude):
        return "n/a"
    if magnitude < 0.147:
        return "negligible"
    if magnitude < 0.33:
        return "small"
    if magnitude < 0.474:
        return "medium"
    return "large"


def holm(pvalues: list[float]) -> list[float]:
    order = np.argsort(pvalues)
    adjusted = [math.nan] * len(pvalues)
    running = 0.0
    m = len(pvalues)
    for rank, idx in enumerate(order):
        value = min(1.0, (m - rank) * pvalues[idx])
        running = max(running, value)
        adjusted[idx] = running
    return adjusted


def describe(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in frame.groupby(["block", "render", "transport", "mode"], dropna=False):
        for metric in METRICS:
            values = group[metric].dropna().to_numpy(dtype=float)
            if values.size == 0:
                continue
            low, high = bootstrap_median_ci(values)
            rows.append(
                {
                    "block": keys[0],
                    "render": keys[1],
                    "transport": keys[2],
                    "mode": keys[3],
                    "metric": metric,
                    "n": int(values.size),
                    "median": float(np.median(values)),
                    "mean": float(values.mean()),
                    "sd": float(values.std(ddof=1)) if values.size > 1 else math.nan,
                    "iqr": float(np.percentile(values, 75) - np.percentile(values, 25)),
                    "cv_pct": float(100 * values.std(ddof=1) / values.mean())
                    if values.size > 1 and values.mean()
                    else math.nan,
                    "ci_low": low,
                    "ci_high": high,
                }
            )
    return pd.DataFrame(rows)


def pairwise(
    frame: pd.DataFrame,
    metric: str,
    selector: dict,
    group_field: str,
    a: str,
    b: str,
) -> dict | None:
    subset = frame.copy()
    for key, value in selector.items():
        subset = subset[subset[key] == value]
    values_a = subset[subset[group_field] == a][metric].dropna().to_numpy(dtype=float)
    values_b = subset[subset[group_field] == b][metric].dropna().to_numpy(dtype=float)
    if values_a.size < 2 or values_b.size < 2:
        return None
    pvalue = stats.mannwhitneyu(values_a, values_b, alternative="two-sided").pvalue
    delta = cliffs_delta(values_a, values_b)
    ratio_low, ratio_high = bootstrap_ratio_ci(values_a, values_b)
    median_a = float(np.median(values_a))
    median_b = float(np.median(values_b))
    return {
        "metric": metric,
        "group_field": group_field,
        "group_a": a,
        "group_b": b,
        "selector": json.dumps(selector, ensure_ascii=False),
        "n_a": int(values_a.size),
        "n_b": int(values_b.size),
        "median_a": median_a,
        "median_b": median_b,
        "delta_abs": median_a - median_b,
        "delta_pct": 100 * (median_a - median_b) / median_b if median_b else math.nan,
        "ratio_ci_low": ratio_low,
        "ratio_ci_high": ratio_high,
        "p_raw": float(pvalue),
        "cliff_delta": delta,
        "effect": effect_label(delta),
    }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (math.nan, math.nan)
    phat = successes / total
    denominator = 1 + z**2 / total
    centre = (phat + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt(phat * (1 - phat) / total + z**2 / (4 * total**2)) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def run_aa(frame: pd.DataFrame) -> dict:
    subset = frame[
        (frame["valid"])
        & (frame["block"] == "A")
        & (frame["render"] == "baseline")
        & (frame["transport"] == "fast")
        & (frame["mode"] == "no_sw_cold")
    ].sort_values("run_index")
    if len(subset) < 6:
        return {"available": False, "n": int(len(subset))}

    order = np.arange(len(subset))
    split_rng = np.random.default_rng(42)
    permuted = split_rng.permutation(order)
    half = len(subset) // 2
    group_a = subset.iloc[np.sort(permuted[:half])]
    group_b = subset.iloc[np.sort(permuted[half:])]

    result: dict = {
        "available": True,
        "n": int(len(subset)),
        "split_seed": 42,
        "groups": {"A": list(group_a["run_id"]), "B": list(group_b["run_id"])},
    }
    for metric in ["fps_mean", "frame_p95_ms", "lcp_ms"]:
        values_a = group_a[metric].dropna().to_numpy(dtype=float)
        values_b = group_b[metric].dropna().to_numpy(dtype=float)
        if values_a.size < 2 or values_b.size < 2:
            continue
        pvalue = stats.mannwhitneyu(values_a, values_b, alternative="two-sided").pvalue
        delta = cliffs_delta(values_a, values_b)
        all_values = subset[metric].dropna().to_numpy(dtype=float)
        result[metric] = {
            "median_a": float(np.median(values_a)),
            "median_b": float(np.median(values_b)),
            "diff_pct": float(
                100 * (np.median(values_a) - np.median(values_b)) / np.median(values_b)
            ),
            "p_value": float(pvalue),
            "cliff_delta": delta,
            "effect": effect_label(delta),
            "run_cv_pct": float(100 * all_values.std(ddof=1) / all_values.mean()),
            "mde_pct_approx": float(100 * 2.8 * all_values.std(ddof=1) / all_values.mean()),
        }
    return result


def drift(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in frame[frame["valid"]].groupby(["block", "render", "transport", "mode"]):
        if len(group) < 5:
            continue
        for metric in ["fps_mean", "frame_p95_ms", "lcp_ms"]:
            values = group[metric].dropna().to_numpy(dtype=float)
            if values.size < 5 or np.allclose(values, values[0]):
                continue
            rho, pvalue = stats.spearmanr(np.arange(values.size), values)
            rows.append(
                {
                    "block": keys[0],
                    "render": keys[1],
                    "transport": keys[2],
                    "mode": keys[3],
                    "metric": metric,
                    "spearman_rho": float(rho),
                    "p_value": float(pvalue),
                }
            )
    return pd.DataFrame(rows)


def plot_box(frame: pd.DataFrame) -> None:
    subset = frame[(frame["valid"]) & (frame["block"] == "A")]
    if subset.empty:
        return
    levels = [level for level in ["baseline", "instanced", "lod"] if level in set(subset["render"])]
    data = [subset[subset["render"] == level]["fps_mean"].dropna() for level in levels]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.boxplot(data, widths=0.5, showfliers=False)
    ax.set_xticks(np.arange(1, len(levels) + 1), levels)
    for index, values in enumerate(data, start=1):
        jitter = RNG.normal(0, 0.04, size=len(values))
        ax.scatter(index + jitter, values, s=18, alpha=0.75, zorder=3)
    ax.set_ylabel("FPS, среднее за прогон")
    ax.set_title("RQ1: частота кадров по методам рендеринга (transport=fast)")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_fps_by_render.png", dpi=150)
    plt.close(fig)


def plot_ecdf() -> None:
    rows = []
    for path in RAW.glob("*.frames.csv"):
        run_id = path.name.replace(".frames.csv", "")
        metrics_path = RAW / f"{run_id}.metrics.json"
        if not metrics_path.exists():
            continue
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        manifest_path = RAW / f"{run_id}.manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        spec = manifest.get("spec", {})
        if spec.get("block") != "A":
            continue
        render = spec.get("render")
        if render not in {"baseline", "instanced", "lod"}:
            continue
        frame = pd.read_csv(path)
        if frame.empty:
            continue
        rows.append((render, frame["frame_ms"].to_numpy(dtype=float)))
    if not rows:
        return

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for render in ["baseline", "instanced", "lod"]:
        values = np.concatenate([v for r, v in rows if r == render]) if any(
            r == render for r, _ in rows
        ) else None
        if values is None or values.size == 0:
            continue
        sorted_values = np.sort(values)
        y = np.arange(1, sorted_values.size + 1) / sorted_values.size
        ax.plot(sorted_values, y, label=f"{render} (n={sorted_values.size} кадров)")
    ax.set_xlim(0, 200)
    ax.set_xlabel("Длительность кадра, мс")
    ax.set_ylabel("ECDF")
    ax.set_title("Эмпирическая функция распределения длительностей кадров")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_frame_ecdf.png", dpi=150)
    plt.close(fig)


def plot_pwa(frame: pd.DataFrame) -> None:
    subset = frame[(frame["valid"]) & (frame["block"] == "B")]
    if subset.empty:
        return
    modes = ["no_sw_cold", "sw_cold", "sw_warm"]
    transports = ["fast", "slow3g"]
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    width = 0.38
    for index, transport in enumerate(transports):
        medians = []
        errors_low = []
        errors_high = []
        for mode in modes:
            values = subset[(subset["transport"] == transport) & (subset["mode"] == mode)][
                "lcp_ms"
            ].dropna()
            medians.append(float(np.median(values)) if len(values) else 0.0)
            low, high = bootstrap_median_ci(values.to_numpy(dtype=float))
            errors_low.append(max(0.0, medians[-1] - low) if len(values) else 0.0)
            errors_high.append(max(0.0, high - medians[-1]) if len(values) else 0.0)
        positions = np.arange(len(modes)) + (index - 0.5) * width
        ax.bar(
            positions,
            medians,
            width=width,
            label=transport,
            yerr=[errors_low, errors_high],
            capsize=4,
            alpha=0.85,
        )
    ax.set_xticks(np.arange(len(modes)), modes)
    ax.set_ylabel("LCP, мс (медиана, 95% bootstrap CI)")
    ax.set_title("RQ2: LCP по режимам кеширования и профилям сети")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_lcp_by_mode.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for index, transport in enumerate(transports):
        medians = []
        for mode in modes:
            values = subset[(subset["transport"] == transport) & (subset["mode"] == mode)][
                "transfer_bytes"
            ].dropna()
            medians.append(float(np.median(values)) / 1024 if len(values) else 0.0)
        positions = np.arange(len(modes)) + (index - 0.5) * width
        ax.bar(positions, medians, width=width, label=transport, alpha=0.85)
    ax.set_xticks(np.arange(len(modes)), modes)
    ax.set_ylabel("Передано, КиБ (медиана)")
    ax.set_title("RQ2: объём передачи по режимам кеширования")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_transfer_by_mode.png", dpi=150)
    plt.close(fig)


def plot_drift(frame: pd.DataFrame) -> None:
    subset = frame[(frame["valid"]) & (frame["block"] == "A") & (frame["render"] == "baseline")]
    if subset.empty:
        return
    subset = subset.sort_values("run_index")
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot(
        subset["run_index"],
        subset["fps_mean"],
        marker="o",
        linestyle="-",
        label="FPS baseline",
    )
    ax.set_xlabel("Порядковый номер прогона в общем плане")
    ax.set_ylabel("FPS, среднее за прогон")
    ax.set_title("Стабильность стенда во времени")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_drift.png", dpi=150)
    plt.close(fig)


def plot_offline(frame: pd.DataFrame) -> None:
    subset = frame[(frame["block"] == "C") & (frame["mode"].notna())]
    if subset.empty:
        return
    labels = []
    rates = []
    lows = []
    highs = []
    for mode in ["offline_sw", "offline_control"]:
        group = subset[subset["mode"] == mode]
        if group.empty:
            continue
        successes = int((group["offline_ok"] == True).sum())  # noqa: E712
        total = int(len(group))
        low, high = wilson_interval(successes, total)
        labels.append(mode)
        rates.append(100 * successes / total)
        lows.append(100 * low)
        highs.append(100 * high)
    fig, ax = plt.subplots(figsize=(6, 4))
    positions = np.arange(len(labels))
    ax.bar(positions, rates, width=0.5, alpha=0.85)
    ax.errorbar(
        positions,
        rates,
        yerr=[np.array(rates) - np.array(lows), np.array(highs) - np.array(rates)],
        fmt="none",
        ecolor="black",
        capsize=5,
    )
    ax.set_xticks(positions, labels)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Успешных офлайн-загрузок, %")
    ax.set_title("Доступность приложения офлайн (95% Wilson CI)")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_offline.png", dpi=150)
    plt.close(fig)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default="results/raw", help="каталог с сырыми прогонами")
    parser.add_argument("--tag", default="main", help="подкаталог для processed/figures")
    args = parser.parse_args()
    configure(args.raw, args.tag)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)

    frame = load_runs()
    if frame.empty:
        print("no runs found in results/raw")
        return 1

    frame.to_csv(PROCESSED / "runs.csv", index=False)
    description = describe(frame[frame["valid"]])
    description.to_csv(PROCESSED / "descriptives.csv", index=False)

    tests: list[dict] = []

    render_subset = {
        "block": "A",
        "transport": "fast",
        "mode": "no_sw_cold",
    }
    for metric in ["fps_mean", "frame_p95_ms", "jank_pct"]:
        pvalues = []
        block_rows = []
        for other in ["instanced", "lod"]:
            row = pairwise(frame, metric, render_subset, "render", other, "baseline")
            if row:
                block_rows.append(row)
                pvalues.append(row["p_raw"])
        for row, adjusted in zip(block_rows, holm(pvalues)):
            row["p_holm"] = adjusted
            row["comparison_family"] = f"A/{metric}"
            tests.append(row)

    pwa_subset = {"block": "B", "render": "baseline"}
    for transport in ["fast", "slow3g"]:
        for metric in ["lcp_ms", "load_ms", "ttfb_ms", "transfer_bytes", "first_frame_ms"]:
            rows = []
            for a, b in [("sw_cold", "no_sw_cold"), ("sw_warm", "no_sw_cold"), ("sw_warm", "sw_cold")]:
                selector = {**pwa_subset, "transport": transport}
                row = pairwise(frame, metric, selector, "mode", a, b)
                if row:
                    rows.append(row)
            for row, adjusted in zip(rows, holm([r["p_raw"] for r in rows])):
                row["p_holm"] = adjusted
                row["comparison_family"] = f"B/{transport}/{metric}"
                tests.append(row)

    tests_frame = pd.DataFrame(tests)
    tests_frame.to_csv(PROCESSED / "tests.csv", index=False)

    aa = run_aa(frame)
    (PROCESSED / "aa.json").write_text(json.dumps(aa, ensure_ascii=False, indent=2), encoding="utf-8")

    drift_frame = drift(frame)
    drift_frame.to_csv(PROCESSED / "drift.csv", index=False)

    valid = frame[frame["valid"]]
    offline_rows = []
    for mode in ["offline_sw", "offline_control"]:
        group = frame[(frame["block"] == "C") & (frame["mode"] == mode)]
        if group.empty:
            continue
        successes = int((group["offline_ok"] == True).sum())  # noqa: E712
        low, high = wilson_interval(successes, len(group))
        offline_rows.append(
            {
                "mode": mode,
                "runs": int(len(group)),
                "successes": successes,
                "success_rate": successes / len(group),
                "wilson_low": low,
                "wilson_high": high,
            }
        )
    pd.DataFrame(offline_rows).to_csv(PROCESSED / "offline.csv", index=False)

    busy = valid["main_thread_busy_pct"].dropna()
    summary = {
        "runs_total": int(len(frame)),
        "runs_valid": int(len(valid)),
        "valid_share": float(len(valid) / len(frame)) if len(frame) else 0.0,
        "main_thread_busy_median_pct": float(busy.median()) if len(busy) else None,
        "main_thread_busy_max_pct": float(busy.max()) if len(busy) else None,
        "main_thread_busy_over_80_share": float((busy > 80).mean()) if len(busy) else None,
        "renderers": sorted({str(x) for x in valid["gpu"].dropna().unique()}),
        "draw_calls": {
            str(k): int(v) for k, v in valid.groupby("render")["draw_calls"].median().items()
        },
        "aa": aa,
    }
    (PROCESSED / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    plot_box(frame)
    plot_ecdf()
    plot_pwa(frame)
    plot_drift(frame)
    plot_offline(frame)

    print(f"raw: {RAW}\nruns: {len(frame)} (valid {len(valid)})")
    print(description.to_string(index=False, max_rows=40))
    if not tests_frame.empty:
        print(tests_frame.to_string(index=False, max_rows=40))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

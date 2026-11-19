"""Один прогон эксперимента: браузерный сценарий и сбор сырых данных.

Запускается либо оркестратором (runner/run_experiment.py), либо вручную:

    python runner/playwright_runner.py --spec specs/run.json --out results/raw
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

CHROMIUM_ARGS = [
    "--enable-unsafe-swiftshader",
    "--use-angle=d3d11",
    "--disable-gpu-vsync",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--force-device-scale-factor=1",
]

NETWORK_PROFILES = {
    "fast": {"latency_ms": 0, "download_kbps": 0, "upload_kbps": 0, "cpu_slowdown": 1},
    "slow3g": {"latency_ms": 300, "download_kbps": 1600, "upload_kbps": 750, "cpu_slowdown": 4},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_url(spec: dict) -> str:
    sw = "0" if spec["mode"] in {"no_sw_cold", "offline_control"} else "1"
    params = (
        f"render={spec['render']}&objects={spec['objects']}"
        f"&seed={spec['seed']}&sw={sw}"
    )
    return f"{spec['base_url'].rstrip('/')}/?{params}"


def apply_network(context, page, profile: dict) -> None:
    cdp = context.new_cdp_session(page)
    cdp.send("Network.enable")
    latency = profile["latency_ms"]
    download = profile["download_kbps"] * 1024 / 8 if profile["download_kbps"] else -1
    upload = profile["upload_kbps"] * 1024 / 8 if profile["upload_kbps"] else -1
    cdp.send(
        "Network.emulateNetworkConditions",
        {
            "offline": False,
            "latency": latency,
            "downloadThroughput": download,
            "uploadThroughput": upload,
            "connectionType": "cellular3g" if latency else "wifi",
        },
    )
    if profile["cpu_slowdown"] > 1:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": profile["cpu_slowdown"]})
    cdp.send("Performance.enable")
    return cdp


def perf_metrics(cdp) -> dict:
    data = cdp.send("Performance.getMetrics")
    return {item["name"]: item["value"] for item in data["metrics"]}


def run_once(spec: dict) -> dict:
    profile = NETWORK_PROFILES[spec["transport"]]
    url = build_url(spec)
    viewport = spec.get("viewport", {"width": 1280, "height": 720})
    started = utc_now()
    started_perf = time.perf_counter()
    console_errors: list[str] = []

    with sync_playwright() as pw:
        args = spec.get("browser_args") or CHROMIUM_ARGS
        browser = pw.chromium.launch(headless=True, args=args)
        context = browser.new_context(
            viewport=viewport,
            device_scale_factor=1,
            service_workers="allow",
        )
        page = context.new_page()
        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
        page.on(
            "console",
            lambda msg: console_errors.append(f"console.{msg.type}: {msg.text}")
            if msg.type == "error"
            else None,
        )
        cdp = apply_network(context, page, profile)

        warmup_ms = spec["warmup_ms"]
        measure_ms = spec["measure_ms"]
        mode = spec["mode"]

        def load(expect_offline_ok: bool = False) -> bool:
            try:
                page.goto(url, wait_until="load", timeout=120000)
                page.wait_for_function("window.__bench && window.__bench.ready", timeout=120000)
                return True
            except PlaywrightError:
                if expect_offline_ok:
                    return False
                raise

        def sw_state() -> dict:
            try:
                return page.evaluate("window.__bench.waitForServiceWorker(20000)")
            except PlaywrightError:
                return {"supported": False, "error": True}

        sw_info: dict = {}
        offline_ok = None
        measure_before = perf_metrics(cdp)
        wall_before = time.perf_counter()

        if mode == "no_sw_cold":
            load()
        elif mode == "sw_cold":
            load()
            sw_info = sw_state()
        elif mode == "sw_warm":
            load()
            sw_info = sw_state()
            load()
        elif mode == "offline_sw":
            load()
            sw_info = sw_state()
            context.set_offline(True)
            offline_ok = load(expect_offline_ok=True)
        elif mode == "offline_control":
            page.goto(url, wait_until="load", timeout=120000)
            page.wait_for_function("window.__bench && window.__bench.ready", timeout=120000)
            context.set_offline(True)
            offline_ok = load(expect_offline_ok=True)
        else:
            raise ValueError(f"unknown mode: {mode}")

        if offline_ok is False:
            result = {
                "valid": False,
                "offline_ok": False,
                "error": "offline navigation failed",
                "sw": sw_info,
            }
        else:
            result = page.evaluate(
                "([w, m]) => window.__bench.measure(w, m)",
                [warmup_ms, measure_ms],
            )
            result["offline_ok"] = offline_ok
            result["sw"] = sw_info

        if result.get("valid", True):
            try:
                page.evaluate("window.__bench.startInteraction()")
                page.click("#probe", timeout=10000)
                page.wait_for_function(
                    "window.__bench._interactionResult !== null", timeout=10000
                )
                result["interaction_proxy_ms"] = page.evaluate(
                    "window.__bench._interactionResult"
                )
            except PlaywrightError:
                result["interaction_proxy_ms"] = None

        measure_after = perf_metrics(cdp)
        wall_after = time.perf_counter()

        busy = measure_after.get("TaskDuration", 0) - measure_before.get("TaskDuration", 0)
        result["main_thread_busy_pct"] = round(
            100 * busy / max(1e-9, (wall_after - wall_before)), 2
        )

        browser_version = browser.version
        context.close()
        browser.close()

    frames = result.pop("frame_series", [])
    finished = utc_now()
    result.setdefault("valid", True)
    result["console_errors"] = console_errors[:20]
    result["duration_s"] = round(time.perf_counter() - started_perf, 2)
    result["run_id"] = spec["run_id"]

    manifest = {
        "run_id": spec["run_id"],
        "started_at": started,
        "finished_at": finished,
        "spec": {k: v for k, v in spec.items() if k not in {"base_url"}},
        "url": url,
        "host": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
        },
        "browser": {"name": "chromium", "version": browser_version, "args": args},
        "network_profile": profile,
        "raw_files": {
            "metrics": f"{spec['run_id']}.metrics.json",
            "frames": f"{spec['run_id']}.frames.csv",
        },
        "config_sha256": spec.get("config_sha256"),
        "git_commit": spec.get("git_commit"),
    }
    return result, manifest, frames


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True, help="path to JSON spec")
    parser.add_argument("--out", required=True, help="output directory for raw data")
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8-sig"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    try:
        result, manifest, frames = run_once(spec)
    except Exception as exc:  # noqa: BLE001 - прогон должен фиксировать ошибку, а не падать молча
        manifest = {
            "run_id": spec["run_id"],
            "started_at": utc_now(),
            "finished_at": utc_now(),
            "spec": spec,
            "error": f"{type(exc).__name__}: {exc}",
            "git_commit": spec.get("git_commit"),
            "config_sha256": spec.get("config_sha256"),
        }
        result = {"run_id": spec["run_id"], "valid": False, "error": manifest["error"]}
        frames = []

    (out / f"{spec['run_id']}.metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / f"{spec['run_id']}.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out / f"{spec['run_id']}.frames.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["run_id", "index", "frame_ms"])
        for index, value in enumerate(frames):
            writer.writerow([spec["run_id"], index, value])

    print(
        f"{spec['run_id']}: valid={result.get('valid')} "
        f"fps={result.get('fps_mean')} p95={result.get('frame_p95_ms')} "
        f"lcp={result.get('lcp_ms')} offline={result.get('offline_ok')}"
    )
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())

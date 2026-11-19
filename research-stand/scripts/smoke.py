"""Smoke-тест стенда: сервер отдаёт файлы, браузер строит WebGL-сцену и считает кадры."""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHECKS = [
    "/",
    "/manifest.webmanifest",
    "/sw.js",
    "/js/main.js",
    "/js/scene.js",
    "/vendor/three.module.min.js",
]


def http_checks(base_url: str) -> list[str]:
    errors = []
    for path in CHECKS:
        try:
            with urllib.request.urlopen(f"{base_url}{path}", timeout=10) as response:
                if response.status != 200:
                    errors.append(f"{path}: HTTP {response.status}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: {exc}")
    return errors


def browser_check(base_url: str) -> list[str]:
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader"],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(f"{base_url}/?render=baseline&objects=200&sw=0", wait_until="load")
        page.wait_for_function("window.__bench && window.__bench.ready", timeout=30000)
        info = page.evaluate("window.__bench.info()")
        if not info.get("gpu", {}).get("renderer"):
            errors.append("webgl: renderer string is empty")
        metrics = page.evaluate("window.__bench.measure(500, 1500)")
        if not metrics.get("frames"):
            errors.append("metrics: no frames collected")
        if not metrics.get("fps_mean"):
            errors.append("metrics: fps_mean is empty")
        browser.close()
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    errors = http_checks(args.base_url)
    errors += browser_check(args.base_url)
    if errors:
        print("SMOKE FAILED")
        for error in errors:
            print("  -", error)
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

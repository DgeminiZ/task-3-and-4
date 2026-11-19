"""Оркестратор эксперимента: строит план, запускает прогоны, пишет метаданные.

Примеры:

    python runner/run_experiment.py --mode local --port 8080
    python runner/run_experiment.py --mode docker --config configs/experiment.yaml
    python runner/run_experiment.py --mode local --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import platform
import random
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sh(*args: str, env: dict | None = None) -> str:
    completed = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, **(env or {})},
    )
    return completed.stdout.strip()


def git_commit() -> str:
    try:
        return sh("git", "rev-parse", "HEAD")
    except Exception:  # noqa: BLE001
        return "no-git"


def git_dirty() -> bool:
    try:
        return bool(sh("git", "status", "--porcelain"))
    except Exception:  # noqa: BLE001
        return True


def config_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def start_local_server(port: int) -> subprocess.Popen | None:
    if port_open(port):
        print(f"[stand] local server already on :{port}")
        return None
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "local_server.py"),
            "--root",
            str(ROOT / "sut" / "public"),
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        cwd=ROOT,
    )
    for _ in range(100):
        if port_open(port):
            print(f"[stand] local server started on :{port} (pid={process.pid})")
            return process
        time.sleep(0.1)
    raise RuntimeError("local server did not start")


def build_plan(cfg: dict) -> list[dict]:
    plan: list[dict] = []
    for block in cfg["blocks"]:
        keys = list(block["factors"].keys())
        values = [block["factors"][key] for key in keys]
        repetitions = block.get("repetitions", cfg["repetitions"])
        for combo in itertools.product(*values):
            for rep in range(repetitions):
                spec = dict(zip(keys, combo))
                spec.update(
                    {
                        "block": block["id"],
                        "rep": rep,
                        "run_id": f"{block['id']}-{'_'.join(str(spec[k]) for k in keys)}-r{rep:02d}",
                    }
                )
                plan.append(spec)
    if cfg.get("randomize_order", True):
        random.Random(cfg["seed"]).shuffle(plan)
    return plan


def raw_dir(cfg: dict) -> Path:
    return ROOT / cfg.get("results_dir", "results/raw")


def write_campaign(cfg: dict, cfg_path: Path, plan: list[dict], mode: str) -> None:
    payload = {
        "name": cfg["name"],
        "seed": cfg["seed"],
        "mode": mode,
        "started_at": utc_now(),
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
        "config": str(cfg_path.relative_to(ROOT)),
        "config_sha256": config_sha256(cfg_path),
        "host": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "python": sys.version.split()[0],
        },
        "plan": plan,
        "plan_size": len(plan),
    }
    target = raw_dir(cfg) / f"_campaign_{cfg['name']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def local_spec(cfg: dict, item: dict, port: int) -> dict:
    return {
        "run_id": item["run_id"],
        "block": item["block"],
        "rep": item["rep"],
        "base_url": f"http://127.0.0.1:{port}",
        "render": item.get("render", "baseline"),
        "objects": cfg["objects"],
        "seed": cfg["seed"] + item["rep"],
        "transport": item.get("transport", "fast"),
        "mode": item.get("mode", "no_sw_cold"),
        "warmup_ms": cfg["warmup_ms"],
        "measure_ms": cfg["measure_ms"],
        "viewport": cfg["viewport"],
        "browser_args": cfg.get("browser", {}).get("args"),
        "results_dir": cfg.get("results_dir", "results/raw"),
        "git_commit": git_commit(),
        "config_sha256": cfg.get("_config_sha256"),
    }


def docker_spec(cfg: dict, item: dict) -> dict:
    spec = local_spec(cfg, item, port=80)
    spec["base_url"] = "http://sut:80"
    return spec


def run_local(spec: dict) -> int:
    target = ROOT / spec["results_dir"]
    target.mkdir(parents=True, exist_ok=True)
    spec_path = target / f"{spec['run_id']}.spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "runner" / "playwright_runner.py"),
            "--spec",
            str(spec_path),
            "--out",
            str(target),
        ],
        cwd=ROOT,
    )
    return completed.returncode


def run_docker(spec: dict) -> int:
    target = ROOT / spec["results_dir"]
    target.mkdir(parents=True, exist_ok=True)
    spec_path = target / f"{spec['run_id']}.spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    relative = spec_path.relative_to(ROOT).as_posix()
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "run",
            "run",
            "--rm",
            "-T",
            "runner",
            "--spec",
            f"/workspace/{relative}",
            "--out",
            f"/workspace/{spec['results_dir']}",
        ],
        cwd=ROOT,
    )
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "configs" / "experiment.yaml"))
    parser.add_argument("--mode", choices=["local", "docker"], default="local")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--limit", type=int, default=0, help="ограничить число прогонов")
    parser.add_argument("--block", default="", help="только указанные блоки, через запятую")
    parser.add_argument("--force", action="store_true", help="перезаписать существующие прогоны")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = (ROOT / cfg_path).resolve()
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["_config_sha256"] = config_sha256(cfg_path)

    plan = build_plan(cfg)
    if args.block:
        wanted = {item.strip().upper() for item in args.block.split(",") if item.strip()}
        plan = [item for item in plan if item["block"].upper() in wanted]
    if args.limit:
        plan = plan[: args.limit]

    print(f"plan: {len(plan)} runs, seed={cfg['seed']}, mode={args.mode}")
    if args.dry_run:
        for item in plan:
            print("  ", item["run_id"])
        return 0

    write_campaign(cfg, cfg_path, plan, args.mode)

    server = None
    if args.mode == "local":
        server = start_local_server(args.port)
        base_port = args.port
    else:
        print("[stand] docker compose up -d --build sut")
        sh("docker", "compose", "up", "-d", "--build", "sut")
        base_port = 80

    failures = 0
    try:
        for index, item in enumerate(plan, 1):
            spec = (
                local_spec(cfg, item, base_port)
                if args.mode == "local"
                else docker_spec(cfg, item)
            )
            manifest_path = raw_dir(cfg) / f"{item['run_id']}.manifest.json"
            if manifest_path.exists() and not args.force:
                print(f"[{index}/{len(plan)}] skip {item['run_id']} (exists)")
                continue
            print(f"[{index}/{len(plan)}] {item['run_id']} {spec['transport']}/{spec['mode']}")
            code = run_local(spec) if args.mode == "local" else run_docker(spec)
            if code != 0:
                failures += 1
    finally:
        if server is not None:
            server.terminate()
            print("[stand] local server stopped")

    print(f"done: {len(plan) - failures}/{len(plan)} ok")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

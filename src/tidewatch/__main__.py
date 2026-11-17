# -*- coding: utf-8 -*-
"""tidewatch 主入口。

用法：
  python -m tidewatch                              # 日常抓取
  python -m tidewatch --force                      # 忽略“今天已成功”检查，强制重跑
  python -m tidewatch --task backfill_t148 --start 2025-01-01 --end 2025-12-31
  python -m tidewatch --task backfill_zjhy --start 2025-06-01 --end 2026-11-15
  python -m tidewatch --record-failure             # 仅记录一次失败（工作流 failure 用）
  python -m tidewatch --no-dashboard               # 不生成看板（本地调试用）
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import archive, health
from .config import load_config, source_cfg
from .render import render
from .sources import glofas, gz_highlow, gz_tide, t148, typhoon, weather, zjhy
from .store import append_log
from .util import is_after_cutoff, now_cn, read_json, write_json

ROOT = Path(__file__).resolve().parents[2]
LOG_HEADERS = ["run_at", "task", "source", "status", "rows", "duration_s", "message"]
REQUIRED = ("gz_tide", "t148")
TASKS = {
    "gz_tide": gz_tide,
    "gz_highlow": gz_highlow,
    "t148": t148,
    "zjhy": zjhy,
    "weather": weather,
    "glofas": glofas,
    "typhoon": typhoon,
}


def log(msg: str) -> None:
    print(f"[{now_cn().strftime('%H:%M:%S')}] {msg}", flush=True)


def _skip_reason(cfg: dict) -> str | None:
    """当天已“有效”抓取过则返回原因；凌晨的延迟运行不算（必须 >= daily_ready_after）。"""
    last = read_json(ROOT / "data" / "meta" / "last_run.json", {}) or {}
    if last.get("date") != now_cn().date().isoformat() or last.get("status") != "ok":
        return None
    cutoff = str(cfg.get("general", {}).get("daily_ready_after", "14:30"))
    run_at = str(last.get("run_at", ""))
    if is_after_cutoff(run_at, cutoff):
        return f"今天 {run_at} 已成功抓取（>= {cutoff}）"
    return None


def _last_run_brief() -> str:
    last = read_json(ROOT / "data" / "meta" / "last_run.json", {}) or {}
    return f"{last.get('run_at', '?')}"


def _write_log(row: dict) -> None:
    append_log(ROOT, row, LOG_HEADERS)


def _archive_steps(cfg: dict, log, results: dict | None = None,
                   force_snapshot: bool = False) -> None:
    """归档旧月份 + 按需刷新 latest 快照；结果写入 results（若提供）与运行日志。"""
    sc = source_cfg(cfg, "archive")
    if not sc.get("enabled", True):
        return
    try:
        res = archive.run(cfg, ROOT, log)
    except Exception as exc:  # noqa: BLE001
        res = {"status": "error", "rows": 0, "message": str(exc)}
        log(f"!! archive ERROR: {exc}")
    if results is not None:
        results["archive"] = res
    _write_log({"run_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"), "task": "archive",
                "source": "archive", "status": res.get("status"), "rows": res.get("rows", 0),
                "duration_s": "", "message": str(res.get("message", ""))[:200]})

    day = now_cn().day
    if sc.get("snapshot_enabled", True) and (force_snapshot or day == int(sc.get("snapshot_on_day", 1))):
        try:
            res2 = archive.snapshot(cfg, ROOT, log, force=force_snapshot)
        except Exception as exc:  # noqa: BLE001
            res2 = {"status": "error", "rows": 0, "message": str(exc)}
            log(f"!! snapshot ERROR: {exc}")
        if results is not None:
            results["snapshot"] = res2
        _write_log({"run_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"), "task": "snapshot",
                    "source": "snapshot", "status": res2.get("status"), "rows": res2.get("rows", 0),
                    "duration_s": "", "message": str(res2.get("message", ""))[:200]})


def daily(cfg: dict, force: bool = False, no_dashboard: bool = False) -> int:
    reason = _skip_reason(cfg)
    if reason and not force:
        log(f"{reason}；跳过抓取。")
        _archive_steps(cfg, log)
        return 0
    if _last_run_brief() and not force:
        last = (read_json(ROOT / "data" / "meta" / "last_run.json", {}) or {})
        if last.get("date") == now_cn().date().isoformat():
            log(f"上次运行 {last.get('run_at')} 早于每日 {cfg.get('general', {}).get('daily_ready_after', '14:30')} 起报时刻，继续抓取。")
    results: dict[str, dict] = {}
    for name, mod in TASKS.items():
        sc = source_cfg(cfg, name)
        if not sc.get("enabled", True):
            log(f"skip {name} (disabled)")
            continue
        t0 = time.time()
        try:
            res = mod.run(cfg, ROOT, log)
        except Exception as exc:  # noqa: BLE001
            res = {"status": "error", "rows": 0, "message": str(exc)}
            log(f"!! {name} ERROR: {exc}")
        dur = round(time.time() - t0, 1)
        results[name] = res
        _write_log({"run_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"), "task": "daily",
                    "source": name, "status": res.get("status", ""), "rows": res.get("rows", 0),
                    "duration_s": dur, "message": str(res.get("message", ""))[:200]})

    _archive_steps(cfg, log, results)

    required_failed = [k for k, v in results.items() if v.get("status") == "error" and k in REQUIRED]
    if required_failed:
        overall = "error"
    elif any(v.get("status") == "partial" for v in results.values()):
        overall = "partial"
    else:
        overall = "ok"
    summary = {k: {"status": v.get("status"), "rows": v.get("rows"),
                   "message": str(v.get("message", ""))[:120]} for k, v in results.items()}
    write_json(ROOT / "data" / "meta" / "last_run.json", {
        "date": now_cn().date().isoformat(),
        "run_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
        "task": "daily", "status": overall, "results": summary,
    })
    health.record_run(ROOT, "daily", summary, overall)

    log("---- summary ----")
    for k, v in summary.items():
        log(f"  {k}: {v['status']} rows={v['rows']} {v['message']}")
    if not no_dashboard:
        try:
            path = render(ROOT, cfg, results)
            log(f"dashboard: {path}")
        except Exception as exc:  # noqa: BLE001
            log(f"!! dashboard render failed: {exc}")
    return 1 if required_failed else 0


def backfill(cfg: dict, task: str, start: str, end: str) -> int:
    if task == "backfill_t148":
        res = t148.backfill(cfg, ROOT, start, end, log)
    else:
        res = zjhy.backfill(cfg, ROOT, start, end, log)
    _write_log({"run_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"), "task": task,
                "source": task, "status": res["status"], "rows": res["rows"],
                "duration_s": "", "message": res["message"][:200]})
    health.record_run(ROOT, task, {task: res}, res["status"])
    log(f"== {task}: {res['status']} rows={res['rows']} {res['message']}")
    return 0 if res["status"] != "error" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="鸦岗断面潮位/水位数据采集（tidewatch）")
    ap.add_argument("--task", default="daily",
                    choices=["daily", "backfill_t148", "backfill_zjhy", "archive", "snapshot"])
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--force", action="store_true", help="忽略今天已成功检查，强制重跑/强制刷新快照")
    ap.add_argument("--no-dashboard", action="store_true", help="不生成 docs 看板")
    ap.add_argument("--no-delete-raw", action="store_true", help="归档时不删除 data/ 原始月文件（仅测试）")
    ap.add_argument("--record-failure", action="store_true", help="仅记录一次失败（工作流用）")
    args = ap.parse_args()

    if args.record_failure:
        health.record_failure(ROOT)
        log("failure recorded -> data/health/failures.jsonl")
        return 0

    cfg = load_config(ROOT)
    log(f"task={args.task}")
    if args.task == "daily":
        return daily(cfg, force=args.force, no_dashboard=args.no_dashboard)
    if args.task == "archive":
        res = archive.run(cfg, ROOT, log, delete_raw=not args.no_delete_raw)
        _write_log({"run_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"), "task": "archive",
                    "source": "archive", "status": res["status"], "rows": res["rows"],
                    "duration_s": "", "message": res["message"][:200]})
        log(f"== archive: {res['status']} rows={res['rows']} {res['message']}")
        return 0 if res["status"] != "error" else 1
    if args.task == "snapshot":
        res = archive.snapshot(cfg, ROOT, log, force=True)
        _write_log({"run_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"), "task": "snapshot",
                    "source": "snapshot", "status": res["status"], "rows": res["rows"],
                    "duration_s": "", "message": res["message"][:200]})
        log(f"== snapshot: {res['status']} rows={res['rows']} {res['message']}")
        return 0 if res["status"] != "error" else 1
    if not args.start or not args.end:
        log("backfill 需要 --start 和 --end（YYYY-MM-DD）")
        return 2
    return backfill(cfg, args.task, args.start, args.end)


if __name__ == "__main__":
    sys.exit(main())

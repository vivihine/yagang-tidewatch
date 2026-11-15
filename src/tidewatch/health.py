# -*- coding: utf-8 -*-
"""运行健康记录（供每周/故障排查使用）。"""
from __future__ import annotations

import os
from pathlib import Path

from .store import append_jsonl
from .util import now_cn

RUNS = "data/health/runs.jsonl"
FAILURES = "data/health/failures.jsonl"


def record_run(root: Path, task: str, summary: dict, status: str) -> None:
    append_jsonl(root / RUNS, {
        "run_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
        "task": task,
        "status": status,
        "results": {k: {"status": v.get("status"), "rows": v.get("rows")}
                    for k, v in summary.items()},
    })


def record_failure(root: Path) -> None:
    append_jsonl(root / FAILURES, {
        "run_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "run_number": os.environ.get("GITHUB_RUN_NUMBER", ""),
        "run_url": os.environ.get("GITHUB_RUN_URL", ""),
        "event": os.environ.get("GITHUB_EVENT_NAME", ""),
    })

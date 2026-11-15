# -*- coding: utf-8 -*-
"""按月 CSV 追加/去重存储。"""
from __future__ import annotations

import csv
from pathlib import Path


def append_monthly(root: Path, dataset: str, rows: list[dict], headers: list[str],
                   key_fields: list[str], month_field: str = "month") -> int:
    """把 rows 按月写入 data/<dataset>/<YYYY-MM>.csv；按 key_fields 去重。返回新增行数。"""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        month = str(r.get(month_field, ""))[:7]
        if len(month) != 7:
            raise ValueError(f"bad {month_field}: {r.get(month_field)!r}")
        groups.setdefault(month, []).append(r)

    added_total = 0
    for month, new_rows in groups.items():
        path = root / "data" / dataset / f"{month}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict] = []
        keys: set[tuple] = set()
        if path.exists():
            with path.open(newline="", encoding="utf-8-sig") as f:
                existing = list(csv.DictReader(f))
            for e in existing:
                keys.add(tuple(str(e.get(k, "")) for k in key_fields))
        added: list[dict] = []
        for r in new_rows:
            k = tuple(str(r.get(k, "")) for k in key_fields)
            if k in keys:
                continue
            keys.add(k)
            added.append(r)
        if not added and existing:
            continue
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            w.writeheader()
            combined = sorted(existing + added,
                              key=lambda r: tuple(str(r.get(k, "")) for k in key_fields))
            for row in combined:
                w.writerow({h: row.get(h, "") for h in headers})
        added_total += len(added)
    return added_total


def append_jsonl(path: Path, obj: dict) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def append_log(root: Path, row: dict, headers: list[str]) -> None:
    """追加运行日志到 data/meta/run_log.csv。"""
    path = root / "data" / "meta" / "run_log.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow({h: row.get(h, "") for h in headers})

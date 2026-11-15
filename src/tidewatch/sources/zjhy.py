# -*- coding: utf-8 -*-
"""交通运输部珠江航务管理局 / 交通运输部网站：珠江水情信息（每日 8:00 实测水位/流量）。"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from pathlib import Path

from ..config import source_cfg
from ..util import http_get, now_cn, table_rows
from ..store import append_monthly

HEADERS = ["source", "report_date", "station", "time", "level_m", "flow_m3s", "fetched_at", "url"]
LINK_RE = re.compile(r'href="([^"]+?)"[^>]*>\s*(\d{4})年(\d{1,2})月(\d{1,2})日水情信息')


def _get_index(base: str) -> list[tuple[str, str]]:
    html = http_get(base)
    out = []
    for m in LINK_RE.finditer(html):
        href, y, mo, d = m.groups()
        out.append((f"{int(y):04d}-{int(mo):02d}-{int(d):02d}", urllib.parse.urljoin(base, href)))
    return out


def parse_article(html: str) -> list[list[str]]:
    rows = []
    for r in table_rows(html):
        if len(r) >= 3 and re.fullmatch(r"\d{2}-\d{2} \d{2}:\d{2}", r[1] or ""):
            rows.append(r)
    return rows


def _fetch_reports(cfg: dict, dates: set[str], log) -> tuple[list[dict], list[str]]:
    sc = source_cfg(cfg, "zjhy")
    rows: list[dict] = []
    errors: list[str] = []
    index: list[tuple[str, str]] = []
    for base in sc.get("bases", []):
        try:
            idx = _get_index(base)
            log(f"  zjhy index {base}: {len(idx)} links")
            index.extend(idx)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"index {base}: {exc}")
            log(f"  zjhy index FAILED {base}: {exc}")
    by_date: dict[str, str] = {}
    for date, url in index:
        by_date.setdefault(date, url)
    for date in sorted(dates):
        url = by_date.get(date)
        if not url:
            log(f"  zjhy {date}: no report link (skip, e.g. weekend)")
            continue
        try:
            recs = parse_article(http_get(url))
            if not recs:
                raise RuntimeError("no table rows parsed")
            for r in recs:
                rows.append({
                    "source": "zjhy_daily",
                    "report_date": date,
                    "station": r[0],
                    "time": r[1],
                    "level_m": r[2],
                    "flow_m3s": r[3] if len(r) > 3 else "",
                    "fetched_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
                    "url": url,
                })
            log(f"  zjhy {date}: {len(recs)} stations")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{date}: {exc}")
            log(f"  zjhy {date} FAILED: {exc}")
    return rows, errors


def _existing_dates(root: Path) -> set[str]:
    import csv
    out: set[str] = set()
    d = root / "data" / "zjhy"
    if d.exists():
        for f in d.glob("*.csv"):
            with f.open(newline="", encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    if row.get("report_date"):
                        out.add(row["report_date"])
    return out


def run(cfg: dict, root: Path, log) -> dict:
    sc = source_cfg(cfg, "zjhy")
    today = now_cn().date()
    lookback = int(sc.get("lookback_days", 3))
    want = {(today - dt.timedelta(days=i)).isoformat() for i in range(lookback + 1)}
    want -= _existing_dates(root)
    if not want:
        return {"status": "ok", "rows": 0, "message": "no new dates"}
    rows, errors = _fetch_reports(cfg, want, log)
    for r in rows:
        r["month"] = r["report_date"][:7]
    added = append_monthly(root, "zjhy", rows, HEADERS,
                           key_fields=["report_date", "station", "time"])
    status = "ok" if not errors else ("partial" if rows else "error")
    return {"status": status, "rows": added, "message": "; ".join(errors[:5])}


def backfill(cfg: dict, root: Path, start: str, end: str, log) -> dict:
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    existing = _existing_dates(root)
    want = set()
    d = d0
    while d <= d1:
        if d.isoformat() not in existing:
            want.add(d.isoformat())
        d += dt.timedelta(days=1)
    if not want:
        return {"status": "ok", "rows": 0, "message": "no missing dates"}
    rows, errors = _fetch_reports(cfg, want, log)
    for r in rows:
        r["month"] = r["report_date"][:7]
    added = append_monthly(root, "zjhy", rows, HEADERS,
                           key_fields=["report_date", "station", "time"])
    status = "ok" if not errors else ("partial" if rows else "error")
    return {"status": status, "rows": added, "message": "; ".join(errors[:5])}

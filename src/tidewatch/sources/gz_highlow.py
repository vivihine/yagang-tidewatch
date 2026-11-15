# -*- coding: utf-8 -*-
"""g.hyyb 风暴潮系统：广州/黄埔/南沙 未来约 16 天高低潮（珠基）。"""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

from ..config import source_cfg
from ..util import http_get, now_cn, table_rows
from ..store import append_monthly

BASE = (
    "http://g.hyyb.org/systems/HyybTyhoonStormsurge/Tide/Zongtai/TideZongtaiStation2.php"
    "?stationC={cn}&stationE={en}&WarningLevel=/&DatumLevel=%E7%8F%A0%E5%9F%BA&Zhujiang=0"
)

HEADERS = [
    "source", "station_name", "run_time", "date",
    "high1_time", "high1_cm", "high2_time", "high2_cm",
    "low1_time", "low1_cm", "low2_time", "low2_cm",
    "fetched_at", "url",
]


def parse_rows(station: dict, html: str, run_time: str, fetched_at: str) -> list[dict]:
    rows = []
    for r in table_rows(html):
        if not r or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[0]):
            continue
        r += [""] * (9 - len(r))
        rows.append({
            "source": "g_hyyb_gz_highlow",
            "station_name": station["name"],
            "run_time": run_time,
            "date": r[0],
            "high1_time": r[1], "high1_cm": r[2],
            "high2_time": r[3], "high2_cm": r[4],
            "low1_time": r[5], "low1_cm": r[6],
            "low2_time": r[7], "low2_cm": r[8],
            "fetched_at": fetched_at,
            "url": BASE.format(cn=urllib.parse.quote(station["name"]), en=station["en"]),
        })
    return rows


def run(cfg: dict, root: Path, log) -> dict:
    sc = source_cfg(cfg, "gz_highlow")
    run_time = now_cn().strftime("%Y-%m-%d %H:%M")
    fetched_at = now_cn().strftime("%Y-%m-%d %H:%M:%S")
    rows, errors = [], []
    for st in sc.get("stations", []):
        url = BASE.format(cn=urllib.parse.quote(st["name"]), en=st["en"])
        try:
            recs = parse_rows(st, http_get(url), run_time, fetched_at)
            if not recs:
                raise RuntimeError("no data rows parsed")
            rows.extend(recs)
            log(f"  gz_highlow {st['name']}: {len(recs)} rows")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{st['name']}: {exc}")
            log(f"  gz_highlow {st['name']} FAILED: {exc}")
    for r in rows:
        r["month"] = r["date"][:7]
    added = append_monthly(root, "gz_highlow", rows, HEADERS,
                           key_fields=["station_name", "date", "run_time"])
    status = "ok" if not errors else ("partial" if rows else "error")
    return {"status": status, "rows": added, "message": "; ".join(errors)}

# -*- coding: utf-8 -*-
"""国家海洋信息中心 publictide 潮汐表 T148「广州」：天文潮逐时 + 高低潮。

接口（POST JSON）：/Tide/GetTideData {"PortCode","TideType","Date"}
- TideType=0 潮汐；返回 report（站名/坐标/基准面）+ data（a0..a23 逐时 cm + cs/cg 高低潮）
- 可查询范围实测约 2025-01-01 ～ 2027-12-31（超出返回空）
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from ..config import source_cfg
from ..util import http_post_json, now_cn, safe_float
from ..store import append_monthly

API = "https://publictide.nmdis.org.cn/Tide/GetTideData"
PAGE = ("https://publictide.nmdis.org.cn/Tide/TideData"
        "?PortCode={port}&TideType=0&SiteGroup=3&DataType=1")

HOURLY_HEADERS = ["source", "port_code", "date", "hour", "height_cm", "fetched_at"]
HL_HEADERS = ["source", "port_code", "date", "seq", "time", "height_cm", "fetched_at"]
STATION_HEADERS = ["port_code", "title", "coordinate", "time_area", "benchmark", "fetched_at"]


def fetch_day(port: str, date: str) -> tuple[dict, list[dict], list[dict]]:
    raw = http_post_json(API, {"PortCode": port, "TideType": "0", "Date": date},
                         extra_headers={"Referer": PAGE.format(port=port)})
    if not raw.get("Data"):
        raise RuntimeError(f"empty Data for {date}: {str(raw)[:120]}")
    obj = json.loads(raw["Data"])
    report = obj["report"]
    data = obj["data"]
    fetched_at = now_cn().strftime("%Y-%m-%d %H:%M:%S")
    hourly = []
    for h in range(24):
        v = data.get(f"a{h}")
        if v is None:
            continue
        hourly.append({"source": "nmdis_publictide", "port_code": port, "date": date,
                       "hour": f"{h:02d}", "height_cm": safe_float(v), "fetched_at": fetched_at})
    hl = []
    for i in range(8):
        t, v = data.get(f"cs{i}"), data.get(f"cg{i}")
        if t is None or v is None:
            continue
        hl.append({"source": "nmdis_publictide", "port_code": port, "date": date,
                   "seq": i + 1, "time": t, "height_cm": safe_float(v), "fetched_at": fetched_at})
    return report, hourly, hl


def _station_row(report: dict, port: str, fetched_at: str) -> dict:
    return {"port_code": port,
            "title": str(report.get("Title", "")).strip(),
            "coordinate": str(report.get("Coordinate", "")).strip(),
            "time_area": str(report.get("TimeArea", "")).strip(),
            "benchmark": str(report.get("Benchmark", "")).strip(),
            "fetched_at": fetched_at}


def run(cfg: dict, root: Path, log) -> dict:
    sc = source_cfg(cfg, "t148")
    port = sc.get("port_code", "T148")
    today = now_cn().date()
    days = [today + dt.timedelta(days=d)
            for d in range(-int(sc.get("days_back", 0)), int(sc.get("days_ahead", 7)) + 1)]
    hourly, hl, errors = [], [], []
    report = None
    for d in days:
        date = d.isoformat()
        try:
            rep, h, l = fetch_day(port, date)
            report = rep
            hourly.extend(h)
            hl.extend(l)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{date}: {exc}")
            log(f"  t148 {date} FAILED: {exc}")
    for r in hourly:
        r["month"] = r["date"][:7]
    for r in hl:
        r["month"] = r["date"][:7]
    added_h = append_monthly(root, "t148/hourly", hourly, HOURLY_HEADERS,
                             key_fields=["port_code", "date", "hour"])
    added_l = append_monthly(root, "t148/highlow", hl, HL_HEADERS,
                             key_fields=["port_code", "date", "seq"])
    if report:
        import csv
        st_path = root / "data" / "t148" / "station.csv"
        st_path.parent.mkdir(parents=True, exist_ok=True)
        exists = st_path.exists()
        with st_path.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=STATION_HEADERS, extrasaction="ignore")
            if not exists:
                w.writeheader()
            w.writerow(_station_row(report, port, now_cn().strftime("%Y-%m-%d %H:%M:%S")))
    status = "ok" if not errors else ("partial" if hourly else "error")
    log(f"  t148 {port}: {len(hourly)} hourly, {len(hl)} high/low, {len(errors)} failed days")
    return {"status": status, "rows": added_h + added_l, "message": "; ".join(errors[:5])}


def backfill(cfg: dict, root: Path, start: str, end: str, log) -> dict:
    sc = source_cfg(cfg, "t148")
    port = sc.get("port_code", "T148")
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    hourly, hl, errors = [], [], []
    d = d0
    while d <= d1:
        date = d.isoformat()
        try:
            _, h, l = fetch_day(port, date)
            hourly.extend(h)
            hl.extend(l)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{date}: {exc}")
            log(f"  t148 backfill {date} FAILED: {exc}")
        d += dt.timedelta(days=1)
        if d.day == 1 or d == d1:
            log(f"  t148 backfill progress: {date}")
    for r in hourly:
        r["month"] = r["date"][:7]
    for r in hl:
        r["month"] = r["date"][:7]
    added_h = append_monthly(root, "t148/hourly", hourly, HOURLY_HEADERS,
                             key_fields=["port_code", "date", "hour"])
    added_l = append_monthly(root, "t148/highlow", hl, HL_HEADERS,
                             key_fields=["port_code", "date", "seq"])
    status = "ok" if not errors else ("partial" if hourly else "error")
    return {"status": status, "rows": added_h + added_l,
            "message": f"{len(errors)} failed days; " + "; ".join(errors[:3])}

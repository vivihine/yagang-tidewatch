# -*- coding: utf-8 -*-
"""g.hyyb 数值预报格点（广州河段）逐时：天文潮 / 总水位 / 增水。"""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

from ..config import source_cfg
from ..util import http_get, now_cn, safe_int, table_rows
from ..store import append_monthly

FORM = (
    "http://g.hyyb.org/systems/HyybTyhoonStormsurge/OperationalForecast/Tide/"
    "station_points_form.php?dykedem=335&sserial={sserial}&station={station}"
    "&stationc={stationc}&zj={zj}&warning={warning}&tide_file=gz"
)

HEADERS = [
    "source", "station_code", "station_name", "run_time", "lead_h", "valid_time",
    "astro_cm", "total_cm", "surge_cm", "dist_to_warning_cm", "dist_to_dike_cm",
    "fetched_at", "url",
]


def parse_rows(station: dict, html: str, run_time: str, fetched_at: str) -> list[dict]:
    rows: list[dict] = []
    recs = [r for r in table_rows(html) if r and re.fullmatch(r"\d{10}", r[0])]
    for idx, r in enumerate(recs):
        r += [""] * (6 - len(r))
        t = r[0]
        valid = f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:00:00"
        rows.append({
            "source": "g_hyyb_gz_grid",
            "station_code": station["code"],
            "station_name": station["name"],
            "run_time": run_time,
            "lead_h": idx,
            "valid_time": valid,
            "astro_cm": safe_int(r[1]),
            "total_cm": safe_int(r[2]),
            "surge_cm": safe_int(r[3]),
            "dist_to_warning_cm": r[4],
            "dist_to_dike_cm": r[5],
            "fetched_at": fetched_at,
            "url": FORM.format(sserial=station["sserial"], station=station["code"],
                               stationc=urllib.parse.quote(station["name"]),
                               zj=station["zj"], warning=station["warning"]),
        })
    return rows


def run(cfg: dict, root: Path, log) -> dict:
    sc = source_cfg(cfg, "gz_tide")
    stations = sc.get("stations", [])
    run_time = now_cn().strftime("%Y-%m-%d %H:%M")
    fetched_at = now_cn().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[dict] = []
    errors: list[str] = []
    for st in stations:
        url = FORM.format(sserial=st["sserial"], station=st["code"],
                          stationc=urllib.parse.quote(st["name"]),
                          zj=st["zj"], warning=st["warning"])
        try:
            recs = parse_rows(st, http_get(url), run_time, fetched_at)
            if not recs:
                raise RuntimeError("no data rows parsed")
            rows.extend(recs)
            log(f"  gz_tide {st['code']} {st['name']}: {len(recs)} rows")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{st['code']}: {exc}")
            log(f"  gz_tide {st['code']} FAILED: {exc}")
    for r in rows:
        r["month"] = r["valid_time"][:7]
    added = append_monthly(root, "gz_tide", rows, HEADERS,
                           key_fields=["station_code", "valid_time", "run_time"])
    status = "ok" if not errors else ("partial" if rows else "error")
    return {"status": status, "rows": added, "message": "; ".join(errors)}

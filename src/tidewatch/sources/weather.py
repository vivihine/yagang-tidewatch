# -*- coding: utf-8 -*-
"""Open-Meteo 天气预报（鸦岗断面坐标，逐时气象要素）。"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from ..config import source_cfg
from ..util import http_get, now_cn
from ..store import append_monthly

API = "https://api.open-meteo.com/v1/forecast"
HEADERS = [
    "source", "run_time", "valid_time", "lead_h",
    "temp_c", "pressure_hpa", "wind_speed_kmh", "wind_dir_deg",
    "humidity_pct", "shortwave_wm2", "precip_mm", "fetched_at",
]
FIELDS = {
    "temperature_2m": "temp_c",
    "pressure_msl": "pressure_hpa",
    "wind_speed_10m": "wind_speed_kmh",
    "wind_direction_10m": "wind_dir_deg",
    "relative_humidity_2m": "humidity_pct",
    "shortwave_radiation": "shortwave_wm2",
    "precipitation": "precip_mm",
}


def run(cfg: dict, root: Path, log) -> dict:
    sc = source_cfg(cfg, "weather")
    params = {
        "latitude": sc["latitude"], "longitude": sc["longitude"],
        "hourly": ",".join(FIELDS.keys()),
        "timezone": "Asia/Shanghai",
        "forecast_days": sc.get("forecast_days", 7),
        "past_days": sc.get("past_days", 0),
    }
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    data = json.loads(http_get(f"{API}?{qs}"))
    hourly = data["hourly"]
    run_dt = now_cn().replace(minute=0, second=0, microsecond=0)
    rows = []
    for i, t in enumerate(hourly["time"]):
        valid = dt.datetime.strptime(t, "%Y-%m-%dT%H:%M")
        row = {
            "source": "open_meteo_forecast",
            "run_time": run_dt.strftime("%Y-%m-%d %H:%M"),
            "valid_time": valid.strftime("%Y-%m-%d %H:%M:%S"),
            "lead_h": int((valid - run_dt.replace(tzinfo=None)).total_seconds() // 3600),
            "fetched_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
        }
        for src_key, out_key in FIELDS.items():
            row[out_key] = hourly[src_key][i]
        row["month"] = valid.strftime("%Y-%m")
        rows.append(row)
    added = append_monthly(root, "weather", rows, HEADERS,
                           key_fields=["valid_time", "run_time"])
    log(f"  weather: {len(rows)} rows ({params['past_days']} past + {params['forecast_days']} forecast days)")
    return {"status": "ok", "rows": added, "message": ""}

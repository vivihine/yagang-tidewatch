# -*- coding: utf-8 -*-
"""Open-Meteo GloFAS 河流流量（日值，预报/历史）。"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import source_cfg
from ..util import http_get, now_cn
from ..store import append_monthly

API = "https://flood-api.open-meteo.com/v1/flood"
HEADERS = ["source", "point_name", "lat", "lon", "run_time", "date", "discharge_m3s", "fetched_at"]


def run(cfg: dict, root: Path, log) -> dict:
    sc = source_cfg(cfg, "glofas")
    rows, errors = [], []
    run_time = now_cn().strftime("%Y-%m-%d %H:%M")
    for p in sc.get("points", []):
        url = (f"{API}?latitude={p['lat']}&longitude={p['lon']}"
               f"&daily=river_discharge&timezone=Asia%2FShanghai"
               f"&forecast_days={sc.get('forecast_days', 7)}&past_days={sc.get('past_days', 0)}")
        try:
            daily = json.loads(http_get(url))["daily"]
            for d, q in zip(daily["time"], daily["river_discharge"]):
                rows.append({
                    "source": "open_meteo_glofas",
                    "point_name": p["name"], "lat": p["lat"], "lon": p["lon"],
                    "run_time": run_time, "date": d, "discharge_m3s": q,
                    "fetched_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
                })
            log(f"  glofas {p['name']}: {len(daily['time'])} days")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{p['name']}: {exc}")
            log(f"  glofas {p['name']} FAILED: {exc}")
    for r in rows:
        r["month"] = r["date"][:7]
    added = append_monthly(root, "glofas", rows, HEADERS,
                           key_fields=["point_name", "date", "run_time"])
    status = "ok" if not errors else ("partial" if rows else "error")
    return {"status": status, "rows": added, "message": "; ".join(errors)}

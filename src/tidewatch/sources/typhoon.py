# -*- coding: utf-8 -*-
"""中央气象台台风网：台风列表（原始 JSONP + 解析 CSV）。"""
from __future__ import annotations

import json
from pathlib import Path

from ..util import http_get, now_cn, write_json
from ..store import append_monthly

API = "http://typhoon.nmc.cn/weatherservice/typhoon/jsons/list_default?callback=callback_typhoon"
HEADERS = ["source", "typhoon_id", "name_en", "name_cn", "code", "status", "fetched_at"]


def parse_typhoon_listp(text: str) -> dict:
    text = text.strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        raise RuntimeError(f"unexpected typhoon response: {text[:120]}")
    return json.loads(text[i:j + 1])


def run(cfg: dict, root: Path, log) -> dict:
    fetched_at = now_cn().strftime("%Y-%m-%d %H:%M:%S")
    data = parse_typhoon_listp(http_get(API))
    tlist = data.get("typhoonList", [])
    raw_path = root / "data" / "typhoon" / "raw" / f"{now_cn().strftime('%Y-%m-%d')}.json"
    write_json(raw_path, data)
    rows = []
    for t in tlist:
        rows.append({
            "source": "nmc_typhoon",
            "typhoon_id": t[0] if len(t) > 0 else "",
            "name_en": t[1] if len(t) > 1 else "",
            "name_cn": t[2] if len(t) > 2 else "",
            "code": t[3] if len(t) > 3 else "",
            "status": t[7] if len(t) > 7 else "",
            "fetched_at": fetched_at,
            "month": now_cn().strftime("%Y-%m"),
        })
    added = append_monthly(root, "typhoon", rows, HEADERS,
                           key_fields=["typhoon_id", "status", "fetched_at"])
    log(f"  typhoon: {len(rows)} entries -> {raw_path.name}")
    return {"status": "ok", "rows": added, "message": ""}

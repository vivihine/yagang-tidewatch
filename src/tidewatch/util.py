# -*- coding: utf-8 -*-
"""公共工具：HTTP（带 curl 回退）、HTML 表格解析、时间、配置。"""
from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 yagang-tidewatch/1.0"
)
CN_TZ = _dt.timezone(_dt.timedelta(hours=8), "Asia/Shanghai")


def now_cn() -> _dt.datetime:
    return _dt.datetime.now(CN_TZ)


def ts(dt: _dt.datetime | None = None) -> str:
    return (dt or now_cn()).strftime("%Y-%m-%d %H:%M:%S")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def _curl_get(url: str, timeout: int) -> bytes:
    cmd = ["curl", "-sS", "-L", "-k", "--http1.1", "--tlsv1.2",
           "--max-time", str(timeout), "-A", UA, url]
    res = subprocess.run(cmd, capture_output=True, timeout=timeout + 15)
    if res.returncode != 0 or not res.stdout:
        raise RuntimeError(f"curl failed rc={res.returncode}: {res.stderr.decode('utf-8', 'ignore')[:200]}")
    return res.stdout


def http_get(url: str, timeout: int = 60, retries: int = 3) -> str:
    """GET 文本；先 urllib，失败回退 curl（部分站点对 TLS 客户端挑剔）。"""
    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _decode(resp.read())
        except Exception as exc:  # noqa: BLE001
            last = exc
        try:
            return _decode(_curl_get(url, timeout))
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def http_post_json(url: str, payload: dict, timeout: int = 60, retries: int = 3,
                   extra_headers: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": UA,
               "X-Requested-With": "XMLHttpRequest"}
    if extra_headers:
        headers.update(extra_headers)
    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(_decode(resp.read()))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"POST failed {url}: {last}")


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


def table_rows(html: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        cells = [strip_tags(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)]
        if cells:
            rows.append(cells)
    return rows


def q(s: str) -> str:
    return urllib.parse.quote(s)


def safe_float(x):
    try:
        return float(str(x).strip())
    except Exception:  # noqa: BLE001
        return None


def safe_int(x):
    try:
        return int(float(str(x).strip()))
    except Exception:  # noqa: BLE001
        return None


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def is_after_cutoff(run_at: str, cutoff: str) -> bool:
    """run_at='YYYY-MM-DD HH:MM:SS' 的 HH:MM 是否 >= cutoff（'HH:MM'）。"""
    t = str(run_at)[11:16] if len(str(run_at)) >= 16 else ""
    return bool(t) and t >= cutoff


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

# -*- coding: utf-8 -*-
"""生成 GitHub Pages 看板（docs/index.html）与 docs/latest.json。

只读取 data/ 下已抓取的 CSV，不额外访问网络；数据缺失时对应区块显示“暂无”。
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import json
from pathlib import Path

from .util import now_cn, read_json, write_json

ZJHY_WATCH = ["梧州（四）", "石角", "高要", "大虎（二）", "天河（二）", "冯马庙（二）"]


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _month_files(root: Path, dataset: str) -> list[Path]:
    d = root / "data" / dataset
    return sorted(d.glob("*.csv")) if d.exists() else []


def _gz_latest(root: Path) -> list[dict]:
    rows: list[dict] = []
    for p in _month_files(root, "gz_tide"):
        rows.extend(_rows(p))
    now = now_cn().strftime("%Y-%m-%d %H:%M:%S")
    past = [r for r in rows if str(r.get("valid_time", "")) <= now]
    if not past:
        return []
    latest = max(r["valid_time"] for r in past)
    out = {}
    for r in past:
        if r["valid_time"] == latest:
            out.setdefault(r["station_name"], []).append(r)
    return [v[0] for _, v in sorted(out.items())]


def _gz_highlow(root: Path, days: int = 3) -> dict[str, list[dict]]:
    rows: list[dict] = []
    for p in _month_files(root, "gz_highlow"):
        rows.extend(_rows(p))
    if not rows:
        return {}
    run_time = max(r["run_time"] for r in rows)
    today = now_cn().date().isoformat()
    out: dict[str, list[dict]] = {}
    for r in rows:
        if r["run_time"] != run_time or r["date"] < today:
            continue
        out.setdefault(r["station_name"], []).append(r)
    for k in out:
        out[k] = sorted(out[k], key=lambda x: x["date"])[:days]
    return out


def _t148_today(root: Path) -> dict:
    today = now_cn().date().isoformat()
    hl = []
    for p in _month_files(root, "t148/highlow"):
        for r in _rows(p):
            if r.get("date") == today:
                hl.append(r)
    hl.sort(key=lambda x: int(x.get("seq", 0)))
    st = {}
    st_path = root / "data" / "t148" / "station.csv"
    if st_path.exists():
        st = _rows(st_path)[0]
    return {"date": today, "highlow": hl, "station": st}


def _zjhy_latest(root: Path) -> dict:
    rows: list[dict] = []
    for p in _month_files(root, "zjhy"):
        rows.extend(_rows(p))
    if not rows:
        return {}
    latest = max(r["report_date"] for r in rows)
    picked = [r for r in rows if r["report_date"] == latest and r["station"] in ZJHY_WATCH]
    return {"report_date": latest, "rows": picked}


def _weather_today(root: Path) -> dict:
    rows: list[dict] = []
    for p in _month_files(root, "weather"):
        rows.extend(_rows(p))
    if not rows:
        return {}
    run_time = max(r["run_time"] for r in rows)
    now = now_cn().replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    window = [r for r in rows if r["run_time"] == run_time]
    future = [r for r in window if now <= r["valid_time"] <= (
        now_cn().replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")]
    if not future:
        return {}
    temps = [float(r["temp_c"]) for r in future if r.get("temp_c")]
    rains = [float(r["precip_mm"]) for r in future if r.get("precip_mm")]
    return {"run_time": run_time, "n": len(future),
            "temp_min": min(temps) if temps else None, "temp_max": max(temps) if temps else None,
            "precip_sum": sum(rains) if rains else 0.0}


def _status(root: Path) -> dict:
    return read_json(root / "data" / "meta" / "last_run.json", {}) or {}


def render(root: Path, cfg: dict, summary: dict) -> Path:
    g = cfg["general"]
    gz = _gz_latest(root)
    hl = _gz_highlow(root)
    t148 = _t148_today(root)
    zj = _zjhy_latest(root)
    wx = _weather_today(root)
    status = _status(root)
    run_at = status.get("run_at", "")

    def esc(x) -> str:
        return html.escape(str(x)) if x is not None else ""

    parts: list[str] = []
    parts.append(f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(g.get('page_title'))}</title>
<style>
body{{font-family:-apple-system,'Microsoft YaHei',sans-serif;margin:0;background:#f5f7fa;color:#222}}
header{{background:#0b5a8a;color:#fff;padding:16px 22px}}
header h1{{margin:0;font-size:20px}} header div{{opacity:.85;font-size:13px;margin-top:4px}}
main{{max-width:1100px;margin:16px auto;padding:0 14px}}
section{{background:#fff;border-radius:8px;box-shadow:0 1px 3px #0001;padding:14px 16px;margin-bottom:14px}}
h2{{font-size:16px;margin:0 0 10px;color:#0b5a8a;border-left:4px solid #0b5a8a;padding-left:8px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #eee;padding:5px 6px;text-align:left}}
th{{color:#666;font-weight:600;background:#fafafa}} .small{{font-size:12px;color:#777}}
.tag{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:12px;margin-right:4px}}
.ok{{background:#e3f6e8;color:#1a7f37}} .warn{{background:#fff4e0;color:#a15c00}} .err{{background:#fde8e8;color:#b42318}}
a{{color:#0b5a8a}}
</style></head><body>
<header><h1>{esc(g.get('page_title'))}</h1>
<div>{esc(g.get('page_subtitle'))} · 数据更新：{esc(run_at)} · <a style="color:#cfe8ff" href="{esc(g.get('repo_url'))}">仓库/数据下载</a></div></header>
<main>""")

    # 运行状态
    parts.append("<section><h2>本次运行状态</h2><table><tr><th>数据源</th><th>状态</th><th>结果 / 文件数</th></tr>")
    for name, res in summary.items():
        cls = "ok" if res.get("status") == "ok" else ("warn" if res.get("status") == "partial" else "err")
        rows = res.get("rows", "")
        msg = str(res.get("message", "") or "")
        if name in ("archive", "snapshot"):
            cell = f"{esc(rows)} 文件" + (f"<div class='small'>{esc(msg)}</div>" if msg else "")
        else:
            cell = esc(rows)
        parts.append(f"<tr><td>{esc(name)}</td><td><span class='tag {cls}'>{esc(res.get('status'))}</span></td>"
                     f"<td>{cell}</td></tr>")
    parts.append("</table><div class='small'>archive 的“文件数”表示本次归档/快照处理的文件数；当月暂无更早月份可归档时为 0，属正常。失败信息见仓库 data/meta/run_log.csv 与 Actions 日志。</div></section>")

    # GZ 最新
    parts.append("<section><h2>g.hyyb 数值预报格点（最新时刻，cm）</h2>")
    if gz:
        parts.append("<table><tr><th>站点</th><th>时刻</th><th>天文潮</th><th>增水</th><th>总水位</th><th>距警戒</th></tr>")
        for r in gz:
            parts.append(f"<tr><td>{esc(r['station_name'])}</td><td>{esc(r['valid_time'])}</td>"
                         f"<td>{esc(r['astro_cm'])}</td><td>{esc(r['surge_cm'])}</td><td><b>{esc(r['total_cm'])}</b></td>"
                         f"<td>{esc(r['dist_to_warning_cm'])}</td></tr>")
        parts.append("</table><div class='small'>总水位 = 天文潮 + 增水；同一时刻可能有多个预报版本，详见 data/gz_tide/。</div>")
    else:
        parts.append("<div class='small'>暂无</div>")
    parts.append("</section>")

    # 高低潮
    parts.append("<section><h2>未来高低潮（珠基，cm）</h2>")
    if hl:
        parts.append("<table><tr><th>站点</th><th>日期</th><th>高潮1</th><th>高潮2</th><th>低潮1</th><th>低潮2</th></tr>")
        for st, recs in hl.items():
            for r in recs:
                def pair(t, v):
                    return f"{esc(t)} / {esc(v)}" if t else "-"
                parts.append(f"<tr><td>{esc(st)}</td><td>{esc(r['date'])}</td>"
                             f"<td>{pair(r['high1_time'], r['high1_cm'])}</td><td>{pair(r['high2_time'], r['high2_cm'])}</td>"
                             f"<td>{pair(r['low1_time'], r['low1_cm'])}</td><td>{pair(r['low2_time'], r['low2_cm'])}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<div class='small'>暂无</div>")
    parts.append("</section>")

    # T148
    parts.append("<section><h2>T148「广州」天文潮（今天高低潮）</h2>")
    if t148.get("highlow"):
        st = t148.get("station", {})
        parts.append(f"<div class='small'>站名：{esc(st.get('title'))} · 坐标：{esc(st.get('coordinate'))} · 基准面：{esc(st.get('benchmark'))}</div>")
        parts.append("<table><tr><th>日期</th><th>序号</th><th>潮时</th><th>潮高(cm)</th></tr>")
        for r in t148["highlow"]:
            parts.append(f"<tr><td>{esc(r['date'])}</td><td>{esc(r['seq'])}</td><td>{esc(r['time'])}</td><td>{esc(r['height_cm'])}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<div class='small'>暂无</div>")
    parts.append("</section>")

    # 珠航局
    parts.append("<section><h2>珠江水情信息（实测，每日 8:00）</h2>")
    if zj.get("rows"):
        parts.append(f"<div class='small'>期次：{esc(zj['report_date'])}</div>")
        parts.append("<table><tr><th>站名</th><th>时间</th><th>水位(m)</th><th>流量(m³/s)</th></tr>")
        for r in zj["rows"]:
            parts.append(f"<tr><td>{esc(r['station'])}</td><td>{esc(r['time'])}</td><td>{esc(r['level_m'])}</td><td>{esc(r['flow_m3s'])}</td></tr>")
        parts.append("</table><div class='small'>上游：梧州/石角/高要；下游：大虎/天河/冯马庙。</div>")
    else:
        parts.append("<div class='small'>暂无</div>")
    parts.append("</section>")

    # 天气
    parts.append("<section><h2>鸦岗气象（未来 24h 摘要）</h2>")
    if wx:
        parts.append(f"<div>起报：{esc(wx['run_time'])} · 气温 {esc(wx['temp_min'])}~{esc(wx['temp_max'])} ℃ · "
                     f"累计降水 {esc(wx['precip_sum'])} mm</div>")
    else:
        parts.append("<div class='small'>暂无</div>")
    parts.append("</section>")

    parts.append(f"<div class='small'>数据目录：<a href='{esc(g.get('repo_url'))}/tree/main/data'>data/</a> · "
                 f"本页由 tidewatch 自动生成，仅作概览，分析请使用 data/ 中 CSV。</div></main></body></html>")
    out_html = root / cfg["general"].get("docs_dir", "docs") / "index.html"
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text("".join(parts), encoding="utf-8")
    (out_html.parent / ".nojekyll").write_text("", encoding="utf-8")
    write_json(out_html.parent / "latest.json", {
        "run_at": run_at, "status": {k: v.get("status") for k, v in summary.items()},
        "gz_latest": gz, "gz_highlow": hl, "t148_today": t148, "zjhy": zj, "weather": wx,
    })
    return out_html

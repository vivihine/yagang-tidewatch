# -*- coding: utf-8 -*-
"""旧数据归档：把“较早月份”的 CSV / 台风原始 JSON 打包进按年 zip，并删除工作区中的原始月文件。

目的：
  1. 控制 GitHub 仓库体积和文件数量（CSV 文本压缩率很高）；
  2. 每个年度 zip 内附带 `指标说明.md`、`LLM分析指南.md`、`schema.json`、`MANIFEST.json`，
     方便直接丢给大模型做数据理解与“与鸦岗水质关联分析”。

规则：
  - 只归档 `keep_raw_months` 之前的月份（默认保留当前月 + 上一个月在 data/ 中可读）；
  - 按年生成 `archive/tidewatch_YYYY.zip`，可增量追加（已归档内容保留在 zip 中）；
  - `data/meta/`、`data/health/` 不归档（体积小、需要随时查看）；
  - 归档成功后删除对应的原始月文件；`data/t148/station.csv` 等元数据文件保留。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

from .config import source_cfg
from .util import now_cn, write_json

TIME_CANDIDATES = ("valid_time", "date", "report_date", "time", "fetched_at")


def _shift_month(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _month_of_file(rel: Path) -> str | None:
    s = rel.as_posix()
    if rel.parent.as_posix().startswith("meta") or rel.parent.as_posix().startswith("health"):
        return None
    m = re.search(r"(\d{4})-(\d{2})\.csv$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.search(r"(\d{4})-(\d{2})-\d{2}\.json$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def _csv_meta(raw: bytes) -> dict:
    text = raw.decode("utf-8-sig", errors="ignore")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return {"rows": 0}
    time_col = next((c for c in TIME_CANDIDATES if c in header), None)
    idx = header.index(time_col) if time_col else None
    rows = 0
    tmin = tmax = ""
    for row in reader:
        if not row:
            continue
        rows += 1
        if idx is not None and idx < len(row):
            v = row[idx]
            if v:
                tmin = v if not tmin or v < tmin else tmin
                tmax = v if not tmax or v > tmax else tmax
    out = {"rows": rows}
    if time_col:
        out["time_field"] = time_col
        out["time_min"] = tmin
        out["time_max"] = tmax
    return out


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _load_zip_files(path: Path) -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    if not path.exists():
        return entries
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name in ("MANIFEST.json",) or name.endswith(("指标说明.md", "LLM分析指南.md", "schema.json")):
                continue
            entries[name] = z.read(name)
    return entries


def _read_manifest(zip_path: Path) -> dict:
    if not zip_path.exists():
        return {}
    try:
        with zipfile.ZipFile(zip_path) as z:
            if "MANIFEST.json" in z.namelist():
                return json.loads(z.read("MANIFEST.json").decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {}


def _doc_files(root: Path, cfg: dict) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for name in source_cfg(cfg, "archive").get("documents", []):
        p = root / name
        if p.exists():
            out[name] = p.read_bytes()
    return out


def snapshot(cfg: dict, root: Path, log, force: bool = False) -> dict:
    """把当前 data/ 下全部数据 + 说明文档打成一个 latest 快照 zip（不删除原始数据）。

    输出：archive/tidewatch_latest.zip，适合直接下载丢给大模型。
    """
    sc = source_cfg(cfg, "archive")
    if not sc.get("snapshot_enabled", True):
        return {"status": "ok", "rows": 0, "message": "snapshot disabled"}
    archive_dir = root / sc.get("dir", "archive")
    archive_dir.mkdir(parents=True, exist_ok=True)
    index_path = archive_dir / "archive_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    today = now_cn().strftime("%Y-%m-%d")
    if not force and (index.get("snapshot") or {}).get("date") == today:
        return {"status": "ok", "rows": 0, "message": "snapshot already refreshed today"}

    data_dir = root / "data"
    files: dict[str, bytes] = {}
    for p in sorted(data_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(data_dir)
        if rel.parts and rel.parts[0] == "health":
            continue
        files[f"data/{rel.as_posix()}"] = p.read_bytes()
    docs = _doc_files(root, cfg)
    doc_hashes = {k: _sha256(v) for k, v in docs.items()}

    manifest_files = []
    for name in sorted(files):
        raw = files[name]
        meta = {"path": name, "size": len(raw), "sha256": _sha256(raw)}
        if name.endswith(".csv"):
            meta.update(_csv_meta(raw))
        manifest_files.append(meta)
    datasets = sorted({n.split("/")[1] for n in files if n.startswith("data/") and not n.startswith("data/meta")})
    months = sorted({m.group(0) for n in files for m in [re.search(r"(\d{4}-\d{2})", n)] if m})
    manifest = {
        "archive": "tidewatch_latest.zip",
        "archive_version": "1.0",
        "archive_type": "snapshot",
        "created_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
        "repo": "https://github.com/vivihine/yagang-tidewatch",
        "purpose": "鸦岗断面潮位/水位/气象数据快照（含说明文档，供分析/大模型使用）",
        "timezone": "Asia/Shanghai",
        "documents": sorted(docs.keys()),
        "doc_hashes": doc_hashes,
        "datasets": datasets,
        "months": months,
        "file_count": len(files),
        "total_rows": sum(f.get("rows", 0) for f in manifest_files),
        "files": manifest_files,
    }
    zip_path = archive_dir / "tidewatch_latest.zip"
    tmp = zip_path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(files):
            z.writestr(name, files[name])
        for name, b in docs.items():
            z.writestr(name, b)
        z.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    tmp.replace(zip_path)
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"snapshot zip 校验失败：{bad}")

    index["snapshot"] = {
        "zip": zip_path.name,
        "date": today,
        "size_bytes": zip_path.stat().st_size,
        "sha256": _sha256(zip_path.read_bytes()),
        "file_count": len(files),
        "total_rows": manifest["total_rows"],
        "datasets": datasets,
        "months": months,
        "updated_at": manifest["created_at"],
    }
    write_json(index_path, dict(sorted(index.items())))
    log(f"  snapshot: {len(files)} files, {zip_path.stat().st_size/1024:.1f} KB -> {zip_path.name}")
    return {"status": "ok", "rows": len(files),
            "message": f"snapshot {zip_path.name} ({zip_path.stat().st_size/1024:.1f} KB)"}


def run(cfg: dict, root: Path, log, delete_raw: bool = True) -> dict:
    sc = source_cfg(cfg, "archive")
    if not sc.get("enabled", True):
        return {"status": "ok", "rows": 0, "message": "archive disabled"}
    keep = max(1, int(sc.get("keep_raw_months", 2)))
    archive_dir = root / sc.get("dir", "archive")
    archive_dir.mkdir(parents=True, exist_ok=True)
    current = now_cn().strftime("%Y-%m")
    cutoff = _shift_month(current, -(keep - 1))  # 归档 month < cutoff 的文件

    # 1) 找出待归档的月文件
    eligible: list[tuple[Path, str, str]] = []  # (path, rel_data_path, month)
    data_dir = root / "data"
    for p in sorted(data_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(data_dir)
        month = _month_of_file(rel)
        if month and month < cutoff:
            eligible.append((p, rel, month))
    docs = _doc_files(root, cfg)
    doc_hashes = {k: _sha256(v) for k, v in docs.items()}

    # 2) 按年处理
    by_year: dict[str, list[tuple[Path, Path, str]]] = {}
    for p, rel, month in eligible:
        by_year.setdefault(month[:4], []).append((p, rel, month))

    index_path = archive_dir / "archive_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    total_new = 0
    deleted = 0
    year_keys = [str(k) for k in index.keys() if re.fullmatch(r"\d{4}", str(k))]
    for year in sorted(set(by_year.keys()) | set(year_keys)):
        if not re.fullmatch(r"\d{4}", year):
            continue
        zip_path = archive_dir / f"tidewatch_{year}.zip"
        existing = _load_zip_files(zip_path)
        old_manifest = _read_manifest(zip_path)
        new_items = by_year.get(year, [])
        docs_changed = old_manifest.get("doc_hashes") != doc_hashes

        if not new_items and existing and not docs_changed:
            continue

        files: dict[str, bytes] = dict(existing)
        added_rel: list[Path] = []
        for p, rel, month in new_items:
            name = f"data/{rel.as_posix()}"
            files[name] = p.read_bytes()
            added_rel.append(p)

        if not files and not docs:
            continue

        # 3) MANIFEST
        manifest_files = []
        for name in sorted(files):
            raw = files[name]
            meta = {"path": name, "size": len(raw), "sha256": _sha256(raw)}
            if name.endswith(".csv"):
                meta.update(_csv_meta(raw))
            manifest_files.append(meta)
        datasets = sorted({n.split("/")[1] for n in files if n.startswith("data/") and not n.startswith("data/meta")})
        months = sorted({m for _, _, m in new_items}) if new_items else old_manifest.get("months", [])
        manifest = {
            "archive": f"tidewatch_{year}.zip",
            "archive_version": "1.0",
            "created_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
            "repo": "https://github.com/vivihine/yagang-tidewatch",
            "purpose": "鸦岗断面潮位/水位/气象数据年度归档（供分析使用）",
            "timezone": "Asia/Shanghai",
            "documents": sorted(docs.keys()),
            "doc_hashes": doc_hashes,
            "datasets": datasets,
            "months": months,
            "file_count": len(files),
            "total_rows": sum(f.get("rows", 0) for f in manifest_files),
            "delete_raw_after_archive": bool(delete_raw),
            "files": manifest_files,
        }

        # 4) 写 zip（先写临时文件再替换，避免损坏）
        tmp = zip_path.with_suffix(".zip.tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for name in sorted(files):
                z.writestr(name, files[name])
            for name, b in docs.items():
                z.writestr(name, b)
            z.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        tmp.replace(zip_path)

        # 5) 校验后删除原始月文件
        with zipfile.ZipFile(zip_path) as z:
            bad = z.testzip()
            if bad:
                raise RuntimeError(f"zip 校验失败：{bad}")
        if delete_raw:
            for p in added_rel:
                try:
                    p.unlink()
                    deleted += 1
                except FileNotFoundError:
                    pass
        total_new += len(new_items)
        index[year] = {
            "zip": zip_path.name,
            "size_bytes": zip_path.stat().st_size,
            "sha256": _sha256(zip_path.read_bytes()),
            "file_count": len(files),
            "total_rows": manifest["total_rows"],
            "datasets": datasets,
            "months": months,
            "updated_at": manifest["created_at"],
        }
        log(f"  archive {year}: +{len(new_items)} files, zip {zip_path.stat().st_size/1024:.1f} KB"
            f"{'，删除原始文件 ' + str(len(added_rel)) + ' 个' if delete_raw else ''}")

    if index:
        write_json(index_path, dict(sorted(index.items())))
    if not total_new and not docs:
        return {"status": "ok", "rows": 0, "message": "no eligible months"}
    return {"status": "ok", "rows": total_new,
            "message": f"archived {total_new} files, deleted {deleted} raw files"}

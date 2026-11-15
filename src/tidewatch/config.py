# -*- coding: utf-8 -*-
"""配置加载（TOML，Python 3.11+ 标准库 tomllib）。"""
from __future__ import annotations

import tomllib
from pathlib import Path


def load_config(root: Path) -> dict:
    path = root / "config.toml"
    with path.open("rb") as f:
        cfg = tomllib.load(f)
    cfg.setdefault("general", {})
    cfg.setdefault("sources", {})
    return cfg


def source_cfg(cfg: dict, name: str) -> dict:
    """取数据源配置：优先 [sources.<name>]，也兼容顶层 [<name>]（如 [archive]）。"""
    sc = cfg.get("sources", {}).get(name)
    if sc is None:
        sc = cfg.get(name)
    return sc if isinstance(sc, dict) else {}

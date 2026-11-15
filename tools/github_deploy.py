#!/usr/bin/env python3
"""用 GitHub REST API 建仓并上传本项目（本机无需安装 git）。

前置步骤（一次性，约 2 分钟）：
  1. GitHub → 右上角头像 → Settings → Developer settings
     → Personal access tokens → Tokens (classic)
     → Generate new token (classic)，勾选 scope: repo + workflow，有效期建议 7 天
  2. 把 token 写入：yagang-tidewatch/.env.local
          GITHUB_TOKEN=ghp_xxxxxxxx
     （.env.local 已被 .gitignore 忽略，不会提交到仓库）
  3. 在 yagang-tidewatch 目录运行：
          python tools/github_deploy.py            # 建仓/增量同步
          python tools/github_deploy.py --trigger  # 同步后立即触发一次 Actions

脚本会：创建**独立仓库** yagang-tidewatch → 上传代码/配置 → 设置 Actions 写权限
      → 开启 GitHub Pages（main /docs）→ 打印仓库地址、看板地址。

重要：
  - 本脚本只操作 yagang-tidewatch 这一个仓库，不会碰 yagang-rainwatch。
  - 重复运行 = 增量同步：代码/配置会更新；data/ 与 docs/ 下已存在的远端文件不会覆盖，
    以保留线上自动采集的数据（首次部署时远端为空，会连同示例数据一起上传）。
  - 免费版 GitHub Pages 只支持公开仓库；如需私有仓库用 --private（看板不可用）。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"
EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}
EXCLUDE_FILES = {".env.local", "管理员手册.md"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log"}
DEFAULT_REPO = "yagang-tidewatch"          # 与 yagang-rainwatch 完全独立
DESCRIPTION = ("鸦岗断面潮位/水位/气象数据采集：g.hyyb 数值预报 + 国家海洋信息中心潮汐表 T148 + "
               "珠江水情实测 + Open-Meteo/GloFAS/台风；GitHub Actions 定时 + GitHub Pages 看板")
PRESERVE_PREFIXES = ("data/", "docs/", "archive/")


def load_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    env_file = ROOT / ".env.local"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GITHUB_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


class GitHub:
    def __init__(self, token: str):
        self.token = token

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            API + path, data=data, method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "yagang-tidewatch-deploy",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                return resp.status, (json.loads(body) if body.strip() else {})
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"message": body[:300]}
            return exc.code, parsed
        except urllib.error.URLError as exc:
            return 0, {"message": f"网络错误：{exc}"}


def collect_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if rel.name in EXCLUDE_FILES or path.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        files.append(rel)
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--trigger", action="store_true", help="部署完成后触发一次 Actions")
    ap.add_argument("--skip-pages", action="store_true")
    args = ap.parse_args()

    token = load_token()
    if not token:
        print("! 未找到 GITHUB_TOKEN。请把 token 写入 .env.local（参考 .env.example）。", file=sys.stderr)
        return 2
    gh = GitHub(token)

    status, user = gh.request("GET", "/user")
    if status != 200:
        print(f"! token 无效（HTTP {status}）：{user.get('message')}", file=sys.stderr)
        return 2
    owner = user["login"]
    print(f"账号：{owner}；目标仓库：{owner}/{args.repo}")

    # 1) 建仓（已存在则忽略）
    status, data = gh.request("POST", "/user/repos", {
        "name": args.repo, "description": DESCRIPTION,
        "private": bool(args.private), "has_issues": True,
        "has_projects": False, "has_wiki": False,
    })
    if status in (201, 200):
        print(f"✓ 已创建仓库 {data.get('html_url')}")
    elif status == 422:
        print("· 仓库已存在，执行增量同步")
    else:
        print(f"! 建仓失败（HTTP {status}）：{data.get('message')}", file=sys.stderr)
        return 1

    # 2) 设置 Actions 默认写权限（失败不阻断）
    status, data = gh.request("PUT", f"/repos/{owner}/{args.repo}/actions/permissions/workflow",
                              {"default_workflow_permissions": "write"})
    if status in (200, 204):
        print("✓ Actions 默认写权限 = write")
    else:
        print(f"! 设置 Actions 权限失败（HTTP {status}，可稍后在 Settings 手工设置）：{data.get('message')}")

    # 3) 上传文件
    files = collect_files()
    ok = skipped = failed = 0
    for i, rel in enumerate(files, 1):
        rel_str = rel.as_posix()
        content_path = f"/repos/{owner}/{args.repo}/contents/{urllib.parse.quote(rel_str)}"
        status, meta = gh.request("GET", content_path + "?ref=main")
        sha = meta.get("sha") if status == 200 else None
        if sha and rel_str.startswith(PRESERVE_PREFIXES):
            skipped += 1
            continue
        body = {
            "message": f"deploy: {rel_str}",
            "content": base64.b64encode(rel.read_bytes()).decode("ascii"),
            "branch": "main",
        }
        if sha:
            body["sha"] = sha
        status, data = gh.request("PUT", content_path, body)
        if status in (200, 201):
            ok += 1
            print(f"  [{i}/{len(files)}] ↑ {rel_str}")
        else:
            failed += 1
            print(f"  [{i}/{len(files)}] ! {rel_str}: HTTP {status} {data.get('message')}")
    print(f"文件：成功 {ok}，跳过（data/docs 保留远端）{skipped}，失败 {failed}")

    # 4) GitHub Pages（main /docs）
    if not args.skip_pages and not args.private:
        status, data = gh.request("POST", f"/repos/{owner}/{args.repo}/pages",
                                  {"source": {"branch": "main", "path": "/docs"}})
        if status in (201, 200):
            print(f"✓ GitHub Pages 已启用：https://{owner}.github.io/{args.repo}/")
        elif status == 409:
            print("· GitHub Pages 已存在")
        else:
            print(f"! 启用 Pages 失败（HTTP {status}，可稍后在 Settings→Pages 手工选择 main /docs）：{data.get('message')}")

    print("\n完成：")
    print(f"  仓库：https://github.com/{owner}/{args.repo}")
    print(f"  看板：https://{owner}.github.io/{args.repo}/")
    print("  下一步：Actions → tidewatch → Run workflow（或加 --trigger 自动触发）")

    if args.trigger:
        status, data = gh.request("POST", f"/repos/{owner}/{args.repo}/actions/workflows/tidewatch.yml/dispatches",
                                  {"ref": "main", "inputs": {"task": "daily", "force": False}})
        if status in (201, 204):
            print("✓ 已触发 Actions，约 1 分钟后到 Actions 页面查看结果")
        else:
            print(f"! 触发 Actions 失败（HTTP {status}）：{data.get('message')}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

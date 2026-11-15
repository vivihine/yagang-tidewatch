# 本地调试入口（Windows PowerShell）
# 用法：
#   .\run.ps1                       # 正常抓取一次（写 data/、docs/）
#   .\run.ps1 --force               # 忽略“今天已成功”检查
#   .\run.ps1 --task backfill_t148 --start 2025-01-01 --end 2025-12-31
#
# 本地需要 Python 3.11+（推荐 3.12）。本脚本不需要任何密钥；GITHUB_TOKEN 只在部署时用。

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$env:PYTHONPATH = Join-Path $root "src"
python -m tidewatch @args

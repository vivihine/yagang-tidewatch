# yagang-tidewatch（鸦岗断面潮位/水位数据采集）

每天定时抓取与**鸦岗断面水质–潮位分析**相关的公开数据，自动提交到本仓库 `data/`，并在 GitHub Pages 生成最新概览看板。

> **本仓库与 `yagang-rainwatch`（降雨预报）完全独立**：独立仓库、独立 workflow（`tidewatch`）、独立数据目录（`data/gz_tide`、`data/t148`…）、独立提交机器人（`tidewatch-bot`）。不修改、不读取、不依赖降雨仓库的任何文件或定时任务。

## 数据源与内容

| 数据集 | 来源 | 内容 | 更新 |
|---|---|---|---|
| `data/gz_tide/` | g.hyyb.org（广东省海洋预报台/南海预报中心，**数值预报格点**） | 广州38/广州39/广州41/南石头/中大码头：天文潮 / 总水位 / 增水（cm） | 每天；每次 72h 逐时 |
| `data/gz_highlow/` | 同上（风暴潮系统） | 广州/黄埔/南沙，未来约 16 天高低潮（珠基，cm） | 每天 |
| `data/t148/hourly`、`data/t148/highlow` | 国家海洋信息中心 publictide（**潮汐表 T148「广州」**） | 天文潮逐时 + 高低潮；站名/坐标/基准面 | 每天；可 `backfill_t148` 回溯 |
| `data/zjhy/` | 交通运输部珠江航务管理局「珠江水情信息」 | 每日 8:00 **实测**水位/流量（梧州、石角、高要、大虎、天河、冯马庙等 15 站） | 每工作日；可 `backfill_zjhy` 回溯 |
| `data/weather/` | Open-Meteo | 鸦岗坐标逐时气温/气压/风/湿度/辐射/降水 | 每天 |
| `data/glofas/` | Open-Meteo GloFAS | 河流流量日值（梧州西江 + 本地网格参考） | 每天 |
| `data/typhoon/` | 中央气象台台风网 | 台风列表 + 原始 JSON 快照 | 每天 |

数据字典与口径见 **[指标说明.md](指标说明.md)**；给同事/领导的说明见 **[用户手册.md](用户手册.md)**。

## 归档与压缩（节省仓库空间）

数据会不断累积。项目会自动把**较早月份**压缩成按年 zip，并删除 `data/` 中的原始月文件：

- `archive/tidewatch_YYYY.zip`：年度归档（自动，每月 1 日或当月首次运行时触发）；包含该年数据 + `指标说明.md` + `LLM分析指南.md` + `schema.json` + `MANIFEST.json`；
- `archive/tidewatch_latest.zip`：**全部当前数据的最新快照**（每月 1 日自动刷新；也可手动 `--task snapshot` 立即生成），适合直接下载/丢给大模型；
- `archive/archive_index.json`：归档索引（年份/月份/文件数/行数/大小/SHA256）；
- `config.toml` 的 `[archive]` 可调 `keep_raw_months`（默认 2：当前月+上月保留原始 CSV，更早的进 zip）；
- 归档成功后，原始月文件从工作区删除（历史仍在 zip 中）；Git 历史里仍保留旧版本，这是正常现象。

> 给大模型的推荐文件：`archive/tidewatch_latest.zip`（内含 `LLM分析指南.md`，已写明如何与鸦岗 DO 数据关联分析）。

## 定时与“跳过”规则

- 主触发：**cron-job.org 每天 14:45（Asia/Shanghai）**；备份：每天 18:45；GitHub 自带 `schedule` 仅作第三重备份（可能延迟数小时，不可依赖）。
- 只有“**当天 14:30 之后**成功抓取过”才会跳过后续运行（`config.toml` 的 `daily_ready_after`）。
  这样可避免 GitHub 自带定时延迟到**凌晨**的运行把“今天”误标为已完成，导致 14:45 主任务被跳过。
- 看板顶部的“数据更新”时间 = 最近一次**真正抓取成功**的时间；被跳过的运行只写 `run_log`，不会更新它，所以偶尔会看到“00:27”这类时间（来自 GitHub 延迟运行）。

## 目录结构

```
yagang-tidewatch/
├─ config.toml                 # 站点、坐标、数据源开关（改配置不用改代码）
├─ README.md / 用户手册.md / 指标说明.md / LLM分析指南.md / schema.json
├─ run.ps1                     # 本地运行入口（Windows PowerShell）
├─ requirements.txt            # 无第三方依赖
├─ .env.example                # 部署用 token 模板（.env.local 不入库）
├─ src/tidewatch/
│  ├─ __main__.py              # daily / backfill / record-failure
│  ├─ config.py  util.py  store.py  health.py
│  ├─ render.py                # 生成 docs 看板
│  └─ sources/                 # gz_tide, gz_highlow, t148, zjhy, weather, glofas, typhoon
├─ tools/github_deploy.py      # 用 GitHub API 建仓/上传（本机无需 git）
├─ tests/                      # 离线单元测试
├─ data/                       # 采集数据（按月 CSV，UTF-8 BOM；较早月份归档后删除）
├─ archive/                    # 年度 zip + latest 快照 + archive_index.json
└─ docs/                       # GitHub Pages 看板（自动生成）
```

## 本地运行

需要 Python 3.11+（推荐 3.12）：

```powershell
cd yagang-tidewatch
.\run.ps1                       # 正常抓取一次（写 data/、docs/，并按需归档）
.\run.ps1 --force               # 忽略“今天已成功”检查
.\run.ps1 --task backfill_t148 --start 2025-01-01 --end 2025-12-31
.\run.ps1 --task backfill_zjhy --start 2025-06-01 --end 2026-11-15
.\run.ps1 --task archive        # 手动归档旧月份（默认删除原始月文件）
.\run.ps1 --task archive --no-delete-raw   # 只打包不删除（测试用）
.\run.ps1 --task snapshot       # 立即生成 archive/tidewatch_latest.zip
```

离线测试：

```powershell
$env:PYTHONPATH="src"; python -m unittest discover -s tests -v
```

## 部署到 GitHub（独立仓库）

1. 在 GitHub 生成 classic PAT（勾选 `repo` + `workflow`，建议 7 天有效），写入本目录 `.env.local`：
   ```
   GITHUB_TOKEN=ghp_xxxxxxxx
   ```
2. 运行（自动建仓 `yagang-tidewatch`、上传、开启 Actions 写权限、启用 Pages）：
   ```powershell
   python tools/github_deploy.py --trigger
   ```
3. 之后：每天北京时间 **14:45**（主）与 18:45（备份）自动运行；数据自动 commit 到 `data/`，看板自动更新到 `docs/`。
4. 下载数据：仓库 Code → Download ZIP，或 `git clone`，或直接打开 `data/` 下 CSV。

> 也可以不用部署脚本：`git init && git add . && git commit` 后 push 到新建仓库，再在
> Settings → Actions → General → Workflow permissions 选 **Read and write**。

## 手动补历史（Actions 页 Run workflow）

| task | 用途 | 参数 |
|---|---|---|
| `backfill_t148` | 批量补 T148 天文潮（实测可回溯约 2025-01～2027-12） | start/end |
| `backfill_zjhy` | 批量补珠航局每日水情历史 | start/end |
| `archive` | 立即归档旧月份（默认删除原始月文件） | — |
| `snapshot` | 立即生成 `archive/tidewatch_latest.zip`（含说明文档） | — |

建议一次补 ≤1 年（单个 job 上限 45 分钟），分多次跑。

## 注意

1. GitHub 托管 runner 在境外，访问国内站点可能慢/偶发失败；代码已做 3 次重试 + curl 回退 + 一次整体重试。若长期不稳定，改用国内 self-hosted runner（`runs-on: [self-hosted]`）或国内云服务器 cron。
2. 预报 ≠ 实测：`gz_tide`/`gz_highlow`/`t148` 是预报；`zjhy` 是实测（每日 8:00）。
3. 同一时刻可能有多个预报版本，见 `run_time`/`lead_h`；做分析取**预报时效最短**的版本。
4. 基准面不同（T148=平均海面下 134cm；GZ 模式基准另见页面参数）；跨源先做平移/相位标定。
5. 数据版权归原机构，仅供科研；低频抓取，请勿商用。

## 许可

代码 MIT；数据版权归各原始发布机构。

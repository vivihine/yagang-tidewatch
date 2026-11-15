# 给大模型的数据使用指南（LLM Usage Guide）

> 本文件随 `archive/tidewatch_YYYY.zip` 与 `archive/tidewatch_latest.zip` 一起分发。
> 使用方式：把**本文件 + `指标说明.md` + `schema.json` + `MANIFEST.json`** 作为上下文提供给大模型，
> 再附上你的**鸦岗断面水质（DO）数据**（CSV/Excel），模型即可按本文档完成"数据识别 → 清洗对齐 → 潮位特征 → 与 DO 关联分析"。

---

## 0. 这份数据是什么

- 项目：`yagang-tidewatch`，为**鸦岗断面水质（溶解氧 DO）—潮位关联分析**每日自动采集的公开数据归档。
- 时区：**全部为北京时间（Asia/Shanghai）**；逐时数据为整点。
- 目录（zip 内）：

```
tidewatch_YYYY.zip
├─ MANIFEST.json        # 本压缩包的文件清单：路径/大小/SHA256/行数/时间范围/文档哈希
├─ 指标说明.md          # 每个数据集字段、单位、基准面、预报/实测性质
├─ LLM分析指南.md       # 本文件
├─ schema.json          # 机器可读 schema（字段/类型/单位/主键/连接方式）
└─ data/
   ├─ gz_tide/YYYY-MM.csv        # 数值预报格点：天文潮/增水/总水位（逐时）
   ├─ gz_highlow/YYYY-MM.csv     # 广州/黄埔/南沙 高低潮预报（珠基）
   ├─ t148/hourly/YYYY-MM.csv    # T148「广州」天文潮（逐时）
   ├─ t148/highlow/YYYY-MM.csv   # T148 高低潮
   ├─ t148/station.csv           # T148 站名/坐标/基准面
   ├─ zjhy/YYYY-MM.csv           # 珠江水情：每日 8:00 实测水位/流量（15 站）
   ├─ weather/YYYY-MM.csv        # 鸦岗坐标逐时气象
   ├─ glofas/YYYY-MM.csv         # GloFAS 河流流量（日值）
   └─ typhoon/YYYY-MM.csv、raw/  # 台风列表 + 原始 JSON
```

- 数据性质速记：**`zjhy` 是实测**；`gz_tide`、`gz_highlow`、`t148` 是**预报**（`t148` 为纯天文潮）；`weather`/`glofas` 含回顾+预报；`typhoon` 是信息。

---

## 1. 第一步：识别与读取数据（给模型的指令）

1. 先读 `MANIFEST.json` 确认文件列表与时间范围；
2. 按 `schema.json` 识别每个数据集的字段、单位、主键、时间字段；
3. 用 pandas 读取 CSV（**UTF-8 BOM**，直接 `pd.read_csv` 即可，`encoding="utf-8-sig"` 更稳）。

```python
import pandas as pd, json, zipfile, io
from pathlib import Path

z = zipfile.ZipFile("tidewatch_latest.zip")
manifest = json.loads(z.read("MANIFEST.json"))
schema   = json.loads(z.read("schema.json"))

def read_csv_in_zip(name):
    return pd.read_csv(io.BytesIO(z.read(name)), encoding="utf-8-sig")

gz    = read_csv_in_zip("data/gz_tide/2026-11.csv")
t148  = read_csv_in_zip("data/t148/hourly/2026-11.csv")
zjhy  = read_csv_in_zip("data/zjhy/2026-11.csv")
wx    = read_csv_in_zip("data/weather/2026-11.csv")

gz["valid_time"] = pd.to_datetime(gz["valid_time"])
t148["datetime"] = pd.to_datetime(t148["date"] + " " + t148["hour"] + ":00:00")
```

> 注意：`gz_tide`/`weather` 同一时刻有多个 `run_time`（预报版本），**必须先按 `lead_h` 最小去重**，否则同一小时会重复。

```python
# 选每个 (station_code, valid_time) 的 lead_h 最小版本
gz_best = (gz.sort_values("lead_h")
             .drop_duplicates(["station_code", "valid_time"], keep="first"))
```

---

## 2. 各数据集怎么用（一句话版）

| 数据集 | 建议角色 | 注意 |
|---|---|---|
| `gz_tide` | **实际水位主变量**（总水位）、增水、天文潮 | 预报；格点不是实体站；多个版本需去重 |
| `gz_highlow` | 高低潮时点/潮差 | 预报；珠基 |
| `t148/hourly` | **纯天文潮**相位、大小潮 | 基准面=平均海面下134cm；与鸦岗相位差 1–2h |
| `zjhy` | **上游径流**（石角/高要/梧州）、**下游潮位边界**（大虎/天河/冯马庙） | 实测但每日仅 8:00 |
| `weather` | DO 复氧/分层控制变量（气温、气压、风、辐射、降水） | 回顾段近似实测，未来段为预报 |
| `glofas` | 径流背景（仅梧州量级可靠） | 鸦岗本地网格不可用 |
| `typhoon` | 识别台风增水/低氧事件窗口 | — |

---

## 3. 与鸦岗 DO 数据关联（核心步骤）

### 3.1 假设你的 DO 数据长这样

| 列 | 说明 |
|---|---|
| `datetime` | 北京时间（逐小时最佳；日数据也可，最后按日聚合） |
| `DO` | 溶解氧 mg/L（或 `do_mgL`） |
| 可选 | `water_temp`、`pH`、`turbidity`、`station` |

### 3.2 小时级连接（推荐）

```python
# 1) DO 标准化
do = pd.read_excel("鸦岗DO.xlsx")
do["datetime"] = pd.to_datetime(do["datetime"])
do = do.sort_values("datetime")

# 2) 潮位宽表：每个时刻一列总水位（用最近的广州38 或南石头；也可两点做平均）
tide = (gz_best[gz_best["station_code"] == "GZ079"]      # 广州38，距鸦岗最近
        [["valid_time", "total_cm", "astro_cm", "surge_cm"]]
        .rename(columns={"valid_time": "datetime"})
        .sort_values("datetime"))

# 3) 按时间最近连接（容差 30 分钟）
merged = pd.merge_asof(do, tide, on="datetime",
                       tolerance=pd.Timedelta("30min"), direction="nearest")

# 4) 日尺度实测（珠航局 8:00）按“日期”聚合后再连接
zjhy["date"] = pd.to_datetime(zjhy["report_date"])
daily_up = (zjhy[zjhy["station"].isin(["石角", "高要", "梧州（四）"])]
            .pivot_table(index="date", columns="station", values="flow_m3s", aggfunc="mean"))
merged["date"] = merged["datetime"].dt.floor("D")
merged = merged.merge(daily_up, left_on="date", right_index=True, how="left")
```

### 3.3 潮位特征工程（建议至少做这些）

```python
d = merged.set_index("datetime").sort_index()

# 1h 变化率（cm/h）
d["tide_rate"] = d["total_cm"].diff()

# 涨/落潮标识
d["rising"] = (d["tide_rate"] > 0).astype(int)

# 日潮差、日最高/最低（按自然日）
daily = d.resample("D").agg(
    do_min=("DO", "min"), do_mean=("DO", "mean"),
    wl_max=("total_cm", "max"), wl_min=("total_cm", "min"),
    surge_mean=("surge_cm", "mean"), rain=("precip_mm", "sum") if "precip_mm" in d else ("DO", "size"),
)
daily["tide_range"] = daily["wl_max"] - daily["wl_min"]

# 潮汐相位（0~2π）：用天文潮做希尔伯特变换或简单按日/半日周期拟合
import numpy as np
d["tide_phase"] = np.angle(
    d["astro_cm"].rolling(25).apply(lambda x: np.sum(x * np.exp(-2j*np.pi*np.arange(len(x))/24.8)), raw=True)
)
```

> 如果只有 DO 日数据：先把潮位按日聚合（日潮差、日最高/最低、日增水均值），再与 DO 日均/日最小做相关。

---

## 4. 关联分析的推荐做法

### 4.1 滞后相关（先看潮位/增水/径流超前或滞后 DO 多久）

```python
def lag_corr(x, y, max_lag=12):
    out = {}
    for k in range(-max_lag, max_lag + 1):
        out[k] = x.shift(k).corr(y)
    return pd.Series(out).sort_values(key=abs, ascending=False)

# DO 与总水位、增水、天文潮、上游流量、气温分别做滞后相关
for col in ["total_cm", "surge_cm", "astro_cm", "石角", "高要", "temp_c"]:
    if col in d:
        print(col, lag_corr(d[col], d["DO"]).head(3))
```

### 4.2 回归/GAM（控制混杂因素）

```python
import statsmodels.formula.api as smf
model = smf.ols("DO ~ total_cm + surge_cm + tide_rate + temp_c + precip_mm + 石角",
                data=d.dropna(subset=["DO"])).fit(cov_type="HAC", cov_kwds={"maxlags": 24})
print(model.summary())
```

### 4.3 分场景分析（建议都做一遍）

1. **季节**：汛期（4–9 月）vs 枯季（10–3 月）；
2. **潮型**：大潮 vs 小潮（日潮差高低分位）；
3. **天气**：台风/强降雨事件 vs 平常日（用 `typhoon` 与 `weather.precip_mm` 识别）；
4. **径流**：上游流量高/低分位；
5. **潮位阶段**：涨潮 vs 落潮、高潮 vs 低潮前后（用 `rising` 与相位分组）。

### 4.4 事件窗口分析

```python
# 找出 DO 低值事件（例如 DO < 3 mg/L）与潮位/增水/降雨的对应关系
events = d[d["DO"] < 3].copy()
# 事件前后 24h 的潮位过程合成（composite）
```

---

## 5. 必须注意的坑

1. **预报 ≠ 实测**：`gz_tide`/`gz_highlow`/`t148` 是预报；`zjhy` 才是实测（每日 8:00）。
2. **多个预报版本**：`run_time` 不同、`lead_h` 不同；分析前按 `lead_h` 最小去重。
3. **基准面不同**：T148=平均海面下 134 cm；GZ 为模式基准；**跨源先做平移/相位标定**，不要直接比绝对值。
4. **GZ 格点不是实体站**：广州38/39 距鸦岗约 14 km 下游；可作趋势/相位参考，不能当“鸦岗站实测”。
5. **GloFAS 本地网格值偏小**（0.2–4 m³/s），不能代表珠江主干；上游径流用 `zjhy` 的石角/高要/梧州。
6. **数据覆盖**：`t148` 可回溯 2025–2027；`gz_tide` 无历史（部署日起）；`zjhy` 周末/节假日可能缺。
7. **缺失值**：不要默认插值；在报告中标注缺失时段与数据来源性质。
8. **频率**：`zjhy` 只有每日 8:00；与小时 DO 连接时按日期聚合，或作为日尺度协变量。

---

## 6. 建议的分析报告输出（给模型）

请模型输出：

1. **数据清单与覆盖**：各数据集时间范围、行数、缺失/异常；
2. **对齐与去重说明**：选了哪些站点/版本（lead_h 最小）、基准面处理；
3. **描述性结果**：DO、总水位、增水、潮差、上下游流量的均值/范围/季节差异；
4. **相关/回归结果**：滞后阶数、系数、显著性、解释力；
5. **分场景结果**：汛期/枯季、大潮/小潮、台风/平常、涨潮/落潮；
6. **图**：DO 与总水位时间序列、DO–潮位滞后相关图、事件前后合成图；
7. **局限与建议**：数据缺口、预报误差、基准面/相位不确定性、后续需补的数据。

---

## 7. 数据来源与引用

- g.hyyb 数值预报格点 / 风暴潮系统：广东省海洋预报台、国家海洋局南海预报中心
- T148 潮汐表：国家海洋信息中心（publictide）
- 珠江水情信息：交通运输部珠江航务管理局
- 天气/GloFAS：Open-Meteo（ECMWF/GFS/GloFAS 等）
- 台风：中央气象台台风网

> 以上均为公开数据；引用/发表请注明来源，不得商用。

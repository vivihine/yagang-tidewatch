# -*- coding: utf-8 -*-
"""基础单元测试（不联网）：解析、去重、配置。"""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tidewatch.archive import _month_of_file, _shift_month  # noqa: E402
from tidewatch.config import load_config, source_cfg  # noqa: E402
from tidewatch.sources.gz_tide import parse_rows as parse_gz  # noqa: E402
from tidewatch.sources.typhoon import parse_typhoon_listp  # noqa: E402
from tidewatch.sources.zjhy import parse_article  # noqa: E402
from tidewatch.store import append_monthly  # noqa: E402
from tidewatch.util import strip_tags, table_rows  # noqa: E402


class TestUtil(unittest.TestCase):
    def test_strip_table(self):
        html = "<table><tr><td>2026111514</td><td>-114</td></tr></table>"
        rows = table_rows(html)
        self.assertEqual(rows, [["2026111514", "-114"]])
        self.assertEqual(strip_tags("<b>a</b>&nbsp;b"), "a b")


class TestConfig(unittest.TestCase):
    def test_load(self):
        cfg = load_config(ROOT)
        self.assertEqual(cfg["general"]["timezone"], "Asia/Shanghai")
        self.assertGreaterEqual(len(source_cfg(cfg, "gz_tide")["stations"]), 3)
        self.assertEqual(source_cfg(cfg, "t148")["port_code"], "T148")


class TestStore(unittest.TestCase):
    def test_append_dedupe(self):
        tmp = ROOT / "tests" / "_tmp_store"
        if tmp.exists():
            import shutil
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        try:
            headers = ["a", "b", "month"]
            rows = [{"a": "1", "b": "x", "month": "2026-11"},
                    {"a": "2", "b": "y", "month": "2026-11"}]
            n1 = append_monthly(tmp, "demo", rows, headers, ["a", "b"])
            n2 = append_monthly(tmp, "demo", rows + [{"a": "3", "b": "z", "month": "2026-11"}],
                                headers, ["a", "b"])
            self.assertEqual(n1, 2)
            self.assertEqual(n2, 1)
            with (tmp / "data" / "demo" / "2026-11.csv").open(encoding="utf-8-sig") as f:
                got = list(csv.DictReader(f))
            self.assertEqual([r["a"] for r in got], ["1", "2", "3"])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestParsers(unittest.TestCase):
    def test_gz_tide_rows(self):
        html = """
        <table>
          <tr><td>时间</td><td>天文潮(cm)</td><td>总水位(cm)</td><td>增水(cm)</td></tr>
          <tr><td>2026111514</td><td>-114</td><td>-113</td><td>1</td><td>-293</td><td>无</td></tr>
          <tr><td>2026111515</td><td>-98</td><td>-93</td><td>5</td><td>-273</td><td>无</td></tr>
        </table>"""
        st = {"code": "GZ079", "name": "广州38", "sserial": 78, "zj": 10, "warning": 180}
        rows = parse_gz(st, html, "2026-11-15 21:00", "2026-11-15 21:00:00")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["valid_time"], "2026-11-15 14:00:00")
        self.assertEqual(rows[0]["lead_h"], 0)
        self.assertEqual(rows[0]["total_cm"], -113)
        self.assertEqual(rows[1]["lead_h"], 1)

    def test_zjhy_article(self):
        html = """
        <table>
          <tr><td>站名</td><td>时间</td><td>水位(m)</td><td>流量(m³/s)</td></tr>
          <tr><td>梧州（四）</td><td>11-12 08:00</td><td>2.92</td><td>2250</td></tr>
          <tr><td>大虎（二）</td><td>11-12 08:00</td><td>-0.57</td><td>-</td></tr>
        </table>"""
        rows = parse_article(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "梧州（四）")

    def test_typhoon_jsonp(self):
        text = 'typhoon_jsons_list_default(({"typhoonList":[[1,"A","甲","2601","2601",null,"x","stop"]]}))'
        data = parse_typhoon_listp(text)
        self.assertEqual(data["typhoonList"][0][2], "甲")


class TestArchive(unittest.TestCase):
    def test_shift_month(self):
        self.assertEqual(_shift_month("2026-01", -1), "2025-12")
        self.assertEqual(_shift_month("2026-11", -1), "2026-10")
        self.assertEqual(_shift_month("2026-12", 1), "2027-01")

    def test_month_of_file(self):
        self.assertEqual(_month_of_file(Path("gz_tide/2026-09.csv")), "2026-09")
        self.assertEqual(_month_of_file(Path("t148/hourly/2025-12.csv")), "2025-12")
        self.assertEqual(_month_of_file(Path("typhoon/raw/2026-11-15.json")), "2026-11")
        self.assertIsNone(_month_of_file(Path("t148/station.csv")))
        self.assertIsNone(_month_of_file(Path("meta/run_log.csv")))


if __name__ == "__main__":
    unittest.main()

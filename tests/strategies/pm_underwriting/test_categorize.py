import duckdb
import pytest

from prospector.strategies.pm_underwriting.categorize import (
    CATEGORY_PREFIXES,
    CATEGORY_SUBSTRINGS,
    category_sql,
    classify,
)


class TestClassify:
    @pytest.mark.parametrize(
        "ticker,expected",
        [
            ("KXNFLGAME-2026-TEAM1", "sports"),
            ("KXNBA-FINALS", "sports"),
            ("KXMVESPORTS-X", "sports"),
            ("KXBTC-50K", "crypto"),
            ("KXETH-3000", "crypto"),
            ("KXSOL-200", "crypto"),
            ("KXNASDAQ-4Q", "financial"),
            ("NASDAQ-SOMETHING", "financial"),
            ("XXX-USDJPY-150", "financial"),
            ("XXX-EURUSD-1.10", "financial"),
            ("KXCITIES-LA", "weather"),
            ("HIGH-NYC", "weather"),
            ("LOW-CHI", "weather"),
            ("CPI-2026-04", "economics"),
            ("KXFED-HIKE", "economics"),
            ("GDP-Q1", "economics"),
            ("PRES-2028", "politics"),
            ("KXMAYOR-NYC", "politics"),
            ("KXGOV-CA", "politics"),
            ("WEIRD-THING", "other"),
            ("", "other"),
        ],
    )
    def test_cases(self, ticker, expected):
        assert classify(ticker) == expected


class TestCategorySql:
    def test_agrees_with_classify_across_fixture(self):
        """Run the generated SQL against a fixture table and compare to `classify()`."""
        con = duckdb.connect()
        fixtures = [
            "KXNFL-X",
            "KXBTC-Y",
            "KXNASDAQ-Z",
            "XXX-USDJPY-150",
            "KXCITIES-LA",
            "CPI-2026",
            "PRES-2028",
            "WEIRD-THING",
            "KXNBA-FINALS",
            "KXSOL-200",
        ]
        con.execute("CREATE TABLE t(event_ticker VARCHAR)")
        for f in fixtures:
            con.execute("INSERT INTO t VALUES (?)", [f])
        sql = category_sql("event_ticker")
        rows = con.execute(f"SELECT event_ticker, {sql} FROM t").fetchall()
        for ticker, sql_category in rows:
            assert sql_category == classify(ticker), f"mismatch on {ticker}"
        con.close()

    def test_custom_column_name(self):
        sql = category_sql("et")
        assert "et LIKE" in sql
        assert "event_ticker" not in sql

    def test_every_category_represented(self):
        sql = category_sql()
        for category in CATEGORY_PREFIXES:
            assert f"'{category}'" in sql

    def test_substrings_emitted(self):
        sql = category_sql()
        for _cat, needles in CATEGORY_SUBSTRINGS.items():
            for needle in needles:
                assert f"'%{needle}%'" in sql

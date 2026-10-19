"""M2: tools, safe arithmetic, filing sections, and comps == metrics table."""
import math

import pandas as pd
import pytest

from verity.config import DATA_DIR
from verity.tools import COMPS_METRICS, ToolBox, ToolError, call_tool, safe_eval


@pytest.fixture(scope="module")
def box():
    return ToolBox()


def test_get_metric_carries_provenance(box):
    r = box.get_metric("VRT", "revenue", 2025)
    assert r["value"] == 10_229.9e6 and r["display"] == "$10,229.9m"
    assert r["accession"] == "0001674101-26-000008"
    assert r["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert r["source_id"].startswith("S")


def test_same_fact_same_source_id(box):
    a = box.get_metric("ETN", "revenue", 2025)["source_id"]
    b = box.get_metric("ETN", "revenue", 2025)["source_id"]
    assert a == b


def test_errors_come_back_as_data(box):
    assert "error" in call_tool(box, "get_metric", {"ticker": "VRT", "metric": "nonsense", "fiscal_year": 2025})
    assert "error" in call_tool(box, "get_metric", {"ticker": "GEV", "metric": "total_assets", "fiscal_year": 2022})
    assert "error" in call_tool(box, "nope", {})


@pytest.mark.parametrize("expr,expected", [("a / b - 1", 0.25), ("(a + b) * 2", 3600), ("-a ** 2", -1e6)])
def test_safe_eval(expr, expected):
    assert safe_eval(expr, {"a": 1000, "b": 800}) == pytest.approx(expected)


@pytest.mark.parametrize("expr", ["__import__('os')", "a.real", "[a]", "a if a else b", "open('x')"])
def test_safe_eval_rejects_code(expr):
    with pytest.raises(ToolError):
        safe_eval(expr, {"a": 1, "b": 2})


def test_compute_uses_source_ids(box):
    rev = box.get_metric("VRT", "revenue", 2025)["source_id"]
    rev0 = box.get_metric("VRT", "revenue", 2024)["source_id"]
    r = box.compute("a / b - 1", {"a": rev, "b": rev0}, unit="ratio")
    assert r["display"] == "27.7%"
    assert box.ledger.get(r["source_id"]).detail["inputs"] == {"a": rev, "b": rev0}


@pytest.mark.parametrize("ticker", ["VRT", "JCI", "MOD"])
def test_filing_sections(box, ticker):
    for section in ("business", "risk_factors", "mdna"):
        r = box.get_filing_section(ticker, section=section)
        assert r["chars"] > 5_000, (ticker, section)
        assert r["accession"] and r["url"].startswith("https://www.sec.gov/Archives/")


def test_comps_match_metrics_table_exactly(box):
    """M2 'done when': every comps cell equals the metrics/derived/valuation tables."""
    comps = box.build_comps()
    long = pd.read_csv(DATA_DIR / "processed" / "metrics_long.csv")
    derived = pd.read_csv(DATA_DIR / "processed" / "derived.csv")
    val = pd.read_csv(DATA_DIR / "processed" / "valuation.csv").set_index("ticker")
    table = pd.concat([long[["ticker", "fiscal_year", "metric", "value"]],
                       derived[["ticker", "fiscal_year", "metric", "value"]]])
    table = table.set_index(["ticker", "fiscal_year", "metric"]).value
    checked = 0
    for row in comps["rows"]:
        t, fy = row["ticker"], row["fiscal_year"]
        assert fy == val.loc[t, "fiscal_year"]
        for m in COMPS_METRICS:
            got = row["cells"][m]["value"]
            want = val.loc[t, m] if m in val.columns else table.loc[(t, fy, m)]
            assert got == pytest.approx(want, rel=1e-12), (t, m)
            checked += 1
    assert checked == 10 * len(COMPS_METRICS)

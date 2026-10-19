"""Concept mapping checked against values read by hand from each 10-K.

Expected values (USD millions) are copied from the income statement or balance
sheet of the filing named in each block; the accession number is asserted too.
"""
from datetime import date

import pytest

from verity.derived import load_settings, split_factor
from verity.xbrl import CompanyFacts, fiscal_year_of

M = 1e6

# (ticker, fiscal year, accession of the 10-K the values were read from, {metric: value})
HAND_CHECKED = [
    ("VRT", 2025, "0001674101-26-000008", {
        "revenue": 10_229.9,          # Net sales
        "gross_profit": 3_715.2,      # Gross profit (VRT tags cost of sales only)
        "operating_income": 1_829.7,  # Operating profit
        "cash": 1_728.4,
        "total_debt": 2_913.0,        # Long-term debt, net 2,892.1 + current portion 20.9
    }),
    ("ETN", 2025, "0001551182-26-000007", {
        "revenue": 27_448,
        "gross_profit": 10_317,       # 27,448 - cost of products sold 17,131
        "operating_income": 5_173,    # income before taxes 4,932 + interest expense-net 241
        "net_income": 4_087,          # attributable to Eaton ordinary shareholders
        "total_debt": 9_895,          # short-term 1 + current LTD 1,136 + LTD 8,758
    }),
    ("JCI", 2025, "0000833444-25-000097", {
        "revenue": 23_596,
        "gross_profit": 8_592,
        "operating_income": 2_288,    # pre-tax 1,969 + net financing charges 319
        "cash": 379,
        "total_debt": 9_880,          # JCI's own "Total debt" line
    }),
    ("TT", 2025, "0001628280-26-005731", {
        "revenue": 21_321.9,
        "gross_profit": 7_710.2,      # EBIT 3,967.4 + S&A 3,742.8
        "operating_income": 3_967.4,
        "cash": 1_763.3,
        "total_debt": 4_615.1,        # TT's own "Total debt" line
    }),
    ("POWL", 2025, "0000080420-25-000152", {
        "revenue": 1_104.318,
        "gross_profit": 324.381,
        "operating_income": 217.860,
        "cash": 450.739,
        "shares_diluted": 12.167,     # thousands in the filing -> millions here
    }),
]


@pytest.fixture(scope="module")
def companies():
    return {t: CompanyFacts.load(t) for t, *_ in HAND_CHECKED}


@pytest.mark.parametrize("ticker,fy,accession,expected", HAND_CHECKED,
                         ids=[c[0] for c in HAND_CHECKED])
def test_hand_checked_values(companies, ticker, fy, accession, expected):
    cf = companies[ticker]
    for metric, value in expected.items():
        mv = cf.metric(metric, fy)
        assert mv.value is not None, f"{ticker} {metric} missing"
        # filings round to 0.1m or 1m; allow half a rounding unit
        assert mv.value / M == pytest.approx(value, abs=0.051), (ticker, metric, mv.method)
        assert accession in mv.accession, (ticker, metric, mv.accession)


def test_tag_used_is_logged(companies):
    assert companies["VRT"].metric("revenue", 2025).method == \
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    gp = companies["ETN"].metric("gross_profit", 2025)
    assert gp.method == "RevenueFromContractWithCustomerExcludingAssessedTax - CostOfRevenue"
    assert [f.tag for f in gp.facts] == ["RevenueFromContractWithCustomerExcludingAssessedTax",
                                         "CostOfRevenue"]


def test_instant_vs_duration_periods(companies):
    rev = companies["JCI"].metric("revenue", 2025)
    assert rev.facts[0].start == date(2024, 10, 1) and rev.facts[0].end == date(2025, 9, 30)
    cash = companies["JCI"].metric("cash", 2025)
    assert cash.facts[0].start is None and cash.facts[0].end == date(2025, 9, 30)


def test_recast_uses_latest_filing_and_is_logged():
    """NVT sold its Thermal business in 2025, so FY2023 revenue was recast."""
    cf = CompanyFacts.load("NVT")
    rev = cf.metric("revenue", 2023)
    assert rev.value / M == pytest.approx(2_668.9)
    assert any(r.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
               and r.fiscal_year == 2023 and r.old_value / M == pytest.approx(3_263.6)
               for r in cf.restatements)


def test_assumed_zero_is_explicit():
    mv = CompanyFacts.load("POWL").metric("total_debt", 2025)
    assert mv.value == 0 and mv.method == "assumed zero" and mv.note


def test_missing_is_none_not_zero():
    mv = CompanyFacts.load("GEV").metric("total_assets", 2022)   # pre-spin, no balance sheet
    assert mv.value is None and mv.method == "not reported"


@pytest.mark.parametrize("end,fy", [
    (date(2025, 12, 31), 2025), (date(2026, 3, 31), 2026),
    (date(2025, 6, 30), 2025), (date(2025, 1, 3), 2024)])
def test_fiscal_year_label(end, fy):
    assert fiscal_year_of(end) == fy


def test_split_factor():
    s = load_settings()
    assert split_factor("POWL", "2025-11-19", s) == 3     # FY2025 10-K, before the split
    assert split_factor("POWL", "2026-08-01", s) == 1
    assert split_factor("VRT", "2020-01-01", s) == 1

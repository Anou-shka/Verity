"""Derived metrics on a tiny synthetic company, so every number is checkable by eye."""
import pytest

from verity.derived import derive_year, load_settings
from verity.xbrl import CompanyFacts


def fact(val, end, start=None, accn="0000000000-26-000001", filed="2026-02-01", form="10-K"):
    row = {"val": val, "end": end, "accn": accn, "filed": filed, "form": form}
    if start:
        row["start"] = start
    return row


def company(rows_by_tag):
    facts = {tag: {"units": {"USD": rows}} for tag, rows in rows_by_tag.items()}
    return CompanyFacts("TEST", {"facts": {"us-gaap": facts}})


FY24 = dict(start="2024-01-01", end="2024-12-31")
FY25 = dict(start="2025-01-01", end="2025-12-31")


@pytest.fixture
def cf():
    return company({
        "Revenues": [fact(800, **FY24), fact(1000, **FY25)],
        "GrossProfit": [fact(400, **FY25)],
        "OperatingIncomeLoss": [fact(200, **FY25)],
        "DepreciationDepletionAndAmortization": [fact(50, **FY25)],
        "NetIncomeLoss": [fact(120, **FY25)],
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
            [fact(160, **FY25)],
        "IncomeTaxExpenseBenefit": [fact(40, **FY25)],
        "StockholdersEquity": [fact(500, "2024-12-31"), fact(700, "2025-12-31")],
        "CashAndCashEquivalentsAtCarryingValue": [fact(100, "2024-12-31"), fact(150, "2025-12-31")],
        "LongTermDebt": [fact(300, "2024-12-31"), fact(250, "2025-12-31")],
    })


def test_derived(cf):
    d = {x.metric: x for x in derive_year(cf, 2025, load_settings())}
    assert d["gross_margin"].value == pytest.approx(0.40)
    assert d["ebit_margin"].value == pytest.approx(0.20)
    assert d["ebitda"].value == 250
    assert d["revenue_growth"].value == pytest.approx(0.25)
    assert d["net_debt"].value == 100
    assert d["roe"].value == pytest.approx(120 / 600)               # average equity
    # tax rate 40/160 = 25%; NOPAT 150; invested capital 700 and 800 -> avg 750
    assert d["roic"].value == pytest.approx(150 / 750)
    assert d["roe"].formula.startswith("net_income /")


def test_latest_filing_wins():
    cf = company({"Revenues": [
        fact(1000, **FY25, accn="A-1", filed="2026-02-01"),
        fact(950, **FY25, accn="A-2", filed="2027-02-01")]})   # recast next year
    mv = cf.metric("revenue", 2025)
    assert mv.value == 950 and mv.accession == "A-2"
    assert cf.restatements[0].old_value == 1000


def test_quarterly_facts_ignored():
    cf = company({"Revenues": [fact(250, "2025-12-31", start="2025-10-01", form="10-K")]})
    assert cf.metric("revenue", 2025).value is None

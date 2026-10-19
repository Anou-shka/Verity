"""M4: claim extraction, verification and deterministic revision."""
import pytest

from verity.agents import fact_checker as fc
from verity.agents.researcher import research
from verity.agents.writer import apply_fixes, template_note
from verity.tools import ToolBox


@pytest.fixture(scope="module")
def setup():
    box = ToolBox()
    pack = research("VRT", box, use_llm=False)
    note = template_note(pack)
    return box, pack, note


def check(box, note):
    return fc.FactChecker(box.ledger).check(note)


def claim_for(report, text):
    return next(c for c in report.claims if c.value_text == text)


def test_extraction_parses_units():
    claims = fc.extract_claims("Revenue was $10,229.9m [S1], margin 36.3% [S2], "
                               "EV/EBITDA 37.7x [S3], EPS $3.41 [S4], net cash -$8,785.0m [S5] "
                               "in FY2025 per the 10-K, and 3 risks.")
    got = [(c.kind, c.value, c.ref) for c in claims]
    assert got == [("money", 10_229.9e6, "S1"), ("pct", pytest.approx(0.363), "S2"),
                   ("multiple", 37.7, "S3"), ("per_share", 3.41, "S4"),
                   ("money", -8_785.0e6, "S5")]


def test_years_dates_citations_and_quotes_are_not_claims():
    claims = fc.extract_claims("On 2026-10-16, in FY2025 and 2024, Item 1A says “growth of 12%” [S9].")
    assert claims == []


def test_clean_note_fully_verified(setup):
    box, pack, note = setup
    r = check(box, note)
    assert len(r.claims) >= 20
    assert all(c.status == "verified" for c in r.claims), [c.reason for c in r.claims if c.status != "verified"]
    assert all(q["status"] == "verified" for q in r.quotes)


def test_wrong_number_is_caught_with_correction(setup):
    box, _, note = setup
    r = check(box, note.replace("$10,229.9m [S1]", "$10,529.9m [S1]"))
    c = claim_for(r, "$10,529.9m")
    assert c.status == "wrong" and c.correct_display == "$10,229.9m"


def test_wrong_year_is_caught(setup):
    box, _, note = setup
    bad = note.replace("FY2025 net income", "FY2024 net income")
    c = claim_for(check(box, bad), "$1,332.8m")
    assert c.status == "wrong" and c.correct_year == 2025


def test_unit_swap_is_caught(setup):
    box, _, note = setup
    c = claim_for(check(box, note.replace("$10,229.9m [S1]", "$10,229.9bn [S1]")), "$10,229.9bn")
    assert c.status == "wrong"


def test_made_up_number_is_unverifiable(setup):
    box, _, note = setup
    bad = note.replace("## Margins", "Order backlog reached $9,500.0m at year end.\n\n## Margins")
    c = claim_for(check(box, bad), "$9,500.0m")
    assert c.status == "unverifiable" and c.reason == "no source cited"


def test_fake_citation_is_caught(setup):
    box, _, note = setup
    bad = note.replace("## Margins", "Order backlog reached $9,500.0m [S1] at year end.\n\n## Margins")
    assert claim_for(check(box, bad), "$9,500.0m").status == "wrong"


def test_within_tolerance_is_verified(setup):
    box, _, note = setup
    # 0.3% off is inside the 0.5% tolerance for reported figures
    c = claim_for(check(box, note.replace("$10,229.9m [S1]", "$10,260.0m [S1]")), "$10,260.0m")
    assert c.status == "verified"


def test_ratio_tolerance_is_absolute(setup):
    box, _, note = setup
    c = claim_for(check(box, note.replace("36.3% [S3]", "36.5% [S3]")), "36.5%")
    assert c.status == "wrong"     # 0.2pp > 0.1pp


def test_altered_quote_is_caught(setup):
    box, _, note = setup
    bad = note.replace("We may not realize all", "We will realize all")
    if bad == note:
        pytest.skip("quote text differs for this filing")
    assert any(q["status"] == "wrong" for q in check(box, bad).quotes)


def test_revision_fixes_everything(setup):
    box, _, note = setup
    bad = (note.replace("$10,229.9m [S1]", "$10,529.9m [S1]")
               .replace("FY2025 net income", "FY2024 net income")
               .replace("## Margins", "Order backlog reached $9,500.0m at year end.\n\n## Margins"))
    first = check(box, bad)
    fixed = apply_fixes(bad, [c for c in first.claims if c.status != "verified"])
    second = check(box, fixed)
    assert all(c.status == "verified" for c in second.claims)
    assert "$10,229.9m [S1]" in fixed and "9,500" not in fixed and "FY2025 net income" in fixed


def test_failure_classification():
    from eval.extraction import classify
    truths = {("VRT", "revenue", 2025): 10_229.9e6, ("VRT", "revenue", 2024): 8_011.8e6,
              ("VRT", "gross_profit", 2025): 3_715.2e6}
    q = {"ticker": "VRT", "metric": "revenue", "fiscal_year": 2025, "truth": 10_229.9e6}
    assert classify(10_230e6, q, truths) == "correct"
    assert classify(10_229.9, q, truths) == "wrong_unit"
    assert classify(8_011.8e6, q, truths) == "wrong_year"
    assert classify(3_715.2e6, q, truths) == "wrong_concept"
    assert classify(9_000e6, q, truths) == "made_up"
    assert classify(None, q, truths) == "no_answer"


def test_injector_plants_real_errors():
    import random
    from verity.inject import inject
    box = ToolBox()
    pack = research("POWL", box, use_llm=False)
    note = template_note(pack)
    rng = random.Random(1)
    for _ in range(20):
        bad, injs = inject(note, pack.fiscal_year, 3, rng)
        assert bad != note and len(injs) == 3

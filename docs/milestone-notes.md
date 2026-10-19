# Milestone notes

## M1: EDGAR + XBRL layer (19 Oct 2026)

### Network check

| Endpoint | Result |
|---|---|
| `www.sec.gov/files/company_tickers.json` | ✅ 200 |
| `data.sec.gov/api/xbrl/companyfacts/…` | ✅ 200 |
| `data.sec.gov/submissions/…` | ✅ 200 |
| Yahoo Finance (`query1.finance.yahoo.com`, via yfinance) | ✅ 200 |

Nothing is blocked.

### Universe check

All 10 companies file 10-Ks with XBRL, so the universe stays at 10.

| Ticker | Fiscal year end | Latest 10-K | Note |
|---|---|---|---|
| VRT | Dec | FY2025 (filed 13 Feb 2026) | |
| ETN | Dec | FY2025 | No gross-profit or operating-income tag |
| NVT | Dec | FY2025 | Thermal business sold, so FY2022–23 were recast |
| MOD | **Mar** | FY2026 (Mar 2026) | |
| HUBB | Dec | FY2025 | |
| GEV | Dec | FY2025 | Spun off Apr 2024, so only FY2022–25 exist and FY2022 has no balance sheet |
| JCI | **Sep** | FY2025 (Sep 2025) | No operating-income tag; FY2026 10-K due Nov 2026 |
| TT | Dec | FY2025 | Cost of sales tagged only by product/service dimension |
| SMCI | **Jun** | FY2026 (Jun 2026) | 10:1 split Oct 2024 (already restated in filings) |
| POWL | **Sep** | FY2025 (Sep 2025) | No debt; 3:1 split Apr 2026, after its latest 10-K |

### What was built

- **`sec.py`**: the EDGAR client. It reads the User-Agent from `.env` and waits ≥0.15s between requests (≤7 req/s). Every response is cached gzipped in `data/cache/`: 2.4 MB for the whole universe, committed so the repo runs offline. It also lists filings and returns filing text, which M2's `get_filing_section` will use.
- **`config/concept_map.yaml`**: an ordered list of options for each of 13 standard metrics plus 3 supporting ones (cost of revenue, pre-tax income, tax). An option is either one tag or a signed sum of tags/metrics, and each fallback has a comment saying which company needs it and how it was checked.
- **`xbrl.py`**:
  - keeps 10-K facts that are annual durations (350–380 days) or fiscal-year-end instants;
  - labels each fact's fiscal year from its period end date;
  - keeps the latest-filed value and logs every restatement;
  - logs the option used for every value.
- **`derived.py`**: computes gross margin, EBIT margin, EBITDA, revenue growth, net debt, ROE and ROIC, plus EV, EV/EBITDA, EV/Sales and P/E on 16 Oct 2026 prices. Each value is stored with its formula and inputs.
- **`prices.py`**: yfinance closes (not dividend-adjusted), cached, and returned with their date.
- **`build_metrics.py`** writes these files to `data/processed/`:
  - `metrics_long.csv`: every value with concept, period, accession and filing date;
  - `derived.csv`;
  - `valuation.csv`;
  - `restatements.csv`;
  - `metrics_wide.csv`.
- **Tests (18 passing, offline):**
  - 25 values across VRT, ETN, JCI, TT and POWL read by hand from the 10-K text, with accession numbers asserted;
  - recast handling (NVT);
  - explicit zero vs missing;
  - fiscal-year labels;
  - split factors;
  - derived metrics on a synthetic company.

**Coverage:** 663 core values across 10 companies × 13 metrics × FY2021–26. Only 2 are missing (GEV FY2022 balance sheet, which is genuinely not reported). 72 values (11%) had to be rebuilt from components, and 70 company-year-concept combinations were recast at 5 companies.

### Three design choices

1. **Fall back by year, in a fixed order, and log the choice.** Companies change tags over time (TT capex moved from `PaymentsToAcquirePropertyPlantAndEquipment` to `…ProductiveAssets` in FY2025). Resolving per year keeps coverage complete, and the `method` column shows every switch so it can't hide. The cost is that a series can mix tags. The log is the safeguard.
2. **Rebuild missing lines from components only after checking the formula against the filing.** EBIT for Eaton is pre-tax + interest. For JCI it is GP − SG&A − restructuring + equity income, which ties to JCI's pre-tax + net financing charges. GP for TT is EBIT + S&A. My first JCI formula used a restructuring tag (427m) that turned out to be a note disclosure, not the income-statement line (546m). That 113m error was caught only by reading the 10-K. This is why the tests pin values from the filing text and not from XBRL itself.
3. **Latest filing wins, restatements are logged, and reported per-share values are kept as filed.** Recasts make history comparable to today's perimeter (NVT FY2023 revenue moved from 3,263.6m to 2,668.9m after the Thermal sale). Per-share values stay as filed, so the fact-checker compares against what the filing says. Split adjustment happens only inside valuation, where it is noted (POWL's FY2025 EPS of 14.86 becomes 4.95 for P/E).

**Smaller choices:**
- **Valuation date.** Fixed at 16 Oct 2026 for reproducibility.
- **Multiples basis.** Multiples use the latest fiscal year, not LTM. This means JCI and POWL (Sep year-ends) are a year staler than the rest. That is a known M2 improvement.
- **EV definition.** EV ignores minorities and leases.
- **ROE and ROIC.** Both use average capital. ROIC falls back to a 21% tax rate when the effective rate is meaningless.

### Questions an interviewer could ask

1. "Why not just use the SEC `frames` API or a data vendor instead of building a concept map?" (Think about traceability to an accession number, vendor black-box adjustments, and cost.)
2. "Eaton doesn't report operating income. How did you get its EBIT, and how do you know it's right?" (Pre-tax + interest; tied to the 10-K; pinned in a test.)
3. "If a company restates, which number does your fact-checker treat as the truth, and could that mark a correct claim wrong?" (Latest filing wins. A note quoting the original 10-K figure would be "wrong" against the recast. Should the checker accept either?)

### For you to do before "continue"

- [ ] Hand-check the 12 values in [`docs/m1-review-sample.md`](m1-review-sample.md) against the 10-Ks.
- [ ] Decide on GEV cash (it includes restricted cash; see the note in the review sheet).
- [ ] Read the governance memo draft: [`docs/governance-memo.md`](governance-memo.md).

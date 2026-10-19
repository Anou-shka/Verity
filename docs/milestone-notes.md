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

---

## M2: Tools and comps (19 Oct 2026)

**What was built.** `tools.py` is the agents' entire view of the world, through seven tools:
- `list_fiscal_years`
- `get_metric`: reported XBRL metrics plus the derived ratios
- `get_metric_history`
- `compute`: arithmetic restricted to + − × ÷ ** on named inputs, checked against an AST whitelist, with no `eval`
- `get_price`
- `get_filing_section`
- `build_comps`

Every result goes into a **ledger** and gets a source id (`S7`) carrying its provenance: concept, period and accession, or formula and input ids, or price date. Each tool has a JSON schema for model tool use. `get_filing_section` parses Items 1, 1A and 7 out of the 10-K text for all 10 companies. Eaton's MD&A is incorporated by reference to an exhibit, which is genuine.

**Done when:** the comps table matches the metrics table exactly. `tests/test_tools.py` compares all 110 cells (10 companies × 11 metrics); all identical.

**Three design choices**
1. **One ledger, one id per fact.** The same fact always gets the same id, so a citation means one thing, and the fact-checker can look up exactly what a number claims to be.
2. **Section parsing anchored to line starts.** The first version matched "see Item 1A. Risk Factors" cross-references and returned the wrong text. Headings are now matched only at the start of a line, and the longest span wins, which also skips the table of contents.
3. **Peer medians are computed by code, not by the model.** A median is a calculation, so it goes through the ledger like any other number.

**Interview questions**
1. "Why not let the model call `eval` on a formula? What exactly does your `compute` allow?"
2. "Why do the multiples use the latest fiscal year rather than LTM, and which companies does that distort?"
3. "How would you know if a tool silently returned the wrong section of a 10-K?"

## M3: Agents (19 Oct 2026)

**What was built.**
- **`llm.py`.** An adapter for Anthropic (official SDK, manual tool loop, server-side refusal fallbacks on Opus 5.5), OpenAI and Ollama. It has a **replay cache** keyed by a hash of the request (provider, model, effort, prompt, tools) and per-call token and cost tracking.
- **Researcher.** It runs a fixed tool plan (rules mode) or a model tool-use loop (LLM mode); the comps table is always built by code.
- **Writer.** It uses a deterministic template or the strong model. Either way, every number is a display string copied from the pack and followed by `[S#]`.

`verity run VRT` produces `outputs/VRT/note.md` with references.

**The no-key constraint.** This environment had no model API key, and I did not use the coding assistant's own credentials to run the pipeline. So:
- **Rules mode.** It runs and is measured, with no model.
- **LLM mode.** It is built and tested end to end with a scripted fake model (`tests/test_llm_mode.py`), but has not yet run against a real model.

**Three design choices**
1. **Two paths through the same pipeline (rules and LLM).** The rules path gives a deterministic reference and lets everything run with no key. The LLM path is measured against it.
2. **Copy display strings, never numbers.** The Writer gets "$10,229.9m", not 10229900000. Rounding and unit choices happen once, in `fmt.py`, and the checker parses the same format back.
3. **Fast model for research, strong model for writing.** Tool-calling to fetch facts is routine; writing ~600 words of clear prose under strict citation rules is harder.

**Interview questions**
1. "How does your replay cache stay valid when you change a prompt?"
2. "Why keep the raw provider content blocks in the message history?"
3. "What stops the Writer from citing `[S1]` next to a number that isn't S1?"

## M4: Fact-checker loop (19 Oct 2026)

**What was built.** `fact_checker.py`:
- **Parser extraction.** It finds money, %, multiples and per-share values. Citations, FY labels, dates, form names and quoted text are masked out first.
- **Independent re-fetch.** It uses its own ToolBox and ledger.
- **Checks.** Tolerance (0.5% / 0.1pp, in `settings.yaml`), fiscal year, a keyword check that the words name the cited metric, and quote matching against the filing.
- **Comps table.** Every cell is re-fetched.

**Orchestrator.** It is a state machine (research → write → check → revise → check, at most 2 rounds) that writes a JSONL trace per run. The fact-check log shows every claim with status and source (`outputs/<T>/factcheck.md`). `verity run VRT --inject 4` plants known errors to show the loop working (`outputs/VRT-demo/`).

**Three design choices**
1. **Extraction by parser, not by model.** A model can skip a number; a regex cannot. In LLM mode the model is used only to flag *qualitative* statements that need a source.
2. **The checker never trusts the Writer's ledger values.** It uses the citation only to learn what the number claims to be (company, metric, year), then fetches the truth itself.
3. **Delete fabrications, don't patch them.** Found by the demo: an invented "organic orders" figure that borrowed a real citation was "corrected" to the cited value, which laundered it. Now a wrong number whose sentence doesn't name the cited metric is deleted.

**Interview questions**
1. "Your checker passed a fabricated sentence after 'fixing' it. How did you find that, and what did you change?"
2. "Why is the tolerance absolute for ratios but relative for reported figures?"
3. "What does your keyword check get wrong?"

## M5: Evaluation (19 Oct 2026)

**What was built.**
- **`eval/catch_rate.py` (experiment 3).** 10 companies × 30 trials × 3 planted errors = 900, across 7 types, scored for recall, false alarms and residual errors after revision.
- **`eval/extraction.py` (experiments 1–2).** 360 questions (10 × 12 metrics × 3 years), the tool-using agent against a no-tools baseline, with failure typing (wrong year, unit, concept, made-up, no answer).
- **`eval/run_all.py`.** It writes `docs/results.md` and the charts.

**Results.**
- **Recall: 98.2%.** Value errors are caught 100% of the time; misdescribed true numbers 87.7%.
- **False alarms: 0%.**
- **Left after revision: 2.7%.**
- **Experiments 1–2: pending an API key.**

**Three design choices**
1. **Make sure a planted error is an error.** The first run counted "misses" that were no-ops (0 perturbed is still 0; 0.4x rounds back to 0.4x). The injector now rejects them.
2. **Score fixed as well as caught.** The residual measure counts an inserted sentence that survives revision even with a changed number. That exposed the laundering bug and the year-only fixes.
3. **Report the weak type.** The headline number is less interesting than the type at 87.7%.

**Interview questions**
1. "Isn't 98% inflated because your writer is a template?"
2. "What error type would you add next, and how would you generate it?"
3. "How would you avoid overfitting the checker to your own injector?"

## M6: App (19 Oct 2026)

**What was built.** `app/streamlit_app.py`:
- **Note tab.** The note on the left with every number underlined by status (✓ verified, ↺ corrected, ? unverifiable; icon and colour, never colour alone; hover for the source). The fact-check log, quote checks and revision rounds are on the right.
- **Comps tab.** The peer table.
- **Run trace tab.** Every event in the run.

It reads the committed `outputs/`, so it runs from a fresh clone with no key. `tests/test_app.py` renders it headlessly.

**Interview questions**
1. "What would an analyst do differently because of the right-hand panel?"
2. "Why show 'corrected' separately from 'verified'?"
3. "How would this UI change for a compliance reviewer?"

## M7: Polish (19 Oct 2026)

**What was built.**
- **README** with the headline results, an architecture diagram, how to run it and limitations.
- **`docs/case-study.md`.**
- **`docs/defence.md`** with 37 questions in 7 groups; the answers are yours.
- **Governance memo** updated with the measured results and a fail on the zero-residual threshold.
- **`make all`** reproduces metrics, experiments, demo and tests offline with no key. Verified on a fresh clone.

**What's left for you**
- [ ] Hand-check the 12 values in [`m1-review-sample.md`](m1-review-sample.md).
- [ ] Decide on GE Vernova's cash (it includes restricted cash).
- [ ] Add an API key and run `VERITY_PROVIDER=anthropic make eval notes`. This fills experiments 1–2 and LLM-mode notes, and the cache then makes it replayable for anyone.
- [ ] Write your answers in `docs/defence.md`.

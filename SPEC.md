# Project spec: Verity — an agentic equity analyst with a fact-checker

Paste this whole file into Claude Code as the first message of the project, then save it in the repo as `SPEC.md`.

---

## 0. Who I am and how we work

I'm Anoushka, a CS + Business graduate (NTU) and CFA Level II candidate. I'm building this for AI investment research roles. My other projects: Credyte (credit-default ML), Portfolio Pulse (portfolio risk dashboard) and Delta Volts (equity research initiation on Delta Electronics). Verity should connect to Delta Volts by covering Delta's US-listed peers.

**The one-sentence pitch:** "Verity is a multi-agent system that researches a company from its SEC filings, writes a comps table and a short research note, and then has a separate fact-checking agent verify every number against the filing — and I measured how many errors the fact-checker catches."

**Working rules (follow these throughout):**

1. **Keep the agent loop simple and readable.** Write the orchestration in plain Python (a small state machine with tool calls), not LangChain, CrewAI or similar frameworks. I need to explain every line in interviews.
2. **LLMs never do arithmetic.** Every ratio, growth rate and multiple is computed by a Python tool and passed back to the model.
3. **Every number is traceable.** Each figure in the output links to its source: the XBRL fact (concept, period, filing accession number) or a price data point with its date.
4. **Measure, don't claim.** No "it works well" without a number from the evaluation harness.
5. **Teach as you go.** At the end of each milestone, add to `docs/milestone-notes.md`: what you built, the 3 most important design choices, and 3 questions an interviewer could ask me.
6. Stop at the end of each milestone and wait for me to say "continue".

---

## 1. Deliverables

| # | Deliverable | Format |
|---|---|---|
| 1 | Python package with tools, agents and orchestrator | `src/verity/` |
| 2 | CLI: `verity run VRT` produces a comps table, a note and a fact-check log | `outputs/<ticker>/` |
| 3 | Evaluation harness with results tables and charts | `eval/`, `docs/results.md` |
| 4 | Streamlit app: note on the left, fact-check log on the right, every claim marked verified / corrected / unverifiable with its source | `app/` |
| 5 | Run traces (every agent step, tool call, tokens, cost, time) | `traces/*.jsonl` |
| 6 | README, website case study, interview defence sheet | `README.md`, `docs/case-study.md`, `docs/defence.md` |

---

## 2. Data sources

| Data | Endpoint | Notes |
|---|---|---|
| Ticker → CIK | `https://www.sec.gov/files/company_tickers.json` | Pad CIK to 10 digits |
| All reported XBRL facts for a company | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | The ground truth for numbers |
| Filing list and metadata | `https://data.sec.gov/submissions/CIK##########.json` | Find the latest 10-K / 10-Q and accession numbers |
| Filing text (for MD&A, risk factors, segment commentary) | EDGAR archives for the filing found above | Used for qualitative claims only |
| Share prices, shares outstanding | yfinance | Record the price date |

**SEC rules:** send a `User-Agent` header with my name and email (read both from `.env`, never hard-code them), stay under 10 requests per second, and cache every response on disk in `data/cache/` so we never download the same file twice.

**Network check first:** test whether this environment can reach `data.sec.gov`, `www.sec.gov` and Yahoo Finance. If anything fails, stop and tell me exactly what's blocked.

### Company universe (data-centre power and cooling, Delta's US-listed peers)

Start with: Vertiv (VRT), Eaton (ETN), nVent (NVT), Modine (MOD), Hubbell (HUBB), GE Vernova (GEV), Johnson Controls (JCI), Trane Technologies (TT), Super Micro Computer (SMCI), Powell Industries (POWL).

Before using them, check that each one files 10-Ks with XBRL data on EDGAR, and tell me about any that don't. Use 8–10 companies.

---

## 3. The XBRL layer (do this carefully — it's where the real learning is)

Build `src/verity/xbrl.py` that turns raw company facts into a clean table of standard metrics per company per fiscal year.

- **Concept mapping:** companies tag the same item differently (for example revenue can be `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax` or `SalesRevenueNet`). Keep an explicit, ordered mapping in `config/concept_map.yaml` from each standard metric to candidate tags. Log which tag was used for every value.
- **Periods:** separate duration facts (revenue, net income) from instant facts (assets, debt, cash). Take annual values from 10-K filings with a ~12-month duration. Handle fiscal years that don't end in December.
- **Duplicates and restatements:** the same fact can appear in several filings. Use the value from the most recent filing for that period and keep a note of restatements.
- **Derived metrics** (computed in Python, never by the LLM): gross margin, EBIT margin, EBITDA (EBIT + D&A), revenue growth, net debt, ROE, ROIC, EV, EV/EBITDA, EV/Sales, P/E.

Standard metrics to support: revenue, gross profit, operating income, net income, D&A, diluted EPS, diluted shares, total assets, total equity, cash, total debt, operating cash flow, capex.

Write unit tests for the mapping on at least 3 companies, checking a few values by hand against the 10-K.

---

## 4. Agents and tools

### Tools (plain Python functions with JSON schemas)

| Tool | Does |
|---|---|
| `get_metric(ticker, metric, fiscal_year)` | Returns value, unit, XBRL concept, period, accession number |
| `get_metric_history(ticker, metric, years)` | Several years at once |
| `compute(expression, inputs)` | Safe arithmetic on named inputs (no `eval` of arbitrary code); returns result + formula |
| `get_price(ticker, date)` | Close price and date |
| `get_filing_section(ticker, form, section)` | Text of a 10-K section (e.g. MD&A) with a reference |
| `build_comps(tickers, metrics)` | Comps table from the XBRL layer |

### Agents

1. **Researcher:** given a ticker, gathers the numbers and qualitative points needed, using tools only. Output: a structured JSON research pack, every item with its source.
2. **Writer:** turns the research pack into a comps table plus a ~600-word note (business, recent performance, margins, balance sheet, valuation vs peers, 3 risks). Each numeric claim carries an inline reference id.
3. **Fact-checker (the critic):** reads the draft, extracts **every** numeric claim into a list (value, unit, metric, period, company), re-fetches the true value with tools, and labels each claim **verified**, **wrong** (with the correct value) or **unverifiable**. Wrong claims go back to the Writer for one revision; repeat at most 2 rounds.
4. **Orchestrator:** plain Python that runs Researcher → Writer → Fact-checker → (revise) → final, logging every step to a trace.

Tolerance for "verified": within 0.5% for reported figures, within 0.1 percentage point for ratios, after unit normalisation. Make tolerances configurable.

### Model provider

- A small adapter so the model can be **Anthropic, OpenAI or a local model via Ollama**, set in `.env`. Default to a fast, cheap model for extraction and a stronger one for writing; make both configurable.
- **Replay mode:** cache every LLM response keyed by prompt hash, so tests, the demo and evaluations can be re-run without an API key or cost.
- Track tokens and estimated cost per run, and print them at the end.

---

## 5. Evaluation (this is what makes the project stand out)

Build `eval/` with three experiments. Report every result in `docs/results.md` with tables and charts.

1. **Extraction accuracy:** for every company × metric × year in the universe (aim for 10 × 12 × 3 ≈ 360 facts), compare what the Researcher reports with the XBRL ground truth. Report accuracy overall and by metric, and list the failure types (wrong year, wrong unit, wrong concept, made-up number).
2. **Baseline vs agent:** ask a single LLM call, with no tools, the same questions ("What was Vertiv's FY2024 revenue?"). Compare its accuracy with the tool-using agent. This shows why tools matter.
3. **Fact-checker catch rate (error injection):** take correct drafts and deliberately inject known errors (wrong numbers, wrong years, swapped units, changed percentages, a made-up figure) at random. Measure the share of injected errors the Fact-checker catches (recall), how often it flags correct numbers (false alarms), and how many errors remain after revision.

Also record per run: number of LLM calls, tokens, cost and time.

---

## 6. Repo structure

```
verity/
├── SPEC.md
├── README.md
├── .env.example          # SEC_USER_AGENT, model keys, model names
├── config/concept_map.yaml
├── src/verity/
│   ├── sec.py            # EDGAR client with caching and rate limiting
│   ├── xbrl.py           # facts → clean metrics table
│   ├── tools.py
│   ├── llm.py            # provider adapter + replay cache
│   ├── agents/researcher.py, writer.py, fact_checker.py
│   ├── orchestrator.py
│   └── cli.py
├── app/streamlit_app.py
├── eval/                 # experiments, injected-error generator, results
├── outputs/
├── traces/
├── docs/milestone-notes.md, results.md, case-study.md, defence.md
└── tests/
```

---

## 7. Milestones

| Day | Milestone | Done when |
|---|---|---|
| Oct 23 | **M1. EDGAR + XBRL layer:** network check, client with cache, concept mapping, clean metrics table for all companies | Tests pass; I've checked 10 values by hand against 10-Ks |
| Oct 24 | **M2. Tools + comps:** all tools, `build_comps`, comps table for the universe | Comps table matches the metrics table exactly |
| Oct 25 | **M3. Agents:** LLM adapter with replay mode, Researcher and Writer, first end-to-end note for VRT | `verity run VRT` produces a note with references |
| Oct 26 | **M4. Fact-checker loop:** claim extraction, verification, revision rounds, traces | Fact-check log shows every claim with status and source |
| Oct 27 | **M5. Evaluation:** the three experiments, results tables and charts | `docs/results.md` complete with real numbers |
| Oct 28 | **M6. App:** Streamlit app with note, comps and fact-check panel; runs in replay mode with no key | App runs from a fresh clone |
| Oct 29 | **M7. Polish:** README with headline results, case study, defence sheet, architecture diagram | One command reproduces everything in replay mode |

---

## 8. Quality bar

- Runs end to end from a fresh clone in replay mode, with no API key.
- No number in any note that didn't come from a tool.
- README shows: the pitch, an architecture diagram (agents and tools), headline evaluation numbers (extraction accuracy, baseline vs agent, fact-checker recall and false-alarm rate), cost per note, how to run it, limitations.
- `docs/defence.md` lists at least 25 likely interview questions grouped by topic (agent design, why no framework, XBRL quirks, evaluation design, failure modes, cost, how this would work at a fund), with empty space under each for my answers. Don't write the answers.
- Limitations section covers at least: US filers only, XBRL tagging inconsistency, qualitative claims are harder to verify, LLM non-determinism, evaluation on a small universe.

---

## 9. Start now

Also: a 2-page AI governance memo for Verity, written as a bank would assess an AI tool before launch: what could go wrong, how it was measured (fact-checker results), what controls to add, and how it maps to MAS's FEAT principles (fairness, ethics, accountability, transparency). HSBC also takes part in MAS's Project MindForge on AI risk management. → `docs/governance-memo.md`

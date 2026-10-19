# Verity: an agentic equity analyst with a fact-checker

> Verity is a multi-agent system that researches a company from its SEC filings, writes a comps table and a short research note, and then has a separate fact-checking agent verify every number against the filing — and I measured how many errors the fact-checker catches.

It covers Delta Electronics' US-listed data-centre power and cooling peers (VRT, ETN, NVT, MOD, HUBB, GEV, JCI, TT, SMCI, POWL) and connects to my [Delta Volts](https://github.com/Anou-shka/delta-volts) initiation on Delta Electronics.

**Status: M1 of 7 done (EDGAR client + XBRL metrics layer).** See [`SPEC.md`](SPEC.md) for the plan and [`docs/milestone-notes.md`](docs/milestone-notes.md) for progress.

## What works now

```bash
git clone https://github.com/Anou-shka/Verity.git && cd Verity
pip install -r requirements.txt
cp .env.example .env            # add SEC_USER_AGENT="Your Name you@example.com"
make offline                    # rebuild data/processed/ from the committed cache, no network
make test                       # 18 tests, offline
```

| Output | What's in it |
|---|---|
| `data/processed/metrics_long.csv` | 13 standard metrics × 10 companies × FY2021–26. Every value carries its XBRL concept, period, accession number and the mapping option used |
| `data/processed/derived.csv` | Margins, EBITDA, growth, net debt, ROE, ROIC, each with its formula and inputs |
| `data/processed/valuation.csv` | Market cap, EV, EV/EBITDA, EV/Sales, P/E on 16 Oct 2026 closes |
| `data/processed/restatements.csv` | Every period whose value changed between filings |
| `data/processed/metrics_wide.csv` | The readable table (USD m, %) |

## Design rules

1. Plain-Python orchestration, no agent framework.
2. LLMs never do arithmetic.
3. Every number is traceable to an XBRL fact or a dated price.
4. Measure, don't claim.

## Governance

[`docs/governance-memo.md`](docs/governance-memo.md) is a pre-launch AI risk assessment written the way a bank's second line would review it. It covers risk materiality (Impact, Complexity, Reliance), failure modes, measured evidence, controls, and a mapping to MAS FEAT and the MindForge AI Risk Management Handbook.

## Limitations (so far)

- **US filers only.** Coverage is limited to non-dimensional us-gaap facts, so anything tagged only by segment or product axis is invisible (e.g. TT's cost of sales).
- **Imperfect XBRL tagging.** 11% of values had to be rebuilt from components. Each rebuild is checked against the filing, but new companies need new checks.
- **Multiples on the latest fiscal year.** They use LFY, not LTM, so September year-ends (JCI, POWL) are a year staler.

# Case study: Verity

**An agentic equity analyst that checks its own numbers, and a measurement of how well it does.**

*Anoushka · CS + Business (NTU) · CFA Level II candidate · [GitHub](https://github.com/Anou-shka/Verity)*

---

## The problem

Language models can write a fluent research note in seconds, but fluency is not accuracy. One wrong year, a figure in the wrong unit, or a number with no source is enough to make a note unusable at a fund or a bank. Asking a model to "be careful" does not fix this. It needs a separate check that does not rely on the model's own judgment.

## What I built

Verity researches a company from its SEC filings, writes a comps table and a ~600-word note, and then a separate fact-checking agent verifies every number. It covers the US-listed peers of Delta Electronics in data-centre power and cooling, linking it to my [Delta Volts](https://github.com/Anou-shka/delta-volts) initiation.

- **Data layer.** It turns raw XBRL facts into clean annual metrics for 10 companies, including filers with no gross-profit or operating-income tag. It handles fiscal years that end in March, June and September, restatements after divestments, and a stock split. 25 values were checked by hand against the 10-Ks.
- **Tools, not memory.** Every value an agent sees comes from a tool and gets a source id. The model never does arithmetic: margins, growth, multiples and peer medians are computed in Python.
- **Three agents, plain Python.** A Researcher, a Writer and a Fact-checker are driven by a small state machine, with no agent framework. Every step, tool call, token and dollar goes into a trace.
- **The fact-checker.** It parses every number out of the note, so none can be skipped. It re-fetches each cited value with its own tools and checks the value, the unit, the fiscal year, and whether the words describe the cited metric. Quoted filing text is matched against the 10-K. Wrong numbers are corrected, and unsupported ones are deleted.

## What I measured

I planted 900 known errors of seven types in correct notes for all 10 companies and ran the fact-checker and revision loop on each.

| | |
|---|---|
| Errors caught | **98.2%** |
| Correct numbers wrongly flagged | **0%** of 7,117 |
| Errors left after revision | **2.7%** |

![Recall by error type](figures/recall_by_type.png)

**What the numbers say.**
- **Value errors are always caught.** Wrong numbers, wrong years, unit slips and invented figures were caught 100% of the time.
- **Meaning is the weak spot.** When a true number is cited correctly but described as something else ("data-centre revenue" quoting total revenue), the value check passes. Only a keyword check stands in the way, and it caught 87.7% of these.

## What went wrong, and what I changed

- **My error injector planted non-errors.** Perturbing a zero still gives zero, and 0.4x rounds back to 0.4x. These inflated the miss count until I made the injector reject changes that change nothing.
- **My first revision loop made fabrications worse.** An invented figure with a borrowed citation was "corrected" to the cited value, which turned a fake claim into a true-looking one. Now a wrong number whose sentence doesn't name the cited metric is deleted, not patched. The residual-error measure also counts a fabricated sentence that survives with a changed number.
- **Mapping XBRL is easy to get subtly wrong.** My first EBIT rebuild for Johnson Controls used a restructuring tag that turned out to be a note disclosure (427m), not the income-statement line (546m). Only reading the 10-K caught it, which is why the tests check figures read from filings, not figures read from XBRL.

## Governance

I wrote a [pre-launch AI governance memo](governance-memo.md) the way a bank's second line would assess the tool. It rates risk materiality on Impact, Complexity and Reliance and maps the controls to the MAS FEAT principles, MAS's AI Risk Management Guidelines (October 2026) and the MindForge AI Risk Management Handbook.

## Limits and next steps

- **Measured without an LLM.** The headline numbers come from a template writer and a rules checker, because the development environment had no API key. The LLM experiments are built and tested: extraction accuracy on 360 questions, and the agent against a no-tools baseline. They are the next run.
- **Meaning needs a semantic check.** Catching true-but-misdescribed numbers needs a check on meaning, not just values. That is the next thing to build and measure.
- **US filers only.** Covering Delta itself would need a different data source (TWSE/MOPS filings).

**Stack:** Python, SEC EDGAR XBRL API, yfinance, Anthropic API (Claude Opus 5.5 / Haiku 5.5), OpenAI and Ollama adapters, Streamlit, pytest, matplotlib.

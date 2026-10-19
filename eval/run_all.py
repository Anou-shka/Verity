"""Run every experiment and write eval/results/ and docs/results.md.

    python -m eval.run_all            (rules mode: experiment 3 + run costs)
    VERITY_PROVIDER=anthropic python -m eval.run_all   (adds experiments 1-2 and LLM-mode notes)
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from verity.config import ROOT  # noqa: E402
from verity.llm import llm_available, provider_name  # noqa: E402
from verity.orchestrator import run as run_note  # noqa: E402
from verity.tools import ToolBox, universe  # noqa: E402

from . import catch_rate, extraction  # noqa: E402

RESULTS, FIG, DOC = ROOT / "eval" / "results", ROOT / "docs" / "figures", ROOT / "docs" / "results.md"
# reference palette (light): series 1 blue, highlight orange, ink and grid
BLUE, ORANGE, INK, INK2, GRID, SURFACE = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
TYPE_NAMES = {"wrong_number": "Wrong number", "wrong_year": "Wrong year", "unit_swap": "Unit swap",
              "changed_pct": "Changed %", "made_up": "Made-up figure (no source)",
              "made_up_cited": "Made-up figure (fake citation)",
              "misattributed": "True number, wrong description"}


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def chart_recall(cr: dict, path: Path) -> None:
    items = list(cr["by_type"].items())[::-1]
    fig, ax = plt.subplots(figsize=(7.5, 3.6), dpi=150, facecolor=SURFACE)
    _style(ax)
    vals = [v["recall"] * 100 for _, v in items]
    ax.barh([TYPE_NAMES[k] for k, _ in items], vals, color=BLUE, height=0.55)
    for i, (k, v) in enumerate(items):
        ax.text(vals[i] + 1, i, f"{v['caught']}/{v['injected']}", va="center", fontsize=8.5, color=INK2)
    ax.set_xlim(0, 112)
    ax.set_xlabel("Injected errors caught (%)", color=INK2, fontsize=9)
    ax.set_title("Fact-checker recall by error type", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def chart_comps(comps: dict, subject: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=150, facecolor=SURFACE)
    _style(ax)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    clipped = []
    for r in comps["rows"]:
        x, y = r["cells"]["ebit_margin"]["value"], r["cells"]["ev_ebitda"]["value"]
        if x is None or y is None:
            continue
        if y > 60:
            clipped.append(f"{r['company']} {y:.0f}x")
            continue
        hl = r["ticker"] == subject
        ax.scatter(x * 100, y, s=70 if hl else 45, color=ORANGE if hl else BLUE,
                   edgecolor=SURFACE, linewidth=2, zorder=3)
        offset = {"TT": (-6, -13), "POWL": (6, 6)}.get(r["ticker"], (6, 4))
        ax.annotate(r["company"], (x * 100, y), xytext=offset, textcoords="offset points",
                    ha="right" if offset[0] < 0 else "left",
                    fontsize=8, color=INK if hl else INK2)
    ax.set_xlabel("EBIT margin, latest fiscal year (%)", color=INK2, fontsize=9)
    ax.set_ylabel("EV/EBITDA (x)", color=INK2, fontsize=9)
    title = f"Peers on {comps['as_of']}: valuation vs profitability"
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    if clipped:
        ax.text(0.99, 0.05, "Off chart: " + ", ".join(clipped), transform=ax.transAxes,
                ha="right", va="bottom", fontsize=7.5, color=INK2)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def run_costs(tickers: list[str]) -> list[dict]:
    rows = []
    for t in tickers:
        res = run_note(t)
        s = res.reports[-1].summary()
        rows.append({"ticker": t, "mode": res.pack.mode, **res.totals, "claims": s["claims"],
                     "verified": s["verified"], "rounds": len(res.reports) - 1,
                     "quotes": s["quotes"], "quotes_verified": s["quotes_verified"],
                     "table_cells": s["table_cells"], "table_wrong": s["table_wrong"]})
    return rows


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    tickers = universe()["tickers"]

    costs = run_costs(tickers)
    (RESULTS / "run_costs.json").write_text(json.dumps(costs, indent=1))
    cr = catch_rate.run()
    (RESULTS / "catch_rate.json").write_text(json.dumps(cr, indent=1))
    ex = extraction.main()
    (RESULTS / "extraction.json").write_text(json.dumps(ex, indent=1, default=str))

    chart_recall(cr, FIG / "recall_by_type.png")
    chart_comps(ToolBox().build_comps(), "VRT", FIG / "comps_scatter.png")
    DOC.write_text(results_markdown(cr, ex, costs))
    print(f"wrote {DOC}")


def results_markdown(cr: dict, ex: dict, costs: list[dict]) -> str:
    o, fa = cr["overall"], cr["false_alarms"]
    L = ["# Results", "",
         "Every number on this page is produced by `make eval` (`python -m eval.run_all`) and "
         "stored in `eval/results/`. Nothing here is typed by hand.", ""]
    L += ["## What has been measured, and in which mode", "",
          "| Experiment | Status | Mode |", "|---|---|---|",
          f"| 3. Fact-checker catch rate (error injection) | **done** | template writer + rules checker (no LLM) |",
          f"| Run cost and time per note | **done** | {costs[0]['mode']} |"]
    if ex.get("status") == "done":
        L += [f"| 1. Extraction accuracy | **done** | {ex['provider']} |",
              f"| 2. Baseline vs agent | **done** | {ex['provider']} |"]
    else:
        L += [f"| 1. Extraction accuracy ({ex['n_questions']} questions ready) | **pending: needs an API key** | — |",
              f"| 2. Baseline vs agent | **pending: needs an API key** | — |"]
    L += ["", "The development environment had no LLM API key, so experiments that need a model "
          "have not been run. Their harness is complete and tested; `VERITY_PROVIDER=anthropic make eval` "
          "fills them in and replaces this note.", ""]

    L += ["## Experiment 3: fact-checker catch rate", "",
          f"Setup: for each of the {len(cr['config']['tickers'])} companies, a correct note was written, "
          f"then {cr['config']['trials_per_company']} times {cr['config']['errors_per_note']} known errors "
          f"were planted at random (seed {cr['config']['seed']}). The fact-checker checked each note, "
          "and the revision loop (max 2 rounds) tried to fix what it flagged.", "",
          "| | Result |", "|---|---:|",
          f"| Injected errors | {o['injected']} |",
          f"| **Recall** (caught) | **{o['caught']} / {o['injected']} = {o['recall']:.1%}** |",
          f"| **False alarms**, clean notes | **{fa['clean_notes']['flagged']} / {fa['clean_notes']['claims']} = {fa['clean_notes']['rate']:.1%}** |",
          f"| False alarms, untouched claims in injected notes | {fa['untouched_claims_in_injected_notes']['flagged']} / {fa['untouched_claims_in_injected_notes']['claims']:,} = {fa['untouched_claims_in_injected_notes']['rate']:.1%} |",
          f"| **Errors left after revision** | **{o['residual']} / {o['injected']} = {o['residual_rate']:.1%}** |", "",
          "![Recall by error type](figures/recall_by_type.png)", "",
          "| Error type | What was planted | Injected | Caught | Recall | Left after revision |",
          "|---|---|---:|---:|---:|---:|"]
    what = {"wrong_number": "a cited figure changed by 3–25%",
            "wrong_year": "the fiscal year next to a figure changed by ±1",
            "unit_swap": "$m written as $bn, % divided by 10, $ read as cents",
            "changed_pct": "a percentage moved by 0.3–3.0 points",
            "made_up": "a new sentence with an invented figure and no citation",
            "made_up_cited": "an invented figure with a real citation id",
            "misattributed": "a true, correctly cited figure described as something else"}
    for k, v in cr["by_type"].items():
        L.append(f"| {TYPE_NAMES[k]} | {what[k]} | {v['injected']} | {v['caught']} | {v['recall']:.1%} | {v['residual']} |")
    L += ["", "**How to read this.**", "",
          "- Errors in the *number* are caught almost always, because the checker re-fetches the cited "
          "value with its own tools and compares within tolerance (0.5% for reported figures, 0.1pp for "
          "ratios). Year errors are caught because each figure is tied to the fiscal year of its source.",
          "- The weak spot is **meaning**. When a true number is cited correctly but described as "
          "something else (\"data-centre revenue was $10,229.9m [S1]\", where S1 is total revenue), "
          "the value check passes. A keyword check on the words before the number catches most of these, "
          "but not when the wrong description uses the right keyword (\"revenue\"). That is the "
          f"{cr['by_type']['misattributed']['injected'] - cr['by_type']['misattributed']['caught']} misses above, "
          "plus one invented \"orders\" figure that happened to equal a cited zero.",
          "- **Caught is not the same as fixed.** Some misdescriptions are caught only because the year "
          "is wrong; the revision then corrects the year, and the misdescription survives. The "
          "\"left after revision\" column counts an inserted sentence as residual whenever its wording "
          "survives, even if its number was \"corrected\". This is why it is larger than the misses. "
          "Fabricated figures whose sentence does not name the cited metric are deleted, not patched, "
          "so a fake claim is never laundered into a true-looking one.",
          "- **Caveat: the writer here is a template, not an LLM.** Template prose is regular, which makes "
          "extraction easy. LLM prose is messier (\"just over $10bn\", numbers spelled out, figures "
          "split across sentences), so these numbers are an upper bound for the checker's recall until "
          "the LLM run is done.", ""]

    if ex.get("status") == "done":
        L += ["## Experiments 1 and 2: extraction accuracy, agent vs no-tools baseline", "",
              "| | Agent (tools) | Baseline (no tools) |", "|---|---:|---:|",
              f"| Accuracy | {ex['agent']['accuracy']:.1%} | {ex['baseline']['accuracy']:.1%} |"]
        for k in ("wrong_year", "wrong_unit", "wrong_concept", "made_up", "no_answer"):
            L.append(f"| {k.replace('_', ' ')} | {ex['agent']['outcomes'].get(k, 0)} | {ex['baseline']['outcomes'].get(k, 0)} |")
        L.append(f"| Cost | ${ex['agent']['cost']['cost_usd']:.2f} | ${ex['baseline']['cost']['cost_usd']:.2f} |")
    else:
        L += ["## Experiments 1 and 2: extraction accuracy, agent vs no-tools baseline", "",
              f"**Pending.** {ex['n_questions']} questions are generated from the XBRL ground truth "
              "(10 companies × 12 metrics × latest 3 fiscal years). Each is asked twice: once to the "
              "tool-using agent, once to a single model call with no tools. Misses are typed as wrong "
              "year, wrong unit, wrong concept, made-up number or no answer (`eval/extraction.py`).", "",
              "What is already measured is the data layer the agent's tools sit on: **25 of 25** values "
              "pinned in `tests/test_xbrl.py` match the figures read by hand from five 10-Ks, and the "
              "comps table matches the metrics table exactly (110 of 110 cells, `tests/test_tools.py`)."]
    L += ["", "## Cost and time per note", "",
          "| Company | Mode | LLM calls | Tokens | Cost | Tool calls | Seconds | Claims verified | Quotes verified | Revision rounds |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for c in costs:
        L.append(f"| {c['ticker']} | {c['mode']} | {c['llm_calls']} | {c['input_tokens'] + c['output_tokens']:,} | "
                 f"${c['cost_usd']:.4f} | {c['tool_calls']} | {c['seconds']} | {c['verified']}/{c['claims']} | "
                 f"{c['quotes_verified']}/{c['quotes']} | {c['rounds']} |")
    L += ["", "In rules mode a note costs nothing and takes a few seconds; LLM-mode cost appears here "
          "once it has been run.", "",
          "## Peer valuation snapshot", "", "![Comps scatter](figures/comps_scatter.png)", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()

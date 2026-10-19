"""Experiment 3: how many planted errors does the fact-checker catch?

For each company: build a correct note, then for each trial plant 3 known
errors at random, run the fact-checker, run the revision loop (max 2 rounds)
and score:
  recall        caught injected errors / injected errors (by type)
  false alarms  correct claims flagged / correct claims
  residual      injected errors still in the final note after revision
"""
from __future__ import annotations

import json
import random
import re
from collections import defaultdict

from verity.agents import fact_checker as fc
from verity.agents.researcher import research
from verity.agents.writer import apply_fixes, template_note
from verity.tools import ToolBox, universe

from verity.inject import TYPES, affected, inject

TRIALS, PER_NOTE, SEED = 30, 3, 20261019


def run(tickers=None, trials=TRIALS, per_note=PER_NOTE, seed=SEED) -> dict:
    tickers = tickers or universe()["tickers"]
    rng = random.Random(seed)
    by_type = defaultdict(lambda: {"injected": 0, "caught": 0, "residual": 0})
    clean_claims = clean_flagged = 0
    other_claims = other_flagged = 0
    rows = []
    for t in tickers:
        box = ToolBox()
        pack = research(t, box, use_llm=False)
        note = template_note(pack)
        checker = fc.FactChecker(box.ledger)
        base = checker.check(note)
        clean_claims += len(base.claims)
        clean_flagged += sum(c.status != "verified" for c in base.claims)
        for trial in range(trials):
            bad, injs = inject(note, pack.fiscal_year, per_note, rng)
            report = checker.check(bad)
            touched = set()
            for inj in injs:
                hit = affected(inj, report.claims)
                touched |= {c.id for c in hit}
                caught = any(c.status != "verified" for c in hit)
                by_type[inj.type]["injected"] += 1
                by_type[inj.type]["caught"] += caught
                inj.caught = caught
            others = [c for c in report.claims if c.id not in touched]
            other_claims += len(others)
            other_flagged += sum(c.status != "verified" for c in others)

            # revision loop, as the orchestrator runs it
            final, rounds = bad, 0
            while rounds < 2 and any(c.status != "verified" for c in report.claims):
                final = apply_fixes(final, [c for c in report.claims if c.status != "verified"])
                report = checker.check(final)
                rounds += 1
            strip = lambda text: re.sub(r"[-$\d.,]+[%xmbn]*\s*(\[S\d+\])?", "", text)
            survivors = {}   # inserted wording -> how many copies are still in the final note
            for inj in sorted(injs, key=lambda i: i.caught):        # uncaught claim the copies first
                if inj.start == inj.end:
                    # inserted sentence: residual if its wording survived, even with
                    # a "corrected" number (that would be a laundered fabrication)
                    words = strip(inj.replacement).strip()[:40]
                    left = survivors.setdefault(words, strip(final).count(words))
                    residual = left > 0
                    survivors[words] = left - 1
                else:
                    window = bad[max(0, inj.new_start - 25): inj.new_end + 8]
                    residual = window in final
                by_type[inj.type]["residual"] += residual
                rows.append({"ticker": t, "trial": trial, "type": inj.type, "detail": inj.detail,
                             "replacement": inj.replacement.strip(), "caught": inj.caught,
                             "residual": residual, "rounds": rounds,
                             "final_unverified": sum(c.status != "verified" for c in report.claims)})
    tot_inj = sum(v["injected"] for v in by_type.values())
    tot_caught = sum(v["caught"] for v in by_type.values())
    tot_resid = sum(v["residual"] for v in by_type.values())
    return {
        "config": {"tickers": tickers, "trials_per_company": trials, "errors_per_note": per_note,
                   "seed": seed, "writer": "template", "checker": "rules (parser + tool re-fetch)"},
        "overall": {"injected": tot_inj, "caught": tot_caught, "recall": tot_caught / tot_inj,
                    "residual": tot_resid, "residual_rate": tot_resid / tot_inj},
        "by_type": {k: {**v, "recall": v["caught"] / v["injected"]} for k, v in
                    sorted(by_type.items(), key=lambda kv: TYPES.index(kv[0]))},
        "false_alarms": {"clean_notes": {"claims": clean_claims, "flagged": clean_flagged,
                                         "rate": clean_flagged / clean_claims},
                         "untouched_claims_in_injected_notes": {
                             "claims": other_claims, "flagged": other_flagged,
                             "rate": other_flagged / other_claims}},
        "rows": rows,
    }


if __name__ == "__main__":
    res = run()
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))

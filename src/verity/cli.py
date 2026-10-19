"""Command line: `verity run VRT`, `verity comps`, `verity metrics`."""
from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="verity")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="research, write and fact-check a note")
    r.add_argument("tickers", nargs="+")
    r.add_argument("--provider", help="rules | anthropic | openai | ollama (default: VERITY_PROVIDER)")
    r.add_argument("--replay", action="store_true", help="serve LLM calls only from the cache")
    sub.add_parser("comps", help="print the peer comps table")
    sub.add_parser("metrics", help="rebuild data/processed/ from the XBRL cache")
    args = p.parse_args(argv)

    if getattr(args, "provider", None):
        os.environ["VERITY_PROVIDER"] = args.provider
    if getattr(args, "replay", False):
        os.environ["VERITY_LLM_CACHE"] = "replay"

    if args.cmd == "metrics":
        from .build_metrics import main as build
        build()
    elif args.cmd == "comps":
        from .agents.researcher import ResearchPack
        from .agents.writer import comps_markdown
        from .tools import ToolBox
        box = ToolBox()
        comps = box.build_comps()
        print(comps_markdown(ResearchPack("", "", 0, box.ledger, comps=comps)))
    elif args.cmd == "run":
        from .orchestrator import OUTPUTS, run
        for t in args.tickers:
            res = run(t)
            s, tot = res.reports[-1].summary(), res.totals
            print(f"{res.ticker}: {s['claims']} claims, {s['verified']} verified, {s['wrong']} wrong, "
                  f"{s['unverifiable']} unverifiable after {len(res.reports) - 1} revision round(s); "
                  f"quotes {s['quotes_verified']}/{s['quotes']}; table {s['table_cells']} cells, "
                  f"{s['table_wrong']} mismatches")
            print(f"   {tot['llm_calls']} LLM calls, {tot['input_tokens'] + tot['output_tokens']:,} tokens, "
                  f"${tot['cost_usd']:.4f}, {tot['tool_calls']} tool calls, {tot['seconds']}s "
                  f"-> {OUTPUTS / res.ticker}")


if __name__ == "__main__":
    main()

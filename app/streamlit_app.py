"""Verity app: the note on the left, the fact-check log on the right.

    streamlit run app/streamlit_app.py

Reads outputs/<ticker>/ (committed), so it runs from a fresh clone with no
API key. "Re-run" regenerates a note in rules mode, or with a model if
VERITY_PROVIDER is set.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "outputs"

STATUS = {  # icon + label + colour: status is never shown by colour alone
    "verified": ("✓", "verified", "#1baf7a"),
    "corrected": ("↺", "corrected", "#2a78d6"),
    "wrong": ("✗", "wrong", "#e34948"),
    "unverifiable": ("?", "unverifiable", "#eda100"),
    "removed (unverifiable)": ("−", "removed", "#8a8985"),
    "removed (fabricated)": ("−", "removed", "#8a8985"),
}

st.set_page_config(page_title="Verity", page_icon="✓", layout="wide")


def load(ticker: str) -> tuple[str, dict, dict, pd.DataFrame]:
    d = OUT / ticker
    note = (d / "note.md").read_text()
    log = json.loads((d / "factcheck.json").read_text())
    pack = json.loads((d / "research_pack.json").read_text())
    comps = pd.read_csv(d / "comps.csv")
    return note, log, pack, comps


def highlight(note: str, claims: list[dict]) -> str:
    """Wrap each checked number in a coloured, labelled span (offsets come from the checker)."""
    body, _, tail = note.partition("\n## Peer comparison")
    spans = sorted((c for c in claims if not c["final_status"].startswith("removed")),
                   key=lambda c: -c["start"])
    for c in spans:
        icon, label, colour = STATUS[c["final_status"]]
        tip = html.escape(f"{label}: {c.get('source') or c.get('reason') or ''}")
        val = html.escape(body[c["start"]:c["end"]])
        body = (body[:c["start"]] +
                f'<span title="{tip}" style="border-bottom:2px solid {colour};padding:0 1px">'
                f'{val}<sup style="color:{colour}">{icon}</sup></span>' + body[c["end"]:])
    return body.replace("$", "&#36;")      # Streamlit would read $...$ as LaTeX


tickers = sorted(p.name for p in OUT.iterdir() if (p / "factcheck.json").exists()) if OUT.exists() else []
st.sidebar.title("Verity")
st.sidebar.caption("An agentic equity analyst with a fact-checker")
if not tickers:
    st.warning("No outputs yet. Run `verity run VRT` first.")
    st.stop()
ticker = st.sidebar.selectbox("Company", tickers, index=tickers.index("VRT") if "VRT" in tickers else 0)

if st.sidebar.button("Re-run this note"):
    from verity.orchestrator import run
    with st.spinner("Researching, writing, fact-checking…"):
        run(ticker)
    st.rerun()

note, log, pack, comps = load(ticker)
claims = log["claims"]
counts = pd.Series([c["final_status"] for c in claims]).value_counts()
t = log["totals"]

st.sidebar.markdown("---")
st.sidebar.markdown(f"**Mode:** {log['mode']}")
st.sidebar.markdown(f"**LLM calls:** {t['llm_calls']} ({t['llm_cache_hits']} cached)")
st.sidebar.markdown(f"**Tokens:** {t['input_tokens'] + t['output_tokens']:,}")
st.sidebar.markdown(f"**Cost:** ${t['cost_usd']:.4f}")
st.sidebar.markdown(f"**Tool calls:** {t['tool_calls']} · **Time:** {t['seconds']}s")

cols = st.columns(5)
groups = {"verified": ["verified"], "corrected": ["corrected"], "unverifiable": ["unverifiable"],
          "wrong": ["wrong"], "removed (unverifiable)": ["removed (unverifiable)", "removed (fabricated)"]}
for col, (key, members) in zip(cols, groups.items()):
    icon, label, _ = STATUS[key]
    col.metric(f"{icon} {label}", int(sum(counts.get(m, 0) for m in members)))

tab_note, tab_comps, tab_trace = st.tabs(["Note and fact-check", "Comps", "Run trace"])
with tab_note:
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown(highlight(note, claims), unsafe_allow_html=True)
        st.caption("Each number is underlined by its fact-check status; hover for its source.")
    with right:
        st.subheader("Fact-check log")
        rows = [{"Claim": c["value_text"], "Status": f"{STATUS[c['final_status']][0]} {STATUS[c['final_status']][1]}",
                 "Source": c.get("source") or c.get("ref") or "—", "Note": c.get("reason") or ""}
                for c in claims]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=520)
        st.markdown("**Quotes from the 10-K**")
        for q in log["quotes"]:
            icon = "✓" if q["status"] == "verified" else "✗"
            st.markdown(f"{icon} {q['status']}: “{q['quote'][:140]}…” ({q.get('accession', '')})")
        tb = log["table"]
        st.markdown(f"**Comps table:** {tb.get('cells', 0)} cells re-fetched, {tb.get('wrong', 0)} mismatches.")
        rounds = pd.DataFrame(log["rounds"])[["round", "claims", "verified", "wrong", "unverifiable"]]
        st.markdown("**Rounds**")
        st.dataframe(rounds, hide_index=True, use_container_width=True)

with tab_comps:
    st.subheader(f"Peers on {pack['comps']['as_of']}, latest fiscal year")
    show = comps.copy()
    for c in ["revenue", "net_debt", "market_cap", "ev"]:
        show[c] = show[c] / 1e6
    for c in ["revenue_growth", "gross_margin", "ebit_margin", "roic"]:
        show[c] = show[c] * 100
    st.dataframe(show.round(1), hide_index=True, use_container_width=True)
    st.caption("USD millions; margins, growth and ROIC in %. Every cell has a source id in research_pack.json.")
    fig = ROOT / "docs" / "figures" / "comps_scatter.png"
    if fig.exists():
        st.image(str(fig))

with tab_trace:
    traces = sorted((ROOT / "traces").glob(f"{ticker}-*.jsonl"))
    if traces:
        events = [json.loads(line) for line in traces[-1].read_text().splitlines()]
        st.caption(f"{traces[-1].name}: {len(events)} events")
        st.dataframe(pd.DataFrame(events).drop(columns=["run_id"], errors="ignore"),
                     hide_index=True, use_container_width=True, height=600)
    else:
        st.info("No trace for this company yet.")

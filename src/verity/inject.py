"""Error injection: plant known mistakes in a correct note.

Each injection records exactly what was changed and where, so the
fact-checker's verdict can be scored against ground truth.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

from .agents.fact_checker import Claim, extract_claims

TYPES = ["wrong_number", "wrong_year", "unit_swap", "changed_pct", "made_up", "made_up_cited",
         "misattributed"]


@dataclass
class Injection:
    type: str
    start: int            # offset of the changed text in the ORIGINAL note
    end: int
    replacement: str
    detail: str
    new_start: int = 0    # offset in the injected note (filled in by inject())
    new_end: int = 0


def _fmt_like(c: Claim, value: float) -> str:
    """Write a value in the same style as the claim it replaces."""
    if c.kind == "money":
        suffix = "bn" if c.value_text.endswith("bn") else "m"
        scale = 1e9 if suffix == "bn" else 1e6
        sign = "-" if value < 0 else ""
        return f"{sign}${abs(value) / scale:,.1f}{suffix}"
    if c.kind == "pct":
        return f"{value * 100:.1f}%"
    if c.kind == "multiple":
        return f"{value:.1f}x"
    if c.kind == "per_share":
        return f"${value:,.2f}"
    return f"{value:,.1f}"


def _perturb(rng, lo=0.03, hi=0.25):
    f = rng.uniform(lo, hi)
    return 1 + f if rng.random() < 0.5 else 1 - f


def make(rng: random.Random, kind: str, note: str, claims: list[Claim], used: set,
         fy: int) -> Injection | None:
    free = [c for c in claims if c.start not in used and c.ref]
    if kind == "wrong_number":
        pool = [c for c in free if c.kind in ("money", "per_share", "multiple")]
        if not pool:
            return None
        c = rng.choice(pool)
        return Injection(kind, c.start, c.end, _fmt_like(c, c.value * _perturb(rng)), c.value_text)
    if kind == "changed_pct":
        pool = [c for c in free if c.kind == "pct"]
        if not pool:
            return None
        c = rng.choice(pool)
        delta = rng.uniform(0.003, 0.03) * rng.choice([-1, 1])
        return Injection(kind, c.start, c.end, _fmt_like(c, c.value + delta), c.value_text)
    if kind == "unit_swap":
        pool = [c for c in free if c.kind in ("money", "pct", "per_share")]
        if not pool:
            return None
        c = rng.choice(pool)
        if c.kind == "money":
            new = c.value_text.replace("m", "bn") if c.value_text.endswith("m") else c.value_text.replace("bn", "m")
        elif c.kind == "pct":
            new = _fmt_like(c, c.value / 10)          # 36.3% -> 3.6%
        else:
            new = f"${c.value * 100:,.2f}"            # dollars read as cents
        return Injection(kind, c.start, c.end, new, c.value_text)
    if kind == "wrong_year":
        pool = [c for c in free if c.year_span and c.year_span[0] not in used]
        if not pool:
            return None
        c = rng.choice(pool)
        s, e = c.year_span
        return Injection(kind, s, e, f"FY{c.year + rng.choice([-1, 1])}", f"FY{c.year}")
    # The rest insert a new sentence at the end of a paragraph.
    paras = [m.start() for m in re.finditer(r"\n\n## ", note)]
    if not paras:
        return None
    at = rng.choice(paras)
    if kind == "made_up":
        sentence = rng.choice([
            f" Order backlog reached ${rng.uniform(2, 30):,.1f}bn at the end of FY{fy}.",
            f" Data-centre end markets were {rng.uniform(20, 70):.1f}% of FY{fy} sales.",
            f" Management targets an adjusted EBITDA margin of {rng.uniform(15, 30):.1f}% by FY{fy + 2}.",
            f" Book-to-bill was {rng.uniform(1.0, 1.6):.2f}x in FY{fy}."])
    elif kind == "made_up_cited":
        c = rng.choice(free) if free else None
        if c is None:
            return None
        fake = _fmt_like(c, c.value * _perturb(rng, 0.1, 0.6))
        sentence = f" Organic orders in FY{fy} were {fake} [{c.ref}]."
    else:  # misattributed: a true, correctly cited number attached to the wrong claim
        pool = [c for c in free if c.kind in ("money", "pct")]
        if not pool:
            return None
        c = rng.choice(pool)
        what = "data-centre revenue" if c.kind == "money" else "the data-centre share of revenue"
        sentence = f" In FY{fy}, {what} was {c.value_text} [{c.ref}]."
    return Injection(kind, at, at, sentence, "inserted")


def _is_noop(inj: Injection, claims: list[Claim]) -> bool:
    """An 'error' that changes nothing (0 perturbed is still 0; 0.4x rounds back
    to 0.4x) is not an error, so it is not planted."""
    if inj.type in ("wrong_number", "changed_pct", "unit_swap"):
        c = next(c for c in claims if c.start == inj.start)
        new = extract_claims(inj.replacement)
        return not new or new[0].value == c.value
    return False


def inject(note: str, fy: int, n: int, rng: random.Random,
           types: list[str] | None = None) -> tuple[str, list[Injection]]:
    claims = extract_claims(note)
    used: set = set()
    out: list[Injection] = []
    for _ in range(n * 5):
        if len(out) == n:
            break
        kind = rng.choice(types or TYPES)
        inj = make(rng, kind, note, claims, used, fy)
        if inj is None or any(o.start == inj.start for o in out) or _is_noop(inj, claims):
            continue
        used.add(inj.start)
        out.append(inj)
    # apply from the end so earlier offsets stay valid, then map offsets
    new = note
    for inj in sorted(out, key=lambda i: -i.start):
        new = new[:inj.start] + inj.replacement + new[inj.end:]
    for inj in out:
        shift = sum(len(o.replacement) - (o.end - o.start) for o in out if o.start < inj.start)
        inj.new_start = inj.start + shift
        inj.new_end = inj.new_start + len(inj.replacement)
    return new, out


def affected(inj: Injection, claims: list[Claim]) -> list[Claim]:
    """Claims in the injected note that the injection touched."""
    if inj.type == "wrong_year":
        return [c for c in claims if c.year_span and c.year_span[0] == inj.new_start]
    return [c for c in claims if inj.new_start <= c.start < inj.new_end]

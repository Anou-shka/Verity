"""One place that turns numbers into the strings a note prints.

The Writer copies these strings verbatim, and the fact-checker parses them
back, so the format is part of the contract between the two.
"""
from __future__ import annotations

UNIT_KIND = {"USD": "money", "ratio": "pct", "x": "multiple",
             "USD/shares": "per_share", "shares": "count"}


def display(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "USD":
        sign = "-" if value < 0 else ""
        return f"{sign}${abs(value) / 1e6:,.1f}m"
    if unit == "ratio":
        return f"{value * 100:.1f}%"
    if unit == "x":
        return f"{value:.1f}x"
    if unit == "USD/shares":
        sign = "-" if value < 0 else ""
        return f"{sign}${abs(value):,.2f}"
    if unit == "shares":
        return f"{value / 1e6:,.1f}m shares"
    return f"{value:,.2f}"


def display_precision(unit: str) -> float:
    """Half of the last printed digit, in base units: the rounding a display adds."""
    return {"USD": 0.05e6, "ratio": 0.0005, "x": 0.05, "USD/shares": 0.005,
            "shares": 0.05e6}.get(unit, 0.0)

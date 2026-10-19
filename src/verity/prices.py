"""Daily close prices from Yahoo Finance (yfinance), cached on disk.

Closes are split-adjusted but not dividend-adjusted (auto_adjust=False), which
is what a market cap needs. Every price is returned with the date it is for.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .config import CACHE_DIR

PRICE_DIR = CACHE_DIR / "prices"
HISTORY_START = "2020-01-01"


@dataclass(frozen=True)
class Price:
    ticker: str
    close: float
    date: date
    source: str = "Yahoo Finance via yfinance (Close, auto_adjust=False)"


def _history(ticker: str, need: date) -> pd.Series:
    path = PRICE_DIR / f"{ticker.upper()}.csv"
    if path.exists():
        s = pd.read_csv(path, index_col=0, parse_dates=True)["close"]
        if s.index.max().date() >= need or os.getenv("VERITY_OFFLINE") == "1":
            return s
    import yfinance as yf  # imported lazily: not needed when cached

    df = yf.download(ticker, start=HISTORY_START, end=str(need + timedelta(days=1)),
                     auto_adjust=False, progress=False, multi_level_index=False)
    if df.empty:
        raise RuntimeError(f"no price data for {ticker}")
    s = df["Close"].rename("close").dropna()
    s.index.name = "date"
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    s.round(4).to_csv(path)
    return s


def get_price(ticker: str, on: date | str) -> Price:
    """Close on `on`, or on the last trading day before it."""
    on = date.fromisoformat(on) if isinstance(on, str) else on
    s = _history(ticker, on)
    s = s[s.index.date <= on]
    if s.empty:
        raise ValueError(f"no {ticker} price on or before {on}")
    return Price(ticker.upper(), float(s.iloc[-1]), s.index[-1].date())

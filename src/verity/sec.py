"""EDGAR client: polite (User-Agent, <10 req/s) and cached on disk.

Every response is stored gzipped under data/cache/ keyed by its URL path,
so a file is downloaded once and the repo can run offline afterwards.
"""
from __future__ import annotations

import gzip
import json
import os
import time
from pathlib import Path

import requests

from .config import CACHE_DIR

MIN_INTERVAL = 0.15  # seconds between requests -> at most ~6.7 req/s


class SecClient:
    def __init__(self, cache_dir: Path = CACHE_DIR, offline: bool | None = None):
        self.cache_dir = cache_dir
        self.offline = offline if offline is not None else os.getenv("VERITY_OFFLINE") == "1"
        self._last = 0.0
        self._session: requests.Session | None = None

    # -- low level -------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        path = url.split("://", 1)[1].replace("/", "__")
        return self.cache_dir / f"{path}.gz"

    def _user_agent(self) -> str:
        ua = os.getenv("SEC_USER_AGENT")
        if not ua:
            raise RuntimeError(
                "SEC_USER_AGENT is not set. Copy .env.example to .env and add "
                "'Your Name your.email@example.com' (SEC requires it)."
            )
        return ua

    def get_bytes(self, url: str) -> bytes:
        cached = self._cache_path(url)
        if cached.exists():
            return gzip.decompress(cached.read_bytes())
        if self.offline:
            raise FileNotFoundError(f"offline mode and not cached: {url}")
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": self._user_agent(),
                                          "Accept-Encoding": "gzip, deflate"})
        wait = MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        resp = self._session.get(url, timeout=60)
        self._last = time.monotonic()
        resp.raise_for_status()
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(gzip.compress(resp.content, compresslevel=9))
        return resp.content

    def get_json(self, url: str) -> dict:
        return json.loads(self.get_bytes(url))

    # -- endpoints -------------------------------------------------------
    def ticker_map(self) -> dict[str, int]:
        data = self.get_json("https://www.sec.gov/files/company_tickers.json")
        return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}

    def cik(self, ticker: str) -> str:
        """Ticker -> 10-digit zero-padded CIK."""
        return f"{self.ticker_map()[ticker.upper()]:010d}"

    def company_facts(self, ticker: str) -> dict:
        return self.get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{self.cik(ticker)}.json")

    def submissions(self, ticker: str) -> dict:
        return self.get_json(f"https://data.sec.gov/submissions/CIK{self.cik(ticker)}.json")

    def filing_index(self, ticker: str, forms: tuple[str, ...] = ("10-K",)) -> list[dict]:
        """Recent filings of the given forms, newest first, with document URLs."""
        sub = self.submissions(ticker)
        recent, cik = sub["filings"]["recent"], int(sub["cik"])
        out = []
        for i, form in enumerate(recent["form"]):
            if form not in forms:
                continue
            accn = recent["accessionNumber"][i]
            doc = recent["primaryDocument"][i]
            out.append({
                "form": form, "accession": accn, "filed": recent["filingDate"][i],
                "report_date": recent["reportDate"][i],
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{doc}",
            })
        return out

    def filing_text(self, url: str) -> str:
        """Primary filing document as plain text (HTML tags stripped)."""
        import html
        import re
        raw = self.get_bytes(url).decode("utf-8", errors="replace")
        raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
        raw = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", raw)
        text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
        text = re.sub(r"[ \t\xa0]+", " ", text)
        return re.sub(r"\n\s*\n+", "\n", text)

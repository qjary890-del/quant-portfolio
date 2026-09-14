"""Price data download and caching."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


def download_prices(
    tickers: list[str],
    start: str,
    end: str | None = None,
    *,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Download adjusted close prices; returns columns=tickers, index=dates."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    end_key = end or "latest"
    cache_path = CACHE_DIR / f"prices_{start}_{end_key}_{len(tickers)}.csv"

    if use_cache and cache_path.exists():
        cached = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        missing = [t for t in tickers if t not in cached.columns]
        if not missing:
            return cached[tickers].dropna(how="all")

    data = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if data.empty:
        raise RuntimeError("No price data downloaded. Check tickers / network.")

    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"].copy()
    else:
        prices = data[["Close"]].copy()
        prices.columns = tickers[:1]

    prices = prices.sort_index().ffill(limit=5)
    if use_cache:
        prices.to_csv(cache_path)
    return prices[tickers].dropna(how="all")

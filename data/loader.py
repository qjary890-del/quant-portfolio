"""Price data download and caching (Tiingo only — clean EOD)."""

from __future__ import annotations

import pandas as pd

from data.providers import _tiingo_token, load_price_frame, normalize_ticker


def download_prices(
    tickers: list[str],
    start: str,
    end: str | None = None,
    *,
    provider: str | None = "tiingo",
    use_cache: bool = True,
) -> pd.DataFrame:
    """Download Tiingo adjusted closes. Requires TIINGO_API_KEY."""
    if not _tiingo_token():
        raise RuntimeError(
            "Clean price data requires Tiingo.\n"
            "1) Sign up free: https://www.tiingo.com/account/api/token\n"
            "2) Create project/.env with: TIINGO_API_KEY=your_token\n"
            "Yahoo/Stooq are intentionally not used (noisy / blocked)."
        )
    print("Price provider: tiingo")
    prices = load_price_frame(
        tickers,
        start,
        end,
        provider="tiingo",
        use_cache=use_cache,
    )
    prices.columns = [normalize_ticker(c) for c in prices.columns]
    return prices.dropna(how="all")

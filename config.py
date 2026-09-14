"""Backtest and strategy defaults."""

from __future__ import annotations

# Liquid US large-cap universe for mean-reversion research
UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM",
    "V", "MA", "UNH", "XOM", "JNJ", "WMT", "PG", "HD", "BAC", "COST",
    "PFE", "CSCO", "ABBV", "CVX", "MRK", "PEP", "KO", "AVGO", "TMO",
    "MCD", "ABT", "CRM", "ACN", "LIN", "DHR", "TXN", "NEE", "PM",
    "UPS", "MS", "RTX", "LOW", "QCOM", "INTU", "IBM", "AMD", "GS",
    "CAT", "AMAT", "SPGI", "ISRG", "BKNG", "CVS",
]

# Pre-selected sector-similar pairs for statistical arb
PAIRS = [
    ("XOM", "CVX"),
    ("JPM", "BAC"),
    ("V", "MA"),
    ("KO", "PEP"),
    ("MSFT", "GOOGL"),
    ("HD", "LOW"),
    ("UNH", "CVS"),
    ("AAPL", "MSFT"),
]

START = "2018-01-01"
END = None  # None = today

# Cross-sectional mean reversion
CS_LOOKBACK = 5          # days of return used for ranking
CS_HOLDING = 5           # rebalance every N days
CS_LONG_PCT = 0.2        # long bottom 20% (losers)
CS_SHORT_PCT = 0.2       # short top 20% (winners)
CS_WEIGHT = 0.5          # portfolio weight vs stat-arb sleeve

# Statistical arbitrage (pairs)
STATARB_LOOKBACK = 60    # rolling window for hedge ratio / z-score
STATARB_ENTRY_Z = 2.0
STATARB_EXIT_Z = 0.5
STATARB_STOP_Z = 4.0
STATARB_WEIGHT = 0.5

# Backtest economics
INITIAL_CAPITAL = 100_000.0
COMMISSION_BPS = 5.0     # 5 bps per side
SLIPPAGE_BPS = 5.0
ANNUALIZATION = 252

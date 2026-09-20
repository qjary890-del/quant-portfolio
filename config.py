"""Backtest and strategy defaults."""

from __future__ import annotations

# --- Data / universe ---
START = "2018-01-01"
END = None  # None = today
USE_PIT_UNIVERSE = True
PIT_INDEX = "sp500"
# asof_start: download S&P members as of START
# union: all members that ever appeared in [START, END] (paid Tiingo recommended)
PIT_PRICE_UNIVERSE = "asof_start"
# Tiingo free starter ~50 req/hour — keep priced universe small for one-shot runs
PIT_MAX_PRICED_NAMES = 50
PRICE_PROVIDER = "tiingo"

# Fallback static list (only used when USE_PIT_UNIVERSE=False)
UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM",
    "V", "MA", "UNH", "XOM", "JNJ", "WMT", "PG", "HD", "BAC", "COST",
    "PFE", "CSCO", "ABBV", "CVX", "MRK", "PEP", "KO", "AVGO", "TMO",
    "MCD", "ABT", "CRM", "ACN", "LIN", "DHR", "TXN", "NEE", "PM",
    "UPS", "MS", "RTX", "LOW", "QCOM", "INTU", "IBM", "AMD", "GS",
    "CAT", "AMAT", "SPGI", "ISRG", "BKNG", "CVS",
]

# Fallback pairs / sectors when PIT GICS groups unavailable
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

SECTOR_GROUPS = {
    "Energy": ["XOM", "CVX"],
    "Banks": ["JPM", "BAC", "MS", "GS"],
    "Payments": ["V", "MA"],
    "Beverages": ["KO", "PEP"],
    "BigTech": ["AAPL", "MSFT", "GOOGL", "META", "AMZN"],
    "Retail": ["HD", "LOW", "WMT", "COST"],
    "Healthcare": ["UNH", "CVS", "JNJ", "PFE", "ABBV", "MRK", "ABT", "TMO", "ISRG", "DHR"],
    "Semi": ["NVDA", "AMD", "AVGO", "TXN", "QCOM", "AMAT"],
    "Software": ["CRM", "INTU", "IBM", "ACN", "CSCO"],
    "Industrial": ["CAT", "UPS", "RTX", "LIN"],
    "Consumer": ["MCD", "PG", "PM", "TSLA", "BKNG"],
}

# Cross-sectional mean reversion
CS_LOOKBACK = 5
CS_HOLDING = 5
CS_LONG_PCT = 0.2
CS_SHORT_PCT = 0.2
CS_WEIGHT = 0.5

# Statistical arbitrage (pairs)
STATARB_LOOKBACK = 60
STATARB_ENTRY_Z = 2.0
STATARB_EXIT_Z = 0.5
STATARB_STOP_Z = 4.0
STATARB_WEIGHT = 0.5

# Cointegration screener
USE_AUTO_PAIRS = True
COINT_FORMATION_DAYS = 504
COINT_PVALUE_MAX = 0.05
COINT_MIN_HALFLIFE = 5.0
COINT_MAX_HALFLIFE = 60.0
COINT_TARGET_HALFLIFE = 15.0
COINT_MIN_CORR = 0.55
COINT_STABILITY_WINDOW = 126
COINT_STABILITY_STEP = 63
COINT_MIN_STABILITY = 0.0
COINT_MAX_PAIRS = 12
COINT_MAX_NAMES_PER_SECTOR = 12  # cap combinatorial explosion on full S&P GICS

# Backtest economics
INITIAL_CAPITAL = 100_000.0
COMMISSION_BPS = 5.0
SLIPPAGE_BPS = 10.0
BORROW_FEE_ANNUAL = 0.015
ANNUALIZATION = 252

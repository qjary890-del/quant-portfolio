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

# Cross-sectional mean reversion (conservative: slower rebalance)
CS_LOOKBACK = 10
CS_HOLDING = 20         # was 5 — weak edge => trade less
CS_LONG_PCT = 0.2
CS_SHORT_PCT = 0.2
CS_WEIGHT = 0.5
CS_SECTOR_NEUTRAL = True

# Statistical arbitrage (pairs) — slightly stricter entry = fewer trades
STATARB_LOOKBACK = 60
STATARB_ENTRY_Z = 2.5   # was 2.0
STATARB_EXIT_Z = 0.5
STATARB_STOP_Z = 4.0
STATARB_HL_TIMEOUT_MULT = 2.0  # exit if not mean-reverted within 2 * half-life days
STATARB_WEIGHT = 0.5

# Hybrid: agreement scale; expand book gross only when sleeves agree
USE_HYBRID_ALLOCATION = True
USE_DYNAMIC_SLEEVE_MIX = False
AGREE_MULT = 1.5
SOLO_MULT = 0.5
CONFLICT_MULT = 0.25
AGREE_BOOK_GROSS_MAX = 1.25  # scale portfolio up to 1.25x by agree fraction
SLEEVE_SCORE_LOOKBACK = 60
SLEEVE_MIX_FLOOR = 0.20
SLEEVE_MIX_CEIL = 0.80
SLEEVE_LOOKBACK_GRID = [21, 42, 60, 63, 90, 126]

# Regime risk: cut gross when universe realized vol is high (gradual)
USE_REGIME_OVERLAY = True
REGIME_VOL_LOOKBACK = 21
REGIME_VOL_TARGET = 0.15
REGIME_GROSS_FLOOR = 0.30
REGIME_GROSS_CEIL = 1.00

# Macro shock circuit breaker on Stat Arb (hard flatten, then cooldown)
# Complements pair-level |z| stop — book-level exit when the market breaks.
USE_SHOCK_BREAKER = True
SHOCK_SHORT_VOL_LB = 5
SHOCK_LONG_VOL_LB = 63
SHOCK_VOL_SPIKE_RATIO = 1.5   # short/long vol
SHOCK_CRASH_DAYS = 5
SHOCK_CRASH_RET = -0.05       # EW basket 5d return
SHOCK_DAY1_CRASH = -0.035     # EW basket 1d return
SHOCK_COOLDOWN_DAYS = 10
SHOCK_FLOOR = 0.0             # 0 = full flatten during shock

# Book trailing stop: flatten Stat Arb when its own DD from peak breaches
USE_BOOK_DD_STOP = True
BOOK_DD_MAX = -0.12           # -12% from book high-water mark
BOOK_DD_COOLDOWN = 15
BOOK_DD_FLOOR = 0.0

# Cointegration screener — more pairs, diversified by sector + rolling refresh
USE_AUTO_PAIRS = True
USE_ROLLING_PAIRS = True
COINT_FORMATION_DAYS = 504
COINT_REFRESH_DAYS = 126   # re-screen every ~6 months (macro-aware pair set)
COINT_PVALUE_MAX = 0.05
COINT_MIN_HALFLIFE = 5.0
COINT_MAX_HALFLIFE = 60.0
COINT_TARGET_HALFLIFE = 15.0
COINT_MIN_CORR = 0.50
COINT_STABILITY_WINDOW = 126
COINT_STABILITY_STEP = 63
COINT_MIN_STABILITY = 0.0
COINT_MAX_PAIRS = 24
COINT_MAX_PER_SECTOR = 3
COINT_MAX_NAMES_PER_SECTOR = 15

# Backtest economics
INITIAL_CAPITAL = 100_000.0
COMMISSION_BPS = 5.0
SLIPPAGE_BPS = 10.0
BORROW_FEE_ANNUAL = 0.015
ANNUALIZATION = 252

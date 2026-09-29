"""
Staged CAGR search for the default book (Stat Arb + guards), rolling OOS.

Pick rule per stage: among variants with Max DD >= MDD_FLOOR and worst year >=
WORST_YEAR_FLOOR, take those within CAGR_TIE_BAND of the best CAGR and keep the
one whose weaker half (min of first/second-half CAGR) is highest.
Every variant is scored from the same evaluation start (first trade day of the
default formation window) and also split into first/second-half CAGR.

  Z  entry / exit / stop z                     (fixed pair schedule)
  P  pair count x per-sector cap               (post-filtered rich pool)
  A  half-life time stop multiple              (fixed pair schedule)
  B  book drawdown stop depth x cooldown       (fixed pair schedule)
  C  shock breaker / regime overlay on or off  (fixed pair schedule)
  D  formation / refresh length                (re-screens pairs)
  E  pair-candidate grouping                   (re-screens pairs)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from backtest.engine import run_backtest
from data.providers import normalize_ticker
from data.universe_pit import membership_matrix, sector_groups_asof
from run_pair_cap_sweep import _ensure_pool, _load_prices
from strategies.pair_screener import filter_pair_log
from strategies.regime import (
    apply_gross_scaler,
    book_drawdown_scaler,
    macro_shock_scaler,
    realized_vol,
    regime_gross_scaler,
)
from strategies.rolling_pairs import build_rolling_stat_arb_weights, weights_from_pair_log
from strategies.universe_structure import make_primary_grouping_fn

MDD_FLOOR = -0.20
WORST_YEAR_FLOOR = -0.15
CAGR_TIE_BAND = 0.005  # within this of the best CAGR, prefer the stronger weaker half

ENTRY_GRID = [2.0, 2.5, 3.0]
EXIT_GRID = [0.0, 0.25, 0.5]
STOP_GRID = [3.5, 4.0, 5.0]
PAIRS_GRID = [4, 6, 8, 12, 16]
SECTOR_CAP_GRID = [1, 2, 3, 4]
TIMEOUT_GRID = [0.0, 1.0, 1.5, 2.0, 3.0]  # 0 = no time stop
BOOK_DD_GRID = [-0.08, -0.10, -0.12, -0.15, -0.20]
BOOK_DD_COOLDOWN_GRID = [10, 15, 30, 60]
WINDOW_GRID = [(504, 126), (504, 63), (378, 63), (252, 63), (504, 252)]
GROUPING_GRID = [
    (None, None),
    ("corr_cluster", 0.5),
    ("corr_cluster", 0.6),
    ("sector_corr_cluster", 0.5),
]


def perf(returns: pd.Series, start: pd.Timestamp, ann: int, end: pd.Timestamp | None = None) -> dict:
    r = returns.loc[returns.index >= start]
    if end is not None:
        r = r.loc[r.index <= end]
    r = r.fillna(0.0)
    eq = (1.0 + r).cumprod()
    years = max(len(r) / ann, 1e-9)
    sd = float(r.std(ddof=0))
    yearly = (1.0 + r).groupby(r.index.year).prod() - 1.0
    half = len(r) // 2

    def _cagr(x: pd.Series) -> float:
        return float((1.0 + x).prod() ** (ann / max(len(x), 1)) - 1.0)

    return {
        "cagr": float(eq.iloc[-1] ** (1.0 / years) - 1.0),
        "sharpe": float(r.mean() / sd * np.sqrt(ann)) if sd > 0 else 0.0,
        "max_dd": float((eq / eq.cummax() - 1.0).min()),
        "worst_year": float(yearly.min()),
        "cagr_h1": _cagr(r.iloc[:half]),
        "cagr_h2": _cagr(r.iloc[half:]),
        "flat_share": float((r == 0.0).mean()),
    }


def pick(table: pd.DataFrame) -> pd.Series:
    ok = table[(table["max_dd"] >= MDD_FLOOR) & (table["worst_year"] >= WORST_YEAR_FLOOR)]
    pool = ok if not ok.empty else table
    near = pool[pool["cagr"] >= pool["cagr"].max() - CAGR_TIE_BAND]
    weaker_half = near[["cagr_h1", "cagr_h2"]].min(axis=1)
    return near.loc[weaker_half.sort_values(ascending=False, kind="stable").index[0]]


class Book:
    def __init__(self, prices, membership):
        self.prices = prices
        self.membership = membership
        self.cache: dict = {}
        self.fallback = [(normalize_ticker(a), normalize_ticker(b)) for a, b in config.PAIRS]
        self.eval_start = prices.index[config.COINT_FORMATION_DAYS]
        self.eval_end: pd.Timestamp | None = None
        self.shock = macro_shock_scaler(
            prices,
            short_vol_lb=config.SHOCK_SHORT_VOL_LB,
            long_vol_lb=config.SHOCK_LONG_VOL_LB,
            vol_spike_ratio=config.SHOCK_VOL_SPIKE_RATIO,
            crash_days=config.SHOCK_CRASH_DAYS,
            crash_ret=config.SHOCK_CRASH_RET,
            day1_crash=config.SHOCK_DAY1_CRASH,
            cooldown_days=config.SHOCK_COOLDOWN_DAYS,
            shock_floor=config.SHOCK_FLOOR,
            ann=config.ANNUALIZATION,
        )
        self.regime = regime_gross_scaler(
            realized_vol(prices, lookback=config.REGIME_VOL_LOOKBACK, ann=config.ANNUALIZATION),
            target_vol=config.REGIME_VOL_TARGET,
            floor=config.REGIME_GROSS_FLOOR,
            ceil=config.REGIME_GROSS_CEIL,
        )
        self.bt_kwargs = dict(
            initial_capital=config.INITIAL_CAPITAL,
            commission_bps=config.COMMISSION_BPS,
            slippage_bps=config.SLIPPAGE_BPS,
            borrow_fee_annual=config.BORROW_FEE_ANNUAL,
            ann=config.ANNUALIZATION,
        )

    def screen(self, p: dict, *, formation_days: int, refresh_days: int, grouping, min_corr) -> pd.DataFrame:
        screen_kwargs = dict(
            pvalue_max=config.COINT_PVALUE_MAX,
            min_half_life=config.COINT_MIN_HALFLIFE,
            max_half_life=config.COINT_MAX_HALFLIFE,
            target_half_life=config.COINT_TARGET_HALFLIFE,
            min_corr=config.COINT_MIN_CORR,
            stability_window=config.COINT_STABILITY_WINDOW,
            stability_step=config.COINT_STABILITY_STEP,
            min_stability=config.COINT_MIN_STABILITY,
            max_pairs=p["max_pairs"],
            max_per_sector=p["sector_cap"],
        )

        def _groups(asof, tickers):
            return sector_groups_asof(asof, tickers=tickers, index=config.PIT_INDEX, min_names=2)

        _, log = build_rolling_stat_arb_weights(
            self.prices,
            sector_groups_fn=_groups,
            membership=self.membership,
            formation_days=formation_days,
            refresh_days=refresh_days,
            lookback=config.STATARB_LOOKBACK,
            entry_z=p["entry"],
            exit_z=p["exit"],
            stop_z=p["stop"],
            timeout_mult=p["timeout"],
            screen_kwargs=screen_kwargs,
            max_names_per_sector=config.COINT_MAX_NAMES_PER_SECTOR,
            fallback_pairs=self.fallback,
            primary_grouping_fn=make_primary_grouping_fn(grouping, min_corr=min_corr or 0.5),
            verbose=False,
        )
        return log

    def evaluate(self, log: pd.DataFrame, p: dict) -> dict:
        w = weights_from_pair_log(
            self.prices,
            log,
            lookback=config.STATARB_LOOKBACK,
            entry_z=p["entry"],
            exit_z=p["exit"],
            stop_z=p["stop"],
            timeout_mult=p["timeout"],
            membership=self.membership,
            formation_days=p["formation"],
            refresh_days=p["refresh"],
            fallback_pairs=self.fallback,
            diagnostics_cache=self.cache,
        )
        w.loc[self.prices.index < self.prices.index[p["formation"]]] = 0.0
        if p["shock"]:
            w = apply_gross_scaler(w, self.shock)
        if p["book_dd"] is not None:
            dd = book_drawdown_scaler(
                w, self.prices, max_dd=p["book_dd"], cooldown_days=p["cooldown"], floor=0.0
            )
            w = apply_gross_scaler(w, dd)
        if p["regime"]:
            w = apply_gross_scaler(w, self.regime)
        res = run_backtest(self.prices, w, **self.bt_kwargs)
        out = perf(res.returns, self.eval_start, config.ANNUALIZATION, self.eval_end)
        out["turnover"] = float(res.stats.get("ann_turnover", np.nan))
        out["pair_rows"] = int(len(log))
        out["_returns"] = res.returns
        return {**p, **out}


def run_stage(
    name: str, book: Book, variants: list[tuple[pd.DataFrame, dict]], out_dir: Path
) -> tuple[dict, pd.DataFrame]:
    rows = [book.evaluate(log, p) for log, p in variants]
    table = pd.DataFrame(rows).drop(columns="_returns")
    table.to_csv(out_dir / f"{name}.csv", index=False)
    cols = [
        c for c in [*PARAM_KEYS, "cagr", "cagr_h1", "cagr_h2", "sharpe", "max_dd",
                    "worst_year", "turnover", "flat_share", "pair_rows"]
        if c in table.columns and (table[c].nunique(dropna=False) > 1 or c in ("cagr", "max_dd"))
    ]
    print(f"\n=== Stage {name} ===")
    print(table[cols].sort_values("cagr", ascending=False).head(12).to_string(
        index=False, float_format=lambda x: f"{x:.4f}"
    ))
    best = pick(table)
    print(
        f"-> pick: CAGR {best.cagr:.2%} (H1 {best.cagr_h1:.2%} / H2 {best.cagr_h2:.2%}), "
        f"MDD {best.max_dd:.2%}, worst year {best.worst_year:.2%}"
    )
    out = {}
    for k in PARAM_KEYS:
        v = best[k]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            out[k] = None
        elif k in INT_KEYS:
            out[k] = int(v)
        elif k in BOOL_KEYS:
            out[k] = bool(v)
        elif isinstance(v, (float, np.floating)):
            out[k] = float(v)
        else:
            out[k] = v
    return out, variants[table.index.get_loc(best.name)][0]


PARAM_KEYS = [
    "entry", "exit", "stop", "max_pairs", "sector_cap", "timeout", "book_dd", "cooldown",
    "shock", "regime", "formation", "refresh", "grouping", "min_corr",
]
INT_KEYS = {"max_pairs", "sector_cap", "cooldown", "formation", "refresh"}

# Pre-tuning defaults: an out-of-sample run must not start from full-sample picks.
NEUTRAL_START = {
    "STATARB_ENTRY_Z": 2.5,
    "STATARB_EXIT_Z": 0.25,
    "STATARB_STOP_Z": 5.0,
    "STATARB_HL_TIMEOUT_MULT": 2.0,
    "COINT_MAX_PAIRS": 8,
    "COINT_MAX_PER_SECTOR": 3,
    "USE_BOOK_DD_STOP": True,
    "BOOK_DD_MAX": -0.12,
    "BOOK_DD_COOLDOWN": 15,
    "USE_SHOCK_BREAKER": True,
    "COINT_FORMATION_DAYS": 504,
    "COINT_REFRESH_DAYS": 126,
}
BOOL_KEYS = {"shock", "regime"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--names", type=int, default=None, help="override PIT_MAX_PRICED_NAMES")
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument(
        "--select-until",
        default=None,
        help="score picks only on returns up to this date, start from NEUTRAL_START, "
        "then report the chosen settings on the held-out period after it",
    )
    args = parser.parse_args()
    if args.names:
        config.PIT_MAX_PRICED_NAMES = args.names
    split = pd.Timestamp(args.select_until) if args.select_until else None
    if split is not None:
        for key, value in NEUTRAL_START.items():
            setattr(config, key, value)

    suffix = f"_oos{split.date()}" if split is not None else ""
    out_dir = ROOT / "output" / f"cagr_sweep_n{config.PIT_MAX_PRICED_NAMES}{suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    prices = _load_prices()
    membership = membership_matrix(prices.index, list(prices.columns), index=config.PIT_INDEX)
    book = Book(prices, membership)
    book.eval_end = split
    pool = _ensure_pool(prices, membership, out_dir)

    cur = {
        "entry": float(config.STATARB_ENTRY_Z),
        "exit": float(config.STATARB_EXIT_Z),
        "stop": float(config.STATARB_STOP_Z),
        "max_pairs": int(config.COINT_MAX_PAIRS),
        "sector_cap": int(config.COINT_MAX_PER_SECTOR),
        "timeout": float(config.STATARB_HL_TIMEOUT_MULT),
        "book_dd": float(config.BOOK_DD_MAX) if config.USE_BOOK_DD_STOP else None,
        "cooldown": int(config.BOOK_DD_COOLDOWN),
        "shock": bool(config.USE_SHOCK_BREAKER),
        "regime": False,
        "formation": int(config.COINT_FORMATION_DAYS),
        "refresh": int(config.COINT_REFRESH_DAYS),
        "grouping": config.PRIMARY_GROUPING,
        "min_corr": None,
    }
    start_params = dict(cur)
    base_log = filter_pair_log(pool, max_pairs=cur["max_pairs"], max_per_sector=cur["sector_cap"])
    start_log = base_log
    baseline = book.evaluate(base_log, cur)
    print(
        f"Baseline: CAGR {baseline['cagr']:.2%} (H1 {baseline['cagr_h1']:.2%} / "
        f"H2 {baseline['cagr_h2']:.2%}), MDD {baseline['max_dd']:.2%}, "
        f"worst year {baseline['worst_year']:.2%}, flat {baseline['flat_share']:.0%}, "
        f"turnover {baseline['turnover']:.1f}x, pair rows {baseline['pair_rows']}"
    )
    if args.baseline_only:
        return

    variants = [
        (base_log, {**cur, "entry": e, "exit": x, "stop": s})
        for e in ENTRY_GRID
        for x in EXIT_GRID
        for s in STOP_GRID
    ]
    cur, _ = run_stage("Z_zscore", book, variants, out_dir)

    variants = [
        (
            filter_pair_log(pool, max_pairs=n, max_per_sector=c),
            {**cur, "max_pairs": n, "sector_cap": c},
        )
        for n in PAIRS_GRID
        for c in SECTOR_CAP_GRID
    ]
    cur, base_log = run_stage("P_pairs", book, variants, out_dir)

    cur, _ = run_stage("A_timeout", book, [(base_log, {**cur, "timeout": t}) for t in TIMEOUT_GRID], out_dir)

    variants = [(base_log, dict(cur)), (base_log, {**cur, "book_dd": None})]
    variants += [
        (base_log, {**cur, "book_dd": d, "cooldown": c})
        for d in BOOK_DD_GRID
        for c in BOOK_DD_COOLDOWN_GRID
    ]
    cur, _ = run_stage("B_book_dd", book, variants, out_dir)

    variants = [
        (base_log, {**cur, "shock": s, "regime": g}) for s in (True, False) for g in (False, True)
    ]
    cur, _ = run_stage("C_guards", book, variants, out_dir)

    variants = []
    logs: dict[tuple, pd.DataFrame] = {}
    for f, r in WINDOW_GRID:
        print(f"Screening formation={f} refresh={r} ...")
        logs[(f, r)] = base_log if (f, r) == (cur["formation"], cur["refresh"]) else book.screen(
            cur, formation_days=f, refresh_days=r, grouping=None, min_corr=None
        )
        variants.append((logs[(f, r)], {**cur, "formation": f, "refresh": r}))
    cur, _ = run_stage("D_window", book, variants, out_dir)

    variants = []
    for grouping, mc in GROUPING_GRID:
        if grouping is None:
            log = logs[(cur["formation"], cur["refresh"])]
        else:
            print(f"Screening grouping={grouping} min_corr={mc} ...")
            log = book.screen(
                cur, formation_days=cur["formation"], refresh_days=cur["refresh"], grouping=grouping, min_corr=mc
            )
        variants.append((log, {**cur, "grouping": grouping, "min_corr": mc}))
    cur, final_log = run_stage("E_grouping", book, variants, out_dir)

    print("\n=== Selected settings ===")
    for k, v in cur.items():
        print(f"  {k}: {v}")

    if split is not None:
        book.eval_start = prices.index[prices.index > split][0]
        book.eval_end = None
        print(f"\n=== Held-out period {book.eval_start.date()} ~ {prices.index[-1].date()} ===")
        for label, log, p in (("selected on train", final_log, cur), ("neutral start", start_log, start_params)):
            m = book.evaluate(log, p)
            r = m["_returns"].loc[m["_returns"].index >= book.eval_start].fillna(0.0)
            yearly = ((1.0 + r).groupby(r.index.year).prod() - 1.0) * 100
            print(
                f"  {label:>17}: CAGR {m['cagr']:.2%}, Sharpe {m['sharpe']:.2f}, "
                f"MDD {m['max_dd']:.2%}, turnover {m['turnover']:.1f}x, "
                f"yearly {yearly.round(1).to_dict()}"
            )


if __name__ == "__main__":
    main()

"""Sweep COINT_MAX_PAIRS then COINT_MAX_PER_SECTOR on a fixed z-param book."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from backtest.engine import run_backtest
from backtest.resilience import resilience_row
from backtest.z_sweep import apply_stat_arb_guards
from data.loader import download_prices
from data.providers import normalize_ticker
from data.universe_pit import membership_matrix, pit_price_tickers, sector_groups_asof
from strategies.pair_screener import filter_pair_log
from strategies.rolling_pairs import build_rolling_pair_pool, weights_from_pair_log
from strategies.universe_structure import make_primary_grouping_fn


def _load_prices():
    if config.USE_PIT_UNIVERSE:
        tickers = pit_price_tickers(
            config.START,
            index=config.PIT_INDEX,
            max_names=int(config.PIT_MAX_PRICED_NAMES),
            seed=config.UNIVERSE,
        )
    else:
        tickers = [normalize_ticker(t) for t in config.UNIVERSE]

    print(f"Downloading {len(tickers)} names from {config.START} ...")
    prices = download_prices(tickers, config.START, config.END, provider="tiingo")
    prices = prices.loc[:, prices.notna().sum() >= 252]
    print(f"Price matrix: {prices.shape[0]} days x {prices.shape[1]} tickers")
    return prices


def _ensure_pool(prices, membership, out_dir: Path) -> pd.DataFrame:
    path = out_dir / (
        f"rolling_pairs_pool_n{prices.shape[1]}"
        f"_f{config.COINT_FORMATION_DAYS}_r{config.COINT_REFRESH_DAYS}.csv"
    )
    if path.exists():
        pool = pd.read_csv(path, parse_dates=["refresh_date"])
        print(f"Reusing pair pool: {path} ({len(pool)} rows)")
        return pool

    print(
        f"Building rich rolling pair pool "
        f"(max_pairs={getattr(config, 'PAIR_POOL_MAX_PAIRS', 48)}, "
        f"max_per_sector={getattr(config, 'PAIR_POOL_MAX_PER_SECTOR', 8)}) ..."
    )
    screen_kwargs = dict(
        pvalue_max=config.COINT_PVALUE_MAX,
        min_half_life=config.COINT_MIN_HALFLIFE,
        max_half_life=config.COINT_MAX_HALFLIFE,
        target_half_life=config.COINT_TARGET_HALFLIFE,
        min_corr=config.COINT_MIN_CORR,
        stability_window=config.COINT_STABILITY_WINDOW,
        stability_step=config.COINT_STABILITY_STEP,
        min_stability=config.COINT_MIN_STABILITY,
    )

    def _groups_asof(asof, tickers):
        if config.USE_PIT_UNIVERSE:
            return sector_groups_asof(
                asof, tickers=tickers, index=config.PIT_INDEX, min_names=2
            )
        return config.SECTOR_GROUPS

    pool = build_rolling_pair_pool(
        prices,
        sector_groups_fn=_groups_asof,
        membership=membership,
        formation_days=config.COINT_FORMATION_DAYS,
        refresh_days=config.COINT_REFRESH_DAYS,
        screen_kwargs=screen_kwargs,
        max_names_per_sector=config.COINT_MAX_NAMES_PER_SECTOR,
        pool_max_pairs=getattr(config, "PAIR_POOL_MAX_PAIRS", 48),
        pool_max_per_sector=getattr(config, "PAIR_POOL_MAX_PER_SECTOR", 8),
        primary_grouping_fn=make_primary_grouping_fn(
            config.PRIMARY_GROUPING, min_corr=config.PRIMARY_CLUSTER_MIN_CORR
        ),
        verbose=True,
    )
    pool.to_csv(path, index=False)
    print(f"Saved pool -> {path} ({len(pool)} rows)")
    return pool


def _eval_log(
    prices,
    pair_log,
    membership,
    *,
    cache: dict,
    bt_kwargs: dict,
    shock_kwargs: dict,
    book_dd_kwargs: dict,
    label: str,
) -> dict:
    fallback = [(normalize_ticker(a), normalize_ticker(b)) for a, b in config.PAIRS]
    w = weights_from_pair_log(
        prices,
        pair_log,
        lookback=config.STATARB_LOOKBACK,
        entry_z=config.STATARB_ENTRY_Z,
        exit_z=config.STATARB_EXIT_Z,
        stop_z=config.STATARB_STOP_Z,
        timeout_mult=config.STATARB_HL_TIMEOUT_MULT,
        membership=membership,
        formation_days=config.COINT_FORMATION_DAYS,
        refresh_days=config.COINT_REFRESH_DAYS,
        fallback_pairs=fallback,
        diagnostics_cache=cache,
    )
    trade_start = prices.index[config.COINT_FORMATION_DAYS]
    w.loc[prices.index < trade_start] = 0.0
    w = apply_stat_arb_guards(
        w,
        prices,
        use_shock=config.USE_SHOCK_BREAKER,
        use_book_dd=config.USE_BOOK_DD_STOP,
        shock_kwargs=shock_kwargs,
        book_dd_kwargs=book_dd_kwargs,
    )
    res = run_backtest(prices, w, **bt_kwargs)
    row = resilience_row(
        label,
        res,
        prices,
        vol_lookback=config.REGIME_VOL_LOOKBACK,
        ann=config.ANNUALIZATION,
    )
    return row


def _pick(table: pd.DataFrame) -> pd.Series:
    best = table.iloc[0]
    top = table[table["resilience_score"] >= float(best["resilience_score"]) - 0.02]
    return top.sort_values(
        ["cagr", "max_dd", "resilience_score"],
        ascending=[False, False, False],
    ).iloc[0]


def _patch_config(key: str, value: int) -> None:
    path = ROOT / "config.py"
    text = path.read_text(encoding="utf-8")
    text, n = re.subn(
        rf"^({key}\s*=\s*)[^#\n]+",
        rf"\g<1>{int(value)}  ",
        text,
        count=1,
        flags=re.M,
    )
    if n != 1:
        raise RuntimeError(f"Failed to update {key}")
    path.write_text(text, encoding="utf-8")
    print(f"Updated config.py: {key}={int(value)}")


def main() -> None:
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)

    prices = _load_prices()
    membership = None
    if config.USE_PIT_UNIVERSE:
        membership = membership_matrix(
            prices.index, list(prices.columns), index=config.PIT_INDEX
        )

    pool = _ensure_pool(prices, membership, out_dir)

    shock_kwargs = dict(
        short_vol_lb=config.SHOCK_SHORT_VOL_LB,
        long_vol_lb=config.SHOCK_LONG_VOL_LB,
        vol_spike_ratio=config.SHOCK_VOL_SPIKE_RATIO,
        crash_days=config.SHOCK_CRASH_DAYS,
        crash_ret=config.SHOCK_CRASH_RET,
        day1_crash=getattr(config, "SHOCK_DAY1_CRASH", -0.035),
        cooldown_days=config.SHOCK_COOLDOWN_DAYS,
        shock_floor=config.SHOCK_FLOOR,
        ann=config.ANNUALIZATION,
    )
    book_dd_kwargs = dict(
        max_dd=config.BOOK_DD_MAX,
        cooldown_days=config.BOOK_DD_COOLDOWN,
        floor=config.BOOK_DD_FLOOR,
    )
    bt_kwargs = dict(
        initial_capital=config.INITIAL_CAPITAL,
        commission_bps=config.COMMISSION_BPS,
        slippage_bps=config.SLIPPAGE_BPS,
        borrow_fee_annual=config.BORROW_FEE_ANNUAL,
        ann=config.ANNUALIZATION,
    )

    cache: dict = {}
    pair_grid = getattr(config, "PAIR_SWEEP_MAX_PAIRS", [6, 8, 12, 16, 20, 24])
    sector_fixed = int(config.COINT_MAX_PER_SECTOR)

    print(f"\n=== Stage 1: max_pairs sweep (max_per_sector={sector_fixed}) ===")
    rows = []
    for n_pairs in pair_grid:
        log = filter_pair_log(pool, max_pairs=int(n_pairs), max_per_sector=sector_fixed)
        metrics = _eval_log(
            prices,
            log,
            membership,
            cache=cache,
            bt_kwargs=bt_kwargs,
            shock_kwargs=shock_kwargs,
            book_dd_kwargs=book_dd_kwargs,
            label=f"pairs={n_pairs}",
        )
        metrics["max_pairs"] = int(n_pairs)
        metrics["max_per_sector"] = sector_fixed
        metrics["n_pair_rows"] = int(len(log))
        rows.append(metrics)
        print(
            f"  pairs={n_pairs}: CAGR={metrics['cagr']:.2%} "
            f"Sharpe={metrics['sharpe']:.2f} MDD={metrics['max_dd']:.2%} "
            f"rows={len(log)}"
        )

    pairs_table = pd.DataFrame(rows).sort_values("resilience_score", ascending=False)
    pairs_table.to_csv(out_dir / "pair_count_sweep.csv", index=False)
    pick_pairs = _pick(pairs_table)
    best_pairs = int(pick_pairs["max_pairs"])
    print(
        f"Selected max_pairs={best_pairs} "
        f"(CAGR={pick_pairs.cagr:.2%}, MDD={pick_pairs.max_dd:.2%})"
    )
    _patch_config("COINT_MAX_PAIRS", best_pairs)

    sector_grid = getattr(config, "PAIR_SWEEP_MAX_PER_SECTOR", [1, 2, 3, 4, 5])
    print(f"\n=== Stage 2: max_per_sector sweep (max_pairs={best_pairs}) ===")
    rows2 = []
    for cap in sector_grid:
        log = filter_pair_log(pool, max_pairs=best_pairs, max_per_sector=int(cap))
        metrics = _eval_log(
            prices,
            log,
            membership,
            cache=cache,
            bt_kwargs=bt_kwargs,
            shock_kwargs=shock_kwargs,
            book_dd_kwargs=book_dd_kwargs,
            label=f"sector_cap={cap}",
        )
        metrics["max_pairs"] = best_pairs
        metrics["max_per_sector"] = int(cap)
        metrics["n_pair_rows"] = int(len(log))
        rows2.append(metrics)
        print(
            f"  sector_cap={cap}: CAGR={metrics['cagr']:.2%} "
            f"Sharpe={metrics['sharpe']:.2f} MDD={metrics['max_dd']:.2%} "
            f"rows={len(log)}"
        )

    sector_table = pd.DataFrame(rows2).sort_values("resilience_score", ascending=False)
    sector_table.to_csv(out_dir / "sector_cap_sweep.csv", index=False)
    pick_sec = _pick(sector_table)
    best_sec = int(pick_sec["max_per_sector"])
    print(
        f"Selected max_per_sector={best_sec} "
        f"(CAGR={pick_sec.cagr:.2%}, MDD={pick_sec.max_dd:.2%})"
    )
    _patch_config("COINT_MAX_PER_SECTOR", best_sec)

    # Refresh truncated trading log for main backtest reuse
    final_log = filter_pair_log(pool, max_pairs=best_pairs, max_per_sector=best_sec)
    final_log.to_csv(out_dir / "rolling_pairs_log.csv", index=False)
    print(
        f"\nDone. Final caps: max_pairs={best_pairs}, max_per_sector={best_sec} "
        f"(pair-rows={len(final_log)})"
    )


if __name__ == "__main__":
    main()

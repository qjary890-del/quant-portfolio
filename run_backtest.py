"""Run mean-reversion portfolio backtest: stat-arb + cross-sectional."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from backtest.engine import combine_weights, run_backtest
from data.providers import cached_tiingo_tickers, normalize_ticker
from data.loader import download_prices
from data.universe_pit import (
    constituents_asof,
    coverage_report,
    historical_tickers,
    membership_matrix,
    normalize_ticker as pit_norm,
    sector_groups_asof,
)
from strategies.mean_reversion import build_cross_sectional_weights
from strategies.pair_screener import pairs_from_screen, screen_cointegrated_pairs
from strategies.stat_arb import build_stat_arb_weights


def format_stats(name: str, stats: dict[str, float]) -> str:
    return (
        f"{name}\n"
        f"  CAGR              {stats.get('cagr', float('nan')):>8.2%}\n"
        f"  Sharpe            {stats.get('sharpe', float('nan')):>8.2f}\n"
        f"  Vol               {stats.get('vol', float('nan')):>8.2%}\n"
        f"  Max DD            {stats.get('max_drawdown', float('nan')):>8.2%}\n"
        f"  Hit rate          {stats.get('hit_rate', float('nan')):>8.2%}\n"
        f"  Ann. turnover     {stats.get('ann_turnover', float('nan')):>8.1f}x\n"
        f"  Avg short gross   {stats.get('avg_short_gross', float('nan')):>8.2%}\n"
        f"  Trading cost/yr   {stats.get('trading_cost_drag', float('nan')):>8.2%}\n"
        f"  Borrow cost/yr    {stats.get('borrow_cost_drag', float('nan')):>8.2%}\n"
        f"  Total cost/yr     {stats.get('total_cost_drag', float('nan')):>8.2%}\n"
    )


def _renorm_l1(weights: pd.DataFrame) -> pd.DataFrame:
    l1 = weights.abs().sum(axis=1).replace(0, np.nan)
    return weights.div(l1, axis=0).fillna(0.0)


def main() -> None:
    end = config.END or pd.Timestamp.today().date().isoformat()
    membership = None

    if config.USE_PIT_UNIVERSE:
        print(f"Building PIT {config.PIT_INDEX} universe {config.START} -> {end} ...")
        if getattr(config, "PIT_PRICE_UNIVERSE", "asof_start") == "union":
            tickers = historical_tickers(config.START, end, index=config.PIT_INDEX)
            print(f"Historical member tickers (union): {len(tickers)}")
        else:
            roster = constituents_asof(config.START, index=config.PIT_INDEX)
            roster_set = {pit_norm(t) for t in roster["ticker"]}
            # Prefer liquid seeds that were actually members at START (no look-ahead)
            seed = [normalize_ticker(t) for t in config.UNIVERSE if normalize_ticker(t) in roster_set]
            rest = sorted(roster_set - set(seed))
            tickers = (seed + rest)[: int(getattr(config, "PIT_MAX_PRICED_NAMES", 50))]
            cached = set(cached_tiingo_tickers(config.START, config.END))
            have = [t for t in tickers if t in cached]
            need = [t for t in tickers if t not in cached]
            print(
                f"PIT priced names as of {config.START}: {len(tickers)} "
                f"(cached {len(have)}, to_fetch {len(need)}; "
                f"membership filter still uses full index)"
            )
    else:
        tickers = sorted(
            set(config.UNIVERSE)
            | {t for p in config.PAIRS for t in p}
            | {t for names in config.SECTOR_GROUPS.values() for t in names}
        )
        tickers = [normalize_ticker(t) for t in tickers]

    provider = "tiingo"
    print(f"Downloading {len(tickers)} names from {config.START} ...")
    prices = download_prices(tickers, config.START, config.END, provider=provider)
    # Keep names with enough history; do NOT dropna(how='any') across all
    # (that would re-introduce survivorship by requiring full-period survival)
    min_obs = 252
    prices = prices.loc[:, prices.notna().sum() >= min_obs]
    print(f"Price matrix: {prices.shape[0]} days x {prices.shape[1]} tickers (min {min_obs} obs)")

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)

    if config.USE_PIT_UNIVERSE:
        membership = membership_matrix(
            prices.index,
            list(prices.columns),
            index=config.PIT_INDEX,
        )
        cov = coverage_report(membership, prices)
        print(
            f"PIT coverage: avg {cov['avg_member_coverage']:.1%} of members priced/day "
            f"({int(cov['priced_tickers'])} priced tickers)"
        )
        pd.Series(cov).to_csv(out_dir / "pit_coverage.csv")

    trade_start = None
    if config.USE_AUTO_PAIRS:
        formation_n = min(config.COINT_FORMATION_DAYS, len(prices) - 60)
        formation = prices.iloc[:formation_n]
        trade_start = prices.index[formation_n]
        formation_end = formation.index[-1]

        if config.USE_PIT_UNIVERSE:
            # Only names that were members at formation end + have prices
            groups = sector_groups_asof(
                formation_end,
                tickers=list(formation.columns),
                index=config.PIT_INDEX,
            )
            # Cap sector size: prefer names with fullest formation history
            max_n = getattr(config, "COINT_MAX_NAMES_PER_SECTOR", 12)
            trimmed: dict[str, list[str]] = {}
            avail = formation.notna().sum()
            for sector, names in groups.items():
                ranked = sorted(names, key=lambda t: float(avail.get(t, 0)), reverse=True)
                trimmed[sector] = ranked[:max_n]
            groups = trimmed
            mem_end = membership.loc[formation_end]
            formation = formation.loc[:, mem_end.reindex(formation.columns).fillna(False)]
            print(
                f"PIT sector groups at {formation_end.date()}: {len(groups)} sectors "
                f"(≤{max_n} names each)"
            )
        else:
            groups = config.SECTOR_GROUPS

        print(
            f"Screening cointegrated pairs on formation "
            f"{formation.index[0].date()} ~ {formation.index[-1].date()} ..."
        )
        screen = screen_cointegrated_pairs(
            formation,
            groups,
            pvalue_max=config.COINT_PVALUE_MAX,
            min_half_life=config.COINT_MIN_HALFLIFE,
            max_half_life=config.COINT_MAX_HALFLIFE,
            target_half_life=config.COINT_TARGET_HALFLIFE,
            min_corr=config.COINT_MIN_CORR,
            stability_window=config.COINT_STABILITY_WINDOW,
            stability_step=config.COINT_STABILITY_STEP,
            min_stability=config.COINT_MIN_STABILITY,
            max_pairs=config.COINT_MAX_PAIRS,
        )
        screen.to_csv(out_dir / "coint_pairs.csv", index=False)
        n_cand = screen.attrs.get("n_candidates", "?")
        n_corr = screen.attrs.get("n_after_corr", "?")
        print(f"Corr pre-filter: {n_cand} candidates -> {n_corr} after min_corr")
        pairs = pairs_from_screen(screen)
        if pairs:
            print(f"Auto-selected {len(pairs)} pairs (trade from {trade_start.date()}):")
            print(screen.to_string(index=False))
        else:
            print("No pairs passed screener; falling back to config.PAIRS")
            pairs = [(normalize_ticker(a), normalize_ticker(b)) for a, b in config.PAIRS]
            trade_start = None
    else:
        pairs = [(normalize_ticker(a), normalize_ticker(b)) for a, b in config.PAIRS]
        print(f"Using {len(pairs)} static pairs from config")

    print("Building statistical arbitrage weights ...")
    w_stat = build_stat_arb_weights(
        prices,
        pairs,
        lookback=config.STATARB_LOOKBACK,
        entry_z=config.STATARB_ENTRY_Z,
        exit_z=config.STATARB_EXIT_Z,
        stop_z=config.STATARB_STOP_Z,
    )
    if trade_start is not None:
        w_stat.loc[prices.index < trade_start] = 0.0
    if membership is not None:
        w_stat = _renorm_l1(w_stat.where(membership, 0.0))

    print("Building cross-sectional mean-reversion weights ...")
    w_cs = build_cross_sectional_weights(
        prices,
        lookback=config.CS_LOOKBACK,
        holding=config.CS_HOLDING,
        long_pct=config.CS_LONG_PCT,
        short_pct=config.CS_SHORT_PCT,
        membership=membership,
    )

    combined = combine_weights(
        {"stat_arb": w_stat, "cross_section": w_cs},
        {"stat_arb": config.STATARB_WEIGHT, "cross_section": config.CS_WEIGHT},
    )

    bt_kwargs = dict(
        initial_capital=config.INITIAL_CAPITAL,
        commission_bps=config.COMMISSION_BPS,
        slippage_bps=config.SLIPPAGE_BPS,
        borrow_fee_annual=config.BORROW_FEE_ANNUAL,
        ann=config.ANNUALIZATION,
    )
    results = {
        "Stat Arb": run_backtest(prices, w_stat, **bt_kwargs),
        "Cross-Sectional MR": run_backtest(prices, w_cs, **bt_kwargs),
        "Combined Portfolio": run_backtest(prices, combined, **bt_kwargs),
    }

    print("\n=== Backtest results ===")
    for name, res in results.items():
        print(format_stats(name, res.stats))
        res.equity.to_csv(out_dir / f"{name.lower().replace(' ', '_')}_equity.csv")
        res.weights.tail(1).T.to_csv(out_dir / f"{name.lower().replace(' ', '_')}_last_weights.csv")

    fig, ax = plt.subplots(figsize=(10, 5))
    for name, res in results.items():
        ax.plot(res.equity.index, res.equity.values, label=name)
    ax.set_title("Mean-Reversion Portfolio Equity (PIT universe)")
    ax.set_ylabel("Equity ($)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig_path = out_dir / "equity_curves.png"
    fig.savefig(fig_path, dpi=140)
    print(f"Saved equity chart -> {fig_path}")

    latest = combined.iloc[-1]
    active = latest[latest.abs() > 1e-6].sort_values()
    print("\nLatest combined weights (nonzero):")
    print(active.to_string())
    pd.DataFrame({"weight": active}).to_csv(out_dir / "latest_combined_weights.csv")
    print(f"\nArtifacts written to {out_dir}")


if __name__ == "__main__":
    main()

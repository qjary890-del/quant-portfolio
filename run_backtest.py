"""Run mean-reversion portfolio backtest: stat-arb + cross-sectional."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from backtest.engine import combine_weights, run_backtest
from data.loader import download_prices
from strategies.mean_reversion import build_cross_sectional_weights
from strategies.stat_arb import build_stat_arb_weights


def format_stats(name: str, stats: dict[str, float]) -> str:
    return (
        f"{name}\n"
        f"  CAGR          {stats.get('cagr', float('nan')):>8.2%}\n"
        f"  Sharpe        {stats.get('sharpe', float('nan')):>8.2f}\n"
        f"  Vol           {stats.get('vol', float('nan')):>8.2%}\n"
        f"  Max DD        {stats.get('max_drawdown', float('nan')):>8.2%}\n"
        f"  Hit rate      {stats.get('hit_rate', float('nan')):>8.2%}\n"
        f"  Avg turnover  {stats.get('avg_daily_turnover', float('nan')):>8.2%}\n"
    )


def main() -> None:
    tickers = sorted(set(config.UNIVERSE) | {t for p in config.PAIRS for t in p})
    print(f"Downloading {len(tickers)} names from {config.START} ...")
    prices = download_prices(tickers, config.START, config.END)
    prices = prices.dropna(axis=1, how="any")
    print(f"Price matrix: {prices.shape[0]} days x {prices.shape[1]} tickers")

    print("Building statistical arbitrage weights ...")
    w_stat = build_stat_arb_weights(
        prices,
        config.PAIRS,
        lookback=config.STATARB_LOOKBACK,
        entry_z=config.STATARB_ENTRY_Z,
        exit_z=config.STATARB_EXIT_Z,
        stop_z=config.STATARB_STOP_Z,
    )

    print("Building cross-sectional mean-reversion weights ...")
    w_cs = build_cross_sectional_weights(
        prices,
        lookback=config.CS_LOOKBACK,
        holding=config.CS_HOLDING,
        long_pct=config.CS_LONG_PCT,
        short_pct=config.CS_SHORT_PCT,
    )

    combined = combine_weights(
        {"stat_arb": w_stat, "cross_section": w_cs},
        {"stat_arb": config.STATARB_WEIGHT, "cross_section": config.CS_WEIGHT},
    )

    results = {
        "Stat Arb": run_backtest(
            prices,
            w_stat,
            initial_capital=config.INITIAL_CAPITAL,
            commission_bps=config.COMMISSION_BPS,
            slippage_bps=config.SLIPPAGE_BPS,
        ),
        "Cross-Sectional MR": run_backtest(
            prices,
            w_cs,
            initial_capital=config.INITIAL_CAPITAL,
            commission_bps=config.COMMISSION_BPS,
            slippage_bps=config.SLIPPAGE_BPS,
        ),
        "Combined Portfolio": run_backtest(
            prices,
            combined,
            initial_capital=config.INITIAL_CAPITAL,
            commission_bps=config.COMMISSION_BPS,
            slippage_bps=config.SLIPPAGE_BPS,
        ),
    }

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)

    print("\n=== Backtest results ===")
    for name, res in results.items():
        print(format_stats(name, res.stats))
        res.equity.to_csv(out_dir / f"{name.lower().replace(' ', '_')}_equity.csv")
        res.weights.tail(1).T.to_csv(out_dir / f"{name.lower().replace(' ', '_')}_last_weights.csv")

    # Equity curves
    fig, ax = plt.subplots(figsize=(10, 5))
    for name, res in results.items():
        ax.plot(res.equity.index, res.equity.values, label=name)
    ax.set_title("Mean-Reversion Portfolio Equity")
    ax.set_ylabel("Equity ($)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig_path = out_dir / "equity_curves.png"
    fig.savefig(fig_path, dpi=140)
    print(f"Saved equity chart -> {fig_path}")

    # Latest combined book snapshot
    latest = combined.iloc[-1]
    active = latest[latest.abs() > 1e-6].sort_values()
    print("\nLatest combined weights (nonzero):")
    print(active.to_string())
    pd.DataFrame({"weight": active}).to_csv(out_dir / "latest_combined_weights.csv")
    print(f"\nArtifacts written to {out_dir}")


if __name__ == "__main__":
    main()

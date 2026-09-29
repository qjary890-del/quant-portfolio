"""Sweep Stat Arb z-score parameters on a fixed rolling pair schedule."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from backtest.z_sweep import sweep_z_params
from data.loader import download_prices
from data.providers import cached_tiingo_tickers, normalize_ticker
from data.universe_pit import membership_matrix, pit_price_tickers, sector_groups_asof
from strategies.rolling_pairs import build_rolling_stat_arb_weights
from strategies.universe_structure import make_primary_grouping_fn


def _load_prices():
    end = config.END or pd.Timestamp.today().date().isoformat()
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


def _ensure_pair_log(prices, membership, out_dir: Path) -> pd.DataFrame:
    log_path = out_dir / "rolling_pairs_log.csv"
    if log_path.exists():
        log = pd.read_csv(log_path, parse_dates=["refresh_date"])
        print(f"Reusing pair schedule: {log_path} ({len(log)} rows)")
        return log

    print("No pair log found — screening rolling pairs once ...")
    screen_kwargs = dict(
        pvalue_max=config.COINT_PVALUE_MAX,
        min_half_life=config.COINT_MIN_HALFLIFE,
        max_half_life=config.COINT_MAX_HALFLIFE,
        target_half_life=config.COINT_TARGET_HALFLIFE,
        min_corr=config.COINT_MIN_CORR,
        stability_window=config.COINT_STABILITY_WINDOW,
        stability_step=config.COINT_STABILITY_STEP,
        min_stability=config.COINT_MIN_STABILITY,
        max_pairs=config.COINT_MAX_PAIRS,
        max_per_sector=getattr(config, "COINT_MAX_PER_SECTOR", 3),
    )
    fallback = [(normalize_ticker(a), normalize_ticker(b)) for a, b in config.PAIRS]

    def _groups_asof(asof, tickers):
        if config.USE_PIT_UNIVERSE:
            return sector_groups_asof(
                asof, tickers=tickers, index=config.PIT_INDEX, min_names=2
            )
        return config.SECTOR_GROUPS

    _, pair_log = build_rolling_stat_arb_weights(
        prices,
        sector_groups_fn=_groups_asof,
        membership=membership,
        formation_days=config.COINT_FORMATION_DAYS,
        refresh_days=config.COINT_REFRESH_DAYS,
        lookback=config.STATARB_LOOKBACK,
        entry_z=config.STATARB_ENTRY_Z,
        exit_z=config.STATARB_EXIT_Z,
        stop_z=config.STATARB_STOP_Z,
        timeout_mult=config.STATARB_HL_TIMEOUT_MULT,
        screen_kwargs=screen_kwargs,
        max_names_per_sector=config.COINT_MAX_NAMES_PER_SECTOR,
        fallback_pairs=fallback,
        primary_grouping_fn=make_primary_grouping_fn(
            config.PRIMARY_GROUPING, min_corr=config.PRIMARY_CLUSTER_MIN_CORR
        ),
        verbose=True,
    )
    pair_log.to_csv(log_path, index=False)
    return pair_log


def _write_config_z(lookback: int, entry_z: float, exit_z: float, stop_z: float) -> None:
    path = ROOT / "config.py"
    text = path.read_text(encoding="utf-8")
    repl = {
        "STATARB_LOOKBACK": str(int(lookback)),
        "STATARB_ENTRY_Z": str(float(entry_z)),
        "STATARB_EXIT_Z": str(float(exit_z)),
        "STATARB_STOP_Z": str(float(stop_z)),
    }
    for key, val in repl.items():
        text, n = re.subn(
            rf"^({key}\s*=\s*)[^#\n]+",
            rf"\g<1>{val}  ",
            text,
            count=1,
            flags=re.M,
        )
        if n != 1:
            raise RuntimeError(f"Failed to update {key} in config.py")
    path.write_text(text, encoding="utf-8")
    print(
        f"Updated config.py: LOOKBACK={lookback}, ENTRY_Z={entry_z}, "
        f"EXIT_Z={exit_z}, STOP_Z={stop_z}"
    )


def main() -> None:
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)

    prices = _load_prices()
    membership = None
    if config.USE_PIT_UNIVERSE:
        membership = membership_matrix(
            prices.index, list(prices.columns), index=config.PIT_INDEX
        )

    pair_log = _ensure_pair_log(prices, membership, out_dir)
    fallback = [(normalize_ticker(a), normalize_ticker(b)) for a, b in config.PAIRS]

    lookbacks = getattr(config, "Z_SWEEP_LOOKBACKS", [42, 60, 90])
    entry_zs = getattr(config, "Z_SWEEP_ENTRY", [2.0, 2.5, 3.0])
    exit_zs = getattr(config, "Z_SWEEP_EXIT", [0.25, 0.5, 0.75])
    stop_zs = getattr(config, "Z_SWEEP_STOP", [3.5, 4.0, 5.0])

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

    print(
        f"Sweeping z params with guards "
        f"(shock={config.USE_SHOCK_BREAKER}, bookDD={config.USE_BOOK_DD_STOP}) ..."
    )
    print(f"  lookbacks={lookbacks}")
    print(f"  entry={entry_zs}  exit={exit_zs}  stop={stop_zs}")

    table = sweep_z_params(
        prices,
        pair_log,
        lookbacks=lookbacks,
        entry_zs=entry_zs,
        exit_zs=exit_zs,
        stop_zs=stop_zs,
        timeout_mult=config.STATARB_HL_TIMEOUT_MULT,
        membership=membership,
        formation_days=config.COINT_FORMATION_DAYS,
        refresh_days=config.COINT_REFRESH_DAYS,
        fallback_pairs=fallback,
        bt_kwargs=bt_kwargs,
        use_shock=config.USE_SHOCK_BREAKER,
        use_book_dd=config.USE_BOOK_DD_STOP,
        shock_kwargs=shock_kwargs,
        book_dd_kwargs=book_dd_kwargs,
        vol_lookback=config.REGIME_VOL_LOOKBACK,
        ann=config.ANNUALIZATION,
    )
    out_csv = out_dir / "z_sweep.csv"
    table.to_csv(out_csv, index=False)

    cols = [
        "lookback", "entry_z", "exit_z", "stop_z",
        "cagr", "sharpe", "max_dd", "worst_year",
        "ann_turnover", "resilience_score",
    ]
    print("\n=== Top 10 z-param sets (guards on) ===")
    print(table[cols].head(10).to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    best = table.iloc[0]
    # Prefer economically better set if resilience is nearly tied (within 0.02)
    top = table[table["resilience_score"] >= float(best["resilience_score"]) - 0.02]
    pick = top.sort_values(
        ["cagr", "max_dd", "resilience_score"],
        ascending=[False, False, False],
    ).iloc[0]
    print(
        f"\nBest (resilience): lookback={int(best.lookback)}, entry={best.entry_z}, "
        f"exit={best.exit_z}, stop={best.stop_z} "
        f"(CAGR={best.cagr:.2%}, Sharpe={best.sharpe:.2f}, MDD={best.max_dd:.2%})"
    )
    print(
        f"Applied (near-tied, prefer CAGR/MDD): lookback={int(pick.lookback)}, "
        f"entry={pick.entry_z}, exit={pick.exit_z}, stop={pick.stop_z} "
        f"(CAGR={pick.cagr:.2%}, Sharpe={pick.sharpe:.2f}, MDD={pick.max_dd:.2%})"
    )
    _write_config_z(
        int(pick.lookback),
        float(pick.entry_z),
        float(pick.exit_z),
        float(pick.stop_z),
    )
    print(f"Saved full grid -> {out_csv}")


if __name__ == "__main__":
    main()

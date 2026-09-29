"""Grid sweep for Stat Arb z-score / lookback parameters."""

from __future__ import annotations

from itertools import product
from typing import Iterable

import pandas as pd

from backtest.engine import run_backtest
from backtest.resilience import resilience_row
from strategies.regime import (
    apply_gross_scaler,
    book_drawdown_scaler,
    macro_shock_scaler,
)
from strategies.rolling_pairs import weights_from_pair_log


def apply_stat_arb_guards(
    weights: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    use_shock: bool,
    use_book_dd: bool,
    shock_kwargs: dict,
    book_dd_kwargs: dict,
) -> pd.DataFrame:
    w = weights
    if use_shock:
        shock = macro_shock_scaler(prices, **shock_kwargs)
        w = apply_gross_scaler(w, shock)
    if use_book_dd:
        dd = book_drawdown_scaler(w, prices, **book_dd_kwargs)
        w = apply_gross_scaler(w, dd)
    return w


def sweep_z_params(
    prices: pd.DataFrame,
    pair_log: pd.DataFrame,
    *,
    lookbacks: Iterable[int],
    entry_zs: Iterable[float],
    exit_zs: Iterable[float],
    stop_zs: Iterable[float],
    timeout_mult: float,
    membership: pd.DataFrame | None,
    formation_days: int,
    refresh_days: int,
    fallback_pairs: list[tuple[str, str]],
    bt_kwargs: dict,
    use_shock: bool,
    use_book_dd: bool,
    shock_kwargs: dict,
    book_dd_kwargs: dict,
    vol_lookback: int = 21,
    ann: int = 252,
    require_stop_gt_entry: bool = True,
) -> pd.DataFrame:
    """
    Sweep z params on a fixed rolling pair schedule.
    Returns a ranked table (best resilience_score first).
    """
    cache: dict[tuple[int, str, str], pd.DataFrame] = {}
    rows: list[dict] = []
    combos = list(product(lookbacks, entry_zs, exit_zs, stop_zs))
    if require_stop_gt_entry:
        combos = [(lb, e, x, s) for lb, e, x, s in combos if s > e > x]

    for i, (lookback, entry_z, exit_z, stop_z) in enumerate(combos, 1):
        w = weights_from_pair_log(
            prices,
            pair_log,
            lookback=int(lookback),
            entry_z=float(entry_z),
            exit_z=float(exit_z),
            stop_z=float(stop_z),
            timeout_mult=timeout_mult,
            membership=membership,
            formation_days=formation_days,
            refresh_days=refresh_days,
            fallback_pairs=fallback_pairs,
            diagnostics_cache=cache,
        )
        trade_start = prices.index[formation_days]
        w.loc[prices.index < trade_start] = 0.0
        w = apply_stat_arb_guards(
            w,
            prices,
            use_shock=use_shock,
            use_book_dd=use_book_dd,
            shock_kwargs=shock_kwargs,
            book_dd_kwargs=book_dd_kwargs,
        )
        res = run_backtest(prices, w, **bt_kwargs)
        metrics = resilience_row(
            f"lb{lookback}_e{entry_z}_x{exit_z}_s{stop_z}",
            res,
            prices,
            vol_lookback=vol_lookback,
            ann=ann,
        )
        metrics.update(
            {
                "lookback": int(lookback),
                "entry_z": float(entry_z),
                "exit_z": float(exit_z),
                "stop_z": float(stop_z),
            }
        )
        rows.append(metrics)
        if i % 10 == 0 or i == len(combos):
            print(f"  z-sweep {i}/{len(combos)} done")

    table = pd.DataFrame(rows).sort_values("resilience_score", ascending=False)
    return table.reset_index(drop=True)

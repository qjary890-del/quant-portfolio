"""Rolling cointegration pair refresh for out-of-sample pair validation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.pair_screener import pairs_from_screen, screen_cointegrated_pairs
from strategies.stat_arb import build_stat_arb_weights


def _trim_sector_groups(
    groups: dict[str, list[str]],
    prices: pd.DataFrame,
    max_names: int,
) -> dict[str, list[str]]:
    avail = prices.notna().sum()
    trimmed: dict[str, list[str]] = {}
    for sector, names in groups.items():
        present = [n for n in names if n in prices.columns]
        ranked = sorted(present, key=lambda t: float(avail.get(t, 0)), reverse=True)
        if len(ranked) >= 2:
            trimmed[sector] = ranked[:max_names]
    return trimmed


def build_rolling_stat_arb_weights(
    prices: pd.DataFrame,
    *,
    sector_groups_fn,
    membership: pd.DataFrame | None = None,
    formation_days: int = 504,
    refresh_days: int = 126,
    lookback: int = 60,
    entry_z: float = 2.5,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    timeout_mult: float = 2.0,
    screen_kwargs: dict | None = None,
    max_names_per_sector: int = 15,
    fallback_pairs: list[tuple[str, str]] | None = None,
    verbose: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Re-screen cointegrated pairs every `refresh_days` using only a trailing
    formation window (no look-ahead). Trade with that pair set until the next refresh.

    Returns
    -------
    weights : DataFrame
    pair_log : DataFrame of refresh_date, y, x, half_life, score, ...
    """
    screen_kwargs = dict(screen_kwargs or {})
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    logs: list[dict] = []

    n = len(prices)
    if n <= formation_days + lookback:
        raise ValueError("Not enough history for rolling pair formation")

    # First tradeable index: after initial formation
    start_i = formation_days
    refresh_points = list(range(start_i, n, refresh_days))
    if refresh_points[-1] != n - 1:
        # ensure we cover through the end via segment ends
        pass

    for k, i in enumerate(refresh_points):
        form_start = max(0, i - formation_days)
        form_end = i  # exclusive end for iloc; last formation day is i-1
        formation = prices.iloc[form_start:form_end]
        asof = prices.index[form_end - 1]

        raw_groups = sector_groups_fn(asof, list(formation.columns))
        groups = _trim_sector_groups(raw_groups, formation, max_names_per_sector)

        if membership is not None:
            mem = membership.loc[asof].reindex(formation.columns).fillna(False)
            formation = formation.loc[:, mem]

        if verbose:
            print(
                f"  refresh {asof.date()}: formation "
                f"{formation.index[0].date()}~{formation.index[-1].date()}, "
                f"{len(groups)} sectors"
            )

        screen = screen_cointegrated_pairs(formation, groups, **screen_kwargs)
        pairs = pairs_from_screen(screen)
        half_lives: dict[tuple[str, str], float] = {}
        if not screen.empty:
            for row in screen.itertuples(index=False):
                half_lives[(str(row.y), str(row.x))] = float(row.half_life)
                logs.append(
                    {
                        "refresh_date": asof,
                        "y": row.y,
                        "x": row.x,
                        "sector": getattr(row, "sector", ""),
                        "half_life": float(row.half_life),
                        "pvalue": float(row.pvalue),
                        "score": float(row.score),
                    }
                )

        if not pairs:
            pairs = list(fallback_pairs or [])
            if verbose:
                print(f"    no pairs passed; fallback n={len(pairs)}")

        elif verbose:
            print(f"    selected {len(pairs)} pairs: {pairs}")

        # Segment: from this refresh day through day before next refresh
        j_end = refresh_points[k + 1] if k + 1 < len(refresh_points) else n
        seg_index = prices.index[i:j_end]
        if len(seg_index) == 0:
            continue

        # Need lookback history before segment for z-scores
        hist_start = max(0, i - lookback - 5)
        window_prices = prices.iloc[hist_start:j_end]
        # Suppress per-pair prints in inner builder by temporarily not printing —
        # build_stat_arb_weights always prints; pass quiet via monkeypatch or add verbose flag.
        seg_w = build_stat_arb_weights(
            window_prices,
            pairs,
            lookback=lookback,
            entry_z=entry_z,
            exit_z=exit_z,
            stop_z=stop_z,
            half_lives=half_lives,
            timeout_mult=timeout_mult,
            verbose=False,
        )
        # Only keep weights on the trade segment (not formation bleed)
        seg_w = seg_w.reindex(index=seg_index, columns=prices.columns).fillna(0.0)
        weights.loc[seg_index] = seg_w

    if membership is not None:
        weights = weights.where(membership.reindex_like(weights).fillna(False), 0.0)
        l1 = weights.abs().sum(axis=1).replace(0, np.nan)
        weights = weights.div(l1, axis=0).fillna(0.0)

    pair_log = pd.DataFrame(logs)
    return weights, pair_log

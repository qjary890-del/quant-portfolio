"""Rolling cointegration pair refresh for out-of-sample pair validation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.pair_screener import (
    filter_pair_log,
    pairs_from_screen,
    screen_cointegrated_pairs,
)

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
    primary_grouping_fn=None,
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
    logs: list[dict] = []

    n = len(prices)
    if n <= formation_days + lookback:
        raise ValueError("Not enough history for rolling pair formation")

    refresh_points = list(range(formation_days, n, refresh_days))

    for i in refresh_points:
        form_start = max(0, i - formation_days)
        form_end = i  # exclusive end for iloc; last formation day is i-1
        formation = prices.iloc[form_start:form_end]
        asof = prices.index[form_end - 1]

        raw_groups = sector_groups_fn(asof, list(formation.columns))
        groups = _trim_sector_groups(raw_groups, formation, max_names_per_sector)
        if primary_grouping_fn is not None:
            groups = primary_grouping_fn(groups, formation, asof)

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
        if not screen.empty:
            for row in screen.itertuples(index=False):
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

        if verbose:
            if pairs:
                print(f"    selected {len(pairs)} pairs: {pairs}")
            else:
                print(f"    no pairs passed; fallback n={len(fallback_pairs or [])}")

    pair_log = pd.DataFrame(logs)
    # Same builder the parameter sweeps use, so swept settings reproduce here.
    weights = weights_from_pair_log(
        prices,
        pair_log,
        lookback=lookback,
        entry_z=entry_z,
        exit_z=exit_z,
        stop_z=stop_z,
        timeout_mult=timeout_mult,
        membership=membership,
        formation_days=formation_days,
        refresh_days=refresh_days,
        fallback_pairs=fallback_pairs,
    )
    return weights, pair_log


def build_rolling_pair_pool(
    prices: pd.DataFrame,
    *,
    sector_groups_fn,
    membership: pd.DataFrame | None = None,
    formation_days: int = 504,
    refresh_days: int = 126,
    screen_kwargs: dict | None = None,
    max_names_per_sector: int = 15,
    pool_max_pairs: int = 48,
    pool_max_per_sector: int = 8,
    primary_grouping_fn=None,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Screen a rich candidate pool each refresh (high caps) for later post-filtering.
    Does not build trading weights.
    """
    base = dict(screen_kwargs or {})
    base["max_pairs"] = int(pool_max_pairs)
    base["max_per_sector"] = int(pool_max_per_sector)

    logs: list[dict] = []
    n = len(prices)
    start_i = formation_days
    refresh_points = list(range(start_i, n, refresh_days))

    for i in refresh_points:
        form_start = max(0, i - formation_days)
        formation = prices.iloc[form_start:i]
        asof = prices.index[i - 1]

        raw_groups = sector_groups_fn(asof, list(formation.columns))
        groups = _trim_sector_groups(raw_groups, formation, max_names_per_sector)
        if primary_grouping_fn is not None:
            groups = primary_grouping_fn(groups, formation, asof)

        form = formation
        if membership is not None:
            mem = membership.loc[asof].reindex(form.columns).fillna(False)
            form = form.loc[:, mem]

        if verbose:
            print(
                f"  pool refresh {asof.date()}: formation "
                f"{form.index[0].date()}~{form.index[-1].date()}, "
                f"{len(groups)} sectors"
            )

        screen = screen_cointegrated_pairs(form, groups, **base)
        if screen.empty:
            if verbose:
                print("    no pairs passed")
            continue
        if verbose:
            print(f"    pool size={len(screen)}")
        for row in screen.itertuples(index=False):
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

    return pd.DataFrame(logs)


def weights_from_pair_log(
    prices: pd.DataFrame,
    pair_log: pd.DataFrame,
    *,
    lookback: int = 60,
    entry_z: float = 2.5,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    timeout_mult: float = 2.0,
    membership: pd.DataFrame | None = None,
    formation_days: int = 504,
    refresh_days: int = 126,
    fallback_pairs: list[tuple[str, str]] | None = None,
    diagnostics_cache: dict[tuple[int, str, str], pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """
    Rebuild Stat Arb weights from a fixed rolling pair schedule (no re-screen).

    diagnostics_cache keyed by (lookback, y, x) stores full-sample pair_spread
    frames so z-parameter sweeps reuse OLS fits.
    """
    from strategies.pair_screener import _half_life
    from strategies.stat_arb import pair_positions, pair_spread

    if diagnostics_cache is None:
        diagnostics_cache = {}

    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    n = len(prices)
    start_i = formation_days
    refresh_points = list(range(start_i, n, refresh_days))

    schedule: dict[pd.Timestamp, list[tuple[str, str, float]]] = {}
    if pair_log is not None and not pair_log.empty:
        log = pair_log.copy()
        log["refresh_date"] = pd.to_datetime(log["refresh_date"])
        for asof, grp in log.groupby("refresh_date"):
            schedule[pd.Timestamp(asof).normalize()] = [
                (str(r.y), str(r.x), float(r.half_life)) for r in grp.itertuples(index=False)
            ]

    def _rows_for(asof: pd.Timestamp) -> list[tuple[str, str, float]]:
        key = pd.Timestamp(asof).normalize()
        if key in schedule:
            return schedule[key]
        return []

    # Prefetch diagnostics for this lookback
    needed: set[tuple[str, str]] = set()
    for rows in schedule.values():
        for y, x, _ in rows:
            needed.add((y, x))
    for y, x in fallback_pairs or []:
        needed.add((y, x))
    for y, x in needed:
        key = (lookback, y, x)
        if key not in diagnostics_cache and y in prices.columns and x in prices.columns:
            diagnostics_cache[key] = pair_spread(prices, y, x, lookback)

    for k, i in enumerate(refresh_points):
        asof = prices.index[i - 1]
        j_end = refresh_points[k + 1] if k + 1 < len(refresh_points) else n
        seg_index = prices.index[i:j_end]
        if len(seg_index) == 0:
            continue

        rows = _rows_for(asof)
        if not rows:
            pairs = list(fallback_pairs or [])
            half_lives: dict[tuple[str, str], float] = {}
        else:
            pairs = [(y, x) for y, x, _ in rows]
            half_lives = {(y, x): hl for y, x, hl in rows}

        seg_w = pd.DataFrame(0.0, index=seg_index, columns=prices.columns)
        for y_t, x_t in pairs:
            key = (lookback, y_t, x_t)
            diag = diagnostics_cache.get(key)
            if diag is None or diag.empty:
                continue
            z = diag["z"].reindex(seg_index)
            beta = diag["beta"].reindex(seg_index).ffill()
            hl = half_lives.get((y_t, x_t), half_lives.get((x_t, y_t)))
            if hl is None or not np.isfinite(hl):
                hl = _half_life(diag["spread"].reindex(seg_index).dropna())
            pos = pair_positions(
                z,
                entry_z,
                exit_z,
                stop_z,
                half_life=float(hl) if np.isfinite(hl) else None,
                timeout_mult=timeout_mult,
            )
            seg_w[y_t] = seg_w[y_t] + pos
            seg_w[x_t] = seg_w[x_t] - pos * beta.fillna(1.0)

        l1 = seg_w.abs().sum(axis=1).replace(0, np.nan)
        seg_w = seg_w.div(l1, axis=0).fillna(0.0)
        weights.loc[seg_index] = seg_w

    if membership is not None:
        weights = weights.where(membership.reindex_like(weights).fillna(False), 0.0)
        l1 = weights.abs().sum(axis=1).replace(0, np.nan)
        weights = weights.div(l1, axis=0).fillna(0.0)
    return weights

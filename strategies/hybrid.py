"""Hybrid allocation: agreement scaling + dynamic sleeve weights."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import combine_weights


def sleeve_gross_returns(prices: pd.DataFrame, weights: pd.DataFrame) -> pd.Series:
    """Next-day gross sleeve returns from close-to-close weights (no costs)."""
    w = weights.reindex(prices.index).fillna(0.0)
    rets = prices.pct_change().fillna(0.0)
    return (w.shift(1).fillna(0.0) * rets).sum(axis=1)


def apply_agreement_scale(
    w_stat: pd.DataFrame,
    w_cs: pd.DataFrame,
    *,
    agree_mult: float = 1.5,
    solo_mult: float = 0.5,
    conflict_mult: float = 0.25,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Scale each name by whether the two sleeves agree on direction.

    - same sign, both active  -> agree_mult
    - only one sleeve active  -> solo_mult
    - opposite signs          -> conflict_mult
    """
    a = w_stat.reindex_like(w_cs).fillna(0.0)
    b = w_cs.reindex_like(w_stat).fillna(0.0)
    # align columns
    cols = sorted(set(a.columns) | set(b.columns))
    a = a.reindex(columns=cols, fill_value=0.0)
    b = b.reindex(columns=cols, fill_value=0.0)

    active_a = a.abs() > 1e-12
    active_b = b.abs() > 1e-12
    same = np.sign(a) == np.sign(b)
    agree = active_a & active_b & same
    conflict = active_a & active_b & ~same
    solo = (active_a ^ active_b)

    scale = pd.DataFrame(1.0, index=a.index, columns=cols)
    scale = scale.mask(solo, solo_mult)
    scale = scale.mask(agree, agree_mult)
    scale = scale.mask(conflict, conflict_mult)

    a_scaled = a * scale
    b_scaled = b * scale

    # L1 renorm each sleeve when active
    def _renorm(w: pd.DataFrame) -> pd.DataFrame:
        l1 = w.abs().sum(axis=1).replace(0, np.nan)
        return w.div(l1, axis=0).fillna(0.0)

    return _renorm(a_scaled), _renorm(b_scaled), scale


def apply_agree_book_gross(
    weights: pd.DataFrame,
    scale: pd.DataFrame,
    *,
    agree_mult: float,
    book_gross_max: float = 1.25,
) -> pd.Series:
    """
    Expand total book gross toward `book_gross_max` in proportion to
    how much of |w| sits on agreement names. Returns a daily multiplier series.
    """
    sc = scale.reindex(index=weights.index, columns=weights.columns).fillna(1.0)
    agree_mask = np.isclose(sc.astype(float), float(agree_mult))
    abs_w = weights.abs()
    total = abs_w.sum(axis=1).replace(0, np.nan)
    agree_gross = abs_w.where(agree_mask, 0.0).sum(axis=1)
    frac = (agree_gross / total).fillna(0.0).clip(0.0, 1.0)
    return 1.0 + (float(book_gross_max) - 1.0) * frac


def rolling_sleeve_scores(
    sleeve_rets: dict[str, pd.Series],
    *,
    lookback: int = 60,
    ann: int = 252,
    min_periods: int | None = None,
) -> pd.DataFrame:
    """
    Rolling Sharpe-like score per sleeve (shifted by 1 to avoid look-ahead).

    score_t uses returns in [t-lookback, t-1].
    """
    min_periods = min_periods or max(lookback // 2, 10)
    scores = {}
    for name, r in sleeve_rets.items():
        mu = r.rolling(lookback, min_periods=min_periods).mean()
        sd = r.rolling(lookback, min_periods=min_periods).std(ddof=0)
        sharpe = (mu / sd.replace(0, np.nan)) * np.sqrt(ann)
        # Inverse-vol tilt blended with sharpe (floor sharpe at 0 for weights)
        inv_vol = 1.0 / sd.replace(0, np.nan)
        # Positive-part sharpe * inv_vol for allocation attractiveness
        scores[name] = (sharpe.clip(lower=0.0) + 0.25) * inv_vol
    out = pd.DataFrame(scores).shift(1)  # available next morning / for today's weights
    return out


def dynamic_sleeve_mix(
    scores: pd.DataFrame,
    *,
    floor: float = 0.2,
    ceil: float = 0.8,
) -> pd.DataFrame:
    """
    Convert rolling scores to daily sleeve weights that sum to 1.
    Each sleeve weight is clipped to [floor, ceil] then renormed.
    """
    raw = scores.clip(lower=0.0).fillna(0.0)
    # If all zero, equal weight
    row_sum = raw.sum(axis=1).replace(0, np.nan)
    w = raw.div(row_sum, axis=0)
    equal = 1.0 / max(len(scores.columns), 1)
    w = w.fillna(equal)
    w = w.clip(lower=floor, upper=ceil)
    w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(equal)
    return w


def combine_with_dynamic_mix(
    sleeves: dict[str, pd.DataFrame],
    mix: pd.DataFrame,
) -> pd.DataFrame:
    """Time-varying sleeve capital mix (rows of mix sum to 1)."""
    cols = sorted({c for w in sleeves.values() for c in w.columns})
    idx = mix.index
    combined = pd.DataFrame(0.0, index=idx, columns=cols)
    for name, w in sleeves.items():
        if name not in mix.columns:
            continue
        ww = w.reindex(index=idx, columns=cols).fillna(0.0)
        combined = combined.add(ww.mul(mix[name], axis=0), fill_value=0.0)
    l1 = combined.abs().sum(axis=1).replace(0, np.nan)
    return combined.div(l1, axis=0).fillna(0.0)


def build_hybrid_portfolio(
    prices: pd.DataFrame,
    w_stat: pd.DataFrame,
    w_cs: pd.DataFrame,
    *,
    lookback: int = 60,
    agree_mult: float = 1.5,
    solo_mult: float = 0.5,
    conflict_mult: float = 0.25,
    mix_floor: float = 0.2,
    mix_ceil: float = 0.8,
    ann: int = 252,
) -> dict[str, pd.DataFrame | pd.Series]:
    """
    1) Agreement-scale both sleeves
    2) Dynamic mix from rolling sleeve scores
    """
    w_s, w_c, scale = apply_agreement_scale(
        w_stat,
        w_cs,
        agree_mult=agree_mult,
        solo_mult=solo_mult,
        conflict_mult=conflict_mult,
    )
    rets = {
        "stat_arb": sleeve_gross_returns(prices, w_s),
        "cross_section": sleeve_gross_returns(prices, w_c),
    }
    scores = rolling_sleeve_scores(rets, lookback=lookback, ann=ann)
    mix = dynamic_sleeve_mix(scores, floor=mix_floor, ceil=mix_ceil)
    combined = combine_with_dynamic_mix(
        {"stat_arb": w_s, "cross_section": w_c},
        mix,
    )
    static = combine_weights(
        {"stat_arb": w_s, "cross_section": w_c},
        {"stat_arb": 0.5, "cross_section": 0.5},
    )
    return {
        "w_stat_scaled": w_s,
        "w_cs_scaled": w_c,
        "agreement_scale": scale,
        "sleeve_mix": mix,
        "combined_dynamic": combined,
        "combined_agree_static": static,
        "score_stat": scores.get("stat_arb", pd.Series(dtype=float)),
        "score_cs": scores.get("cross_section", pd.Series(dtype=float)),
    }


def compare_lookbacks(
    prices: pd.DataFrame,
    w_stat: pd.DataFrame,
    w_cs: pd.DataFrame,
    lookbacks: list[int],
    *,
    run_backtest_fn,
    bt_kwargs: dict,
    agree_mult: float = 1.5,
    solo_mult: float = 0.5,
    conflict_mult: float = 0.25,
) -> pd.DataFrame:
    """Sensitivity of hybrid Sharpe/CAGR/MDD to sleeve-score lookback."""
    rows = []
    for lb in lookbacks:
        hybrid = build_hybrid_portfolio(
            prices,
            w_stat,
            w_cs,
            lookback=lb,
            agree_mult=agree_mult,
            solo_mult=solo_mult,
            conflict_mult=conflict_mult,
        )
        res = run_backtest_fn(prices, hybrid["combined_dynamic"], **bt_kwargs)
        rows.append(
            {
                "lookback": lb,
                "cagr": res.stats.get("cagr"),
                "sharpe": res.stats.get("sharpe"),
                "max_drawdown": res.stats.get("max_drawdown"),
                "ann_turnover": res.stats.get("ann_turnover"),
                "total_cost_drag": res.stats.get("total_cost_drag"),
                "avg_stat_weight": float(hybrid["sleeve_mix"]["stat_arb"].mean()),
                "avg_cs_weight": float(hybrid["sleeve_mix"]["cross_section"].mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("lookback").reset_index(drop=True)

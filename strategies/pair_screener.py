"""Sector-aware cointegration pair screener (Engle-Granger + half-life)."""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from statsmodels.tsa.stattools import coint


def _half_life(spread: pd.Series) -> float:
    """OU / AR(1) half-life in days. Returns nan if not mean-reverting."""
    s = spread.dropna()
    if len(s) < 30:
        return float("nan")
    lag = s.shift(1).iloc[1:]
    delta = s.diff().iloc[1:]
    aligned = pd.concat([delta, lag], axis=1).dropna()
    if len(aligned) < 20:
        return float("nan")
    model = OLS(aligned.iloc[:, 0], add_constant(aligned.iloc[:, 1])).fit()
    phi = float(model.params.iloc[1])
    ar = 1.0 + phi
    if ar <= 0 or ar >= 1:
        return float("nan")
    return float(-np.log(2.0) / np.log(ar))


def return_corr(a: pd.Series, b: pd.Series) -> float:
    """Daily return correlation (formation-window friendly pre-filter)."""
    rets = pd.concat([a.pct_change(), b.pct_change()], axis=1).dropna()
    if len(rets) < 30:
        return float("nan")
    return float(rets.iloc[:, 0].corr(rets.iloc[:, 1]))


def half_life_weight(half_life: float, target: float = 15.0) -> float:
    """1 near target half-life (e.g. 15d); decays as Gaussian distance."""
    if not np.isfinite(half_life) or target <= 0:
        return 0.0
    return float(np.exp(-((abs(half_life - target) / target) ** 2)))


def engle_granger(
    y: pd.Series,
    x: pd.Series,
) -> tuple[float, float, float]:
    """
    Returns (pvalue, hedge_ratio, half_life).
    pvalue from Engle-Granger cointegration test on log prices if positive.
    """
    aligned = pd.concat([y, x], axis=1).dropna()
    if len(aligned) < 60:
        return float("nan"), float("nan"), float("nan")

    if (aligned > 0).all().all():
        y_v = np.log(aligned.iloc[:, 0])
        x_v = np.log(aligned.iloc[:, 1])
    else:
        y_v = aligned.iloc[:, 0]
        x_v = aligned.iloc[:, 1]

    try:
        _, pvalue, _ = coint(y_v, x_v, trend="c", autolag="aic")
    except Exception:
        return float("nan"), float("nan"), float("nan")

    ols = OLS(y_v, add_constant(x_v)).fit()
    beta = float(ols.params.iloc[1])
    resid = y_v - (float(ols.params.iloc[0]) + beta * x_v)
    hl = _half_life(resid)
    return float(pvalue), beta, hl


def best_direction_engle_granger(
    a: pd.Series,
    b: pd.Series,
    ticker_a: str,
    ticker_b: str,
) -> dict[str, float | str]:
    """
    Test both coint(a,b) and coint(b,a); keep the lower p-value direction.
    Returns dict with y, x, pvalue, beta, half_life (nan fields if both fail).
    """
    p_ab, beta_ab, hl_ab = engle_granger(a, b)
    p_ba, beta_ba, hl_ba = engle_granger(b, a)

    ab_ok = np.isfinite(p_ab)
    ba_ok = np.isfinite(p_ba)
    if not ab_ok and not ba_ok:
        return {
            "y": ticker_a,
            "x": ticker_b,
            "pvalue": float("nan"),
            "beta": float("nan"),
            "half_life": float("nan"),
        }
    if ab_ok and (not ba_ok or p_ab <= p_ba):
        return {
            "y": ticker_a,
            "x": ticker_b,
            "pvalue": p_ab,
            "beta": beta_ab,
            "half_life": hl_ab,
        }
    return {
        "y": ticker_b,
        "x": ticker_a,
        "pvalue": p_ba,
        "beta": beta_ba,
        "half_life": hl_ba,
    }


def rolling_coint_pass_rate(
    y: pd.Series,
    x: pd.Series,
    *,
    window: int,
    step: int,
    pvalue_max: float,
) -> float:
    """Fraction of rolling windows that still reject no-cointegration (fixed direction)."""
    aligned = pd.concat([y, x], axis=1).dropna()
    if len(aligned) < window:
        return 0.0
    passes = 0
    total = 0
    for start in range(0, len(aligned) - window + 1, step):
        chunk = aligned.iloc[start : start + window]
        pval, _, _ = engle_granger(chunk.iloc[:, 0], chunk.iloc[:, 1])
        total += 1
        if np.isfinite(pval) and pval <= pvalue_max:
            passes += 1
    return passes / total if total else 0.0


def candidate_pairs(sector_groups: dict[str, list[str]]) -> list[tuple[str, str, str]]:
    """All unordered pairs within each sector: (sector, a, b)."""
    out: list[tuple[str, str, str]] = []
    for sector, names in sector_groups.items():
        uniq = sorted(set(names))
        for a, b in combinations(uniq, 2):
            out.append((sector, a, b))
    return out


def screen_cointegrated_pairs(
    prices: pd.DataFrame,
    sector_groups: dict[str, list[str]],
    *,
    pvalue_max: float = 0.05,
    min_half_life: float = 5.0,
    max_half_life: float = 60.0,
    target_half_life: float = 15.0,
    min_corr: float = 0.55,
    stability_window: int = 126,
    stability_step: int = 63,
    min_stability: float = 0.0,
    max_pairs: int = 12,
    max_per_sector: int | None = 3,
) -> pd.DataFrame:
    """
    Screen intra-sector pairs on the formation sample.

    Pipeline
    --------
    1) sector combinations
    2) return-corr pre-filter (cheap)
    3) bidirectional Engle-Granger; keep lower-p direction
    4) half-life band filter
    5) optional rolling stability (chosen direction only)
    6) score = (-log10 p) * (0.5+0.5*stability) * corr * w_HL
    7) take top scores with optional per-sector cap, then max_pairs
    """
    rows: list[dict] = []
    n_candidates = 0
    n_after_corr = 0

    for sector, a, b in candidate_pairs(sector_groups):
        if a not in prices.columns or b not in prices.columns:
            continue
        n_candidates += 1

        # --- cheap pre-filter before any EG ---
        ret_corr = return_corr(prices[a], prices[b])
        if not np.isfinite(ret_corr) or ret_corr < min_corr:
            continue
        n_after_corr += 1

        best = best_direction_engle_granger(prices[a], prices[b], a, b)
        pval = float(best["pvalue"])
        if not np.isfinite(pval) or pval > pvalue_max or pval <= 0:
            continue

        hl = float(best["half_life"])
        if not np.isfinite(hl) or hl < min_half_life or hl > max_half_life:
            continue

        y_t = str(best["y"])
        x_t = str(best["x"])
        stability = rolling_coint_pass_rate(
            prices[y_t],
            prices[x_t],
            window=stability_window,
            step=stability_step,
            pvalue_max=min(pvalue_max * 2, 0.10),
        )
        if stability < min_stability:
            continue

        w_hl = half_life_weight(hl, target=target_half_life)
        score = (
            float(-np.log10(pval))
            * (0.5 + 0.5 * stability)
            * max(ret_corr, 0.0)
            * w_hl
        )
        rows.append(
            {
                "sector": sector,
                "y": y_t,
                "x": x_t,
                "pvalue": pval,
                "beta": float(best["beta"]),
                "half_life": hl,
                "hl_weight": w_hl,
                "ret_corr": ret_corr,
                "stability": stability,
                "neg_log10_p": float(-np.log10(pval)),
                "score": score,
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        empty = result
        empty.attrs["n_candidates"] = n_candidates
        empty.attrs["n_after_corr"] = n_after_corr
        return empty

    ranked = result.sort_values("score", ascending=False).reset_index(drop=True)
    ranked = select_top_pairs(
        ranked, max_pairs=max_pairs, max_per_sector=max_per_sector
    )

    ranked.attrs["n_candidates"] = n_candidates
    ranked.attrs["n_after_corr"] = n_after_corr
    return ranked


def pairs_from_screen(screen: pd.DataFrame) -> list[tuple[str, str]]:
    return [(str(r.y), str(r.x)) for r in screen.itertuples(index=False)]


def select_top_pairs(
    candidates: pd.DataFrame,
    *,
    max_pairs: int = 12,
    max_per_sector: int | None = 3,
) -> pd.DataFrame:
    """Rank by score, apply per-sector cap, then global max_pairs."""
    if candidates is None or candidates.empty:
        return candidates.copy() if candidates is not None else pd.DataFrame()
    ranked = candidates.sort_values("score", ascending=False).reset_index(drop=True)
    if max_per_sector is not None and max_per_sector > 0:
        picked: list[pd.Series] = []
        counts: dict[str, int] = {}
        for _, row in ranked.iterrows():
            sec = str(row["sector"])
            if counts.get(sec, 0) >= max_per_sector:
                continue
            picked.append(row)
            counts[sec] = counts.get(sec, 0) + 1
            if len(picked) >= max_pairs:
                break
        return pd.DataFrame(picked).reset_index(drop=True)
    return ranked.head(max_pairs).reset_index(drop=True)


def filter_pair_log(
    pair_log: pd.DataFrame,
    *,
    max_pairs: int,
    max_per_sector: int | None,
) -> pd.DataFrame:
    """Per refresh_date, keep top pairs under caps (expects a rich candidate pool)."""
    if pair_log is None or pair_log.empty:
        return pair_log.copy() if pair_log is not None else pd.DataFrame()
    log = pair_log.copy()
    log["refresh_date"] = pd.to_datetime(log["refresh_date"])
    chunks: list[pd.DataFrame] = []
    for asof, grp in log.groupby("refresh_date", sort=True):
        picked = select_top_pairs(grp, max_pairs=max_pairs, max_per_sector=max_per_sector)
        if not picked.empty:
            chunks.append(picked)
    if not chunks:
        return pd.DataFrame(columns=log.columns)
    return pd.concat(chunks, ignore_index=True)

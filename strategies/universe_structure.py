"""Pair-candidate grouping applied after GICS sector groups, before cointegration."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform


def correlation_clusters(
    formation: pd.DataFrame,
    names: list[str],
    *,
    min_corr: float,
    max_size: int,
    min_obs: int = 120,
) -> list[list[str]]:
    """
    Average-linkage clusters on formation-window daily return correlation.
    A cluster's members average at least `min_corr` pairwise correlation.
    Oversized clusters keep the `max_size` names with highest mean intra-cluster corr.
    """
    names = [n for n in names if n in formation.columns]
    if len(names) < 2:
        return []
    corr = formation[names].pct_change().corr(min_periods=min_obs)
    corr = corr.dropna(how="all").dropna(axis=1, how="all")
    if len(corr) < 2:
        return []
    dist = (1.0 - corr.fillna(0.0)).clip(lower=0.0).to_numpy(copy=True)
    np.fill_diagonal(dist, 0.0)
    labels = fcluster(
        linkage(squareform(dist, checks=False), method="average"),
        t=1.0 - min_corr,
        criterion="distance",
    )
    clusters: list[list[str]] = []
    for lab in np.unique(labels):
        members = list(corr.index[labels == lab])
        if len(members) < 2:
            continue
        if len(members) > max_size:
            mean_corr = corr.loc[members, members].mean(axis=1)
            members = list(mean_corr.sort_values(ascending=False).index[:max_size])
        clusters.append(sorted(members))
    return clusters


def make_primary_grouping_fn(mode: str | None, *, min_corr: float = 0.5, max_size: int = 15):
    """
    Stage 1 grouping: fn(groups, formation, asof) -> groups. None passes sector groups through.

    corr_cluster         replace sectors with return-correlation clusters (cross-sector allowed)
    sector_corr_cluster  split each sector into return-correlation clusters
    """
    if mode is None:
        return None

    if mode == "corr_cluster":

        def _cross(groups, formation, asof):
            names = sorted({n for members in groups.values() for n in members})
            clusters = correlation_clusters(formation, names, min_corr=min_corr, max_size=max_size)
            return {f"C{k}": members for k, members in enumerate(clusters)}

        return _cross

    if mode == "sector_corr_cluster":

        def _within(groups, formation, asof):
            out: dict[str, list[str]] = {}
            for sector, members in groups.items():
                clusters = correlation_clusters(
                    formation, members, min_corr=min_corr, max_size=max_size
                )
                for k, cl in enumerate(clusters):
                    out[f"{sector}#{k}"] = cl
            return out

        return _within

    raise ValueError(f"Unknown PRIMARY_GROUPING: {mode!r}")

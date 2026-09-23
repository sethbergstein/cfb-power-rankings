"""Quality / efficiency features for BCPI."""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import pandas as pd

from bcpi.games import (
    GameResult,
    compress_margin,
    effective_margin_for_rating,
    filter_games_through_week,
)
from bcpi.params import ModelParams
from bcpi.recency import blend_form_season, recency_weight


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0, skipna=True)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index).where(series.notna())
    return (series - series.mean(skipna=True)) / std


def compute_form(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
    params: ModelParams,
    opponent_ratings: Dict[str, float],
) -> pd.Series:
    """
    Opponent-adjusted scoring form from FBS games (no lookahead).

    Each game scores the compressed neutral-field margin minus the compressed
    margin an average FBS team would be expected to post against the same
    opponent. Recency-weighted mean; NaN for teams without an FBS game.
    """
    rated = [opponent_ratings[school] for school in schools if school in opponent_ratings]
    if not rated:
        return pd.Series(float("nan"), index=schools)
    mean_rating = sum(rated) / len(rated)
    scale = params.margin_compression
    sums: Dict[str, List[float]] = {school: [0.0, 0.0] for school in schools}

    for game in filter_games_through_week(games, current_week):
        if not game.is_fbs_game or not game.completed:
            continue
        weight = recency_weight(current_week, game.week, lambda_=params.recency_lambda)
        for team, opp in ((game.home_team, game.away_team), (game.away_team, game.home_team)):
            if team not in sums or opp not in opponent_ratings:
                continue
            margin = effective_margin_for_rating(game, team, params)
            baseline = (mean_rating - opponent_ratings[opp]) / params.margin_scale
            sums[team][0] += weight * (
                compress_margin(margin, scale) - compress_margin(baseline, scale)
            )
            sums[team][1] += weight

    return pd.Series(
        {school: (total / weight if weight > 0 else float("nan")) for school, (total, weight) in sums.items()}
    )


def efficiency_score(
    game_quality: Optional[pd.DataFrame],
    schools: List[str],
    params: ModelParams,
) -> pd.Series:
    """Weighted mean of z-scored efficiency differentials; NaN without data."""
    if game_quality is None or game_quality.empty:
        return pd.Series(float("nan"), index=schools)
    total = pd.Series(0.0, index=schools)
    weight_sum = pd.Series(0.0, index=schools)
    for metric, weight in params.quality_weights.items():
        if weight <= 0 or metric not in game_quality.columns:
            continue
        z = _zscore(game_quality[metric].astype(float)).reindex(schools)
        valid = z.notna()
        total[valid] += weight * z[valid]
        weight_sum[valid] += weight
    return (total / weight_sum).where(weight_sum > 0)


def build_walkforward_quality_z(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
    params: ModelParams,
    game_quality: Optional[pd.DataFrame] = None,
    opponent_ratings: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    In-season quality: ``form_weight`` x z(form) + the rest x efficiency.

    Uses only games through ``current_week``. NaN for teams without an FBS game,
    so the composite can fall back to the preseason prior for them.
    """
    form_z = _zscore(
        compute_form(games, schools, current_week, params, opponent_ratings or {}).astype(float)
    )
    efficiency = efficiency_score(game_quality, schools, params)
    return pd.Series(
        {
            school: blend_form_season(
                float(form_z.get(school, math.nan)),
                float(efficiency.get(school, math.nan)),
                form_weight=params.form_weight,
            )
            for school in schools
        }
    )

"""Quality / efficiency features for BCPI."""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from bcpi.constants import RATING_MEAN
from bcpi.games import (
    GameResult,
    effective_margin_for_rating,
    filter_games_through_week,
    opponent_key,
)
from bcpi.game_stats import elite_opponent_set, opponent_quality_multiplier
from bcpi.params import ModelParams
from bcpi.recency import blend_form_season, recency_weight


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _cap_form_margin(margin: float, params: ModelParams) -> float:
    cap = params.form_margin_cap
    if margin > cap:
        return cap
    if margin < -cap:
        return -cap
    return margin


def compute_form_margins(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
    params: ModelParams,
    form_games: int = 3,
    opponent_ratings: Optional[Dict[str, float]] = None,
    elite_opponents: Optional[set] = None,
) -> pd.Series:
    """Recency-weighted scoring margins from FBS games only (no lookahead)."""
    ratings = opponent_ratings or {}
    margins: Dict[str, List[tuple]] = {school: [] for school in schools}

    for game in filter_games_through_week(games, current_week):
        if not game.is_fbs_game:
            continue
        recency = recency_weight(
            current_week,
            game.week,
            lambda_=params.recency_lambda,
        )
        for team in (game.home_team, game.away_team):
            margin = effective_margin_for_rating(game, team, params)
            if margin is None:
                continue
            opp = opponent_key(game, team)
            if elite_opponents is not None and (opp is None or opp not in elite_opponents):
                continue
            opp_rating = ratings.get(opp, RATING_MEAN) if opp else RATING_MEAN
            weight = recency * opponent_quality_multiplier(opp_rating, params)
            margins[team].append((_cap_form_margin(margin, params), weight))

    form_values = {}
    for school in schools:
        values = margins.get(school, [])
        if not values:
            form_values[school] = 0.0
            continue
        recent = sorted(values, key=lambda x: x[1], reverse=True)[:form_games]
        weight_sum = sum(weight for _, weight in recent)
        form_values[school] = (
            sum(margin * weight for margin, weight in recent) / weight_sum
            if weight_sum
            else 0.0
        )
    return pd.Series(form_values)


def build_walkforward_quality_z(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
    params: ModelParams,
    season_quality: Optional[pd.DataFrame] = None,
    opponent_ratings: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    Quality z-score for walk-forward evaluation.

    Uses form margins only when season_quality is omitted (avoids lookahead).
    Live pipeline can pass cumulative season advanced stats when appropriate.
    """
    ratings = opponent_ratings or {}
    elite_set = elite_opponent_set(ratings, schools, params.elite_opponent_top_n)

    form_all = compute_form_margins(
        games, schools, current_week, params, opponent_ratings=ratings
    )
    form_elite = compute_form_margins(
        games,
        schools,
        current_week,
        params,
        opponent_ratings=ratings,
        elite_opponents=elite_set,
    )

    form_values: Dict[str, float] = {}
    filtered_games = [
        g for g in filter_games_through_week(games, current_week) if g.is_fbs_game
    ]
    for school in schools:
        all_val = float(form_all.get(school, 0.0))
        elite_val = float(form_elite.get(school, 0.0))
        has_elite = any(
            (g.home_team == school and g.away_team in elite_set)
            or (g.away_team == school and g.home_team in elite_set)
            for g in filtered_games
            if school in (g.home_team, g.away_team)
        )
        if has_elite and params.elite_quality_weight > 0:
            ew = params.elite_quality_weight
            form_values[school] = ew * elite_val + (1.0 - ew) * all_val
        else:
            form_values[school] = all_val
    form_margin = pd.Series(form_values)
    form_z = _zscore(form_margin.astype(float))

    if season_quality is None or season_quality.empty:
        return form_z.reindex(schools).fillna(0.0)

    season_quality_score = pd.Series(0.0, index=schools)
    for metric, weight in params.quality_weights.items():
        if metric in season_quality.columns:
            season_quality_score += weight * _zscore(
                season_quality[metric].astype(float)
            ).reindex(schools).fillna(0.0)

    blended = pd.Series(
        {
            school: blend_form_season(
                float(form_z.get(school, 0.0)),
                float(season_quality_score.get(school, 0.0)),
                form_weight=params.form_weight,
            )
            for school in schools
        }
    )
    return blended


def load_season_quality_table(
    advanced_rows: List[dict],
    schools: List[str],
    params: ModelParams,
) -> pd.DataFrame:
    """Build quality metric columns from CFBD advanced season stats."""
    frame = pd.DataFrame(advanced_rows)
    if frame.empty:
        return pd.DataFrame(index=schools)

    frame = frame[frame["team"].isin(schools)].copy()
    frame = frame.set_index("team")

    offense = frame.get("offense", pd.Series(dtype=object))
    defense = frame.get("defense", pd.Series(dtype=object))

    quality = pd.DataFrame(index=frame.index)
    quality["epa_off"] = offense.map(lambda d: d.get("ppa") if isinstance(d, dict) else None)
    quality["epa_def"] = defense.map(lambda d: d.get("ppa") if isinstance(d, dict) else None)
    quality["success_off"] = offense.map(
        lambda d: d.get("successRate") if isinstance(d, dict) else None
    )
    quality["success_def"] = defense.map(
        lambda d: d.get("successRate") if isinstance(d, dict) else None
    )
    quality["explosiveness_off"] = offense.map(
        lambda d: d.get("explosiveness") if isinstance(d, dict) else None
    )
    quality["explosiveness_def"] = defense.map(
        lambda d: d.get("explosiveness") if isinstance(d, dict) else None
    )
    quality["pass_off"] = offense.map(
        lambda d: d.get("passingPlays", {}).get("ppa") if isinstance(d, dict) else None
    )
    quality["pass_def"] = defense.map(
        lambda d: d.get("passingPlays", {}).get("ppa") if isinstance(d, dict) else None
    )
    quality["havoc_off"] = offense.map(
        lambda d: d.get("havoc", {}).get("total") if isinstance(d, dict) else None
    )
    quality["havoc_def"] = defense.map(
        lambda d: d.get("havoc", {}).get("total") if isinstance(d, dict) else None
    )

    quality["epa_diff"] = quality["epa_off"] - quality["epa_def"]
    quality["success_diff"] = quality["success_off"] - quality["success_def"]
    quality["explosiveness_diff"] = quality["explosiveness_off"] - quality["explosiveness_def"]
    quality["passing_diff"] = quality["pass_off"] - quality["pass_def"]
    quality["havoc_diff"] = quality["havoc_def"] - quality["havoc_off"]

    return quality.reindex(schools)

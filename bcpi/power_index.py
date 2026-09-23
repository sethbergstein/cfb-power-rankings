"""Composite Bergstein CFB Power Index."""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from bcpi.constants import RATING_MEAN, RATING_SPREAD
from bcpi.games import GameResult, filter_games_through_week, team_records
from bcpi.game_stats import (
    aggregate_game_quality,
    build_team_game_logs,
    load_season_game_advanced,
)
from bcpi.head_to_head import head_to_head_adjustments
from bcpi.params import ModelParams
from bcpi.quality import build_walkforward_quality_z
from bcpi.recency import sample_credibility
from bcpi.solver import TeamRatingState


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0, skipna=True)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index).where(series.notna())
    return (series - series.mean(skipna=True)) / std


def _rating_from_z(z: float) -> float:
    return RATING_MEAN + z * (RATING_SPREAD / 2.5)


def _solver_ratings(states: Dict[str, TeamRatingState]) -> Dict[str, float]:
    return {school: state.rating for school, state in states.items()}


def fbs_games_played(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
) -> pd.Series:
    """Completed FBS-vs-FBS games per team (the games that feed quality)."""
    counts = {school: 0 for school in schools}
    for game in filter_games_through_week(games, current_week):
        if not game.is_fbs_game or not game.completed:
            continue
        for team in (game.home_team, game.away_team):
            if team in counts:
                counts[team] += 1
    return pd.Series(counts, dtype=float)


def build_power_components(
    schools: List[str],
    solver_states: Dict[str, TeamRatingState],
    prior_ratings: Dict[str, float],
    games: List[GameResult],
    current_week: int,
    params: ModelParams,
    game_quality: Optional[pd.DataFrame] = None,
    opponent_ratings: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """
    power score = solver weight x z(solver rating)
                + in-season weight x [c x quality + (1 - c) x z(prior)]

    c = min(FBS games / power_sample_games, 1): quality replaces the preseason
    prior as a team's own sample grows. Teams without quality data use the prior.
    A site-adjusted head-to-head step then closes small gaps between a winner
    and the team it beat.
    """
    ratings = opponent_ratings or _solver_ratings(solver_states)
    quality_z = build_walkforward_quality_z(
        games=games,
        schools=schools,
        current_week=current_week,
        params=params,
        game_quality=game_quality,
        opponent_ratings=ratings,
    ).reindex(schools)

    solver_rating = pd.Series(
        {s: solver_states[s].rating if s in solver_states else RATING_MEAN for s in schools}
    )
    prior_rating = pd.Series({s: prior_ratings.get(s, RATING_MEAN) for s in schools})
    market_value = pd.Series(
        {
            s: (
                solver_states[s].market_value
                if s in solver_states and solver_states[s].market_weight > 0
                else float("nan")
            )
            for s in schools
        }
    )

    solver_z = _zscore(solver_rating.astype(float)).fillna(0.0)
    prior_z = _zscore(prior_rating.astype(float)).fillna(0.0)
    market_z = _zscore(market_value.astype(float))

    n_fbs = fbs_games_played(games, schools, current_week).reindex(schools).fillna(0.0)
    cred = sample_credibility(n_fbs, params.power_sample_games)
    if not isinstance(cred, pd.Series):
        cred = pd.Series(float(cred), index=schools)

    solver_w = params.power_weights.get("solver", 0.0)
    quality_w = params.power_weights.get("quality", 0.0)
    market_w = params.power_weights.get("market", 0.0)
    in_season = quality_w * quality_z.fillna(prior_z) + market_w * market_z.fillna(prior_z)
    base = solver_w * solver_z + cred * in_season + (1.0 - cred) * (quality_w + market_w) * prior_z

    h2h = head_to_head_adjustments(
        base,
        games,
        current_week,
        window=params.h2h_window,
        max_total=params.h2h_max_total,
        site_adjusted=params.h2h_site_adjusted,
        params=params,
    )
    score = base + h2h

    records = team_records(games, schools, current_week, fbs_only=False)
    components = pd.DataFrame(index=schools)
    components["solver_rating"] = solver_rating
    components["solver_iterations"] = [
        solver_states[s].solver_iterations if s in solver_states else 0 for s in schools
    ]
    components["solver_max_change"] = [
        solver_states[s].solver_max_change if s in solver_states else 0.0 for s in schools
    ]
    components["solver_z"] = solver_z
    components["quality_z"] = quality_z
    components["prior_rating"] = prior_rating
    components["prior_z"] = prior_z
    components["market_z"] = market_z
    components["fbs_games"] = n_fbs.astype(int)
    components["credibility"] = cred
    components["h2h_adjustment"] = h2h
    components["power_score"] = score
    components["power_rating"] = score.map(lambda z: _rating_from_z(float(z)))
    components["wins"] = [records[s][0] for s in schools]
    components["losses"] = [records[s][1] for s in schools]
    components["rank"] = components["power_rating"].rank(ascending=False, method="min").astype(int)
    return components.sort_values("rank")


def build_power_index_from_client(
    client,
    season: int,
    schools: List[str],
    solver_states: Dict[str, TeamRatingState],
    prior_ratings: Dict[str, float],
    games: List[GameResult],
    current_week: int,
    params: ModelParams,
    include_postseason: bool = False,
) -> pd.DataFrame:
    opponent_ratings = _solver_ratings(solver_states)
    game_stats = load_season_game_advanced(
        client,
        season,
        include_postseason=include_postseason,
        exclude_garbage_time=params.exclude_garbage_time,
    )
    team_logs = build_team_game_logs(game_stats, games, schools)
    game_quality = aggregate_game_quality(
        team_logs,
        schools,
        through_week=current_week,
        current_week=current_week,
        params=params,
        opponent_ratings=opponent_ratings,
    )
    return build_power_components(
        schools=schools,
        solver_states=solver_states,
        prior_ratings=prior_ratings,
        games=games,
        current_week=current_week,
        params=params,
        game_quality=game_quality,
        opponent_ratings=opponent_ratings,
    )

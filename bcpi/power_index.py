"""Quality metrics and composite Bergstein CFB Power Index."""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from bcpi.constants import RATING_MEAN, RATING_SPREAD
from bcpi.games import GameResult, filter_games_through_week
from bcpi.params import ModelParams
from bcpi.priors import decay_prior_weight
from bcpi.game_stats import (
    aggregate_game_quality,
    build_team_game_logs,
    load_season_game_advanced,
)
from bcpi.quality import build_walkforward_quality_z, load_season_quality_table
from bcpi.recency import recency_weight
from bcpi.solver import TeamRatingState


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _rating_from_z(z: float) -> float:
    return RATING_MEAN + z * (RATING_SPREAD / 2.5)


def _solver_ratings(states: Dict[str, TeamRatingState]) -> Dict[str, float]:
    return {school: state.rating for school, state in states.items()}


def _apply_head_to_head_nudge(
    scores: pd.Series,
    games: List[GameResult],
    current_week: int,
    params: ModelParams,
) -> pd.Series:
    """Penalize teams ranked above opponents that beat them head-to-head."""
    if params.h2h_penalty <= 0:
        return scores

    adjusted = scores.copy()
    loser_penalties: Dict[str, float] = {}

    for game in filter_games_through_week(games, current_week):
        if not game.is_fbs_game or not game.completed or game.margin_home == 0:
            continue
        if game.margin_home > 0:
            winner, loser = game.home_team, game.away_team
        else:
            winner, loser = game.away_team, game.home_team
        if winner not in adjusted.index or loser not in adjusted.index:
            continue
        if adjusted[loser] <= adjusted[winner]:
            continue

        weight = (
            recency_weight(current_week, game.week, params.recency_lambda)
            if params.h2h_use_recency
            else 1.0
        )
        penalty = params.h2h_penalty * weight
        remaining = params.h2h_max_total - loser_penalties.get(loser, 0.0)
        if remaining <= 0:
            continue
        penalty = min(penalty, remaining)
        loser_penalties[loser] = loser_penalties.get(loser, 0.0) + penalty
        adjusted[loser] -= penalty
        adjusted[winner] += penalty * params.h2h_winner_boost

    return adjusted


def _apply_playoff_path_bonus(
    scores: pd.Series,
    games: List[GameResult],
    current_week: int,
    params: ModelParams,
) -> pd.Series:
    """Modest bonus for CFP appearance and playoff wins."""
    if params.playoff_appearance_bonus <= 0 and params.playoff_win_bonus <= 0:
        return scores

    adjusted = scores.copy()
    for team in adjusted.index:
        cfp_games = [
            g
            for g in filter_games_through_week(games, current_week)
            if g.is_fbs_game and g.completed and g.is_cfp and team in (g.home_team, g.away_team)
        ]
        if not cfp_games:
            continue
        adjusted[team] += params.playoff_appearance_bonus
        wins = sum(
            1
            for g in cfp_games
            if (g.home_team == team and g.margin_home > 0)
            or (g.away_team == team and g.margin_home < 0)
        )
        adjusted[team] += wins * params.playoff_win_bonus
    return adjusted


def build_power_components(
    schools: List[str],
    solver_states: Dict[str, TeamRatingState],
    prior_ratings: Dict[str, float],
    games: List[GameResult],
    current_week: int,
    params: ModelParams,
    season_quality: Optional[pd.DataFrame] = None,
    game_quality: Optional[pd.DataFrame] = None,
    use_season_advanced: bool = True,
    opponent_ratings: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    ratings = opponent_ratings or _solver_ratings(solver_states)

    if game_quality is not None:
        quality_input = game_quality
    elif use_season_advanced and season_quality is not None:
        quality_input = season_quality
    else:
        quality_input = None
    quality_z = build_walkforward_quality_z(
        games=games,
        schools=schools,
        current_week=current_week,
        params=params,
        season_quality=quality_input,
        opponent_ratings=ratings,
    )

    game_value = pd.Series(
        {s: solver_states[s].game_value if s in solver_states else 0.0 for s in schools}
    )
    market_value = pd.Series(
        {s: solver_states[s].market_value if s in solver_states else 0.0 for s in schools}
    )
    talent_prior = pd.Series({s: prior_ratings.get(s, RATING_MEAN) for s in schools})
    talent_weight = params.power_weights["talent_prior"] * decay_prior_weight(
        current_week,
        fade_start=params.prior_fade_start,
        fade_end=params.prior_fade_end,
    )

    components = pd.DataFrame(index=schools)
    components["quality_z"] = quality_z
    components["game_value_z"] = _zscore(game_value.astype(float))
    components["market_z"] = _zscore(market_value.astype(float))
    components["talent_prior_z"] = _zscore(talent_prior.astype(float))

    composite_z = (
        params.power_weights["quality"] * components["quality_z"]
        + params.power_weights["game_value"] * components["game_value_z"]
        + params.power_weights["market"] * components["market_z"]
        + talent_weight * components["talent_prior_z"]
    )
    composite_z = _apply_head_to_head_nudge(composite_z, games, current_week, params)
    composite_z = _apply_playoff_path_bonus(composite_z, games, current_week, params)

    components["solver_rating"] = [
        solver_states[s].rating if s in solver_states else RATING_MEAN for s in schools
    ]
    components["power_score"] = composite_z
    components["power_rating"] = composite_z.map(lambda z: _rating_from_z(float(z)))
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
    use_game_epa: bool = True,
    include_postseason: bool = False,
) -> pd.DataFrame:
    season_quality = None
    game_quality = None
    opponent_ratings = _solver_ratings(solver_states)

    if use_game_epa:
        game_stats = load_season_game_advanced(
            client, season, include_postseason=include_postseason
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
    else:
        advanced_rows = client.get_advanced_season_stats(season)
        season_quality = load_season_quality_table(advanced_rows, schools)

    return build_power_components(
        schools=schools,
        solver_states=solver_states,
        prior_ratings=prior_ratings,
        games=games,
        current_week=current_week,
        params=params,
        season_quality=season_quality,
        game_quality=game_quality,
        use_season_advanced=not use_game_epa,
        opponent_ratings=opponent_ratings,
    )

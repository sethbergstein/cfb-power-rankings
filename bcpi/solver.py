"""Iterative margin-based rating solver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from bcpi.constants import (
    FCS_INITIAL_RATING_OFFSET,
    FCS_OPPONENT_KEY,
    HOME_FIELD_ADVANTAGE,
    RATING_MEAN,
    SOLVER_ITERATIONS,
)
from bcpi.games import (
    GameResult,
    effective_margin_for_rating,
    filter_games_through_week,
    market_residual,
    opponent_key,
)
from bcpi.priors import decay_prior_weight
from bcpi.recency import recency_weight


@dataclass
class TeamRatingState:
    school: str
    rating: float
    game_value: float = 0.0
    market_value: float = 0.0
    game_weight: float = 0.0
    market_weight: float = 0.0


def expected_margin(rating_team: float, rating_opp: float) -> float:
    return (rating_team - rating_opp) / 25.0


def solve_ratings(
    teams: List[str],
    games: List[GameResult],
    prior_ratings: Dict[str, float],
    current_week: int,
    k_factor: float = 18.0,
) -> Dict[str, TeamRatingState]:
    ratings = {team: prior_ratings.get(team, RATING_MEAN) for team in teams}
    ratings[FCS_OPPONENT_KEY] = prior_ratings.get(
        FCS_OPPONENT_KEY,
        RATING_MEAN + FCS_INITIAL_RATING_OFFSET,
    )

    prior_blend = decay_prior_weight(current_week)
    game_states = {team: TeamRatingState(school=team, rating=ratings[team]) for team in teams}

    active_games = [
        g
        for g in filter_games_through_week(games, current_week)
        if g.involves_fbs and g.completed
    ]

    for _ in range(SOLVER_ITERATIONS):
        for team in teams:
            rating = ratings[team]
            if prior_blend > 0 and team in prior_ratings:
                rating = prior_blend * prior_ratings[team] + (1.0 - prior_blend) * rating

            total_delta = 0.0
            total_weight = 0.0
            gv_accum = 0.0
            gv_weight = 0.0
            mkt_accum = 0.0
            mkt_weight = 0.0

            for game in active_games:
                opp = opponent_key(game, team)
                if opp is None:
                    continue
                if team not in (game.home_team, game.away_team):
                    continue

                margin = effective_margin_for_rating(game, team)
                if margin is None:
                    continue

                opp_rating = ratings.get(opp, RATING_MEAN)
                expected = expected_margin(rating, opp_rating)
                residual = margin - expected
                weight = recency_weight(current_week, game.week)

                total_delta += k_factor * weight * residual
                total_weight += weight
                gv_accum += weight * residual
                gv_weight += weight

                market_res = market_residual(game, team)
                if market_res is not None:
                    mkt_accum += weight * market_res
                    mkt_weight += weight

            if total_weight > 0:
                ratings[team] = rating + total_delta / total_weight
                game_states[team].rating = ratings[team]
                game_states[team].game_value = gv_accum / gv_weight
                game_states[team].game_weight = gv_weight
                if mkt_weight > 0:
                    game_states[team].market_value = mkt_accum / mkt_weight
                    game_states[team].market_weight = mkt_weight

        # FCS aggregate stays near fixed anchor (don't drift from FCS game noise).
        ratings[FCS_OPPONENT_KEY] = prior_ratings.get(
            FCS_OPPONENT_KEY,
            RATING_MEAN + FCS_INITIAL_RATING_OFFSET,
        )

    return game_states

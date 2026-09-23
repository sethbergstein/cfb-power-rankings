"""Iterative margin-based rating solver."""

from __future__ import annotations

import math

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from bcpi.constants import FCS_OPPONENT_KEY, RATING_MEAN
from bcpi.games import (
    GameResult,
    compress_margin,
    effective_margin_for_rating,
    filter_games_through_week,
    market_residual,
    opponent_key,
)
from bcpi.params import ModelParams
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
    solver_iterations: int = 0
    solver_max_change: float = 0.0


def expected_margin(
    rating_team: float,
    rating_opp: float,
    params: ModelParams,
) -> float:
    return (rating_team - rating_opp) / params.margin_scale


def predict_home_margin(
    home_rating: float,
    away_rating: float,
    neutral_site: bool,
    params: ModelParams,
    home_team: Optional[str] = None,
    team_hfa: Optional[Dict[str, float]] = None,
    scale: Optional[float] = None,
) -> float:
    """Home margin from solver ratings; ``scale`` defaults to the solver's margin scale."""
    margin = (home_rating - away_rating) / (scale or params.margin_scale)
    if not neutral_site:
        from bcpi.home_field import home_field_for_team

        margin += home_field_for_team(home_team or "", team_hfa, params.hfa)
    return margin


def predict_matchup_margin(
    home_rating: float,
    away_rating: float,
    home_rank: int,
    away_rank: int,
    neutral_site: bool,
    params: ModelParams,
    home_team: Optional[str] = None,
    team_hfa: Optional[Dict[str, float]] = None,
) -> float:
    """Spread-oriented margin for the public matchup view."""
    scale = getattr(params, "matchup_margin_scale", params.margin_scale)
    rank_pt = getattr(params, "matchup_rank_pt", 0.0)
    rating_margin = (home_rating - away_rating) / scale
    rank_margin = (away_rank - home_rank) * rank_pt
    if rank_margin >= 0:
        margin = max(rating_margin, rank_margin)
    else:
        margin = min(rating_margin, rank_margin)
    if not neutral_site:
        from bcpi.home_field import home_field_for_team

        margin += home_field_for_team(home_team or "", team_hfa, params.matchup_hfa)
    return margin


def margin_to_win_probability(margin: float, scale: float) -> float:
    """Logistic win probability from expected margin (home perspective)."""
    return 1.0 / (1.0 + math.exp(-margin / scale))


def _team_schedules(
    teams: List[str],
    games: List[GameResult],
    current_week: int,
    params: ModelParams,
) -> Tuple[Dict[str, List[Tuple[str, float, float]]], Dict[str, List[Tuple[float, float]]]]:
    """Per team: (opponent key, recency weight, compressed neutral-field margin), plus market residuals."""
    schedule: Dict[str, List[Tuple[str, float, float]]] = {team: [] for team in teams}
    market: Dict[str, List[Tuple[float, float]]] = {team: [] for team in teams}
    for game in filter_games_through_week(games, current_week):
        if not (game.involves_fbs and game.completed):
            continue
        weight = recency_weight(current_week, game.week, lambda_=params.recency_lambda)
        for team in (game.home_team, game.away_team):
            if team not in schedule:
                continue
            opp = opponent_key(game, team)
            margin = effective_margin_for_rating(game, team, params)
            if opp is None or margin is None:
                continue
            schedule[team].append(
                (opp, weight, compress_margin(margin, params.margin_compression))
            )
            market_res = market_residual(game, team)
            if market_res is not None:
                market[team].append((weight, market_res))
    return schedule, market


_NEWTON_MAX_STEP = 300.0


def _solve_fixed_point(
    active: List[str],
    schedule: Dict[str, List[Tuple[str, float, float]]],
    ratings: Dict[str, float],
    prior_ratings: Dict[str, float],
    prior_blend: float,
    params: ModelParams,
) -> Tuple[np.ndarray, int, float]:
    """
    Newton's method on the rating update's fixed point.

    For each team, the update is T(r) = r_b + k * mean residual(r_b), with
    r_b = blend * prior + (1 - blend) * r. A rating is solved when T(r) = r,
    i.e. one more pass would not move it. Newton reaches that point in a few
    steps; passing over teams one at a time needs hundreds late in the season.
    Least squares handles schedule islands with no anchor (e.g. the 2020
    conference-only Pac-12), whose level is then left where the prior put it.
    """
    n = len(active)
    index = {team: i for i, team in enumerate(active)}
    rows: List[int] = []
    cols: List[int] = []
    fixed: List[float] = []
    weights: List[float] = []
    actual: List[float] = []
    for i, team in enumerate(active):
        entries = schedule[team]
        total = sum(weight for _, weight, _ in entries)
        for opp, weight, margin in entries:
            rows.append(i)
            cols.append(index.get(opp, -1))
            fixed.append(ratings.get(opp, RATING_MEAN))
            weights.append(weight / total)
            actual.append(margin)
    row_arr = np.array(rows)
    col_arr = np.array(cols)
    linked = col_arr >= 0
    col_idx = np.where(linked, col_arr, 0)
    fixed_arr = np.array(fixed)
    weight_arr = np.array(weights)
    actual_arr = np.array(actual)
    blend = np.array([prior_blend if team in prior_ratings else 0.0 for team in active])
    prior = np.array([prior_ratings.get(team, ratings[team]) for team in active])
    scale = params.margin_compression
    margin_scale = params.margin_scale
    k_factor = params.k_factor

    def evaluate(r: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        blended = blend * prior + (1.0 - blend) * r
        opponents = np.where(linked, r[col_idx], fixed_arr)
        expected = (blended[row_arr] - opponents) / margin_scale
        if scale > 0:
            squashed = np.tanh(expected / scale)
            expected = scale * squashed
            slope = (1.0 - squashed * squashed) / margin_scale
        else:
            slope = np.full_like(expected, 1.0 / margin_scale)
        residual = np.bincount(
            row_arr, weights=weight_arr * (actual_arr - expected), minlength=n
        )
        return blended + k_factor * residual - r, slope

    r = np.array([ratings[team] for team in active])
    gap, slope = evaluate(r)
    iterations = 0
    max_change = 0.0
    diagonal = np.arange(n)
    for iterations in range(1, max(1, int(params.solver_max_iterations)) + 1):
        jacobian = np.zeros((n, n))
        own_slope = np.bincount(row_arr, weights=weight_arr * slope, minlength=n)
        jacobian[diagonal, diagonal] = (1.0 - blend) * (1.0 - k_factor * own_slope) - 1.0
        np.add.at(
            jacobian,
            (row_arr[linked], col_arr[linked]),
            k_factor * weight_arr[linked] * slope[linked],
        )
        step = np.linalg.lstsq(jacobian, -gap, rcond=None)[0]
        biggest = float(np.abs(step).max()) if n else 0.0
        if biggest > _NEWTON_MAX_STEP:
            step *= _NEWTON_MAX_STEP / biggest

        current = float(np.abs(gap).max())
        for _ in range(10):
            trial = r + step
            trial_gap, trial_slope = evaluate(trial)
            if float(np.abs(trial_gap).max()) <= current:
                break
            step *= 0.5
        r, gap, slope = trial, trial_gap, trial_slope
        max_change = max(float(np.abs(step).max()), float(np.abs(gap).max()))
        if max_change <= params.solver_tolerance:
            break
    return r, iterations, max_change


def solve_ratings(
    teams: List[str],
    games: List[GameResult],
    prior_ratings: Dict[str, float],
    current_week: int,
    params: ModelParams,
) -> Dict[str, TeamRatingState]:
    """
    Opponent-adjusted margin ratings.

    A team's rating settles where k times its recency-weighted mean residual
    (compressed actual margin minus compressed expected margin) exactly offsets
    the pull toward its preseason prior. The prior's pull fades out by
    ``prior_fade_end``; after that the rating is where the mean residual is zero.
    """
    ratings = {team: prior_ratings.get(team, RATING_MEAN) for team in teams}
    ratings[FCS_OPPONENT_KEY] = prior_ratings.get(FCS_OPPONENT_KEY, params.fcs_rating)

    prior_blend = decay_prior_weight(
        current_week,
        fade_start=params.prior_fade_start,
        fade_end=params.prior_fade_end,
    )
    schedule, market = _team_schedules(teams, games, current_week, params)
    scale = params.margin_compression

    active = [team for team in teams if schedule[team]]
    iterations = 0
    max_change = 0.0
    if active:
        solved, iterations, max_change = _solve_fixed_point(
            active, schedule, ratings, prior_ratings, prior_blend, params
        )
        for team, rating in zip(active, solved):
            ratings[team] = float(rating)

    states: Dict[str, TeamRatingState] = {}
    for team in teams:
        state = TeamRatingState(
            school=team,
            rating=ratings[team],
            solver_iterations=iterations,
            solver_max_change=max_change,
        )
        entries = schedule[team]
        if entries:
            weight_sum = sum(weight for _, weight, _ in entries)
            state.game_value = sum(
                weight
                * (
                    actual
                    - compress_margin(
                        expected_margin(ratings[team], ratings.get(opp, RATING_MEAN), params),
                        scale,
                    )
                )
                for opp, weight, actual in entries
            ) / weight_sum
            state.game_weight = weight_sum
        if market[team]:
            state.market_weight = sum(weight for weight, _ in market[team])
            state.market_value = (
                sum(weight * value for weight, value in market[team]) / state.market_weight
            )
        states[team] = state
    return states

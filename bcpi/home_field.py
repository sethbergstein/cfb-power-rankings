"""Data-driven team home field advantage for matchup predictions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from bcpi.cfbd import CFBDClient
from bcpi.config import PROJECT_ROOT
from bcpi.constants import BACKTEST_START_SEASON
from bcpi.games import load_season_games
from bcpi.params import ModelParams
from bcpi.priors import build_preseason_priors
from bcpi.solver import expected_margin, solve_ratings
from bcpi.teams import get_fbs_teams

HFA_CACHE_DIR = PROJECT_ROOT / "data" / "hfa"


def _season_solver_ratings(
    client: CFBDClient,
    season: int,
    params: ModelParams,
) -> Dict[str, float]:
    teams = get_fbs_teams(client, season)
    schools = [team.school for team in teams]
    priors = build_preseason_priors(client, teams, season, params)
    games = load_season_games(client, season, include_postseason=True)
    if not games:
        return {}
    week = max(game.week for game in games)
    states = solve_ratings(
        teams=schools,
        games=games,
        prior_ratings=priors,
        current_week=week,
        params=params,
    )
    return {school: states[school].rating for school in schools if school in states}


def compute_team_hfa(
    client: CFBDClient,
    schools: List[str],
    through_season: int,
    params: ModelParams,
    lookback_seasons: int = 5,
    min_games: int = 6,
    shrink_games: float = 12.0,
    max_delta: Optional[float] = None,
) -> Dict[str, float]:
    """
    Estimate each team's home-field edge in expected margin points.

    Observed HFA = actual home margin minus neutral-strength expectation from
    BCPI solver ratings. Values shrink toward the global base and are capped so
    no venue runs away (typical spread ~±1.5 pts from league average).
    """
    base = params.hfa
    max_delta = max_delta if max_delta is not None else params.hfa_team_max_delta
    start = max(BACKTEST_START_SEASON, through_season - lookback_seasons)
    weighted_sum = {school: 0.0 for school in schools}
    weighted_count = {school: 0.0 for school in schools}

    for season in range(start, through_season):
        age = through_season - season
        season_weight = 0.85**age
        ratings = _season_solver_ratings(client, season, params)
        if not ratings:
            continue

        games = load_season_games(client, season, include_postseason=True)
        for game in games:
            if not game.is_fbs_game or game.neutral_site or not game.completed:
                continue
            home = game.home_team
            away = game.away_team
            if home not in schools or away not in ratings or home not in ratings:
                continue
            actual = float(game.margin_home)
            neutral = expected_margin(ratings[home], ratings[away], params)
            observed = actual - neutral
            weighted_sum[home] += season_weight * observed
            weighted_count[home] += season_weight

    result: Dict[str, float] = {}
    for school in schools:
        n = weighted_count[school]
        if n < min_games:
            result[school] = base
            continue
        raw = weighted_sum[school] / n
        shrink = n / (n + shrink_games)
        shrunk = shrink * raw + (1.0 - shrink) * base
        result[school] = max(base - max_delta, min(base + max_delta, shrunk))
    return result


def load_team_hfa(
    client: CFBDClient,
    schools: List[str],
    through_season: int,
    params: ModelParams,
    refresh: bool = False,
) -> Dict[str, float]:
    """Load cached team HFA table or recompute."""
    HFA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = HFA_CACHE_DIR / f"through_{through_season}.json"
    if cache_path.exists() and not refresh:
        with cache_path.open("r", encoding="utf-8") as handle:
            cached = json.load(handle)
        base = params.hfa
        return {school: float(cached.get(school, base)) for school in schools}

    table = compute_team_hfa(client, schools, through_season, params)
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump(table, handle, indent=2, sort_keys=True)
    return table


def home_field_for_team(
    team: str,
    team_hfa: Optional[Dict[str, float]],
    params: ModelParams,
) -> float:
    if team_hfa and team in team_hfa:
        return float(team_hfa[team])
    return params.hfa

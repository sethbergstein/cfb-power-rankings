"""Backtest harness for BCPI (skeleton)."""

from __future__ import annotations

from typing import List, Optional

import pandas as pd
import time

from bcpi.cfbd import CFBDClient
from bcpi.constants import BACKTEST_END_SEASON, BACKTEST_START_SEASON
from bcpi.games import GameResult, parse_games, filter_games_through_week
from bcpi.priors import build_preseason_priors
from bcpi.solver import expected_margin, solve_ratings
from bcpi.teams import get_fbs_teams


def _predict_games(
    ratings: dict,
    games: List[GameResult],
) -> pd.DataFrame:
    rows = []
    for game in games:
        if not game.is_fbs_game:
            continue
        home_rating = ratings.get(game.home_team, 1500.0)
        away_rating = ratings.get(game.away_team, 1500.0)
        predicted_margin = expected_margin(home_rating, away_rating)
        if not game.neutral_site:
            predicted_margin += 2.75
        actual_margin = game.margin_home
        rows.append(
            {
                "game_id": game.game_id,
                "week": game.week,
                "home_team": game.home_team,
                "away_team": game.away_team,
                "predicted_margin": predicted_margin,
                "actual_margin": actual_margin,
                "error": actual_margin - predicted_margin,
            }
        )
    return pd.DataFrame(rows)


def run_backtest(
    start_season: int = BACKTEST_START_SEASON,
    end_season: int = BACKTEST_END_SEASON,
    client: Optional[CFBDClient] = None,
) -> pd.DataFrame:
    owns_client = client is None
    if owns_client:
        client = CFBDClient()

    season_results = []

    try:
        for season in range(start_season, end_season + 1):
            time.sleep(1.5)
            teams = get_fbs_teams(client, season)
            schools = [team.school for team in teams]
            priors = build_preseason_priors(client, teams, season)

            raw_games = client.get_games(season, season_type="regular")
            games = parse_games(raw_games)

            max_week = max(g.week for g in games) if games else 0
            train_week = max(1, max_week - 1)

            train_games = filter_games_through_week(games, train_week)
            test_games = [g for g in games if g.week == max_week]

            states = solve_ratings(
                teams=schools,
                games=train_games,
                prior_ratings=priors,
                current_week=train_week,
            )
            ratings = {school: state.rating for school, state in states.items()}

            preds = _predict_games(ratings, test_games)
            if preds.empty:
                continue
            mae = preds["error"].abs().mean()
            season_results.append(
                {
                    "season": season,
                    "train_through_week": train_week,
                    "test_week": max_week,
                    "games": len(preds),
                    "margin_mae": mae,
                }
            )

        return pd.DataFrame(season_results)
    finally:
        if owns_client and client is not None:
            client.close()

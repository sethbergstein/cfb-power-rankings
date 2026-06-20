"""Walk-forward backtest harness for BCPI."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

from bcpi.cfbd import CFBDClient
from bcpi.constants import BACKTEST_END_SEASON, BACKTEST_START_SEASON
from bcpi.games import GameResult, parse_games
from bcpi.params import ModelParams
from bcpi.power_index import build_power_components
from bcpi.game_stats import (
    GameAdvancedStat,
    aggregate_game_quality,
    build_team_game_logs,
    load_season_game_advanced,
)
from bcpi.priors import PriorComponents, blend_prior_components, load_prior_components
from bcpi.solver import predict_home_margin, solve_ratings
from bcpi.teams import Team, get_fbs_teams


@dataclass
class SeasonBundle:
    season: int
    schools: List[str]
    teams: List[Team]
    games: List[GameResult]
    prior_components: PriorComponents
    team_game_logs: Dict[str, List]


@dataclass
class BacktestMetrics:
    games: int = 0
    margin_mae: float = 0.0
    margin_rmse: float = 0.0
    win_log_loss: float = 0.0
    win_accuracy: float = 0.0
    solver_margin_mae: float = 0.0

    def score(self) -> float:
        """Objective: lower is better (MAE + log loss)."""
        return self.margin_mae + self.win_log_loss


def _win_probability(margin: float, scale: float) -> float:
    # Logistic mapping from expected margin to win probability.
    return 1.0 / (1.0 + math.exp(-margin / scale))


def _accumulate_metrics(
    metrics: BacktestMetrics,
    predicted_margin: float,
    actual_margin: float,
    win_prob_scale: float,
) -> None:
    error = actual_margin - predicted_margin
    metrics.games += 1
    metrics.margin_mae += abs(error)
    metrics.margin_rmse += error ** 2

    actual_win = 1.0 if actual_margin > 0 else 0.0
    if actual_margin == 0:
        actual_win = 0.5
    win_prob = _win_probability(predicted_margin, win_prob_scale)
    win_prob = min(max(win_prob, 1e-6), 1.0 - 1e-6)
    metrics.win_log_loss += -(
        actual_win * math.log(win_prob) + (1.0 - actual_win) * math.log(1.0 - win_prob)
    )
    predicted_win = 1.0 if win_prob >= 0.5 else 0.0
    if actual_margin == 0:
        metrics.win_accuracy += 0.5
    else:
        metrics.win_accuracy += 1.0 if predicted_win == actual_win else 0.0


def _finalize_metrics(metrics: BacktestMetrics) -> BacktestMetrics:
    if metrics.games == 0:
        return metrics
    metrics.margin_mae /= metrics.games
    metrics.margin_rmse = math.sqrt(metrics.margin_rmse / metrics.games)
    metrics.win_log_loss /= metrics.games
    metrics.win_accuracy /= metrics.games
    return metrics


def load_season_bundles(
    client: CFBDClient,
    start_season: int,
    end_season: int,
    pause_seconds: float = 1.0,
) -> List[SeasonBundle]:
    bundles: List[SeasonBundle] = []
    for season in range(start_season, end_season + 1):
        if pause_seconds:
            time.sleep(pause_seconds)
        teams = get_fbs_teams(client, season)
        schools = [team.school for team in teams]
        raw_games = client.get_games(season, season_type="regular")
        line_rows = client.get_lines(season, season_type="regular")
        games = parse_games(raw_games, line_rows)
        prior_components = load_prior_components(client, teams, season)
        game_stats = load_season_game_advanced(client, season)
        team_logs = build_team_game_logs(game_stats, games, schools)
        bundles.append(
            SeasonBundle(
                season=season,
                schools=schools,
                teams=teams,
                games=games,
                prior_components=prior_components,
                team_game_logs=team_logs,
            )
        )
    return bundles


def evaluate_params(
    bundles: List[SeasonBundle],
    params: ModelParams,
    client: CFBDClient,
    min_train_week: int = 0,
) -> Tuple[BacktestMetrics, pd.DataFrame]:
    """Walk-forward: train through week t, predict week t+1 FBS vs FBS games."""
    power_metrics = BacktestMetrics()
    solver_metrics = BacktestMetrics()
    detail_rows: List[dict] = []

    for bundle in bundles:
        priors = blend_prior_components(bundle.prior_components, params)
        games = bundle.games
        if not games:
            continue
        max_week = max(game.week for game in games)

        for test_week in range(max(min_train_week + 1, 1), max_week + 1):
            train_week = test_week - 1
            train_games = [g for g in games if g.week <= train_week]
            test_games = [g for g in games if g.week == test_week and g.is_fbs_game]
            if not test_games:
                continue

            states = solve_ratings(
                teams=bundle.schools,
                games=train_games,
                prior_ratings=priors,
                current_week=train_week,
                params=params,
            )
            opponent_ratings = {s: states[s].rating for s in bundle.schools}
            game_quality = aggregate_game_quality(
                bundle.team_game_logs,
                bundle.schools,
                through_week=train_week,
                current_week=train_week,
                params=params,
                opponent_ratings=opponent_ratings,
            )
            power = build_power_components(
                schools=bundle.schools,
                solver_states=states,
                prior_ratings=priors,
                games=train_games,
                current_week=train_week,
                params=params,
                game_quality=game_quality,
                use_season_advanced=False,
                opponent_ratings=opponent_ratings,
            )

            for game in test_games:
                home_power = float(power.loc[game.home_team, "power_rating"])
                away_power = float(power.loc[game.away_team, "power_rating"])
                pred_margin = predict_home_margin(
                    home_power,
                    away_power,
                    game.neutral_site,
                    params,
                )
                actual = float(game.margin_home)

                _accumulate_metrics(
                    power_metrics,
                    pred_margin,
                    actual,
                    params.win_prob_scale,
                )

                home_solver = states[game.home_team].rating
                away_solver = states[game.away_team].rating
                solver_pred = predict_home_margin(
                    home_solver,
                    away_solver,
                    game.neutral_site,
                    params,
                )
                _accumulate_metrics(
                    solver_metrics,
                    solver_pred,
                    actual,
                    params.win_prob_scale,
                )

                detail_rows.append(
                    {
                        "season": bundle.season,
                        "week": test_week,
                        "game_id": game.game_id,
                        "home_team": game.home_team,
                        "away_team": game.away_team,
                        "predicted_margin": pred_margin,
                        "solver_margin": solver_pred,
                        "actual_margin": actual,
                        "power_error": actual - pred_margin,
                        "solver_error": actual - solver_pred,
                    }
                )

    power_metrics = _finalize_metrics(power_metrics)
    solver_metrics = _finalize_metrics(solver_metrics)
    power_metrics.solver_margin_mae = solver_metrics.margin_mae
    detail = pd.DataFrame(detail_rows)
    return power_metrics, detail


def run_backtest(
    start_season: int = BACKTEST_START_SEASON,
    end_season: int = BACKTEST_END_SEASON,
    params: Optional[ModelParams] = None,
    client: Optional[CFBDClient] = None,
) -> Tuple[pd.DataFrame, BacktestMetrics]:
    owns_client = client is None
    if params is None:
        params = ModelParams()
    if owns_client:
        client = CFBDClient()

    try:
        bundles = load_season_bundles(client, start_season, end_season)
        metrics, detail = evaluate_params(bundles, params, client)

        summary_rows = []
        for season, group in detail.groupby("season"):
            season_metrics = BacktestMetrics()
            for _, row in group.iterrows():
                _accumulate_metrics(
                    season_metrics,
                    row["predicted_margin"],
                    row["actual_margin"],
                    params.win_prob_scale,
                )
            season_metrics = _finalize_metrics(season_metrics)
            summary_rows.append(
                {
                    "season": season,
                    "games": season_metrics.games,
                    "margin_mae": season_metrics.margin_mae,
                    "margin_rmse": season_metrics.margin_rmse,
                    "win_log_loss": season_metrics.win_log_loss,
                    "win_accuracy": season_metrics.win_accuracy,
                }
            )

        summary = pd.DataFrame(summary_rows)
        return summary, metrics
    finally:
        if owns_client and client is not None:
            client.close()

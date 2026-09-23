"""Walk-forward backtest harness for BCPI."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from bcpi.cfbd import CFBDClient
from bcpi.champions import load_defending_champion
from bcpi.constants import BACKTEST_END_SEASON, BACKTEST_START_SEASON, RATING_SPREAD
from bcpi.games import GameResult, parse_games
from bcpi.params import ModelParams
from bcpi.power_index import build_power_components
from bcpi.game_stats import (
    aggregate_game_quality,
    build_team_game_logs,
    load_season_game_advanced,
)
from bcpi.priors import PriorComponents, blend_prior_components, load_prior_components
from bcpi.solver import predict_home_margin, solve_ratings
from bcpi.teams import Team, get_fbs_teams

# Season phases scored separately: early (prior-heavy), middle, late.
PHASES: Dict[str, Tuple[int, int]] = {"early": (2, 4), "mid": (5, 8), "late": (9, 99)}


@dataclass
class SeasonBundle:
    season: int
    schools: List[str]
    teams: List[Team]
    games: List[GameResult]
    prior_components: PriorComponents
    team_game_logs: Dict[str, List]
    defending_champion: Optional[str] = None


@dataclass
class BacktestMetrics:
    """
    Walk-forward accuracy of week t+1 predictions from ratings through week t.

    ``margin_*`` / ``win_*`` use the matchup page's formula (``site_margins``).
    ``fitted_*`` refit points per rating point and home field by least squares,
    so they measure how well the ratings order and space teams regardless of
    how the page maps ratings to points.
    """

    games: int = 0
    margin_mae: float = 0.0
    margin_rmse: float = 0.0
    win_log_loss: float = 0.0
    win_accuracy: float = 0.0
    solver_margin_mae: float = 0.0
    fitted_mae: float = 0.0
    fitted_mae_early: float = 0.0
    fitted_mae_mid: float = 0.0
    fitted_mae_late: float = 0.0
    fitted_log_loss: float = 0.0
    fitted_accuracy: float = 0.0
    fitted_points_per_rating: float = 0.0
    fitted_hfa: float = 0.0
    fitted_win_prob_scale: float = 0.0

    def score(self) -> float:
        """Tuning objective (lower is better): each season phase counts equally."""
        phase_mae = (self.fitted_mae_early + self.fitted_mae_mid + self.fitted_mae_late) / 3.0
        return phase_mae + self.fitted_log_loss

    @property
    def implied_matchup_margin_scale(self) -> float:
        if self.fitted_points_per_rating <= 0:
            return 0.0
        return 1.0 / self.fitted_points_per_rating


def _log_loss(margin: np.ndarray, actual: np.ndarray, scale: float) -> float:
    prob = 1.0 / (1.0 + np.exp(-margin / scale))
    prob = np.clip(prob, 1e-6, 1.0 - 1e-6)
    outcome = np.where(actual > 0, 1.0, np.where(actual < 0, 0.0, 0.5))
    return float(np.mean(-(outcome * np.log(prob) + (1.0 - outcome) * np.log(1.0 - prob))))


def _accuracy(margin: np.ndarray, actual: np.ndarray) -> float:
    hits = np.where(actual == 0, 0.5, (np.sign(margin) == np.sign(actual)).astype(float))
    return float(np.mean(hits))


def fit_win_prob_scale(margin: np.ndarray, actual: np.ndarray) -> float:
    """Logistic scale that minimizes log loss for these predicted margins."""
    grid = np.arange(4.0, 25.0, 0.05)
    losses = [_log_loss(margin, actual, scale) for scale in grid]
    return float(grid[int(np.argmin(losses))])


def site_margins(
    detail: pd.DataFrame,
    params: ModelParams,
    scale: Optional[float] = None,
    rank_pt: Optional[float] = None,
    hfa: Optional[float] = None,
) -> np.ndarray:
    """Home margins exactly as the matchup page computes them (league-wide home field)."""
    scale = scale if scale is not None else params.matchup_margin_scale
    rank_pt = rank_pt if rank_pt is not None else params.matchup_rank_pt
    hfa = hfa if hfa is not None else params.matchup_hfa
    rating_margin = detail["rating_diff"].to_numpy(dtype=float) / scale
    rank_margin = (
        detail["away_rank"].to_numpy(dtype=float) - detail["home_rank"].to_numpy(dtype=float)
    ) * rank_pt
    margin = np.where(
        rank_margin >= 0,
        np.maximum(rating_margin, rank_margin),
        np.minimum(rating_margin, rank_margin),
    )
    return margin + hfa * detail["home_field"].to_numpy(dtype=float)


def summarize_predictions(detail: pd.DataFrame, params: ModelParams) -> BacktestMetrics:
    metrics = BacktestMetrics()
    if detail.empty:
        return metrics
    week = detail["week"].to_numpy()
    actual = detail["actual_margin"].to_numpy(dtype=float)
    raw = site_margins(detail, params)
    solver = detail["solver_margin"].to_numpy(dtype=float)
    design = np.column_stack(
        [detail["rating_diff"].to_numpy(dtype=float), detail["home_field"].to_numpy(dtype=float)]
    )
    coef, *_ = np.linalg.lstsq(design, actual, rcond=None)
    fitted = design @ coef

    metrics.games = len(actual)
    metrics.margin_mae = float(np.mean(np.abs(actual - raw)))
    metrics.margin_rmse = float(np.sqrt(np.mean((actual - raw) ** 2)))
    metrics.win_log_loss = _log_loss(raw, actual, params.win_prob_scale)
    metrics.win_accuracy = _accuracy(raw, actual)
    metrics.solver_margin_mae = float(np.mean(np.abs(actual - solver)))
    metrics.fitted_mae = float(np.mean(np.abs(actual - fitted)))
    for name, (start, end) in PHASES.items():
        mask = (week >= start) & (week <= end)
        value = float(np.mean(np.abs(actual[mask] - fitted[mask]))) if mask.any() else 0.0
        setattr(metrics, f"fitted_mae_{name}", value)
    metrics.fitted_points_per_rating = float(coef[0])
    metrics.fitted_hfa = float(coef[1])
    metrics.fitted_win_prob_scale = fit_win_prob_scale(fitted, actual)
    metrics.fitted_log_loss = _log_loss(fitted, actual, metrics.fitted_win_prob_scale)
    metrics.fitted_accuracy = _accuracy(fitted, actual)
    return metrics


def load_season_bundles(
    client: CFBDClient,
    start_season: int,
    end_season: int,
    pause_seconds: float = 1.0,
    exclude_garbage_time: bool = False,
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
        game_stats = load_season_game_advanced(
            client, season, exclude_garbage_time=exclude_garbage_time
        )
        team_logs = build_team_game_logs(game_stats, games, schools)
        bundles.append(
            SeasonBundle(
                season=season,
                schools=schools,
                teams=teams,
                games=games,
                prior_components=prior_components,
                team_game_logs=team_logs,
                defending_champion=load_defending_champion(client, season),
            )
        )
    return bundles


def season_priors(bundle: SeasonBundle, params: ModelParams) -> Dict[str, float]:
    """Same priors as ``build_preseason_priors``, from pre-loaded components."""
    priors = blend_prior_components(bundle.prior_components, params)
    champ = bundle.defending_champion
    if params.defending_champion_prior_z > 0 and champ in priors:
        priors[champ] += params.defending_champion_prior_z * (RATING_SPREAD / 2.5)
    return priors


def evaluate_params(
    bundles: List[SeasonBundle],
    params: ModelParams,
    client: Optional[CFBDClient] = None,
    min_train_week: int = 0,
) -> Tuple[BacktestMetrics, pd.DataFrame]:
    """Walk-forward: train through week t, predict week t+1 FBS vs FBS games."""
    detail_rows: List[dict] = []

    for bundle in bundles:
        priors = season_priors(bundle, params)
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
                opponent_ratings=opponent_ratings,
            )
            power_rating = power["power_rating"].to_dict()
            power_rank = power["rank"].to_dict()

            for game in test_games:
                if game.home_team not in power_rating or game.away_team not in power_rating:
                    continue
                detail_rows.append(
                    {
                        "season": bundle.season,
                        "week": test_week,
                        "game_id": game.game_id,
                        "home_team": game.home_team,
                        "away_team": game.away_team,
                        "home_field": 0.0 if game.neutral_site else 1.0,
                        "rating_diff": power_rating[game.home_team] - power_rating[game.away_team],
                        "home_rank": int(power_rank[game.home_team]),
                        "away_rank": int(power_rank[game.away_team]),
                        "solver_margin": predict_home_margin(
                            states[game.home_team].rating,
                            states[game.away_team].rating,
                            game.neutral_site,
                            params,
                        ),
                        "actual_margin": float(game.margin_home),
                    }
                )

    detail = pd.DataFrame(detail_rows)
    if not detail.empty:
        detail["predicted_margin"] = site_margins(detail, params)
        detail["power_error"] = detail["actual_margin"] - detail["predicted_margin"]
        detail["solver_error"] = detail["actual_margin"] - detail["solver_margin"]
    return summarize_predictions(detail, params), detail


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
        bundles = load_season_bundles(
            client,
            start_season,
            end_season,
            pause_seconds=0.0,
            exclude_garbage_time=params.exclude_garbage_time,
        )
        metrics, detail = evaluate_params(bundles, params, client)
        if detail.empty:
            return pd.DataFrame(), metrics

        detail["fitted_margin"] = (
            metrics.fitted_points_per_rating * detail["rating_diff"]
            + metrics.fitted_hfa * detail["home_field"]
        )
        summary_rows = []
        for season, group in detail.groupby("season"):
            actual = group["actual_margin"].to_numpy(dtype=float)
            raw = group["predicted_margin"].to_numpy(dtype=float)
            fitted = group["fitted_margin"].to_numpy(dtype=float)
            summary_rows.append(
                {
                    "season": season,
                    "games": len(group),
                    "margin_mae": float(np.mean(np.abs(actual - raw))),
                    "fitted_mae": float(np.mean(np.abs(actual - fitted))),
                    "win_log_loss": _log_loss(raw, actual, params.win_prob_scale),
                    "win_accuracy": _accuracy(raw, actual),
                }
            )

        summary = pd.DataFrame(summary_rows)
        return summary, metrics
    finally:
        if owns_client and client is not None:
            client.close()

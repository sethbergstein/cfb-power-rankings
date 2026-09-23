"""Walk-forward parameter search for the BCPI power model."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from bcpi.backtest import (
    BacktestMetrics,
    SeasonBundle,
    evaluate_params,
    fit_win_prob_scale,
    load_season_bundles,
    season_priors,
    site_margins,
)
from bcpi.cfbd import CFBDClient
from bcpi.game_stats import QUALITY_METRICS, game_metric_diffs
from bcpi.params import ModelParams, TUNED_PARAMS_PATH, get_active_params
from bcpi.solver import solve_ratings


@dataclass(frozen=True)
class Coordinate:
    """One searchable parameter; ``group.key`` addresses a weight inside a dict."""

    name: str
    low: float
    high: float
    step: float
    integer: bool = False


COORDINATES: Tuple[Coordinate, ...] = (
    Coordinate("recency_lambda", 0.0, 0.40, 0.04),
    Coordinate("k_factor", 2.0, 30.0, 2.0),
    Coordinate("margin_scale", 10.0, 40.0, 2.0),
    Coordinate("hfa", 1.0, 5.0, 0.4),
    Coordinate("fcs_rating", 850.0, 1300.0, 50.0),
    Coordinate("margin_compression", 10.0, 80.0, 6.0),
    Coordinate("prior_fade_end", 4, 20, 2, integer=True),
    Coordinate("form_weight", 0.0, 1.0, 0.1),
    Coordinate("power_sample_games", 1.0, 14.0, 1.5),
    Coordinate("h2h_window", 0.0, 0.4, 0.05),
    Coordinate("power_weights.solver", 0.3, 0.95, 0.05),
    Coordinate("quality_weights.epa_diff", 0.0, 0.9, 0.08),
    Coordinate("quality_weights.success_diff", 0.0, 0.9, 0.08),
    Coordinate("quality_weights.explosiveness_diff", 0.0, 0.9, 0.08),
    Coordinate("quality_weights.passing_diff", 0.0, 0.9, 0.08),
    Coordinate("prior_weights.previous_season", 0.0, 0.9, 0.08),
    Coordinate("prior_weights.talent", 0.0, 0.9, 0.08),
    Coordinate("prior_weights.consensus", 0.0, 0.9, 0.08),
)


def get_value(params: ModelParams, name: str) -> float:
    if "." in name:
        group, key = name.split(".", 1)
        return float(getattr(params, group).get(key, 0.0))
    return float(getattr(params, name))


def with_value(params: ModelParams, coord: Coordinate, value: float) -> Optional[ModelParams]:
    """Copy of ``params`` with one coordinate moved; None if clamping leaves it unchanged."""
    value = min(coord.high, max(coord.low, value))
    if coord.integer:
        value = int(round(value))
    if abs(value - get_value(params, coord.name)) < 1e-9:
        return None
    candidate = copy.deepcopy(params)
    if "." not in coord.name:
        setattr(candidate, coord.name, value)
        return candidate

    group, key = coord.name.split(".", 1)
    weights = dict(getattr(candidate, group))
    if group == "power_weights":
        # Market stays where it is; quality takes whatever the solver gives up.
        weights[key] = value
        weights["quality"] = max(0.0, 1.0 - weights.get("solver", 0.0) - weights.get("market", 0.0))
    else:
        others = sum(weight for name, weight in weights.items() if name != key)
        weights[key] = value
        if others > 0:
            for name in weights:
                if name != key:
                    weights[name] *= (1.0 - value) / others
    setattr(candidate, group, weights)
    return candidate


def estimate_quality_slopes(bundles: Sequence[SeasonBundle], params: ModelParams) -> Dict[str, float]:
    """
    Efficiency differential per point of expected margin, for each quality metric.

    Pools every FBS game log and regresses the offense-minus-defense differential
    (through the origin) on the end-of-season rating gap in points. The quality
    step credits each game ``slope * opponent strength`` using these values.
    """
    sxx = 0.0
    sxy = {metric: 0.0 for metric in QUALITY_METRICS}
    for bundle in bundles:
        if not bundle.games:
            continue
        final_week = max(game.week for game in bundle.games)
        states = solve_ratings(
            teams=bundle.schools,
            games=bundle.games,
            prior_ratings=season_priors(bundle, params),
            current_week=final_week,
            params=params,
        )
        ratings = {school: states[school].rating for school in bundle.schools}
        for team, log in bundle.team_game_logs.items():
            if team not in ratings:
                continue
            for contrib in log:
                if contrib.opponent not in ratings:
                    continue
                gap = (ratings[team] - ratings[contrib.opponent]) / params.margin_scale
                sxx += gap * gap
                for metric, value in game_metric_diffs(contrib).items():
                    sxy[metric] += gap * value
    return {metric: (sxy[metric] / sxx if sxx > 0 else 0.0) for metric in QUALITY_METRICS}


def coordinate_search(
    bundles: Sequence[SeasonBundle],
    start: ModelParams,
    rounds: int = 4,
    min_improvement: float = 1e-3,
    progress: Optional[Callable[[int, str, BacktestMetrics], None]] = None,
) -> Tuple[ModelParams, BacktestMetrics, int]:
    """
    Greedy coordinate descent on ``BacktestMetrics.score``.

    Each coordinate walks in whichever direction improves the score until it
    stops improving. Step sizes halve after a round with no improvement.
    """
    best = copy.deepcopy(start)
    best_metrics, _ = evaluate_params(list(bundles), best)
    evaluations = 1
    steps = {coord.name: coord.step for coord in COORDINATES}

    for round_index in range(rounds):
        improved = False
        for coord in COORDINATES:
            for direction in (1.0, -1.0):
                moved = False
                while True:
                    target = get_value(best, coord.name) + direction * steps[coord.name]
                    candidate = with_value(best, coord, target)
                    if candidate is None:
                        break
                    metrics, _ = evaluate_params(list(bundles), candidate)
                    evaluations += 1
                    if metrics.score() < best_metrics.score() - min_improvement:
                        best, best_metrics, moved = candidate, metrics, True
                        continue
                    break
                if moved:
                    improved = True
                    break
            if progress:
                progress(round_index + 1, coord.name, best_metrics)
        if not improved:
            steps = {
                coord.name: max(1.0, steps[coord.name] / 2.0) if coord.integer else steps[coord.name] / 2.0
                for coord in COORDINATES
            }
    return best, best_metrics, evaluations


def calibrate_matchups(bundles: Sequence[SeasonBundle], params: ModelParams) -> Dict[str, float]:
    """
    Fit the matchup page's scale, home field and win-probability curve, and the
    win-probability curve for solver-rating margins used by the poll's SOR.

    The rank floor is kept only if it lowers the page's error at the fitted scale.
    """
    metrics, detail = evaluate_params(list(bundles), params)
    params.matchup_margin_scale = metrics.implied_matchup_margin_scale
    params.matchup_hfa = metrics.fitted_hfa
    params.win_prob_scale = metrics.fitted_win_prob_scale

    actual = detail["actual_margin"].to_numpy(dtype=float)
    params.solver_win_prob_scale = fit_win_prob_scale(
        detail["solver_margin"].to_numpy(dtype=float), actual
    )
    rank_floor_mae = {}
    for rank_pt in (0.0, 0.1, 0.2):
        margins = site_margins(detail, params, rank_pt=rank_pt)
        rank_floor_mae[rank_pt] = float(np.mean(np.abs(actual - margins)))
    params.matchup_rank_pt = min(rank_floor_mae, key=rank_floor_mae.get)
    return {f"rank_pt_{key:.1f}_mae": value for key, value in rank_floor_mae.items()}


def run_tuning(
    start_season: int = 2018,
    end_season: int = 2025,
    rounds: int = 4,
    holdout: Sequence[int] = (),
    save: bool = True,
    client: Optional[CFBDClient] = None,
    progress: Optional[Callable[[int, str, BacktestMetrics], None]] = None,
) -> Dict:
    """
    Tune from the active params, then calibrate the matchup mapping.

    Seasons in ``holdout`` are excluded from the search and reported separately
    (baseline vs tuned) as an out-of-sample check.
    """
    import os

    # Small Newton solves are faster on one BLAS thread; the walk-forward
    # launches hundreds of them.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")

    owns_client = client is None
    if owns_client:
        client = CFBDClient()

    try:
        baseline = get_active_params()
        bundles = load_season_bundles(
            client,
            start_season,
            end_season,
            pause_seconds=0.0,
            exclude_garbage_time=baseline.exclude_garbage_time,
        )
        train = [bundle for bundle in bundles if bundle.season not in set(holdout)]
        test = [bundle for bundle in bundles if bundle.season in set(holdout)]

        baseline_metrics, _ = evaluate_params(train, baseline)
        start = copy.deepcopy(baseline)
        start.quality_opponent_slopes = estimate_quality_slopes(train, start)
        tuned, _, evaluations = coordinate_search(train, start, rounds=rounds, progress=progress)
        tuned.h2h_max_total = tuned.h2h_window
        tuned.quality_opponent_slopes = estimate_quality_slopes(train, tuned)
        rank_floor = calibrate_matchups(train, tuned)
        tuned.normalize()
        tuned_metrics, _ = evaluate_params(train, tuned)

        result: Dict = {
            "evaluations": evaluations,
            "baseline": {"metrics": baseline_metrics, "params": baseline.to_dict()},
            "tuned": {"metrics": tuned_metrics, "params": tuned.to_dict()},
            "rank_floor": rank_floor,
        }
        if test:
            result["holdout"] = {
                "seasons": sorted(bundle.season for bundle in test),
                "baseline": evaluate_params(test, baseline)[0],
                "tuned": evaluate_params(test, tuned)[0],
            }

        if save:
            payload = tuned.to_dict()
            payload["tuning_method"] = "coordinate_search_phase_split"
            TUNED_PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with TUNED_PARAMS_PATH.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        return result
    finally:
        if owns_client and client is not None:
            client.close()

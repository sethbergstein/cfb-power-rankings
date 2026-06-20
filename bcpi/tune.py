"""Hyperparameter search for BCPI model weights."""

from __future__ import annotations

import copy
import random
from typing import Callable, Dict, List, Optional, Tuple

from bcpi.backtest import (
    BacktestMetrics,
    SeasonBundle,
    evaluate_params,
    load_season_bundles,
)
from bcpi.cfbd import CFBDClient
from bcpi.params import DEFAULT_PARAMS_PATH, ModelParams, TUNED_PARAMS_PATH


def _sample_weight_dict(keys: List[str], rng: random.Random) -> Dict[str, float]:
    raw = {key: rng.random() for key in keys}
    total = sum(raw.values())
    return {key: value / total for key, value in raw.items()}


def _mutate_weights(
    weights: Dict[str, float],
    keys: List[str],
    rng: random.Random,
    sigma: float = 0.08,
) -> Dict[str, float]:
    mutated = {}
    for key in keys:
        mutated[key] = max(0.01, weights[key] + rng.uniform(-sigma, sigma))
    total = sum(mutated.values())
    return {key: value / total for key, value in mutated.items()}


def random_params(rng: random.Random, base: Optional[ModelParams] = None) -> ModelParams:
    params = copy.deepcopy(base) if base else ModelParams()
    params.recency_lambda = rng.uniform(0.18, 0.50)
    params.form_weight = rng.uniform(0.40, 0.70)
    params.k_factor = rng.uniform(12.0, 24.0)
    params.margin_scale = rng.uniform(22.0, 30.0)
    params.hfa = rng.uniform(2.0, 3.5)
    params.fcs_margin_cap = rng.uniform(17.0, 24.0)
    params.prior_fade_end = rng.randint(6, 10)
    params.win_prob_scale = rng.uniform(11.0, 16.0)
    params.power_weights = _sample_weight_dict(list(params.power_weights.keys()), rng)
    params.quality_weights = _sample_weight_dict(list(params.quality_weights.keys()), rng)
    params.prior_weights = _sample_weight_dict(list(params.prior_weights.keys()), rng)
    params.normalize()
    return params


def _local_refine(
    bundles: List[SeasonBundle],
    client: CFBDClient,
    start: ModelParams,
    rng: random.Random,
    iterations: int = 40,
) -> Tuple[ModelParams, BacktestMetrics]:
    best = copy.deepcopy(start)
    best_metrics, _ = evaluate_params(bundles, best, client)
    best_score = best_metrics.score()

    for _ in range(iterations):
        candidate = copy.deepcopy(best)
        candidate.recency_lambda += rng.uniform(-0.04, 0.04)
        candidate.form_weight += rng.uniform(-0.06, 0.06)
        candidate.k_factor += rng.uniform(-2.0, 2.0)
        candidate.margin_scale += rng.uniform(-1.5, 1.5)
        candidate.hfa += rng.uniform(-0.25, 0.25)
        candidate.fcs_margin_cap += rng.uniform(-2.0, 2.0)
        candidate.prior_fade_end = int(
            max(5, min(12, candidate.prior_fade_end + rng.randint(-1, 1)))
        )
        candidate.win_prob_scale += rng.uniform(-1.0, 1.0)
        candidate.power_weights = _mutate_weights(
            candidate.power_weights,
            list(candidate.power_weights.keys()),
            rng,
            sigma=0.05,
        )
        candidate.quality_weights = _mutate_weights(
            candidate.quality_weights,
            list(candidate.quality_weights.keys()),
            rng,
            sigma=0.05,
        )
        candidate.prior_weights = _mutate_weights(
            candidate.prior_weights,
            list(candidate.prior_weights.keys()),
            rng,
            sigma=0.05,
        )
        candidate.recency_lambda = max(0.10, min(0.60, candidate.recency_lambda))
        candidate.form_weight = max(0.30, min(0.80, candidate.form_weight))
        candidate.k_factor = max(8.0, min(30.0, candidate.k_factor))
        candidate.margin_scale = max(18.0, min(35.0, candidate.margin_scale))
        candidate.hfa = max(1.5, min(4.5, candidate.hfa))
        candidate.fcs_margin_cap = max(14.0, min(28.0, candidate.fcs_margin_cap))
        candidate.win_prob_scale = max(9.0, min(18.0, candidate.win_prob_scale))
        candidate.normalize()

        metrics, _ = evaluate_params(bundles, candidate, client)
        score = metrics.score()
        if score < best_score:
            best = candidate
            best_metrics = metrics
            best_score = score

    return best, best_metrics


def tune_params(
    bundles: List[SeasonBundle],
    client: CFBDClient,
    rng_seed: int = 42,
    random_samples: int = 80,
    refine_iterations: int = 50,
    progress_callback: Optional[
        Callable[[int, int, ModelParams, BacktestMetrics], None]
    ] = None,
) -> Tuple[ModelParams, BacktestMetrics, ModelParams, BacktestMetrics]:
    rng = random.Random(rng_seed)
    baseline = ModelParams()
    baseline_metrics, _ = evaluate_params(bundles, baseline, client)
    baseline_score = baseline_metrics.score()

    best = copy.deepcopy(baseline)
    best_metrics = baseline_metrics
    best_score = baseline_score

    for index in range(random_samples):
        candidate = random_params(rng, base=best)
        metrics, _ = evaluate_params(bundles, candidate, client)
        score = metrics.score()
        if score < best_score:
            best = candidate
            best_metrics = metrics
            best_score = score
        if progress_callback:
            progress_callback(index + 1, random_samples, best, best_metrics)

    refined, refined_metrics = _local_refine(
        bundles,
        client,
        best,
        rng,
        iterations=refine_iterations,
    )
    if refined_metrics.score() < best_score:
        best = refined
        best_metrics = refined_metrics
        best_score = refined_metrics.score()

    return best, best_metrics, baseline, baseline_metrics


def run_tuning(
    start_season: int = 2018,
    end_season: int = 2025,
    random_samples: int = 80,
    refine_iterations: int = 50,
    save: bool = True,
    client: Optional[CFBDClient] = None,
) -> Dict:
    owns_client = client is None
    if owns_client:
        client = CFBDClient()

    try:
        bundles = load_season_bundles(client, start_season, end_season, pause_seconds=0.0)

        def progress(done: int, total: int, best: ModelParams, metrics: BacktestMetrics) -> None:
            print(
                f"  sample {done}/{total} | best MAE={metrics.margin_mae:.2f} "
                f"logloss={metrics.win_log_loss:.3f} score={metrics.score():.3f}",
                flush=True,
            )

        tuned, tuned_metrics, baseline, baseline_metrics = tune_params(
            bundles=bundles,
            client=client,
            random_samples=random_samples,
            refine_iterations=refine_iterations,
            progress_callback=progress,
        )

        if save:
            payload = tuned.to_dict()
            payload["tuning_method"] = "game_epa"
            TUNED_PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with TUNED_PARAMS_PATH.open("w", encoding="utf-8") as handle:
                import json
                json.dump(payload, handle, indent=2)
            baseline.save(DEFAULT_PARAMS_PATH)

        return {
            "baseline": {
                "metrics": baseline_metrics,
                "params": baseline.to_dict(),
            },
            "tuned": {
                "metrics": tuned_metrics,
                "params": tuned.to_dict(),
            },
            "improvement": {
                "margin_mae": baseline_metrics.margin_mae - tuned_metrics.margin_mae,
                "win_log_loss": baseline_metrics.win_log_loss - tuned_metrics.win_log_loss,
                "score": baseline_metrics.score() - tuned_metrics.score(),
            },
        }
    finally:
        if owns_client and client is not None:
            client.close()

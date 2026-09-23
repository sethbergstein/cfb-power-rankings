"""Tunable model parameters for BCPI."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

from bcpi.config import PROJECT_ROOT
from bcpi.constants import (
    FCS_RATING,
    HOME_FIELD_ADVANTAGE,
    MARGIN_COMPRESSION,
    POWER_WEIGHTS,
    PRIOR_WEIGHTS,
    QUALITY_OPPONENT_SLOPES,
    QUALITY_WEIGHTS,
    RECENCY_DECAY_LAMBDA,
    SOLVER_MAX_ITERATIONS,
    SOLVER_TOLERANCE,
)

TUNED_PARAMS_PATH = PROJECT_ROOT / "config" / "tuned_params.json"
DEFAULT_PARAMS_PATH = PROJECT_ROOT / "config" / "default_params.json"


def _normalize(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {key: value / total for key, value in weights.items()}


@dataclass
class ModelParams:
    """All weights and scalars used by the BCPI power model."""

    # Solver: opponent-adjusted margin ratings.
    recency_lambda: float = RECENCY_DECAY_LAMBDA
    k_factor: float = 8.0
    margin_scale: float = 19.0
    hfa: float = HOME_FIELD_ADVANTAGE
    fcs_rating: float = FCS_RATING
    margin_compression: float = MARGIN_COMPRESSION
    solver_max_iterations: int = SOLVER_MAX_ITERATIONS
    solver_tolerance: float = SOLVER_TOLERANCE
    prior_fade_start: int = 1
    prior_fade_end: int = 12
    defending_champion_prior_z: float = 0.0

    # Quality: opponent-adjusted efficiency blended with scoring form.
    form_weight: float = 0.35
    exclude_garbage_time: bool = False
    quality_opponent_slopes: Dict[str, float] = field(
        default_factory=lambda: deepcopy(QUALITY_OPPONENT_SLOPES)
    )

    # Composite: games needed before quality fully replaces the prior, and the
    # head-to-head window (power-score units) inside which a winner closes the gap.
    power_sample_games: float = 6.0
    h2h_window: float = 0.15
    h2h_max_total: float = 0.15
    h2h_site_adjusted: bool = True
    playoff_appearance_bonus: float = 0.0
    playoff_win_bonus: float = 0.0

    # Matchup predictions from published power ratings. ``matchup_hfa`` is the
    # league-wide home edge for those predictions; ``hfa`` above only neutralizes
    # game sites inside the solver.
    matchup_margin_scale: float = 9.0
    matchup_hfa: float = HOME_FIELD_ADVANTAGE
    matchup_rank_pt: float = 0.20
    win_prob_scale: float = 13.5
    # Logistic scale turning solver-rating margins into win probabilities (poll SOR).
    solver_win_prob_scale: float = 8.5
    hfa_team_max_delta: float = 1.75
    hfa_lookback_seasons: int = 5
    hfa_min_games: int = 6
    hfa_shrink_games: float = 12.0

    power_weights: Dict[str, float] = field(default_factory=lambda: deepcopy(POWER_WEIGHTS))
    quality_weights: Dict[str, float] = field(default_factory=lambda: deepcopy(QUALITY_WEIGHTS))
    prior_weights: Dict[str, float] = field(default_factory=lambda: deepcopy(PRIOR_WEIGHTS))

    def normalize(self) -> None:
        self.power_weights = _normalize(self.power_weights)
        self.quality_weights = _normalize(self.quality_weights)
        self.prior_weights = _normalize(self.prior_weights)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict) -> "ModelParams":
        params = cls()
        skip_keys = {"tuning_method"}
        for key, value in payload.items():
            if key in skip_keys:
                continue
            if key.endswith("_weights") and isinstance(value, dict):
                setattr(params, key, value)
            elif hasattr(params, key):
                setattr(params, key, value)
        params.normalize()
        return params

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ModelParams":
        target = path or TUNED_PARAMS_PATH
        if target.exists():
            with target.open("r", encoding="utf-8") as handle:
                return cls.from_dict(json.load(handle))
        return cls()

    def save(self, path: Optional[Path] = None) -> Path:
        target = path or TUNED_PARAMS_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        self.normalize()
        with target.open("w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2)
        return target


def get_active_params() -> ModelParams:
    """Return tuned params if present, otherwise defaults."""
    if TUNED_PARAMS_PATH.exists():
        return ModelParams.load(TUNED_PARAMS_PATH)
    return ModelParams()

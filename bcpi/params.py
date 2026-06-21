"""Tunable model parameters for BCPI."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from bcpi.config import PROJECT_ROOT
from bcpi.constants import (
    FCS_MARGIN_CAP,
    HOME_FIELD_ADVANTAGE,
    POWER_WEIGHTS,
    PRIOR_WEIGHTS,
    QUALITY_WEIGHTS,
    RECENCY_DECAY_LAMBDA,
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
    """All weights and scalars used by the BCPI model."""

    recency_lambda: float = RECENCY_DECAY_LAMBDA
    form_weight: float = 0.55
    k_factor: float = 18.0
    margin_scale: float = 25.0
    hfa: float = HOME_FIELD_ADVANTAGE
    fcs_margin_cap: float = FCS_MARGIN_CAP
    form_margin_cap: float = 28.0
    opp_quality_scale: float = 0.45
    opp_quality_min: float = 0.40
    opp_quality_max: float = 1.60
    h2h_penalty: float = 0.14
    h2h_winner_boost: float = 0.30
    h2h_max_total: float = 0.28
    h2h_use_recency: bool = False
    elite_quality_weight: float = 0.70
    elite_opponent_top_n: int = 30
    playoff_appearance_bonus: float = 0.05
    playoff_win_bonus: float = 0.035
    prior_fade_start: int = 1
    prior_fade_end: int = 8
    win_prob_scale: float = 13.5
    defending_champion_prior_z: float = 0.10
    power_weights: Dict[str, float] = field(default_factory=lambda: deepcopy(POWER_WEIGHTS))
    quality_weights: Dict[str, float] = field(default_factory=lambda: deepcopy(QUALITY_WEIGHTS))
    prior_weights: Dict[str, float] = field(default_factory=lambda: deepcopy(PRIOR_WEIGHTS))

    def normalize(self) -> None:
        self.power_weights = _normalize(self.power_weights)
        self.quality_weights = _normalize(self.quality_weights)
        self.prior_weights = _normalize(self.prior_weights)

    def to_dict(self) -> Dict:
        return {
            "recency_lambda": self.recency_lambda,
            "form_weight": self.form_weight,
            "k_factor": self.k_factor,
            "margin_scale": self.margin_scale,
            "hfa": self.hfa,
            "fcs_margin_cap": self.fcs_margin_cap,
            "form_margin_cap": self.form_margin_cap,
            "opp_quality_scale": self.opp_quality_scale,
            "opp_quality_min": self.opp_quality_min,
            "opp_quality_max": self.opp_quality_max,
            "h2h_penalty": self.h2h_penalty,
            "h2h_winner_boost": self.h2h_winner_boost,
            "h2h_max_total": self.h2h_max_total,
            "h2h_use_recency": self.h2h_use_recency,
            "elite_quality_weight": self.elite_quality_weight,
            "elite_opponent_top_n": self.elite_opponent_top_n,
            "playoff_appearance_bonus": self.playoff_appearance_bonus,
            "playoff_win_bonus": self.playoff_win_bonus,
            "prior_fade_start": self.prior_fade_start,
            "prior_fade_end": self.prior_fade_end,
            "win_prob_scale": self.win_prob_scale,
            "defending_champion_prior_z": self.defending_champion_prior_z,
            "power_weights": self.power_weights,
            "quality_weights": self.quality_weights,
            "prior_weights": self.prior_weights,
        }

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

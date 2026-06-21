"""Parameters for Bergstein poll-style (resume) rankings."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from bcpi.config import PROJECT_ROOT

RESUME_PARAMS_PATH = PROJECT_ROOT / "config" / "resume_params.json"

DEFAULT_RESUME_WEIGHTS = {
    "record": 0.26,
    "schedule": 0.22,
    "results": 0.24,
    "elite_wins": 0.14,
    "playoff": 0.14,
}

DEFAULT_PLAYOFF_ROUND_PARTICIPATION = {
    "first_round": 0.04,
    "quarterfinal": 0.06,
    "semifinal": 0.08,
    "championship": 0.14,
}


def _normalize(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {key: value / total for key, value in weights.items()}


@dataclass
class ResumeParams:
    """Poll/resume index weights — separate from BCPI power tuning."""

    resume_weights: Dict[str, float] = field(default_factory=lambda: deepcopy(DEFAULT_RESUME_WEIGHTS))
    playoff_appearance_bonus: float = 0.05
    playoff_round_participation: Dict[str, float] = field(
        default_factory=lambda: deepcopy(DEFAULT_PLAYOFF_ROUND_PARTICIPATION)
    )
    playoff_round_win_bonus: float = 0.04
    playoff_champion_bonus: float = 0.06
    elite_win_top_n: int = 30
    loss_penalty_factor: float = 0.65
    sub500_poll_penalty: float = 0.85
    preseason_resume_weight: float = 0.45
    preseason_forward_weight: float = 0.35
    preseason_consensus_weight: float = 0.20

    def normalize(self) -> None:
        self.resume_weights = _normalize(self.resume_weights)

    def to_dict(self) -> Dict:
        return {
            "resume_weights": self.resume_weights,
            "playoff_appearance_bonus": self.playoff_appearance_bonus,
            "playoff_round_participation": self.playoff_round_participation,
            "playoff_round_win_bonus": self.playoff_round_win_bonus,
            "playoff_champion_bonus": self.playoff_champion_bonus,
            "elite_win_top_n": self.elite_win_top_n,
            "loss_penalty_factor": self.loss_penalty_factor,
            "sub500_poll_penalty": self.sub500_poll_penalty,
            "preseason_resume_weight": self.preseason_resume_weight,
            "preseason_forward_weight": self.preseason_forward_weight,
            "preseason_consensus_weight": self.preseason_consensus_weight,
        }

    @classmethod
    def from_dict(cls, payload: Dict) -> "ResumeParams":
        params = cls()
        for key, value in payload.items():
            if key == "resume_weights" and isinstance(value, dict):
                params.resume_weights = value
            elif key == "playoff_round_participation" and isinstance(value, dict):
                params.playoff_round_participation = value
            elif hasattr(params, key):
                setattr(params, key, value)
        params.normalize()
        return params

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ResumeParams":
        target = path or RESUME_PARAMS_PATH
        if target.exists():
            with target.open("r", encoding="utf-8") as handle:
                return cls.from_dict(json.load(handle))
        return cls()


def get_resume_params() -> ResumeParams:
    return ResumeParams.load()

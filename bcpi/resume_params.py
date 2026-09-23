"""Parameters for Bergstein poll-style (resume) rankings."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

from bcpi.config import PROJECT_ROOT

RESUME_PARAMS_PATH = PROJECT_ROOT / "config" / "resume_params.json"

# Bonus in wins for the deepest CFP round reached (a first-round loss earns nothing
# beyond the games themselves).
DEFAULT_PLAYOFF_ROUND_BONUS = {
    "first_round": 0.0,
    "quarterfinal": 0.1,
    "semifinal": 0.25,
    "championship": 0.5,
}

DEFAULT_PRESEASON_WEIGHTS = {
    "previous_poll": 0.45,
    "talent": 0.35,
    "consensus": 0.20,
}


def _normalize(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {key: value / total for key, value in weights.items()}


@dataclass
class ResumeParams:
    """Poll/resume index settings — separate from BCPI power tuning."""

    # Benchmark: the average of the top N teams by solver rating.
    benchmark_top_n: int = 25
    # Resume = sor_weight * z(SOR) + (1 - sor_weight) * z(performance).
    sor_weight: float = 0.8
    # Preseason share of the poll = K / (K + games); FCS games count as a fraction.
    preseason_games_k: float = 2.0
    fcs_game_weight: float = 0.5
    preseason_weights: Dict[str, float] = field(
        default_factory=lambda: deepcopy(DEFAULT_PRESEASON_WEIGHTS)
    )
    defending_champion_bonus: float = 0.10
    # A winner within this many poll-score units of the team it beat closes the gap.
    h2h_window: float = 0.40
    h2h_max_total: float = 0.40
    playoff_round_bonus: Dict[str, float] = field(
        default_factory=lambda: deepcopy(DEFAULT_PLAYOFF_ROUND_BONUS)
    )
    playoff_champion_bonus: float = 0.25
    playoff_bonus_cap: float = 1.0
    # Off by default: the champion is flagged by the checks, not forced to #1.
    force_champion_first: bool = True

    def normalize(self) -> None:
        self.preseason_weights = _normalize(self.preseason_weights)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict) -> "ResumeParams":
        params = cls()
        for key, value in payload.items():
            if isinstance(value, dict) and isinstance(getattr(params, key, None), dict):
                setattr(params, key, dict(value))
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

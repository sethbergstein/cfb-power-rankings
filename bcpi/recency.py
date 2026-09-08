"""Recency weighting for in-season updates."""

from __future__ import annotations

import math
from typing import Union

import pandas as pd

from bcpi.constants import RECENCY_DECAY_LAMBDA


def sample_credibility(
    n_games: Union[pd.Series, float, int],
    full_sample: float,
) -> Union[pd.Series, float]:
    """Share of in-season weight to trust. Unplayed teams stay on the prior."""
    if full_sample <= 0:
        if isinstance(n_games, pd.Series):
            return pd.Series(1.0, index=n_games.index)
        return 1.0
    cred = n_games / full_sample
    if isinstance(cred, pd.Series):
        return cred.astype(float).clip(upper=1.0)
    return float(min(1.0, cred))


def recency_weight(current_week: int, game_week: int, lambda_: float = RECENCY_DECAY_LAMBDA) -> float:
    weeks_ago = max(0, current_week - game_week)
    return math.exp(-lambda_ * weeks_ago)


def blend_form_season(
    form_value: float,
    season_value: float,
    form_weight: float = 0.55,
) -> float:
    form_ok = form_value is not None and not math.isnan(form_value)
    season_ok = season_value is not None and not math.isnan(season_value)
    if form_ok and season_ok:
        return form_weight * form_value + (1.0 - form_weight) * season_value
    if form_ok:
        return form_value
    if season_ok:
        return season_value
    return float("nan")

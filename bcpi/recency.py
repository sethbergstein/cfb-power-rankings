"""Recency weighting for in-season updates."""

from __future__ import annotations

import math

from bcpi.constants import RECENCY_DECAY_LAMBDA


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

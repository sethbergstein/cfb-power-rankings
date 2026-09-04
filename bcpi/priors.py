"""Preseason priors for BCPI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from bcpi.cfbd import CFBDClient
from bcpi.champions import load_defending_champion
from bcpi.constants import (
    FCS_INITIAL_RATING_OFFSET,
    FCS_OPPONENT_KEY,
    RATING_MEAN,
    RATING_SPREAD,
)
from bcpi.params import ModelParams
from bcpi.teams import Team


def _zscore(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    std = series.std(ddof=0, skipna=True)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean(skipna=True)) / std


def _rating_from_z(z: float) -> float:
    return RATING_MEAN + z * (RATING_SPREAD / 2.5)


def _returning_value(row: dict) -> Optional[float]:
    value = row.get("percentPPA")
    if value is None:
        value = row.get("usage")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


RETURNING_Z_CLIP = 1.25


@dataclass
class PriorComponents:
    schools: List[str]
    prev_elo_z: pd.Series
    talent_z: pd.Series
    returning_z: pd.Series
    consensus_z: pd.Series


def load_prior_components(
    client: CFBDClient,
    teams: List[Team],
    season: int,
) -> PriorComponents:
    """Fetch raw prior inputs once per season (for fast tuning)."""
    schools = [team.school for team in teams]
    frame = pd.DataFrame({"school": schools}).set_index("school")

    prev_year = season - 1
    elo_map = {row["team"]: float(row["elo"]) for row in client.get_elo(prev_year)}
    frame["prev_elo"] = frame.index.map(lambda s: elo_map.get(s))

    talent_rows = client.get_team_talent(season) or client.get_team_talent(prev_year)
    talent_map = {row["team"]: float(row["talent"]) for row in talent_rows}
    frame["talent"] = frame.index.map(lambda s: talent_map.get(s))

    try:
        returning = client.get("/player/returning", {"year": season})
        returning_map = {}
        for row in returning:
            value = _returning_value(row)
            if value is not None:
                returning_map[row["team"]] = value
        frame["returning"] = frame.index.map(lambda s: returning_map.get(s))
    except Exception:
        frame["returning"] = None

    consensus_map: Dict[str, float] = {}
    try:
        poll = client.get_rankings(season, week=1, season_type="regular")
        if poll:
            ranks = poll[0].get("polls", [])
            ap = next((p for p in ranks if p.get("poll") == "AP Top 25"), None)
            if ap:
                for rank_row in ap.get("ranks", []):
                    consensus_map[rank_row["school"]] = float(rank_row["rank"])
    except Exception:
        pass
    frame["consensus_rank"] = frame.index.map(lambda s: consensus_map.get(s))

    returning_z = _zscore(frame["returning"].astype(float)).clip(
        -RETURNING_Z_CLIP, RETURNING_Z_CLIP
    )
    consensus_z = _zscore(
        frame["consensus_rank"].astype(float).map(lambda r: -r if pd.notna(r) else None)
    ).fillna(0.0)

    return PriorComponents(
        schools=schools,
        prev_elo_z=_zscore(frame["prev_elo"].astype(float)),
        talent_z=_zscore(frame["talent"].astype(float)),
        returning_z=returning_z,
        consensus_z=consensus_z,
    )


def blend_prior_components(components: PriorComponents, params: ModelParams) -> Dict[str, float]:
    key_to_series = {
        "previous_season": components.prev_elo_z,
        "talent": components.talent_z,
        "returning": components.returning_z,
        "consensus": components.consensus_z,
    }
    composite_z = pd.Series(0.0, index=components.schools)
    weight_sum = pd.Series(0.0, index=components.schools)
    for key, weight in params.prior_weights.items():
        series = key_to_series[key]
        valid = series.notna()
        composite_z.loc[valid] += weight * series.loc[valid]
        weight_sum.loc[valid] += weight
    nonzero = weight_sum > 0
    composite_z.loc[nonzero] = composite_z.loc[nonzero] / weight_sum.loc[nonzero]

    ratings = {
        school: _rating_from_z(float(composite_z.loc[school]))
        for school in components.schools
    }
    ratings[FCS_OPPONENT_KEY] = RATING_MEAN + FCS_INITIAL_RATING_OFFSET
    return ratings


def build_preseason_priors(
    client: CFBDClient,
    teams: List[Team],
    season: int,
    params: Optional[ModelParams] = None,
    components: Optional[PriorComponents] = None,
) -> Dict[str, float]:
    """Blend previous-season performance, talent, returning production, and consensus."""
    if params is None:
        params = ModelParams()
    if components is None:
        components = load_prior_components(client, teams, season)

    ratings = blend_prior_components(components, params)
    if params.defending_champion_prior_z > 0:
        champ = load_defending_champion(client, season)
        if champ in ratings:
            ratings[champ] += params.defending_champion_prior_z * (RATING_SPREAD / 2.5)
    return ratings


def decay_prior_weight(week: int, fade_start: int = 1, fade_end: int = 8) -> float:
    """How much preseason prior remains at a given week."""
    if week <= fade_start:
        return 1.0
    if week >= fade_end:
        return 0.0
    return max(0.0, 1.0 - (week - fade_start) / (fade_end - fade_start))

"""Preseason priors for BCPI."""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from bcpi.cfbd import CFBDClient
from bcpi.constants import (
    FCS_INITIAL_RATING_OFFSET,
    FCS_OPPONENT_KEY,
    PRIOR_WEIGHTS,
    RATING_MEAN,
    RATING_SPREAD,
)
from bcpi.teams import Team


def _zscore(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    std = series.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _rating_from_z(z: float) -> float:
    return RATING_MEAN + z * (RATING_SPREAD / 2.5)


def build_preseason_priors(
    client: CFBDClient,
    teams: List[Team],
    season: int,
) -> Dict[str, float]:
    """Blend previous-season performance, talent, returning production, and consensus."""
    schools = [team.school for team in teams]
    frame = pd.DataFrame({"school": schools}).set_index("school")

    prev_year = season - 1
    elo_rows = client.get_elo(prev_year)
    elo_map = {row["team"]: float(row["elo"]) for row in elo_rows}
    frame["prev_elo"] = frame.index.map(lambda s: elo_map.get(s))

    talent_rows = client.get_team_talent(prev_year)
    talent_map = {row["team"]: float(row["talent"]) for row in talent_rows}
    frame["talent"] = frame.index.map(lambda s: talent_map.get(s))

    # Returning production (optional; CFBD endpoint may be sparse).
    try:
        returning = client.get("/player/returning", {"year": season})
        returning_map = {
            row["team"]: float(row.get("percentPPA", row.get("usage", 0)))
            for row in returning
        }
        frame["returning"] = frame.index.map(lambda s: returning_map.get(s))
    except Exception:
        frame["returning"] = None

    # Consensus preseason AP poll when available (week 1).
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

    components = {
        "prev_elo": _zscore(frame["prev_elo"].astype(float)),
        "talent": _zscore(frame["talent"].astype(float)),
        "returning": _zscore(frame["returning"].astype(float)),
        "consensus": _zscore(
            frame["consensus_rank"].astype(float).map(lambda r: -r if pd.notna(r) else None)
        ),
    }

    weights = {
        "previous_season": PRIOR_WEIGHTS["previous_season"],
        "talent": PRIOR_WEIGHTS["talent"],
        "returning": PRIOR_WEIGHTS["returning"],
        "consensus": PRIOR_WEIGHTS["consensus"],
    }
    key_to_component = {
        "previous_season": "prev_elo",
        "talent": "talent",
        "returning": "returning",
        "consensus": "consensus",
    }

    composite_z = pd.Series(0.0, index=frame.index)
    used_weight = 0.0
    for key, weight in weights.items():
        col = components[key_to_component[key]]
        valid = col.notna()
        if valid.any():
            composite_z.loc[valid] += weight * col.loc[valid]
            used_weight += weight

    if used_weight > 0:
        composite_z = composite_z / used_weight

    ratings = {
        school: _rating_from_z(float(composite_z.loc[school]))
        for school in frame.index
    }
    ratings[FCS_OPPONENT_KEY] = RATING_MEAN + FCS_INITIAL_RATING_OFFSET
    return ratings


def decay_prior_weight(week: int, fade_start: int = 1, fade_end: int = 8) -> float:
    """How much preseason prior remains at a given week."""
    if week <= fade_start:
        return 1.0
    if week >= fade_end:
        return 0.0
    return max(0.0, 1.0 - (week - fade_start) / (fade_end - fade_start))

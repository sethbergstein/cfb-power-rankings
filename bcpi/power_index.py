"""Quality metrics and composite Bergstein CFB Power Index."""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from bcpi.cfbd import CFBDClient
from bcpi.constants import POWER_WEIGHTS, QUALITY_WEIGHTS, RATING_MEAN, RATING_SPREAD
from bcpi.games import GameResult, filter_games_through_week
from bcpi.recency import blend_form_season, recency_weight
from bcpi.solver import TeamRatingState


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _rating_from_z(z: float) -> float:
    return RATING_MEAN + z * (RATING_SPREAD / 2.5)


def load_quality_metrics(
    client: CFBDClient,
    season: int,
    schools: List[str],
) -> pd.DataFrame:
    """Pull opponent-adjusted-ish season advanced stats from CFBD."""
    rows = client.get_advanced_season_stats(season)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(index=schools)

    frame = frame[frame["team"].isin(schools)].copy()
    frame = frame.set_index("team")

    offense = frame.get("offense", pd.Series(dtype=object))
    defense = frame.get("defense", pd.Series(dtype=object))

    def _metric(side: pd.Series, key: str) -> pd.Series:
        return side.map(lambda d: d.get(key) if isinstance(d, dict) else None)

    quality = pd.DataFrame(index=frame.index)
    quality["epa_off"] = _metric(offense, "ppa")
    quality["epa_def"] = _metric(defense, "ppa")
    quality["success_off"] = _metric(offense, "successRate")
    quality["success_def"] = _metric(defense, "successRate")
    quality["explosiveness_off"] = _metric(offense, "explosiveness")
    quality["explosiveness_def"] = _metric(defense, "explosiveness")
    quality["pass_off"] = offense.map(
        lambda d: d.get("passingPlays", {}).get("ppa") if isinstance(d, dict) else None
    )
    quality["pass_def"] = defense.map(
        lambda d: d.get("passingPlays", {}).get("ppa") if isinstance(d, dict) else None
    )
    quality["havoc_off"] = offense.map(
        lambda d: d.get("havoc", {}).get("total") if isinstance(d, dict) else None
    )
    quality["havoc_def"] = defense.map(
        lambda d: d.get("havoc", {}).get("total") if isinstance(d, dict) else None
    )

    quality["epa_diff"] = quality["epa_off"] - quality["epa_def"]
    quality["success_diff"] = quality["success_off"] - quality["success_def"]
    quality["explosiveness_diff"] = quality["explosiveness_off"] - quality["explosiveness_def"]
    quality["passing_diff"] = quality["pass_off"] - quality["pass_def"]
    quality["havoc_diff"] = quality["havoc_def"] - quality["havoc_off"]

    return quality.reindex(schools)


def compute_form_quality(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
    form_games: int = 3,
) -> pd.Series:
    """Simple form proxy: weighted average scoring margin in recent games."""
    margins: Dict[str, List[tuple]] = {school: [] for school in schools}

    for game in filter_games_through_week(games, current_week):
        if not game.is_fbs_game:
            continue
        weight = recency_weight(current_week, game.week)
        margins[game.home_team].append((game.margin_home, weight))
        margins[game.away_team].append((-game.margin_home, weight))

    form_values = {}
    for school in schools:
        values = margins.get(school, [])
        if not values:
            form_values[school] = 0.0
            continue
        recent = sorted(values, key=lambda x: x[1], reverse=True)[:form_games]
        w_sum = sum(w for _, w in recent)
        form_values[school] = sum(m * w for m, w in recent) / w_sum if w_sum else 0.0
    return pd.Series(form_values)


def build_power_index(
    client: CFBDClient,
    season: int,
    schools: List[str],
    solver_states: Dict[str, TeamRatingState],
    prior_ratings: Dict[str, float],
    games: List[GameResult],
    current_week: int,
) -> pd.DataFrame:
    quality = load_quality_metrics(client, season, schools)

    if not quality.empty:
        season_quality = pd.Series(0.0, index=schools)
        for metric, weight in QUALITY_WEIGHTS.items():
            if metric in quality.columns:
                season_quality += weight * _zscore(quality[metric].astype(float))
    else:
        season_quality = pd.Series(0.0, index=schools)

    form_margin = compute_form_quality(games, schools, current_week)
    blended_quality = pd.Series(
        {
            school: blend_form_season(
                float(_zscore(form_margin).get(school, 0.0)),
                float(season_quality.get(school, 0.0)),
            )
            for school in schools
        }
    )

    game_value = pd.Series(
        {s: solver_states[s].game_value if s in solver_states else 0.0 for s in schools}
    )
    market_value = pd.Series(
        {s: solver_states[s].market_value if s in solver_states else 0.0 for s in schools}
    )
    talent_prior = pd.Series(
        {s: prior_ratings.get(s, RATING_MEAN) for s in schools}
    )

    components = pd.DataFrame(index=schools)
    components["quality_z"] = blended_quality
    components["game_value_z"] = _zscore(game_value.astype(float))
    components["market_z"] = _zscore(market_value.astype(float))
    components["talent_prior_z"] = _zscore(talent_prior.astype(float))

    composite_z = (
        POWER_WEIGHTS["quality"] * components["quality_z"]
        + POWER_WEIGHTS["game_value"] * components["game_value_z"]
        + POWER_WEIGHTS["market"] * components["market_z"]
        + POWER_WEIGHTS["talent_prior"] * components["talent_prior_z"]
    )

    output = components.copy()
    output["solver_rating"] = [solver_states[s].rating if s in solver_states else RATING_MEAN for s in schools]
    output["power_score"] = composite_z
    output["power_rating"] = composite_z.map(lambda z: _rating_from_z(float(z)))
    output["rank"] = output["power_rating"].rank(ascending=False, method="min").astype(int)
    output = output.sort_values("rank")
    return output

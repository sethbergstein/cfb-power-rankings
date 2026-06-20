"""End-to-end BCPI pipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from bcpi.cfbd import CFBDClient
from bcpi.config import OUTPUT_DIR
from bcpi.constants import TARGET_SEASON
from bcpi.games import load_season_games, POSTSEASON_AS_WEEK
from bcpi.params import get_active_params, ModelParams
from bcpi.resume_index import build_poll_index
from bcpi.resume_params import get_resume_params
from bcpi.power_index import build_power_index_from_client
from bcpi.priors import build_preseason_priors
from bcpi.solver import solve_ratings
from bcpi.teams import get_fbs_teams, team_lookup


def run_rankings(
    season: int = TARGET_SEASON,
    week: Optional[int] = None,
    refresh_data: bool = False,
    client: Optional[CFBDClient] = None,
    params: Optional[ModelParams] = None,
    include_postseason: bool = False,
) -> Path:
    """Fetch data, solve ratings, and write BCPI output CSV."""
    owns_client = client is None
    if owns_client:
        client = CFBDClient(use_cache=not refresh_data)

    if params is None:
        params = get_active_params()

    try:
        teams = get_fbs_teams(client, season, refresh=refresh_data)
        schools = [team.school for team in teams]
        lookup = team_lookup(teams)

        prior_ratings = build_preseason_priors(client, teams, season, params)

        games = load_season_games(client, season, include_postseason=include_postseason)

        if games:
            current_week = week if week is not None else max(g.week for g in games)
        else:
            current_week = week or 0

        solver_states = solve_ratings(
            teams=schools,
            games=games,
            prior_ratings=prior_ratings,
            current_week=current_week,
            params=params,
        )

        rankings = build_power_index_from_client(
            client=client,
            season=season,
            schools=schools,
            solver_states=solver_states,
            prior_ratings=prior_ratings,
            games=games,
            current_week=current_week,
            params=params,
            include_postseason=include_postseason,
        )

        rankings.insert(0, "school", rankings.index)
        rankings["conference"] = rankings["school"].map(
            lambda s: lookup[s].conference if s in lookup else ""
        )
        rankings["abbreviation"] = rankings["school"].map(
            lambda s: lookup[s].abbreviation if s in lookup else ""
        )
        rankings["season"] = season
        rankings["week"] = current_week
        rankings["as_of"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        label = f"bcpi_power_{season}"
        if include_postseason and current_week >= POSTSEASON_AS_WEEK:
            label += "_postseason"
        elif current_week:
            label += f"_week{current_week:02d}"
        else:
            label += "_preseason"

        output_path = OUTPUT_DIR / f"{label}.csv"
        rankings.to_csv(output_path, index=False)

        snapshot_path = OUTPUT_DIR / f"{label}.json"
        rankings.to_json(snapshot_path, orient="records", indent=2)

        return output_path
    finally:
        if owns_client and client is not None:
            client.close()


def run_poll_rankings(
    season: int = TARGET_SEASON,
    week: Optional[int] = None,
    refresh_data: bool = False,
    client: Optional[CFBDClient] = None,
    params: Optional[ModelParams] = None,
    include_postseason: bool = False,
) -> Path:
    """Fetch data and write Bergstein poll-style (resume) rankings CSV."""
    owns_client = client is None
    if owns_client:
        client = CFBDClient(use_cache=not refresh_data)

    if params is None:
        params = get_active_params()

    resume = get_resume_params()

    try:
        teams = get_fbs_teams(client, season, refresh=refresh_data)
        schools = [team.school for team in teams]
        lookup = team_lookup(teams)

        prior_ratings = build_preseason_priors(client, teams, season, params)
        games = load_season_games(client, season, include_postseason=include_postseason)

        if games:
            current_week = week if week is not None else max(g.week for g in games)
        else:
            current_week = week or 0

        solver_states = solve_ratings(
            teams=schools,
            games=games,
            prior_ratings=prior_ratings,
            current_week=current_week,
            params=params,
        )

        rankings = build_poll_index(
            schools=schools,
            solver_states=solver_states,
            games=games,
            current_week=current_week,
            params=params,
            resume=resume,
        )

        rankings.insert(0, "school", rankings.index)
        rankings["conference"] = rankings["school"].map(
            lambda s: lookup[s].conference if s in lookup else ""
        )
        rankings["abbreviation"] = rankings["school"].map(
            lambda s: lookup[s].abbreviation if s in lookup else ""
        )
        rankings["season"] = season
        rankings["week"] = current_week
        rankings["as_of"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        label = f"bcpi_poll_{season}"
        if include_postseason and current_week >= POSTSEASON_AS_WEEK:
            label += "_postseason"
        elif current_week:
            label += f"_week{current_week:02d}"
        else:
            label += "_preseason"

        output_path = OUTPUT_DIR / f"{label}.csv"
        rankings.to_csv(output_path, index=False)

        snapshot_path = OUTPUT_DIR / f"{label}.json"
        rankings.to_json(snapshot_path, orient="records", indent=2)

        return output_path
    finally:
        if owns_client and client is not None:
            client.close()

"""End-to-end BCPI pipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from bcpi.cfbd import CFBDClient
from bcpi.config import OUTPUT_DIR
from bcpi.constants import TARGET_SEASON
from bcpi.games import parse_games
from bcpi.power_index import build_power_index
from bcpi.priors import build_preseason_priors
from bcpi.solver import solve_ratings
from bcpi.teams import get_fbs_teams, team_lookup


def run_rankings(
    season: int = TARGET_SEASON,
    week: Optional[int] = None,
    refresh_data: bool = False,
    client: Optional[CFBDClient] = None,
) -> Path:
    """Fetch data, solve ratings, and write BCPI output CSV."""
    owns_client = client is None
    if owns_client:
        client = CFBDClient(use_cache=not refresh_data)

    try:
        teams = get_fbs_teams(client, season, refresh=refresh_data)
        schools = [team.school for team in teams]
        lookup = team_lookup(teams)

        prior_ratings = build_preseason_priors(client, teams, season)

        raw_games = client.get_games(season, season_type="regular")
        line_rows = client.get_lines(season, season_type="regular")
        games = parse_games(raw_games, line_rows)

        if games:
            current_week = week if week is not None else max(g.week for g in games)
        else:
            current_week = week or 0

        solver_states = solve_ratings(
            teams=schools,
            games=games,
            prior_ratings=prior_ratings,
            current_week=current_week,
        )

        rankings = build_power_index(
            client=client,
            season=season,
            schools=schools,
            solver_states=solver_states,
            prior_ratings=prior_ratings,
            games=games,
            current_week=current_week,
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
        if current_week:
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


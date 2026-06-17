"""Team registry and season-specific FBS lists."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from bcpi.cfbd import CFBDClient
from bcpi.config import TEAMS_DIR
from bcpi.constants import (
    CONFERENCE_OVERRIDES_2026,
    FBS_ADDITIONS_2026,
    TARGET_SEASON,
)


@dataclass(frozen=True)
class Team:
    school: str
    conference: str
    abbreviation: str
    classification: str = "fbs"

    @property
    def key(self) -> str:
        return self.school


def _normalize_team(raw: Dict) -> Team:
    return Team(
        school=raw["school"],
        conference=raw.get("conference") or "Independent",
        abbreviation=raw.get("abbreviation") or raw["school"][:4].upper(),
        classification=raw.get("classification", "fbs"),
    )


def apply_2026_overrides(teams: List[Team]) -> List[Team]:
    updated: List[Team] = []
    seen = {team.school for team in teams}

    for team in teams:
        conf = CONFERENCE_OVERRIDES_2026.get(team.school, team.conference)
        updated.append(
            Team(
                school=team.school,
                conference=conf,
                abbreviation=team.abbreviation,
                classification=team.classification,
            )
        )

    for addition in FBS_ADDITIONS_2026:
        if addition["school"] not in seen:
            updated.append(
                Team(
                    school=addition["school"],
                    conference=addition["conference"],
                    abbreviation=addition["abbreviation"],
                    classification="fbs",
                )
            )
    return sorted(updated, key=lambda t: t.school)


def fetch_fbs_teams(client: CFBDClient, season: int) -> List[Team]:
    """Load FBS teams for a season, applying known future overrides when needed."""
    if season >= TARGET_SEASON:
        base_year = min(season - 1, 2025)
    else:
        base_year = season

    year_teams = client.get_teams(base_year)
    fbs = [
        _normalize_team(t)
        for t in year_teams
        if t.get("classification") == "fbs"
    ]

    if not fbs:
        fbs = [_normalize_team(t) for t in client.get_fbs_teams()]

    if season >= TARGET_SEASON:
        fbs = apply_2026_overrides(fbs)

    return fbs


def save_team_snapshot(season: int, teams: List[Team]) -> Path:
    path = TEAMS_DIR / f"{season}.json"
    payload = [
        {
            "school": t.school,
            "conference": t.conference,
            "abbreviation": t.abbreviation,
            "classification": t.classification,
        }
        for t in teams
    ]
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return path


def load_team_snapshot(season: int) -> Optional[List[Team]]:
    path = TEAMS_DIR / f"{season}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return [_normalize_team(item) for item in payload]


def get_fbs_teams(
    client: CFBDClient,
    season: int,
    refresh: bool = False,
) -> List[Team]:
    if not refresh:
        cached = load_team_snapshot(season)
        if cached:
            return cached

    teams = fetch_fbs_teams(client, season)
    save_team_snapshot(season, teams)
    return teams


def team_lookup(teams: List[Team]) -> Dict[str, Team]:
    return {team.school: team for team in teams}

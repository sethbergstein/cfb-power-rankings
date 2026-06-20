"""FBS team profiles: logos, colors, home venues (CFBD)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from bcpi.cfbd import CFBDClient
from bcpi.config import DATA_DIR

PROFILES_DIR = DATA_DIR / "profiles"


def _venue_label(loc: Dict[str, Any], school: str) -> Dict[str, Any]:
    name = loc.get("name") or f"{school} Stadium"
    city = loc.get("city") or ""
    state = loc.get("state") or ""
    if city and state:
        location_line = f"{city}, {state}"
    elif city:
        location_line = city
    else:
        location_line = ""
    return {
        "venue_name": name,
        "venue_city": city,
        "venue_state": state,
        "venue_location": location_line,
        "venue_capacity": loc.get("capacity"),
    }


def build_team_profiles(client: CFBDClient, season: int) -> Dict[str, Dict[str, Any]]:
    rows = client.get_teams(season)
    profiles: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if row.get("classification") != "fbs":
            continue
        school = row["school"]
        loc = row.get("location") or {}
        logos = row.get("logos") or []
        venue = _venue_label(loc, school)
        profiles[school] = {
            "school": school,
            "abbreviation": row.get("abbreviation") or school[:4].upper(),
            "conference": row.get("conference") or "",
            "color": row.get("color") or "#2a2a2a",
            "alternate_color": row.get("alternateColor") or "#f3ede4",
            "logo": logos[0] if logos else None,
            "logo_dark": logos[1] if len(logos) > 1 else (logos[0] if logos else None),
            **venue,
        }
    return profiles


def save_team_profiles(season: int, profiles: Dict[str, Dict[str, Any]]) -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILES_DIR / f"{season}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(profiles, handle, indent=2)
    return path


def load_team_profiles(season: int) -> Optional[Dict[str, Dict[str, Any]]]:
    path = PROFILES_DIR / f"{season}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_team_profiles(
    client: CFBDClient,
    season: int,
    refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    if not refresh:
        cached = load_team_profiles(season)
        if cached:
            return cached
    profiles = build_team_profiles(client, season)
    save_team_profiles(season, profiles)
    return profiles

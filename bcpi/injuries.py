"""Matchup-only injury adjustment from conference availability reports.

Power ratings and the poll are unchanged. A player counts when the report
says out or doubtful, he is a quarterback or has a real share of the offense,
and both his usage and a next man at the position can be named. Production is
shrunk toward recruiting (a few explosive plays count, a full workload counts
more), then faded by how much of the current rating was built while he played.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from bcpi.availability import Absence, fetch_offensive_absences
from bcpi.cfbd import CFBDClient
from bcpi.config import DATA_DIR
from bcpi.params import ModelParams, get_active_params
from bcpi.recency import recency_weight
from bcpi.teams import get_fbs_teams

logger = logging.getLogger(__name__)

CACHE_PATH = DATA_DIR / "availability" / "current.json"
CACHE_HOURS = 6

# Howard was about 9% of Penn State's plays. Below that, a skill player is a
# reserve and the rating already barely includes him.
USAGE_MIN = 0.07
# Plays at which a rate is half believed. Five plays stay mostly the prior.
SAMPLE_PLAYS = 20.0
QB_CAP = 6.0
SKILL_CAP = 4.0
MIN_POINTS = 0.2
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_OFFENSE_CATEGORIES = {"passing", "rushing", "receiving"}


def name_key(name: str) -> str:
    text = name.lower().replace("'", "").replace("’", "").replace(".", " ")
    text = re.sub(r"[^a-z\s]", " ", text)
    parts = [part for part in text.split() if part not in _SUFFIXES]
    return " ".join(parts)


def _talent_prior(rating: Optional[float]) -> float:
    """Expected points added per play with no college sample."""
    if rating is None:
        return 0.25
    return max(0.05, min(1.2, 0.20 + (rating - 0.85) * 6.0))


def _plays(ppa_row: Optional[dict]) -> Tuple[float, float]:
    if not ppa_row:
        return 0.0, 0.0
    average = (ppa_row.get("averagePPA") or {}).get("all")
    total = (ppa_row.get("totalPPA") or {}).get("all")
    if not average or total is None:
        return 0.0, 0.0
    try:
        avg = float(average)
        tot = float(total)
    except (TypeError, ValueError):
        return 0.0, 0.0
    if avg == 0:
        return 0.0, 0.0
    return tot / avg, avg


def _shrink(plays: float, rate: float, prior: float) -> float:
    weight = plays / (plays + SAMPLE_PLAYS) if plays > 0 else 0.0
    return weight * rate + (1.0 - weight) * prior


def _resolve_school(label: str, schools: List[str]) -> Optional[str]:
    if label in schools:
        return label
    lower = label.lower()
    exact = [school for school in schools if school.lower() == lower]
    if len(exact) == 1:
        return exact[0]
    partial = [school for school in schools if lower in school.lower() or school.lower() in lower]
    if len(partial) == 1:
        return partial[0]
    return None


def _recruiting_ratings(client: CFBDClient, school: str) -> Dict[str, float]:
    ratings: Dict[str, float] = {}
    for year in range(2021, 2027):
        try:
            rows = client.get("/recruiting/players", {"year": year, "team": school})
        except Exception:
            continue
        for row in rows or []:
            rating = row.get("rating")
            if rating is None:
                continue
            key = name_key(str(row.get("name") or ""))
            if not key:
                continue
            ratings[key] = max(ratings.get(key, 0.0), float(rating))
    return ratings


def _participation(
    client: CFBDClient,
    school: str,
    season: int,
    rating_week: int,
    params: ModelParams,
) -> Tuple[Dict[str, float], float, Dict[str, int]]:
    """Recency weight of games a player showed up on offense, and the team total."""
    player_weight: Dict[str, float] = {}
    player_games: Dict[str, int] = {}
    team_weight = 0.0
    for week in range(1, rating_week + 1):
        try:
            games = client.get(
                "/games/players",
                {"year": season, "week": week, "team": school, "seasonType": "regular"},
            )
        except Exception:
            continue
        appeared = set()
        played = False
        for game in games or []:
            for side in game.get("teams") or []:
                team_name = (side.get("team") or "")
                if team_name != school and school.lower() not in team_name.lower():
                    continue
                played = True
                for category in side.get("categories") or []:
                    if str(category.get("name") or "").lower() not in _OFFENSE_CATEGORIES:
                        continue
                    for stat in category.get("types") or []:
                        for athlete in stat.get("athletes") or []:
                            key = name_key(str(athlete.get("name") or ""))
                            if key:
                                appeared.add(key)
        if not played:
            continue
        weight = recency_weight(rating_week, week, lambda_=params.recency_lambda)
        team_weight += weight
        for key in appeared:
            player_weight[key] = player_weight.get(key, 0.0) + weight
            player_games[key] = player_games.get(key, 0) + 1
    return player_weight, team_weight, player_games


def _price_team(
    client: CFBDClient,
    school: str,
    absences: List[Absence],
    season: int,
    rating_week: int,
    params: ModelParams,
) -> List[dict]:
    skill = [row for row in absences if row.group != "OL"]
    if not skill:
        return []

    usage_rows = client.get("/player/usage", {"year": season, "team": school}) or []
    ppa_rows = client.get("/ppa/players/season", {"year": season, "team": school}) or []
    usage = {name_key(row.get("name") or ""): row for row in usage_rows}
    ppa = {name_key(row.get("name") or ""): row for row in ppa_rows}
    ratings = _recruiting_ratings(client, school)
    played_weight, team_weight, played_games = _participation(
        client, school, season, rating_week, params
    )

    absent_keys = {name_key(row.player) for row in skill}
    notes = []
    for absence in skill:
        key = name_key(absence.player)
        usage_row = usage.get(key)
        if usage_row is None:
            continue
        overall = float((usage_row.get("usage") or {}).get("overall") or 0.0)
        if absence.group != "QB" and overall < USAGE_MIN:
            continue
        plays, rate = _plays(ppa.get(key))
        if plays < 1:
            continue

        group_rows = []
        for other_key, other in usage.items():
            if other_key in absent_keys:
                continue
            other_pos = str(other.get("position") or "").upper()
            other_group = {
                "QB": "QB",
                "RB": "RB",
                "HB": "RB",
                "FB": "RB",
                "WR": "WR",
                "TE": "TE",
            }.get(other_pos)
            if other_group != absence.group:
                continue
            other_plays, other_rate = _plays(ppa.get(other_key))
            group_rows.append((other_plays, other_rate, other_key))
        if not group_rows:
            continue
        group_rows.sort(reverse=True)
        repl_plays, repl_rate, repl_key = group_rows[0]

        prior = _talent_prior(ratings.get(key))
        repl_prior = _talent_prior(ratings.get(repl_key))
        shrunk = _shrink(plays, rate, prior)
        repl_shrunk = _shrink(repl_plays, repl_rate, repl_prior)
        gap = shrunk - repl_shrunk
        if gap <= 0:
            continue

        player_w = played_weight.get(key, 0.0)
        appearances = played_games.get(key, 0)
        if team_weight <= 0 or appearances <= 0:
            # Season production exists but the week log missed him. Treat the
            # sample as part of the current rating.
            still_in = 1.0
            appearances = max(rating_week, 1)
        else:
            still_in = min(1.0, player_w / team_weight)
        per_game = plays / appearances
        points = per_game * gap * still_in
        cap = QB_CAP if absence.group == "QB" else SKILL_CAP
        points = min(points, cap)
        if points < MIN_POINTS:
            continue
        notes.append(
            {
                "team": school,
                "player": absence.player,
                "position": absence.position,
                "status": absence.status,
                "points": round(points, 2),
                "conference": absence.conference,
            }
        )
    return notes


def build_adjustments(
    season: int,
    rating_week: int,
    client: Optional[CFBDClient] = None,
    params: Optional[ModelParams] = None,
) -> dict:
    """Price every current offensive absence. Safe to cache for a few hours."""
    owns_client = client is None
    if owns_client:
        client = CFBDClient(use_cache=True)
    if params is None:
        params = get_active_params()
    try:
        schools = [team.school for team in get_fbs_teams(client, season)]
        by_school: Dict[str, List[Absence]] = {}
        for absence in fetch_offensive_absences():
            school = _resolve_school(absence.school_name, schools)
            if school is None:
                logger.info("No school match for availability team %s", absence.school_name)
                continue
            by_school.setdefault(school, []).append(absence)

        teams: Dict[str, dict] = {}
        for school, rows in by_school.items():
            try:
                notes = _price_team(client, school, rows, season, rating_week, params)
            except Exception:
                logger.warning("Injury pricing failed for %s", school, exc_info=True)
                continue
            if not notes:
                continue
            teams[school] = {
                "points": round(sum(note["points"] for note in notes), 2),
                "players": notes,
            }
        return {
            "season": season,
            "rating_week": rating_week,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "teams": teams,
        }
    finally:
        if owns_client and client is not None:
            client.close()


def _cache_fresh(payload: dict, season: int, rating_week: int) -> bool:
    if payload.get("season") != season or payload.get("rating_week") != rating_week:
        return False
    fetched = payload.get("fetched_at")
    if not fetched:
        return False
    try:
        stamp = datetime.fromisoformat(fetched)
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - stamp < timedelta(hours=CACHE_HOURS)


def load_adjustments(
    season: int,
    rating_week: int,
    client: Optional[CFBDClient] = None,
    params: Optional[ModelParams] = None,
    refresh: bool = False,
) -> dict:
    """Return the cached adjustment table, rebuilding it when it is stale."""
    if CACHE_PATH.exists() and not refresh:
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if cached and _cache_fresh(cached, season, rating_week):
            return cached

    try:
        payload = build_adjustments(season, rating_week, client=client, params=params)
    except Exception:
        logger.warning("Availability adjustment unavailable", exc_info=True)
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return {"season": season, "rating_week": rating_week, "teams": {}}

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def availability_for_matchup(
    home_team: str,
    away_team: str,
    season: int,
    rating_week: int,
    client: Optional[CFBDClient] = None,
    params: Optional[ModelParams] = None,
) -> Tuple[float, float, List[dict]]:
    """Points to subtract from the home margin for each side, plus the notes."""
    table = load_adjustments(season, rating_week, client=client, params=params)
    if table.get("season") != season or table.get("rating_week") != rating_week:
        return 0.0, 0.0, []
    teams = table.get("teams") or {}
    home = teams.get(home_team) or {}
    away = teams.get(away_team) or {}
    notes = list(home.get("players") or []) + list(away.get("players") or [])
    return float(home.get("points") or 0.0), float(away.get("points") or 0.0), notes

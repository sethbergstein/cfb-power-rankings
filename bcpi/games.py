"""Game result normalization for BCPI."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from bcpi.constants import FCS_OPPONENT_KEY, HOME_FIELD_ADVANTAGE
from bcpi.cfbd import CFBDClient
from bcpi.params import ModelParams

SPREAD_PROVIDER_PREFERENCE = ("consensus", "Bovada")


@dataclass(frozen=True)
class GameResult:
    game_id: int
    season: int
    week: int
    home_team: str
    away_team: str
    home_points: int
    away_points: int
    neutral_site: bool
    home_classification: str
    away_classification: str
    spread: Optional[float] = None  # home team perspective (negative = home favored)
    notes: Optional[str] = None

    @property
    def is_cfp(self) -> bool:
        return "college football playoff" in (self.notes or "").lower()

    @property
    def completed(self) -> bool:
        return self.home_points is not None and self.away_points is not None

    @property
    def margin_home(self) -> int:
        return self.home_points - self.away_points

    @property
    def home_is_fbs(self) -> bool:
        return self.home_classification == "fbs"

    @property
    def away_is_fbs(self) -> bool:
        return self.away_classification == "fbs"

    @property
    def is_fbs_game(self) -> bool:
        return self.home_is_fbs and self.away_is_fbs

    @property
    def involves_fbs(self) -> bool:
        return self.home_is_fbs or self.away_is_fbs


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _provider_lines(rows: List[Dict]) -> List[Dict]:
    """CFBD /lines returns one row per game with a nested ``lines`` list (one per provider)."""
    flat: List[Dict] = []
    for row in rows:
        nested = row.get("lines")
        if isinstance(nested, list):
            flat.extend(line for line in nested if isinstance(line, dict))
        elif "spread" in row:
            flat.append(row)
    return flat


def _pick_closing_spread(rows: List[Dict]) -> Optional[float]:
    lines = [
        (line.get("provider"), _to_float(line.get("spread")))
        for line in _provider_lines(rows)
    ]
    lines = [(provider, spread) for provider, spread in lines if spread is not None]
    if not lines:
        return None
    for preferred in SPREAD_PROVIDER_PREFERENCE:
        for provider, spread in lines:
            if provider == preferred:
                return spread
    return lines[0][1]


def parse_games(
    raw_games: List[Dict],
    line_rows: Optional[List[Dict]] = None,
) -> List[GameResult]:
    line_index: Dict[int, List[Dict]] = {}
    if line_rows:
        for row in line_rows:
            line_index.setdefault(row["id"], []).append(row)

    games: List[GameResult] = []
    for raw in raw_games:
        if not raw.get("completed"):
            continue
        home_points = raw.get("homePoints")
        away_points = raw.get("awayPoints")
        if home_points is None or away_points is None:
            continue
        season = raw.get("year") or raw.get("season")
        if season is None:
            continue

        games.append(
            GameResult(
                game_id=raw["id"],
                season=season,
                week=raw["week"],
                home_team=raw["homeTeam"],
                away_team=raw["awayTeam"],
                home_points=int(home_points),
                away_points=int(away_points),
                neutral_site=bool(raw.get("neutralSite")),
                home_classification=raw.get("homeClassification", "fbs"),
                away_classification=raw.get("awayClassification", "fbs"),
                spread=_pick_closing_spread(line_index.get(raw["id"], [])),
                notes=raw.get("notes"),
            )
        )
    return games


def compress_margin(margin: float, scale: float) -> float:
    """Shrink blowouts smoothly: close to linear inside two scores, saturating near ±scale.

    Applied the same way to actual and expected margins so a team is never
    penalized for failing to beat a cap it was expected to clear.
    """
    if scale <= 0:
        return margin
    return scale * math.tanh(margin / scale)


def site_advantage(
    game: GameResult,
    perspective_team: str,
    params: Optional[ModelParams] = None,
) -> float:
    """Home field in points from one team's perspective (0 at neutral sites)."""
    if game.neutral_site:
        return 0.0
    hfa = params.hfa if params else HOME_FIELD_ADVANTAGE
    if perspective_team == game.home_team:
        return hfa
    if perspective_team == game.away_team:
        return -hfa
    return 0.0


def effective_margin_for_rating(
    game: GameResult,
    perspective_team: str,
    params: Optional[ModelParams] = None,
) -> Optional[float]:
    """Margin from one team's perspective with home field removed (neutral-field margin)."""
    if perspective_team == game.home_team:
        margin = float(game.margin_home)
    elif perspective_team == game.away_team:
        margin = float(-game.margin_home)
    else:
        return None
    return margin - site_advantage(game, perspective_team, params)


def team_won(game: GameResult, team: str) -> Optional[bool]:
    """True/False for a decided game involving ``team``; None for ties or other teams."""
    if team not in (game.home_team, game.away_team) or game.margin_home == 0:
        return None
    return (game.margin_home > 0) == (team == game.home_team)


def opponent_key(game: GameResult, perspective_team: str) -> Optional[str]:
    if perspective_team == game.home_team:
        if game.away_classification == "fcs":
            return FCS_OPPONENT_KEY
        return game.away_team
    if perspective_team == game.away_team:
        if game.home_classification == "fcs":
            return FCS_OPPONENT_KEY
        return game.home_team
    return None


def market_residual(game: GameResult, perspective_team: str) -> Optional[float]:
    """Actual margin minus closing spread from team's perspective."""
    if game.spread is None:
        return None
    if perspective_team == game.home_team:
        actual = float(game.margin_home)
        expected = -game.spread  # spread is home line; home favored => negative spread
        return actual - expected
    if perspective_team == game.away_team:
        actual = float(-game.margin_home)
        expected = game.spread
        return actual - expected
    return None


POSTSEASON_AS_WEEK = 17  # CFBD uses week=1 for postseason; remap after regular season


def remap_game_week(game: GameResult, week: int) -> GameResult:
    return GameResult(
        game_id=game.game_id,
        season=game.season,
        week=week,
        home_team=game.home_team,
        away_team=game.away_team,
        home_points=game.home_points,
        away_points=game.away_points,
        neutral_site=game.neutral_site,
        home_classification=game.home_classification,
        away_classification=game.away_classification,
        spread=game.spread,
        notes=game.notes,
    )


def load_season_games(
    client: CFBDClient,
    season: int,
    include_postseason: bool = False,
) -> List[GameResult]:
    """Load completed games; optionally merge postseason with week remapped to 17."""
    raw_regular = client.get_games(season, season_type="regular")
    line_regular = client.get_lines(season, season_type="regular")
    games = parse_games(raw_regular, line_regular)

    if include_postseason:
        raw_post = client.get_games(season, season_type="postseason")
        line_post = client.get_lines(season, season_type="postseason")
        post_games = parse_games(raw_post, line_post)
        for game in post_games:
            if game.involves_fbs:
                games.append(remap_game_week(game, POSTSEASON_AS_WEEK))

    return games


def filter_games_through_week(
    games: List[GameResult],
    through_week: Optional[int] = None,
) -> List[GameResult]:
    if through_week is None:
        return games
    return [g for g in games if g.week <= through_week]


def team_records(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
    fbs_only: bool = False,
) -> Dict[str, Tuple[int, int]]:
    """Win-loss records. Display uses all games; resume scoring can pass fbs_only."""
    records = {school: [0, 0] for school in schools}
    for game in filter_games_through_week(games, current_week):
        if not game.completed:
            continue
        if fbs_only and not game.is_fbs_game:
            continue
        if not game.involves_fbs:
            continue
        if game.margin_home > 0:
            winner, loser = game.home_team, game.away_team
        elif game.margin_home < 0:
            winner, loser = game.away_team, game.home_team
        else:
            continue
        if winner in records:
            records[winner][0] += 1
        if loser in records:
            records[loser][1] += 1
    return {school: (wins, losses) for school, (wins, losses) in records.items()}


def games_played(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
) -> Dict[str, int]:
    """Completed games involving each FBS school (including FCS opponents)."""
    counts = {school: 0 for school in schools}
    for game in filter_games_through_week(games, current_week):
        if not game.completed or not game.involves_fbs:
            continue
        for team in (game.home_team, game.away_team):
            if team in counts:
                counts[team] += 1
    return counts

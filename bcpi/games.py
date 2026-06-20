"""Game result normalization for BCPI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from bcpi.constants import FCS_OPPONENT_KEY
from bcpi.cfbd import CFBDClient
from bcpi.params import ModelParams


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


def _pick_closing_spread(lines: List[Dict]) -> Optional[float]:
    if not lines:
        return None
    preferred = [line for line in lines if line.get("provider") in ("consensus", "Bovada")]
    candidates = preferred or lines
    for line in reversed(candidates):
        spread = line.get("spread")
        if spread is not None:
            return float(spread)
    return None


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


def effective_margin_for_rating(
    game: GameResult,
    perspective_team: str,
    params: Optional[ModelParams] = None,
) -> Optional[float]:
    """Margin from one team's perspective, with FCS caps and HFA removed for power rating."""
    from bcpi.constants import FCS_MARGIN_CAP, HOME_FIELD_ADVANTAGE

    hfa = params.hfa if params else HOME_FIELD_ADVANTAGE
    fcs_cap = params.fcs_margin_cap if params else FCS_MARGIN_CAP

    if perspective_team == game.home_team:
        margin = float(game.margin_home)
        if not game.neutral_site:
            margin -= hfa
        opponent_class = game.away_classification
    elif perspective_team == game.away_team:
        margin = float(-game.margin_home)
        if not game.neutral_site:
            margin += hfa
        opponent_class = game.home_classification
    else:
        return None

    if opponent_class == "fcs":
        if margin > 0:
            margin = min(margin, fcs_cap)
        else:
            margin = max(margin, -fcs_cap)
    return margin


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

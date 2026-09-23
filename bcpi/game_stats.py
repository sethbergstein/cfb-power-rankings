"""Game-level advanced stats aggregation for walk-forward quality (no lookahead)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from bcpi.cfbd import CFBDClient
from bcpi.constants import RATING_MEAN
from bcpi.games import POSTSEASON_AS_WEEK, GameResult
from bcpi.params import ModelParams
from bcpi.recency import recency_weight


@dataclass(frozen=True)
class GameAdvancedStat:
    game_id: int
    season: int
    week: int
    team: str
    opponent: str
    offense: Dict
    defense: Dict


@dataclass
class GameMetricContrib:
    week: int
    opponent: str
    off_ppa: float
    off_plays: float
    def_ppa: float
    def_plays: float
    off_success: float
    def_success: float
    off_expl: float
    def_expl: float
    off_pass_ppa: float
    off_pass_plays: float
    def_pass_ppa: float
    def_pass_plays: float


def parse_game_advanced_rows(rows: List[dict]) -> List[GameAdvancedStat]:
    stats: List[GameAdvancedStat] = []
    for row in rows:
        offense = row.get("offense") or {}
        defense = row.get("defense") or {}
        if not offense or not defense:
            continue
        season = row.get("season") or row.get("year")
        if season is None:
            continue
        stats.append(
            GameAdvancedStat(
                game_id=int(row["gameId"]),
                season=int(season),
                week=int(row["week"]),
                team=row["team"],
                opponent=row["opponent"],
                offense=offense,
                defense=defense,
            )
        )
    return stats


def load_season_game_advanced(
    client: CFBDClient,
    season: int,
    include_postseason: bool = False,
    exclude_garbage_time: bool = False,
) -> List[GameAdvancedStat]:
    rows = client.get_advanced_game_stats(
        season, season_type="regular", exclude_garbage_time=exclude_garbage_time
    )
    stats = parse_game_advanced_rows(rows)
    if include_postseason:
        post_rows = client.get_advanced_game_stats(
            season, season_type="postseason", exclude_garbage_time=exclude_garbage_time
        )
        post_stats = parse_game_advanced_rows(post_rows)
        for stat in post_stats:
            stats.append(
                GameAdvancedStat(
                    game_id=stat.game_id,
                    season=stat.season,
                    week=POSTSEASON_AS_WEEK,
                    team=stat.team,
                    opponent=stat.opponent,
                    offense=stat.offense,
                    defense=stat.defense,
                )
            )
    return stats


def _plays(side: Dict) -> int:
    return int(side.get("plays") or 0)


def _pass_plays(side: Dict, key: str) -> int:
    nested = side.get(key) or {}
    total_ppa = nested.get("totalPPA")
    ppa = nested.get("ppa")
    if total_ppa is None or ppa is None or ppa == 0:
        return 0
    estimated = abs(total_ppa / ppa)
    return max(1, int(round(estimated)))


def _contrib_from_sides(offense: Dict, defense: Dict) -> Optional[GameMetricContrib]:
    off_plays = _plays(offense)
    def_plays = _plays(defense)
    if off_plays <= 0 or def_plays <= 0:
        return None

    off_pass_plays = _pass_plays(offense, "passingPlays")
    def_pass_plays = _pass_plays(defense, "passingPlays")

    return GameMetricContrib(
        week=0,
        opponent="",
        off_ppa=float(offense.get("ppa") or 0.0),
        off_plays=float(off_plays),
        def_ppa=float(defense.get("ppa") or 0.0),
        def_plays=float(def_plays),
        off_success=float(offense.get("successRate") or 0.0),
        def_success=float(defense.get("successRate") or 0.0),
        off_expl=float(offense.get("explosiveness") or 0.0),
        def_expl=float(defense.get("explosiveness") or 0.0),
        off_pass_ppa=float(
            (offense.get("passingPlays") or {}).get("ppa") or offense.get("ppa") or 0.0
        ),
        off_pass_plays=float(off_pass_plays if off_pass_plays > 0 else off_plays),
        def_pass_ppa=float(
            (defense.get("passingPlays") or {}).get("ppa") or defense.get("ppa") or 0.0
        ),
        def_pass_plays=float(def_pass_plays if def_pass_plays > 0 else def_plays),
    )


def _is_fbs_opponent(game: GameResult, team: str) -> bool:
    if team == game.home_team:
        return game.away_classification == "fbs"
    if team == game.away_team:
        return game.home_classification == "fbs"
    return False


def build_team_game_logs(
    game_stats: List[GameAdvancedStat],
    games: List[GameResult],
    schools: List[str],
) -> Dict[str, List[GameMetricContrib]]:
    games_by_id = {g.game_id: g for g in games}
    logs: Dict[str, List[GameMetricContrib]] = {school: [] for school in schools}

    for stat in game_stats:
        game = games_by_id.get(stat.game_id)
        if game is None or not _is_fbs_opponent(game, stat.team):
            continue
        contrib = _contrib_from_sides(stat.offense, stat.defense)
        if contrib is None:
            continue
        contrib.week = stat.week
        contrib.opponent = stat.opponent
        if stat.team not in logs:
            logs[stat.team] = []
        logs[stat.team].append(contrib)

    for school in logs:
        logs[school].sort(key=lambda c: c.week)
    return logs


QUALITY_METRICS = ("epa_diff", "success_diff", "explosiveness_diff", "passing_diff")


def game_metric_diffs(contrib: GameMetricContrib) -> Dict[str, float]:
    """Offense minus defense for one game, before any opponent adjustment."""
    return {
        "epa_diff": contrib.off_ppa - contrib.def_ppa,
        "success_diff": contrib.off_success - contrib.def_success,
        "explosiveness_diff": contrib.off_expl - contrib.def_expl,
        "passing_diff": contrib.off_pass_ppa - contrib.def_pass_ppa,
    }


def aggregate_game_quality(
    team_logs: Dict[str, List[GameMetricContrib]],
    schools: List[str],
    through_week: int,
    current_week: int,
    params: ModelParams,
    opponent_ratings: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """
    Recency-weighted per-game efficiency differentials, adjusted for opponent strength.

    Each game's differential is credited ``slope * opponent strength``, where
    strength is the opponent's expected margin against an average FBS team, so
    out-gaining a top-10 defense counts for more than out-gaining a bottom-10 one.
    The slopes (efficiency per point of expected margin) are fit on 2018-2025.
    """
    ratings = opponent_ratings or {}
    mean_rating = (
        sum(ratings.get(school, RATING_MEAN) for school in schools) / len(schools)
        if schools
        else RATING_MEAN
    )
    slopes = params.quality_opponent_slopes
    rows: Dict[str, Dict[str, float]] = {}
    for school in schools:
        sums = {metric: 0.0 for metric in QUALITY_METRICS}
        total = 0.0
        for contrib in team_logs.get(school, []):
            if contrib.week > through_week:
                continue
            weight = recency_weight(current_week, contrib.week, params.recency_lambda)
            strength = (ratings.get(contrib.opponent, RATING_MEAN) - mean_rating) / params.margin_scale
            for metric, value in game_metric_diffs(contrib).items():
                sums[metric] += weight * (value + slopes.get(metric, 0.0) * strength)
            total += weight
        rows[school] = {
            metric: (sums[metric] / total if total > 0 else float("nan"))
            for metric in QUALITY_METRICS
        }
    return pd.DataFrame.from_dict(rows, orient="index", columns=list(QUALITY_METRICS))

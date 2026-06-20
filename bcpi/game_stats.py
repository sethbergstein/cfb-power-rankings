"""Game-level advanced stats aggregation for walk-forward quality (no lookahead)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from bcpi.cfbd import CFBDClient
from bcpi.constants import RATING_MEAN, RATING_SPREAD
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
) -> List[GameAdvancedStat]:
    rows = client.get_advanced_game_stats(season, season_type="regular")
    stats = parse_game_advanced_rows(rows)
    if include_postseason:
        post_rows = client.get_advanced_game_stats(season, season_type="postseason")
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


def opponent_quality_multiplier(
    opp_rating: float,
    params: ModelParams,
) -> float:
    """Scale game quality weight by opponent solver strength (1.0 = average FBS)."""
    if params.opp_quality_scale <= 0:
        return 1.0
    z = (opp_rating - RATING_MEAN) / (RATING_SPREAD / 2.5)
    mult = 1.0 + params.opp_quality_scale * z
    return max(params.opp_quality_min, min(params.opp_quality_max, mult))


def elite_opponent_set(
    opponent_ratings: Dict[str, float],
    schools: List[str],
    top_n: int,
) -> set:
    """Teams in the top N by solver rating (elite competition tier)."""
    rated = [(team, opponent_ratings.get(team, RATING_MEAN)) for team in schools]
    rated.sort(key=lambda item: item[1], reverse=True)
    return {team for team, _ in rated[:top_n]}


def _empty_totals() -> Dict[str, float]:
    return {
        "off_ppa": 0.0,
        "off_w": 0.0,
        "def_ppa": 0.0,
        "def_w": 0.0,
        "off_success": 0.0,
        "off_success_w": 0.0,
        "def_success": 0.0,
        "def_success_w": 0.0,
        "off_expl": 0.0,
        "off_expl_w": 0.0,
        "def_expl": 0.0,
        "def_expl_w": 0.0,
        "off_pass": 0.0,
        "off_pass_w": 0.0,
        "def_pass": 0.0,
        "def_pass_w": 0.0,
    }


def _accumulate_contrib(
    totals: Dict[str, float],
    contrib: GameMetricContrib,
    weight: float,
) -> None:
    w_off = weight * contrib.off_plays
    w_def = weight * contrib.def_plays
    totals["off_ppa"] += w_off * contrib.off_ppa
    totals["off_w"] += w_off
    totals["def_ppa"] += w_def * contrib.def_ppa
    totals["def_w"] += w_def
    totals["off_success"] += w_off * contrib.off_success
    totals["off_success_w"] += w_off
    totals["def_success"] += w_def * contrib.def_success
    totals["def_success_w"] += w_def
    totals["off_expl"] += w_off * contrib.off_expl
    totals["off_expl_w"] += w_off
    totals["def_expl"] += w_def * contrib.def_expl
    totals["def_expl_w"] += w_def
    w_pass_off = weight * contrib.off_pass_plays
    w_pass_def = weight * contrib.def_pass_plays
    totals["off_pass"] += w_pass_off * contrib.off_pass_ppa
    totals["off_pass_w"] += w_pass_off
    totals["def_pass"] += w_pass_def * contrib.def_pass_ppa
    totals["def_pass_w"] += w_pass_def


def _metrics_from_totals(totals: Dict[str, float]) -> Dict[str, float]:
    if totals["off_w"] <= 0 or totals["def_w"] <= 0:
        return {
            "epa_diff": 0.0,
            "success_diff": 0.0,
            "explosiveness_diff": 0.0,
            "passing_diff": 0.0,
            "havoc_diff": 0.0,
        }
    off_ppa = totals["off_ppa"] / totals["off_w"]
    def_ppa = totals["def_ppa"] / totals["def_w"]
    off_success = totals["off_success"] / totals["off_success_w"]
    def_success = totals["def_success"] / totals["def_success_w"]
    off_expl = totals["off_expl"] / totals["off_expl_w"]
    def_expl = totals["def_expl"] / totals["def_expl_w"]
    off_pass = totals["off_pass"] / totals["off_pass_w"] if totals["off_pass_w"] else off_ppa
    def_pass = totals["def_pass"] / totals["def_pass_w"] if totals["def_pass_w"] else def_ppa
    return {
        "epa_diff": off_ppa - def_ppa,
        "success_diff": off_success - def_success,
        "explosiveness_diff": off_expl - def_expl,
        "passing_diff": off_pass - def_pass,
        "havoc_diff": 0.0,
    }


def _blend_metric_rows(
    elite: Dict[str, float],
    all_games: Dict[str, float],
    elite_weight: float,
    has_elite: bool,
) -> Dict[str, float]:
    if not has_elite or elite_weight <= 0:
        return all_games
    if elite_weight >= 1:
        return elite
    rest_weight = 1.0 - elite_weight
    keys = all_games.keys()
    return {
        key: elite_weight * elite[key] + rest_weight * all_games[key]
        for key in keys
    }


def aggregate_game_quality(
    team_logs: Dict[str, List[GameMetricContrib]],
    schools: List[str],
    through_week: int,
    current_week: int,
    params: ModelParams,
    opponent_ratings: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    rows: Dict[str, Dict[str, float]] = {}

    ratings = opponent_ratings or {}
    elite_set = elite_opponent_set(ratings, schools, params.elite_opponent_top_n)

    for school in schools:
        totals_all = _empty_totals()
        totals_elite = _empty_totals()
        has_elite = False

        for contrib in team_logs.get(school, []):
            if contrib.week > through_week:
                continue
            opp_rating = ratings.get(contrib.opponent, RATING_MEAN)
            opp_mult = opponent_quality_multiplier(opp_rating, params)
            weight = recency_weight(current_week, contrib.week, params.recency_lambda) * opp_mult
            _accumulate_contrib(totals_all, contrib, weight)
            if contrib.opponent in elite_set:
                has_elite = True
                _accumulate_contrib(totals_elite, contrib, weight)

        all_metrics = _metrics_from_totals(totals_all)
        elite_metrics = _metrics_from_totals(totals_elite)
        rows[school] = _blend_metric_rows(
            elite_metrics,
            all_metrics,
            params.elite_quality_weight,
            has_elite,
        )

    return pd.DataFrame.from_dict(rows, orient="index")

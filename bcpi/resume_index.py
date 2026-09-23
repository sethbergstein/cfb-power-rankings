"""
Bergstein Poll Index (resume rankings).

Separate from BCPI power: answers "who has earned the highest ranking?"
rather than "who would win?".

Every completed game is scored against a benchmark team, the average of the
top 25 by solver rating, playing the same opponent at the same site:
  - SOR (strength of record): wins minus the wins the benchmark would expect.
  - performance: compressed neutral-field margin minus the margin the
    benchmark would be expected to post.
Resume = z(sor_weight * z(SOR + CFP round bonus) + (1 - sor_weight) * z(performance)).

Poll score = w * preseason + (1 - w) * resume, with w = K / (K + games)
(FCS games count as a fraction) and w = 0 once the national title game is
final. A head-to-head pass then lets winners close small gaps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from bcpi.champions import load_defending_champion, national_champion_from_games
from bcpi.constants import FCS_OPPONENT_KEY, RATING_MEAN, RATING_SPREAD
from bcpi.games import (
    GameResult,
    compress_margin,
    effective_margin_for_rating,
    filter_games_through_week,
    load_season_games,
    opponent_key,
    site_advantage,
    team_records,
    team_won,
)
from bcpi.head_to_head import head_to_head_adjustments
from bcpi.params import ModelParams
from bcpi.resume_params import ResumeParams, get_resume_params
from bcpi.solver import TeamRatingState

CFP_ROUND_ORDER = ("first_round", "quarterfinal", "semifinal", "championship")


def _zscore(series: pd.Series) -> pd.Series:
    """Z-score over non-missing values; missing values stay NaN."""
    std = series.std(ddof=0, skipna=True)
    if std == 0 or pd.isna(std):
        return series.where(series.isna(), 0.0)
    return (series - series.mean(skipna=True)) / std


def _rating_from_z(z: float) -> float:
    return RATING_MEAN + z * (RATING_SPREAD / 2.5)


@dataclass
class GameResume:
    opponent: str
    won: bool
    fbs_opponent: bool
    value: float  # won minus the benchmark's win probability
    performance: float  # compressed margin beyond the benchmark's expected margin


def benchmark_rating(ratings: Dict[str, float], schools: List[str], top_n: int) -> float:
    """Average solver rating of the top ``top_n`` schools."""
    top = sorted((ratings[s] for s in schools if s in ratings), reverse=True)[: max(top_n, 1)]
    return sum(top) / len(top) if top else RATING_MEAN


def game_resumes(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
    ratings: Dict[str, float],
    benchmark: float,
    params: ModelParams,
) -> Dict[str, List[GameResume]]:
    """Per school, each decided game scored against the benchmark team."""
    out: Dict[str, List[GameResume]] = {school: [] for school in schools}
    fcs_rating = ratings.get(FCS_OPPONENT_KEY, params.fcs_rating)
    for game in filter_games_through_week(games, current_week):
        if not game.completed or not game.involves_fbs:
            continue
        for team in (game.home_team, game.away_team):
            if team not in out:
                continue
            won = team_won(game, team)
            opponent = opponent_key(game, team)
            margin = effective_margin_for_rating(game, team, params)
            if won is None or opponent is None or margin is None:
                continue
            is_fcs = opponent == FCS_OPPONENT_KEY
            opp_rating = fcs_rating if is_fcs else ratings.get(opponent, RATING_MEAN)
            expected = (benchmark - opp_rating) / params.margin_scale
            logit = (expected + site_advantage(game, team, params)) / params.solver_win_prob_scale
            benchmark_win = 1.0 / (1.0 + math.exp(-logit))
            out[team].append(
                GameResume(
                    opponent=game.away_team if team == game.home_team else game.home_team,
                    won=won,
                    fbs_opponent=not is_fcs,
                    value=(1.0 if won else 0.0) - benchmark_win,
                    performance=compress_margin(margin, params.margin_compression)
                    - compress_margin(expected, params.margin_compression),
                )
            )
    return out


def _cfp_round_key(notes: Optional[str]) -> Optional[str]:
    text = (notes or "").lower()
    if "national championship" in text:
        return "championship"
    if "semifinal" in text:
        return "semifinal"
    if "quarterfinal" in text:
        return "quarterfinal"
    if "first round" in text:
        return "first_round"
    return None


def playoff_bonus(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
    resume: ResumeParams,
) -> pd.Series:
    """Bonus in wins for the deepest CFP round reached, plus a title bonus, capped."""
    deepest: Dict[str, int] = {}
    champions = set()
    for game in filter_games_through_week(games, current_week):
        if not game.completed:
            continue
        round_key = _cfp_round_key(game.notes)
        if round_key is None:
            continue
        depth = CFP_ROUND_ORDER.index(round_key)
        for team in (game.home_team, game.away_team):
            deepest[team] = max(deepest.get(team, -1), depth)
            if round_key == "championship" and team_won(game, team):
                champions.add(team)

    bonus = {}
    for school in schools:
        value = 0.0
        if school in deepest:
            value += resume.playoff_round_bonus.get(CFP_ROUND_ORDER[deepest[school]], 0.0)
        if school in champions:
            value += resume.playoff_champion_bonus
        bonus[school] = min(value, resume.playoff_bonus_cap)
    return pd.Series(bonus, dtype=float)


def compute_resume(
    schools: List[str],
    solver_states: Dict[str, TeamRatingState],
    games: List[GameResult],
    current_week: int,
    params: ModelParams,
    resume: ResumeParams,
) -> pd.DataFrame:
    """Resume components per school; resume fields are NaN for teams without games."""
    ratings = {s: solver_states[s].rating for s in schools if s in solver_states}
    if FCS_OPPONENT_KEY in solver_states:
        ratings[FCS_OPPONENT_KEY] = solver_states[FCS_OPPONENT_KEY].rating
    benchmark = benchmark_rating(ratings, schools, resume.benchmark_top_n)
    per_game = game_resumes(games, schools, current_week, ratings, benchmark, params)
    bonus = playoff_bonus(games, schools, current_week, resume)

    rows = {}
    for school in schools:
        results = per_game[school]
        wins = [g for g in results if g.won]
        losses = [g for g in results if not g.won]
        best = max(wins, key=lambda g: g.value) if wins else None
        worst = min(losses, key=lambda g: g.value) if losses else None
        rows[school] = {
            "sor": sum(g.value for g in results) if results else float("nan"),
            "performance": (
                sum(g.performance for g in results) / len(results) if results else float("nan")
            ),
            "fbs_games": sum(1 for g in results if g.fbs_opponent),
            "fcs_games": sum(1 for g in results if not g.fbs_opponent),
            "best_win": best.opponent if best else "",
            "best_win_value": best.value if best else float("nan"),
            "worst_loss": worst.opponent if worst else "",
            "worst_loss_value": worst.value if worst else float("nan"),
        }
    table = pd.DataFrame.from_dict(rows, orient="index")
    table["playoff_bonus"] = bonus.reindex(table.index).fillna(0.0)
    sor_total = table["sor"] + table["playoff_bonus"]
    blended = resume.sor_weight * _zscore(sor_total) + (1.0 - resume.sor_weight) * _zscore(
        table["performance"]
    )
    table["resume_z"] = _zscore(blended)
    table["solver_rating"] = [ratings.get(s, RATING_MEAN) for s in table.index]
    table["benchmark_rating"] = benchmark
    return table


def build_poll_index(
    schools: List[str],
    solver_states: Dict[str, TeamRatingState],
    games: List[GameResult],
    current_week: int,
    params: ModelParams,
    resume: Optional[ResumeParams] = None,
    preseason: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Poll table for one week. ``preseason`` is a z-scored preseason poll score;
    without it (or once the title game is final) the poll is pure resume.
    """
    if resume is None:
        resume = get_resume_params()

    table = compute_resume(schools, solver_states, games, current_week, params, resume)
    played_games = filter_games_through_week(games, current_week)
    champion = national_champion_from_games(played_games)

    sample = table["fbs_games"] + resume.fcs_game_weight * table["fcs_games"]
    if preseason is None or champion is not None:
        share = pd.Series(0.0, index=table.index)
        pre = pd.Series(0.0, index=table.index)
    else:
        share = resume.preseason_games_k / (resume.preseason_games_k + sample)
        pre = preseason.reindex(table.index).fillna(0.0)
    table["preseason_z"] = pre
    table["preseason_share"] = share
    base = share * pre + (1.0 - share) * table["resume_z"].fillna(0.0)

    table["h2h_adjustment"] = head_to_head_adjustments(
        base,
        games,
        current_week,
        window=resume.h2h_window,
        max_total=resume.h2h_max_total,
    )
    score = base + table["h2h_adjustment"]
    if resume.force_champion_first and champion in score.index:
        others = score.drop(champion)
        if len(others) and score[champion] <= others.max():
            score[champion] = others.max() + 0.01

    records = team_records(games, schools, current_week, fbs_only=False)
    table["wins"] = [records[s][0] for s in table.index]
    table["losses"] = [records[s][1] for s in table.index]
    table["poll_score"] = score
    table["poll_rating"] = table["poll_score"].map(lambda z: _rating_from_z(float(z)))
    table["rank"] = table["poll_rating"].rank(ascending=False, method="min").astype(int)
    return table.sort_values("rank")


def final_poll_scores(
    client,
    season: int,
    params: ModelParams,
    resume: ResumeParams,
) -> pd.Series:
    """Final (postseason, resume-only) poll scores for a completed season."""
    from bcpi.priors import build_preseason_priors
    from bcpi.solver import solve_ratings
    from bcpi.teams import get_fbs_teams

    teams = get_fbs_teams(client, season)
    schools = [team.school for team in teams]
    games = load_season_games(client, season, include_postseason=True)
    if not games:
        return pd.Series(dtype=float)
    week = max(game.week for game in games)
    states = solve_ratings(
        teams=schools,
        games=games,
        prior_ratings=build_preseason_priors(client, teams, season, params),
        current_week=week,
        params=params,
    )
    final = build_poll_index(schools, states, games, week, params, resume, preseason=None)
    return final["poll_score"]


def build_preseason_scores(
    client,
    schools: List[str],
    season: int,
    params: ModelParams,
    resume: Optional[ResumeParams] = None,
) -> pd.Series:
    """
    Z-scored preseason poll: last season's final poll, roster talent and the AP
    preseason poll (unranked = 26th), plus a bump for the defending champion.
    Weights renormalize over the inputs a team has (new FBS programs have no
    previous poll).
    """
    if resume is None:
        resume = get_resume_params()

    from bcpi.priors import load_prior_components
    from bcpi.teams import get_fbs_teams

    components = load_prior_components(client, get_fbs_teams(client, season), season)
    try:
        previous = final_poll_scores(client, season - 1, params, resume)
    except Exception:
        previous = pd.Series(dtype=float)
    inputs = {
        "previous_poll": _zscore(previous.reindex(schools)),
        "talent": components.talent_z.reindex(schools),
        "consensus": components.consensus_z.reindex(schools),
    }
    total = pd.Series(0.0, index=schools)
    weight = pd.Series(0.0, index=schools)
    for key, series in inputs.items():
        w = resume.preseason_weights.get(key, 0.0)
        valid = series.notna()
        total[valid] += w * series[valid]
        weight[valid] += w
    composite = (total / weight.where(weight > 0)).fillna(0.0)

    champion = load_defending_champion(client, season)
    if champion in composite.index:
        composite[champion] += resume.defending_champion_bonus
    return _zscore(composite).fillna(0.0)


def build_current_poll_index(
    client,
    schools: List[str],
    season: int,
    solver_states: Dict[str, TeamRatingState],
    games: List[GameResult],
    current_week: int,
    params: ModelParams,
    resume: Optional[ResumeParams] = None,
) -> pd.DataFrame:
    """Preseason poll blended toward the in-season resume as games accumulate."""
    if resume is None:
        resume = get_resume_params()
    preseason = build_preseason_scores(client, schools, season, params, resume)
    return build_poll_index(
        schools, solver_states, games, current_week, params, resume, preseason=preseason
    )

"""
Bergstein Poll Index (resume rankings).

Separate from BCPI power — answers "who deserves to be ranked highest?"

Components (z-scored, then weighted):
  - record:     FBS win rate with losses discounted (resume cares about L's)
  - schedule:   average opponent solver strength faced
  - results:    opponent-adjusted game value (solver residuals)
  - elite_wins: weighted wins vs top-N opponents by solver rating
  - playoff:    CFP path by round depth (NCG participant > semifinal exit)

Does NOT use raw per-play efficiency (power index territory).
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from bcpi.constants import RATING_MEAN, RATING_SPREAD
from bcpi.champions import load_defending_champion
from bcpi.games import GameResult, filter_games_through_week, load_season_games, opponent_key
from bcpi.game_stats import elite_opponent_set
from bcpi.params import ModelParams
from bcpi.resume_params import ResumeParams
from bcpi.solver import TeamRatingState


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _rating_from_z(z: float) -> float:
    return RATING_MEAN + z * (RATING_SPREAD / 2.5)


def _team_margin(game: GameResult, team: str) -> Optional[int]:
    if team == game.home_team:
        return game.margin_home
    if team == game.away_team:
        return -game.margin_home
    return None


def _compute_record(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
    resume: ResumeParams,
) -> pd.Series:
    scores = {}
    for school in schools:
        wins = 0.0
        losses = 0.0
        for game in filter_games_through_week(games, current_week):
            if not game.is_fbs_game:
                continue
            margin = _team_margin(game, school)
            if margin is None:
                continue
            if margin > 0:
                wins += 1.0
            elif margin < 0:
                losses += 1.0
        total = wins + losses
        if total <= 0:
            scores[school] = 0.0
        else:
            adjusted = wins - resume.loss_penalty_factor * losses
            scores[school] = adjusted / total
    return pd.Series(scores)


def _compute_schedule_strength(
    games: List[GameResult],
    schools: List[str],
    opponent_ratings: Dict[str, float],
    current_week: int,
) -> pd.Series:
    scores = {}
    for school in schools:
        ratings: List[float] = []
        for game in filter_games_through_week(games, current_week):
            if not game.is_fbs_game:
                continue
            if school not in (game.home_team, game.away_team):
                continue
            opp = opponent_key(game, school)
            if opp is None:
                continue
            ratings.append(opponent_ratings.get(opp, RATING_MEAN))
        scores[school] = sum(ratings) / len(ratings) if ratings else RATING_MEAN
    return pd.Series(scores)


def _compute_elite_wins(
    games: List[GameResult],
    schools: List[str],
    opponent_ratings: Dict[str, float],
    current_week: int,
    elite_set: set,
) -> pd.Series:
    scores = {}
    for school in schools:
        value = 0.0
        for game in filter_games_through_week(games, current_week):
            if not game.is_fbs_game:
                continue
            margin = _team_margin(game, school)
            if margin is None or margin <= 0:
                continue
            opp = opponent_key(game, school)
            if opp is None or opp not in elite_set:
                continue
            opp_rating = opponent_ratings.get(opp, RATING_MEAN)
            value += (opp_rating - RATING_MEAN) / (RATING_SPREAD / 2.5)
            value += margin / 35.0
        scores[school] = value
    return pd.Series(scores)


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


def _compute_playoff_score(
    games: List[GameResult],
    schools: List[str],
    current_week: int,
    resume: ResumeParams,
) -> pd.Series:
    """
    Playoff score by round depth reached, not flat win count.

    Playing in the national championship (even in a loss) scores above
    losing in the semifinals — Miami over Oregon in 2025.
    """
    scores = {school: 0.0 for school in schools}

    for school in schools:
        cfp_games = [
            g
            for g in filter_games_through_week(games, current_week)
            if g.is_fbs_game
            and g.completed
            and g.is_cfp
            and school in (g.home_team, g.away_team)
        ]
        if not cfp_games:
            continue

        scores[school] += resume.playoff_appearance_bonus
        rounds_seen: set = set()

        for game in cfp_games:
            round_key = _cfp_round_key(game.notes)
            if round_key is None:
                continue
            if round_key not in rounds_seen:
                rounds_seen.add(round_key)
                scores[school] += resume.playoff_round_participation.get(round_key, 0.0)

            margin = _team_margin(game, school)
            if margin is not None and margin > 0:
                scores[school] += resume.playoff_round_win_bonus
                if round_key == "championship":
                    scores[school] += resume.playoff_champion_bonus

    return pd.Series(scores)


def build_poll_index(
    schools: List[str],
    solver_states: Dict[str, TeamRatingState],
    games: List[GameResult],
    current_week: int,
    params: ModelParams,
    resume: Optional[ResumeParams] = None,
) -> pd.DataFrame:
    if resume is None:
        from bcpi.resume_params import get_resume_params

        resume = get_resume_params()

    opponent_ratings = {
        school: solver_states[school].rating if school in solver_states else RATING_MEAN
        for school in schools
    }
    elite_set = elite_opponent_set(opponent_ratings, schools, resume.elite_win_top_n)

    record = _compute_record(games, schools, current_week, resume)
    schedule = _compute_schedule_strength(games, schools, opponent_ratings, current_week)
    results = pd.Series(
        {
            s: solver_states[s].game_value if s in solver_states else 0.0
            for s in schools
        }
    )
    elite_wins = _compute_elite_wins(
        games, schools, opponent_ratings, current_week, elite_set
    )
    playoff = _compute_playoff_score(games, schools, current_week, resume)

    components = pd.DataFrame(index=schools)
    components["record"] = record
    components["schedule"] = schedule
    components["results"] = results
    components["elite_wins"] = elite_wins
    components["playoff_raw"] = playoff

    components["record_z"] = _zscore(record.astype(float))
    components["schedule_z"] = _zscore(schedule.astype(float))
    components["results_z"] = _zscore(results.astype(float))
    components["elite_wins_z"] = _zscore(elite_wins.astype(float))
    components["playoff_z"] = _zscore(playoff.astype(float))

    composite = pd.Series(0.0, index=schools)
    weight_map = {
        "record": "record_z",
        "schedule": "schedule_z",
        "results": "results_z",
        "elite_wins": "elite_wins_z",
        "playoff": "playoff_z",
    }
    for key, col in weight_map.items():
        weight = resume.resume_weights.get(key, 0.0)
        composite += weight * components[col]

    # Record wins/losses for display
    components["wins"] = 0
    components["losses"] = 0
    for school in schools:
        w, l = 0, 0
        for game in filter_games_through_week(games, current_week):
            if not game.is_fbs_game:
                continue
            margin = _team_margin(game, school)
            if margin is None:
                continue
            if margin > 0:
                w += 1
            elif margin < 0:
                l += 1
        components.loc[school, "wins"] = w
        components.loc[school, "losses"] = l

    components["poll_score"] = composite

    # Losing records should not pollute the ranked list — schedule strength alone
    # cannot justify a sub-.500 team in a resume-style poll.
    penalty = resume.sub500_poll_penalty
    for school in schools:
        w = int(components.loc[school, "wins"])
        l = int(components.loc[school, "losses"])
        if w + l >= 6 and w <= l:
            components.loc[school, "poll_score"] = float(components.loc[school, "poll_score"]) - penalty

    components["poll_rating"] = components["poll_score"].map(lambda z: _rating_from_z(float(z)))
    components["rank"] = components["poll_rating"].rank(ascending=False, method="min").astype(int)
    components["solver_rating"] = [opponent_ratings[s] for s in schools]
    return components.sort_values("rank")


def _season_has_fbs_results(games: List[GameResult], current_week: int) -> bool:
    return any(
        g.is_fbs_game and g.completed
        for g in filter_games_through_week(games, current_week)
    )


def build_preseason_poll_index(
    client,
    schools: List[str],
    season: int,
    solver_states: Dict[str, TeamRatingState],
    params: ModelParams,
    resume: Optional[ResumeParams] = None,
) -> pd.DataFrame:
    """
    Preseason poll proxy before any current-season games.

    Backward-looking resume from last year's final poll composite, optional AP
    preseason consensus, and a defending-champion bump — distinct from the
    forward-looking power priors.
    """
    if resume is None:
        from bcpi.resume_params import get_resume_params

        resume = get_resume_params()

    from bcpi.priors import build_preseason_priors, load_prior_components
    from bcpi.solver import solve_ratings
    from bcpi.teams import get_fbs_teams

    prior_resume = pd.Series(0.0, index=schools)
    prev = season - 1
    prev_teams = get_fbs_teams(client, prev)
    prev_schools = [team.school for team in prev_teams]
    prev_games = load_season_games(client, prev, include_postseason=True)

    if prev_games:
        prev_priors = build_preseason_priors(client, prev_teams, prev, params)
        prev_week = max(game.week for game in prev_games)
        prev_solver = solve_ratings(
            teams=prev_schools,
            games=prev_games,
            prior_ratings=prev_priors,
            current_week=prev_week,
            params=params,
        )
        prev_poll = build_poll_index(
            schools=prev_schools,
            solver_states=prev_solver,
            games=prev_games,
            current_week=prev_week,
            params=params,
            resume=resume,
        )
        for school in schools:
            if school in prev_poll.index:
                prior_resume[school] = float(prev_poll.loc[school, "poll_score"])

    current_teams = get_fbs_teams(client, season)
    prior_components = load_prior_components(client, current_teams, season)
    consensus = pd.Series(0.0, index=schools)
    for school in schools:
        if school in prior_components.consensus_z.index:
            value = prior_components.consensus_z.loc[school]
            if pd.notna(value):
                consensus[school] = float(value)

    prior_resume_z = _zscore(prior_resume.astype(float))
    consensus_z = _zscore(consensus.astype(float))

    composite = pd.Series(0.0, index=schools)
    used_weight = 0.0
    if prior_resume_z.std(ddof=0) not in (0, None) and not pd.isna(prior_resume_z.std(ddof=0)):
        composite += resume.preseason_resume_weight * prior_resume_z
        used_weight += resume.preseason_resume_weight
    if consensus_z.std(ddof=0) not in (0, None) and not pd.isna(consensus_z.std(ddof=0)):
        composite += resume.preseason_consensus_weight * consensus_z
        used_weight += resume.preseason_consensus_weight
    if used_weight > 0:
        composite = composite / used_weight

    champ = load_defending_champion(client, season)
    if champ and champ in composite.index and resume.defending_champion_poll_z > 0:
        composite.loc[champ] += resume.defending_champion_poll_z

    opponent_ratings = {
        school: solver_states[school].rating if school in solver_states else RATING_MEAN
        for school in schools
    }

    components = pd.DataFrame(index=schools)
    components["record"] = 0.0
    components["schedule"] = RATING_MEAN
    components["results"] = 0.0
    components["elite_wins"] = 0.0
    components["playoff_raw"] = 0.0
    components["record_z"] = 0.0
    components["schedule_z"] = 0.0
    components["results_z"] = 0.0
    components["elite_wins_z"] = 0.0
    components["playoff_z"] = 0.0
    components["wins"] = 0
    components["losses"] = 0
    components["poll_score"] = composite
    components["poll_rating"] = components["poll_score"].map(lambda z: _rating_from_z(float(z)))
    components["rank"] = components["poll_rating"].rank(ascending=False, method="min").astype(int)
    components["solver_rating"] = [opponent_ratings[s] for s in schools]
    return components.sort_values("rank")

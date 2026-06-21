"""BCPI power-based matchup predictions (team vs team, site-aware)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd

from bcpi.cfbd import CFBDClient
from bcpi.games import load_season_games
from bcpi.home_field import load_team_hfa
from bcpi.params import ModelParams, get_active_params
from bcpi.power_index import build_power_index_from_client
from bcpi.priors import build_preseason_priors
from bcpi.rankings_io import load_rankings_df
from bcpi.solver import margin_to_win_probability, predict_home_margin, solve_ratings
from bcpi.teams import Team, get_fbs_teams


@dataclass(frozen=True)
class MatchupPrediction:
    home_team: str
    away_team: str
    neutral_site: bool
    home_power_rating: float
    away_power_rating: float
    home_bcpi_rank: int
    away_bcpi_rank: int
    predicted_margin_home: float
    home_win_probability: float
    away_win_probability: float
    season: int
    week: int

    def to_dict(self) -> dict:
        margin = self.predicted_margin_home
        if abs(margin) < 0.05:
            favorite = None
            margin_abs = 0.0
        elif margin > 0:
            favorite = self.home_team
            margin_abs = margin
        else:
            favorite = self.away_team
            margin_abs = -margin
        return {
            "home_team": self.home_team,
            "away_team": self.away_team,
            "neutral_site": self.neutral_site,
            "site_label": (
                "Neutral site"
                if self.neutral_site
                else f"{self.home_team} home"
            ),
            "home_power_rating": round(self.home_power_rating, 1),
            "away_power_rating": round(self.away_power_rating, 1),
            "home_bcpi_rank": self.home_bcpi_rank,
            "away_bcpi_rank": self.away_bcpi_rank,
            "predicted_margin_home": round(self.predicted_margin_home, 2),
            "favorite": favorite,
            "margin_points": round(margin_abs, 1),
            "home_win_probability": round(self.home_win_probability, 4),
            "away_win_probability": round(self.away_win_probability, 4),
            "season": self.season,
            "week": self.week,
        }


def resolve_team_name(query: str, teams: List[Team]) -> str:
    """Match school name, abbreviation, or partial string to canonical school."""
    q = query.strip()
    if not q:
        raise ValueError("Team name is required.")

    lower = q.lower()
    schools = {t.school for t in teams}
    if q in schools:
        return q

    for team in teams:
        if team.abbreviation.lower() == lower:
            return team.school

    exact_ci = [t.school for t in teams if t.school.lower() == lower]
    if len(exact_ci) == 1:
        return exact_ci[0]

    partial = [t.school for t in teams if lower in t.school.lower()]
    if len(partial) == 1:
        return partial[0]

    starts = [t.school for t in teams if t.school.lower().startswith(lower)]
    if len(starts) == 1:
        return starts[0]

    if partial:
        options = ", ".join(sorted(partial)[:8])
        raise ValueError(f"Ambiguous team '{query}'. Matches: {options}")
    raise ValueError(f"Unknown team '{query}'. Use full school name or abbreviation.")


def _parse_site(team_a: str, team_b: str, site: str) -> Tuple[str, str, bool]:
    site = site.lower().replace("-", "_")
    if site in ("neutral", "neither"):
        return team_a, team_b, True
    if site in ("home_a", "a_home", "home_team_a"):
        return team_a, team_b, False
    if site in ("home_b", "b_home", "home_team_b"):
        return team_b, team_a, False
    if site == "home":
        return team_a, team_b, False
    raise ValueError(
        "Site must be neutral, home_a (first team home), or home_b (second team home)."
    )


def build_power_table(
    season: int,
    week: Optional[int] = None,
    refresh_data: bool = False,
    client: Optional[CFBDClient] = None,
    params: Optional[ModelParams] = None,
    include_postseason: bool = False,
) -> Tuple[pd.DataFrame, int]:
    owns_client = client is None
    if owns_client:
        client = CFBDClient(use_cache=not refresh_data)
    if params is None:
        params = get_active_params()

    try:
        teams = get_fbs_teams(client, season, refresh=refresh_data)
        schools = [team.school for team in teams]
        prior_ratings = build_preseason_priors(client, teams, season, params)
        games = load_season_games(client, season, include_postseason=include_postseason)

        if games:
            current_week = week if week is not None else max(g.week for g in games)
        else:
            current_week = week or 0

        solver_states = solve_ratings(
            teams=schools,
            games=games,
            prior_ratings=prior_ratings,
            current_week=current_week,
            params=params,
        )

        rankings = build_power_index_from_client(
            client=client,
            season=season,
            schools=schools,
            solver_states=solver_states,
            prior_ratings=prior_ratings,
            games=games,
            current_week=current_week,
            params=params,
            include_postseason=include_postseason,
        )
        return rankings, current_week
    finally:
        if owns_client and client is not None:
            client.close()


def predict_matchup(
    team_a: str,
    team_b: str,
    site: str = "neutral",
    season: int = 2026,
    week: Optional[int] = None,
    refresh_data: bool = False,
    client: Optional[CFBDClient] = None,
    params: Optional[ModelParams] = None,
    include_postseason: bool = False,
    use_cached_rankings: bool = True,
) -> MatchupPrediction:
    """Predict margin and win probability using BCPI power ratings."""
    if params is None:
        params = get_active_params()

    if use_cached_rankings and not refresh_data:
        cached = predict_matchup_from_rankings(
            team_a=team_a,
            team_b=team_b,
            site=site,
            season=season,
            params=params,
            include_postseason=include_postseason,
            refresh=refresh_data,
        )
        if cached is not None:
            return cached

    owns_client = client is None
    if owns_client:
        client = CFBDClient(use_cache=not refresh_data)

    try:
        teams = get_fbs_teams(client, season, refresh=refresh_data)
        school_a = resolve_team_name(team_a, teams)
        school_b = resolve_team_name(team_b, teams)

        rankings, current_week = build_power_table(
            season=season,
            week=week,
            refresh_data=refresh_data,
            client=client,
            params=params,
            include_postseason=include_postseason,
        )

        home_team, away_team, neutral = _parse_site(school_a, school_b, site)

        if home_team not in rankings.index or away_team not in rankings.index:
            missing = [t for t in (home_team, away_team) if t not in rankings.index]
            raise ValueError(f"Team(s) not in rankings: {', '.join(missing)}")

        home_row = rankings.loc[home_team]
        away_row = rankings.loc[away_team]
        schools = [team.school for team in teams]
        team_hfa = load_team_hfa(client, schools, season, params, refresh=refresh_data)
        margin = predict_home_margin(
            float(home_row["power_rating"]),
            float(away_row["power_rating"]),
            neutral,
            params,
            home_team=home_team,
            team_hfa=team_hfa,
        )
        home_win = margin_to_win_probability(margin, params.win_prob_scale)

        return MatchupPrediction(
            home_team=home_team,
            away_team=away_team,
            neutral_site=neutral,
            home_power_rating=float(home_row["power_rating"]),
            away_power_rating=float(away_row["power_rating"]),
            home_bcpi_rank=int(home_row["rank"]),
            away_bcpi_rank=int(away_row["rank"]),
            predicted_margin_home=margin,
            home_win_probability=home_win,
            away_win_probability=1.0 - home_win,
            season=season,
            week=current_week,
        )
    finally:
        if owns_client and client is not None:
            client.close()


def predict_matchup_from_rankings(
    team_a: str,
    team_b: str,
    site: str = "neutral",
    season: int = 2026,
    params: Optional[ModelParams] = None,
    include_postseason: bool = False,
    refresh: bool = False,
    client: Optional[CFBDClient] = None,
) -> Optional[MatchupPrediction]:
    """Fast matchup using saved rankings CSV when available."""
    if params is None:
        params = get_active_params()

    owns_client = client is None
    if owns_client:
        client = CFBDClient(use_cache=True)

    try:
        teams = get_fbs_teams(client, season)
        school_a = resolve_team_name(team_a, teams)
        school_b = resolve_team_name(team_b, teams)
        df, current_week, _ = load_rankings_df(
            "power",
            season,
            postseason=include_postseason,
            refresh=refresh,
        )
        rankings = df.set_index("school")
        home_team, away_team, neutral = _parse_site(school_a, school_b, site)

        if home_team not in rankings.index or away_team not in rankings.index:
            return None

        home_row = rankings.loc[home_team]
        away_row = rankings.loc[away_team]
        schools = [team.school for team in teams]
        team_hfa = load_team_hfa(client, schools, season, params, refresh=refresh)
        margin = predict_home_margin(
            float(home_row["power_rating"]),
            float(away_row["power_rating"]),
            neutral,
            params,
            home_team=home_team,
            team_hfa=team_hfa,
        )
        home_win = margin_to_win_probability(margin, params.win_prob_scale)

        return MatchupPrediction(
            home_team=home_team,
            away_team=away_team,
            neutral_site=neutral,
            home_power_rating=float(home_row["power_rating"]),
            away_power_rating=float(away_row["power_rating"]),
            home_bcpi_rank=int(home_row["rank"]),
            away_bcpi_rank=int(away_row["rank"]),
            predicted_margin_home=margin,
            home_win_probability=home_win,
            away_win_probability=1.0 - home_win,
            season=season,
            week=current_week,
        )
    except Exception:
        return None
    finally:
        if owns_client and client is not None:
            client.close()


def format_matchup(prediction: MatchupPrediction) -> str:
    lines = []
    site_label = "Neutral site" if prediction.neutral_site else f"{prediction.home_team} home"
    lines.append(f"BCPI matchup ({prediction.season}, week {prediction.week} ratings)")
    lines.append(f"Site: {site_label}")
    lines.append("")
    lines.append(
        f"  {prediction.home_team}  BCPI #{prediction.home_bcpi_rank}  "
        f"(power {prediction.home_power_rating:.0f})"
    )
    lines.append(
        f"  {prediction.away_team}  BCPI #{prediction.away_bcpi_rank}  "
        f"(power {prediction.away_power_rating:.0f})"
    )
    lines.append("")

    margin = prediction.predicted_margin_home
    if abs(margin) < 0.05:
        lines.append("Predicted margin: Even (~pick'em)")
    elif margin > 0:
        lines.append(f"Predicted margin: {prediction.home_team} by {margin:.1f} points")
    else:
        lines.append(f"Predicted margin: {prediction.away_team} by {-margin:.1f} points")

    lines.append(
        f"Win probability: {prediction.home_team} {prediction.home_win_probability:.0%} | "
        f"{prediction.away_team} {prediction.away_win_probability:.0%}"
    )
    return "\n".join(lines)

"""Invariant and health checks for published BCPI rankings."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from bcpi.champions import national_champion_from_games
from bcpi.constants import FCS_OPPONENT_KEY
from bcpi.games import (
    GameResult,
    compress_margin,
    effective_margin_for_rating,
    filter_games_through_week,
    opponent_key,
    team_won,
)
from bcpi.params import ModelParams

# FCS residual health: mean compressed residual by the FBS team's solver rank.
# Calibrated so 2018-2025 passes at the current FCS rating and fails at 1380.
FCS_RESIDUAL_TIERS = ((1, 25), (26, 50), (51, 80), (81, 200))
FCS_RESIDUAL_LIMIT = 6.0


@dataclass
class CheckResult:
    check: str
    name: str
    kind: str  # "invariant" or "health"
    severity: str  # "warning" or "error"
    teams: List[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


def by_school(table: pd.DataFrame) -> pd.DataFrame:
    if table.index.name == "school" or (
        not isinstance(table.index, pd.RangeIndex) and "school" not in table.columns
    ):
        return table
    if "school" in table.columns:
        return table.set_index("school")
    return table


def _rank(table: pd.DataFrame) -> Dict[str, int]:
    return {school: int(row["rank"]) for school, row in by_school(table).iterrows()}


def _results(
    games: Sequence[GameResult],
    schools: Sequence[str],
    week: int,
) -> Dict[str, List]:
    """Per school: (opponent, won, fbs) for decided games through ``week``."""
    out = {school: [] for school in schools}
    for game in filter_games_through_week(list(games), week):
        if not game.completed or not game.involves_fbs:
            continue
        for team in (game.home_team, game.away_team):
            if team not in out:
                continue
            won = team_won(game, team)
            opponent = opponent_key(game, team)
            if won is None or opponent is None:
                continue
            name = game.away_team if team == game.home_team else game.home_team
            out[team].append((name, won, opponent != FCS_OPPONENT_KEY))
    return out


def ranking_invariants(
    power: pd.DataFrame,
    poll: pd.DataFrame,
    games: Sequence[GameResult],
    week: int,
    schools: Sequence[str],
    final: bool = False,
) -> List[CheckResult]:
    """The seven ranking invariants. Failures are warnings, not build failures."""
    power_rank = _rank(power)
    poll_rank = _rank(poll)
    results = _results(games, schools, week)
    losses = {s: [o for o, won, _ in results[s] if not won] for s in schools}
    wins = {s: [o for o, won, _ in results[s] if won] for s in schools}
    fbs_wins = {s: sum(1 for _, won, fbs in results[s] if won and fbs) for s in schools}
    fbs_losses = {s: sum(1 for _, won, fbs in results[s] if not won and fbs) for s in schools}

    def pr(team: str) -> int:
        return power_rank.get(team, 999)

    def qr(team: str) -> int:
        return poll_rank.get(team, 999)

    found: List[CheckResult] = []

    def add(check: str, name: str, teams: Iterable[str], message: str) -> None:
        names = list(teams)
        if names:
            found.append(
                CheckResult(check, name, "invariant", "warning", names, message)
            )

    quality_loss = []
    for school in schools:
        lost = losses[school]
        if pr(school) <= 15 and len(lost) == 1 and qr(lost[0]) <= 5 and qr(school) > 25:
            quality_loss.append(school)
    add(
        "1",
        "quality-loss floor",
        quality_loss,
        "Power top-15 team whose only loss is to a poll top-5 team is outside the poll top 25.",
    )

    bad_loss = []
    for school in schools:
        if qr(school) <= 10 and any(pr(o) > 60 for o in losses[school]) and not any(
            pr(o) <= 15 for o in wins[school]
        ):
            bad_loss.append(school)
    add(
        "2",
        "bad-loss ceiling",
        bad_loss,
        "Poll top-10 team lost to a power #61-or-worse team and has no win over a power top-15 team.",
    )

    empty = []
    if week >= 6:
        for school in schools:
            if qr(school) <= 5 and not any(pr(o) <= 40 for o in wins[school]):
                empty.append(school)
    add(
        "3",
        "empty-resume ceiling",
        empty,
        "From week 6 on, a poll top-5 team has no win over a power top-40 team.",
    )

    record = []
    for school in schools:
        if (
            qr(school) <= 10
            and fbs_wins[school] + fbs_losses[school] > 0
            and fbs_wins[school] <= fbs_losses[school]
            and not any(pr(o) <= 10 for o in wins[school])
        ):
            record.append(school)
    add(
        "4",
        "record floor",
        record,
        "Poll top-10 team is at or below .500 against FBS and has no win over a power top-10 team.",
    )

    h2h = []
    for game in filter_games_through_week(list(games), week):
        if not game.is_fbs_game or not game.completed:
            continue
        won = team_won(game, game.home_team)
        if won is None:
            continue
        winner, loser = (game.home_team, game.away_team) if won else (game.away_team, game.home_team)
        if winner not in losses or loser not in losses:
            continue
        if len(losses[winner]) <= len(losses[loser]) and qr(winner) <= 25 and 0 < qr(winner) - qr(loser) <= 3:
            h2h.append(f"{loser} over {winner}")
    add(
        "5",
        "head-to-head",
        h2h,
        "Winner with no more losses than the loser is ranked 1-3 spots behind that loser in the poll top 25.",
    )

    power_gap = []
    for school in schools:
        if pr(school) <= 10 and qr(school) > 25 and not (
            len(losses[school]) >= 2 or any(pr(o) > 60 for o in losses[school])
        ):
            power_gap.append(school)
    add(
        "6a",
        "power-top-10 but unranked",
        power_gap,
        "Power top-10 team is outside the poll top 25 without two losses or a loss to power #61-or-worse.",
    )

    poll_gap = []
    for school in schools:
        if qr(school) <= 10 and pr(school) > 40 and not any(pr(o) <= 15 for o in wins[school]):
            poll_gap.append(school)
    add(
        "6b",
        "poll-top-10 but weak power",
        poll_gap,
        "Poll top-10 team is outside the power top 40 and has no win over a power top-15 team.",
    )

    if final:
        champion = national_champion_from_games(list(filter_games_through_week(list(games), week)))
        if champion and qr(champion) != 1:
            add("7", "champion not #1", [champion], "The national champion is not #1 in the final poll.")
    return found


def _constant_columns(table: pd.DataFrame, columns: Sequence[str], used: bool) -> List[str]:
    if not used:
        return []
    indexed = by_school(table)
    flagged = []
    for column in columns:
        if column not in indexed.columns:
            continue
        values = indexed[column].astype(float)
        if values.notna().sum() < 2:
            continue
        if float(values.std(ddof=0, skipna=True) or 0.0) < 1e-9:
            flagged.append(column)
    return flagged


def power_health_checks(
    power: pd.DataFrame,
    games: Sequence[GameResult],
    week: int,
    schools: Sequence[str],
    params: ModelParams,
) -> List[CheckResult]:
    found: List[CheckResult] = []
    table = by_school(power)
    market_on = params.power_weights.get("market", 0.0) > 0

    constant = _constant_columns(
        table,
        ("solver_rating", "quality_z", "prior_z", "power_score", "market_z" if market_on else ""),
        True,
    )
    if constant:
        found.append(
            CheckResult(
                "H1",
                "constant component",
                "health",
                "error",
                constant,
                "A used power component is the same for every team.",
            )
        )

    fbs = [
        g
        for g in filter_games_through_week(list(games), week)
        if g.is_fbs_game and g.completed
    ]
    if fbs:
        covered = sum(1 for g in fbs if g.spread is not None) / len(fbs)
        if covered < 0.90:
            found.append(
                CheckResult(
                    "H2",
                    "spread coverage",
                    "health",
                    "error" if market_on else "warning",
                    [],
                    f"{covered:.0%} of completed FBS games have a parsed spread (need 90%).",
                )
            )

    fcs_games = [
        g
        for g in filter_games_through_week(list(games), week)
        if g.completed and g.involves_fbs and not g.is_fbs_game
    ]
    residual_flags = _fcs_residual_flags(table, games, week, params) if week >= 4 and len(fcs_games) >= 20 else []
    if residual_flags:
        found.append(
            CheckResult(
                "H3",
                "FCS residual",
                "health",
                "error",
                residual_flags,
                "Mean FCS residual in a rating tier is farther from zero than the calibrated limit.",
            )
        )

    if "solver_max_change" in table.columns:
        max_change = float(table["solver_max_change"].max())
        if max_change > params.solver_tolerance:
            found.append(
                CheckResult(
                    "H4",
                    "solver convergence",
                    "health",
                    "error",
                    [],
                    f"Solver max change {max_change:.3f} exceeds tolerance {params.solver_tolerance}.",
                )
            )

    nan_cols = [
        col
        for col in ("power_score", "power_rating", "rank", "solver_rating")
        if col in table.columns and table[col].isna().any()
    ]
    unmapped = _unmapped_teams(games, week, schools)
    if nan_cols or unmapped:
        found.append(
            CheckResult(
                "H5",
                "missing values",
                "health",
                "error",
                nan_cols + unmapped,
                "NaN in a published power field, or an FBS game involves a team not in the school list.",
            )
        )
    return found


def poll_health_checks(
    poll: pd.DataFrame,
    games: Sequence[GameResult],
    week: int,
    schools: Sequence[str],
) -> List[CheckResult]:
    found: List[CheckResult] = []
    table = by_school(poll)
    constant = _constant_columns(table, ("poll_score", "resume_z", "sor"), True)
    if constant:
        found.append(
            CheckResult(
                "H1",
                "constant component",
                "health",
                "error",
                constant,
                "A used poll component is the same for every team.",
            )
        )
    nan_cols = [
        col
        for col in ("poll_score", "poll_rating", "rank")
        if col in table.columns and table[col].isna().any()
    ]
    unmapped = _unmapped_teams(games, week, schools)
    if nan_cols or unmapped:
        found.append(
            CheckResult(
                "H5",
                "missing values",
                "health",
                "error",
                nan_cols + unmapped,
                "NaN in a published poll field, or an FBS game involves a team not in the school list.",
            )
        )
    return found


def _fcs_residual_flags(
    power: pd.DataFrame,
    games: Sequence[GameResult],
    week: int,
    params: ModelParams,
) -> List[str]:
    ratings = power["solver_rating"].astype(float).to_dict()
    fcs_rating = params.fcs_rating
    by_tier: Dict[str, List[float]] = {f"{lo}-{hi}": [] for lo, hi in FCS_RESIDUAL_TIERS}
    ranks = power["rank"].astype(int).to_dict() if "rank" in power.columns else {}
    # Prefer solver rank so the playoff bonus doesn't move a team across tiers.
    if "solver_rating" in power.columns:
        order = sorted(ratings, key=ratings.get, reverse=True)
        ranks = {school: i + 1 for i, school in enumerate(order)}

    for game in filter_games_through_week(list(games), week):
        if not game.completed or not game.involves_fbs or game.is_fbs_game:
            continue
        for team in (game.home_team, game.away_team):
            if team not in ratings:
                continue
            opp = opponent_key(game, team)
            if opp != FCS_OPPONENT_KEY:
                continue
            margin = effective_margin_for_rating(game, team, params)
            if margin is None:
                continue
            expected = (ratings[team] - fcs_rating) / params.margin_scale
            residual = compress_margin(margin, params.margin_compression) - compress_margin(
                expected, params.margin_compression
            )
            rank = ranks.get(team, 999)
            for lo, hi in FCS_RESIDUAL_TIERS:
                if lo <= rank <= hi:
                    by_tier[f"{lo}-{hi}"].append(residual)
                    break

    flags = []
    for label, values in by_tier.items():
        if len(values) < 8:
            continue
        mean = sum(values) / len(values)
        if abs(mean) > FCS_RESIDUAL_LIMIT:
            flags.append(f"{label} mean {mean:+.1f}")
    return flags


def _unmapped_teams(games: Sequence[GameResult], week: int, schools: Sequence[str]) -> List[str]:
    known = set(schools)
    missing = set()
    for game in filter_games_through_week(list(games), week):
        if not game.completed:
            continue
        if game.home_classification == "fbs" and game.home_team not in known:
            missing.add(game.home_team)
        if game.away_classification == "fbs" and game.away_team not in known:
            missing.add(game.away_team)
    return sorted(missing)


def evaluate_checks(
    power: Optional[pd.DataFrame],
    poll: Optional[pd.DataFrame],
    games: Sequence[GameResult],
    week: int,
    schools: Sequence[str],
    params: ModelParams,
    final: bool = False,
) -> List[CheckResult]:
    found: List[CheckResult] = []
    if power is not None:
        found.extend(power_health_checks(power, games, week, schools, params))
    if poll is not None:
        found.extend(poll_health_checks(poll, games, week, schools))
    if power is not None and poll is not None:
        found.extend(ranking_invariants(power, poll, games, week, schools, final=final))
    return found


def write_checks(path: Path, results: Sequence[CheckResult], extra: Optional[Dict] = None) -> Path:
    payload = {
        "violations": [result.to_dict() for result in results],
        "health_errors": sum(1 for r in results if r.kind == "health" and r.severity == "error"),
        "invariant_warnings": sum(1 for r in results if r.kind == "invariant"),
    }
    if extra:
        payload.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return path


def flag_teams(results: Sequence[CheckResult], schools: Sequence[str]) -> Dict[str, str]:
    flags: Dict[str, List[str]] = {school: [] for school in schools}
    for result in results:
        for team in result.teams:
            if team in flags:
                flags[team].append(result.check)
    return {school: ",".join(names) for school, names in flags.items()}


def format_annotations(results: Sequence[CheckResult]) -> List[str]:
    """GitHub Actions workflow commands for each violation."""
    lines = []
    for result in results:
        level = "error" if result.severity == "error" else "warning"
        teams = ", ".join(result.teams) if result.teams else "(none)"
        lines.append(f"::{level}::{result.check} {result.name}: {result.message} [{teams}]")
    return lines

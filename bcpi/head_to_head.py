"""Head-to-head adjustment shared by the power index and the poll."""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from bcpi.games import GameResult, effective_margin_for_rating, filter_games_through_week
from bcpi.params import ModelParams


def head_to_head_adjustments(
    scores: pd.Series,
    games: List[GameResult],
    current_week: int,
    window: float,
    max_total: float,
    site_adjusted: bool = False,
    params: Optional[ModelParams] = None,
    winner_of=None,
) -> pd.Series:
    """
    Per-team score adjustments from FBS head-to-head results.

    Games are applied in week order against the running scores. When the winner
    trails the loser by a gap inside ``window``, the winner gains and the loser
    gives up min(gap, (window - gap) / 2). The winner passes the loser whenever
    the gap is under half the window, and the adjustment fades to zero at the
    window edge, so a tiny score change never flips the outcome. Each team's
    total adjustment is capped at ``max_total``.

    With ``site_adjusted``, a game only counts if the winner still wins after
    removing home field (a 1-point home win is not evidence the winner is better).
    """
    original = scores.astype(float)
    if window <= 0 or original.empty:
        return original * 0.0

    adjusted: Dict[str, float] = original.to_dict()
    used: Dict[str, float] = {team: 0.0 for team in adjusted}
    decided = [
        game
        for game in filter_games_through_week(games, current_week)
        if game.is_fbs_game and game.completed and game.margin_home != 0
    ]
    decided.sort(key=lambda game: (game.week, game.game_id))

    for game in decided:
        forced = winner_of(game) if winner_of is not None else None
        if forced == game.home_team:
            winner, loser = game.home_team, game.away_team
        elif forced == game.away_team:
            winner, loser = game.away_team, game.home_team
        elif game.margin_home > 0:
            winner, loser = game.home_team, game.away_team
        else:
            winner, loser = game.away_team, game.home_team
        if winner not in used or loser not in used:
            continue
        if site_adjusted:
            neutral_margin = effective_margin_for_rating(game, winner, params)
            if neutral_margin is None or neutral_margin <= 0:
                continue
        gap = adjusted[loser] - adjusted[winner]
        if not 0.0 < gap < window:
            continue
        amount = min(gap, (window - gap) / 2.0)
        if max_total > 0:
            amount = min(amount, max_total - used[winner], max_total - used[loser])
        if amount <= 0:
            continue
        adjusted[winner] += amount
        adjusted[loser] -= amount
        used[winner] += amount
        used[loser] += amount

    return pd.Series(adjusted).reindex(original.index) - original

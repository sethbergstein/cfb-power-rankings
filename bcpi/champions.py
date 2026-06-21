"""National championship detection for preseason priors and poll."""

from __future__ import annotations

from typing import List, Optional

from bcpi.cfbd import CFBDClient
from bcpi.games import GameResult, load_season_games


def _is_title_game(notes: Optional[str]) -> bool:
    text = (notes or "").lower()
    return "national championship" in text or "bcs national championship" in text


def national_champion_from_games(games: List[GameResult]) -> Optional[str]:
    """Return the winner of the national title game, if present."""
    for game in games:
        if not game.completed or not game.is_fbs_game:
            continue
        if not _is_title_game(game.notes):
            continue
        if game.margin_home > 0:
            return game.home_team
        if game.margin_home < 0:
            return game.away_team
    return None


def load_defending_champion(client: CFBDClient, season: int) -> Optional[str]:
    """Winner of the prior season's national championship."""
    prev_games = load_season_games(client, season - 1, include_postseason=True)
    return national_champion_from_games(prev_games)

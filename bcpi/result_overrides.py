"""Poll-only result overrides for games whose official winner is not the one we score.

Official records and the power index keep the scoreboard. The poll uses these
when a governing body has said in writing that a protocol failure changed the
winner and the result stands only because the game cannot be reopened.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, List, Optional

from bcpi.config import PROJECT_ROOT
from bcpi.games import GameResult, team_won

OVERRIDES_PATH = PROJECT_ROOT / "config" / "poll_result_overrides.json"


@lru_cache(maxsize=1)
def load_overrides() -> Dict[int, dict]:
    if not OVERRIDES_PATH.exists():
        return {}
    with OVERRIDES_PATH.open("r", encoding="utf-8") as handle:
        rows = json.load(handle)
    return {int(row["game_id"]): row for row in rows}


def forced_winner(game: GameResult) -> Optional[str]:
    """School the poll treats as the winner, or None to use the scoreboard."""
    row = load_overrides().get(int(game.game_id))
    if not row:
        return None
    winner = row.get("winner")
    if winner not in (game.home_team, game.away_team):
        return None
    return winner


def poll_team_won(game: GameResult, team: str) -> Optional[bool]:
    """Win/loss for poll scoring. Displayed records still use ``team_won``."""
    winner = forced_winner(game)
    if winner is None:
        return team_won(game, team)
    if team not in (game.home_team, game.away_team) or game.margin_home == 0:
        return team_won(game, team)
    return team == winner


def result_notes(games: List[GameResult], schools: List[str]) -> Dict[str, str]:
    """Short note for each school that played in an overridden game."""
    notes = {school: "" for school in schools}
    for game in games:
        row = load_overrides().get(int(game.game_id))
        if not row:
            continue
        text = row.get("note") or ""
        for school in (row.get("winner"), row.get("loser")):
            if school in notes and text:
                notes[school] = text
    return notes

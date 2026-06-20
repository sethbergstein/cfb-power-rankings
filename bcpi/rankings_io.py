"""Load or generate BCPI ranking tables for the web UI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from bcpi.config import OUTPUT_DIR
from bcpi.params import get_active_params
from bcpi.pipeline import run_poll_rankings, run_rankings


def _postseason_path(kind: str, season: int) -> Path:
    return OUTPUT_DIR / f"bcpi_{kind}_{season}_postseason.csv"


def _week_path(kind: str, season: int, week: int) -> Path:
    return OUTPUT_DIR / f"bcpi_{kind}_{season}_week{week:02d}.csv"


def _preseason_path(kind: str, season: int) -> Path:
    return OUTPUT_DIR / f"bcpi_{kind}_{season}_preseason.csv"


def find_rankings_path(
    kind: str,
    season: int,
    postseason: bool = False,
    week: Optional[int] = None,
) -> Optional[Path]:
    if postseason:
        path = _postseason_path(kind, season)
        if path.exists():
            return path
    if week is not None:
        path = _week_path(kind, season, week)
        if path.exists():
            return path
    preseason = _preseason_path(kind, season)
    if preseason.exists():
        return preseason
    # Latest week file
    prefix = f"bcpi_{kind}_{season}_week"
    week_files = sorted(OUTPUT_DIR.glob(f"{prefix}*.csv"))
    if week_files:
        return week_files[-1]
    if postseason:
        return _postseason_path(kind, season)
    return None


def load_rankings_df(
    kind: str,
    season: int,
    postseason: bool = False,
    week: Optional[int] = None,
    refresh: bool = False,
) -> Tuple[pd.DataFrame, int, Path]:
    """Return rankings dataframe, as-of week, and source path."""
    path = find_rankings_path(kind, season, postseason, week)
    if path is None or refresh or not path.exists():
        params = get_active_params()
        if kind == "power":
            path = run_rankings(
                season=season,
                week=week,
                refresh_data=refresh,
                params=params,
                include_postseason=postseason,
            )
        elif kind == "poll":
            path = run_poll_rankings(
                season=season,
                week=week,
                refresh_data=refresh,
                params=params,
                include_postseason=postseason,
            )
        else:
            raise ValueError(f"Unknown rankings kind: {kind}")

    df = pd.read_csv(path)
    as_of_week = int(df["week"].iloc[0]) if "week" in df.columns and len(df) else 0
    return df, as_of_week, path
